"""Daily marks: the volatility surface every position is valued on.

A desk does not observe a full surface for every name every day in its history, and neither do we.
Each underlying gets three numbers per day, the rest is a stated parametrisation:

- `atm30`: one-month ATM implied vol, in vol points.
  * live chain, when the sister projects captured that day's option chain (the dispersion project's
    50-chain snapshot for single names, the vol dashboard's SPY snapshot for the index);
  * model otherwise. S&P 500: the vol dashboard's ATM history (VXO, then VIX x a ratio on ln VIX and
    SKEW). Single names: the dispersion project's rebuild. COR1M is the correlation CBOE solves from
    ATM vols, so one common factor k solves  ATM_spx² = k² [B + rho (A - B)]  with A and B the top-50
    trailing 63-day moments, and each name is marked at k x its own trailing vol.
- `atm90`: three-month ATM vol where a live chain gives it; the term structure is otherwise borrowed
  from the S&P 500 (VIX9D, VIX, VIX3M, VIX6M relative to VIX), flat beyond six months.
- `beta`: the skew slope. sigma(K, T) = ATM(T) + beta x ln(K/F) / sqrt(T), in decimal vol. Calibrated
  from the live 25-delta risk reversal (RR25 = beta x 1.349 x ATM), held at the median of the live
  days on model days. Floored at 30% and capped at 300% of ATM.

Variance-swap levels: S&P 500 from the VIX family (model-free, interpolated in total variance); single
names at ATM x 1.10, the model-free / ATM ratio the dispersion project measured on the 50 chains.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .links import C_SINGLE_VS, RISK_FREE, basket_moments, sp_atm_vol

INDEX = "SPX"
ANCHORS = [9, 30, 91, 182]           # VIX9D, VIX, VIX3M, VIX6M
DEFAULT_BETA = {INDEX: -0.25}         # used only if no live chain was ever captured
DEFAULT_SINGLE_BETA = -0.10
RR_TO_BETA = 1.349                    # x_call25 - x_put25 = 1.349 sigma (standardised log-moneyness)


def beta_from_rr(rr25: float, atm: float) -> float:
    """Skew slope from a 25-delta risk reversal and the ATM vol, both in vol points."""
    return rr25 / (RR_TO_BETA * atm)


@dataclass
class Marks:
    spot: pd.DataFrame                   # date x underlying
    atm30: pd.DataFrame                  # vol points
    atm90: pd.DataFrame                  # vol points, NaN when no live chain
    beta: pd.DataFrame
    source: pd.DataFrame                 # "live chain" / "model"
    model_atm30: pd.DataFrame            # what the model says every day, for the independent check
    vixfam: pd.DataFrame                 # date x ANCHORS, vol points
    corr_factor: pd.Series               # d sigma_index / d rho, vol points per correlation point
    div_yield: dict = field(default_factory=dict)
    rate: float = RISK_FREE

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.spot.index

    @property
    def underlyings(self) -> list[str]:
        return list(self.spot.columns)

    # ----- term structure -----
    def _ts_ratio(self, d, t_days: float) -> float:
        row = self.vixfam.loc[d]
        pts = [(a, row[a]) for a in ANCHORS if pd.notna(row[a])]
        if not pts or pd.isna(row[30]):
            return 1.0
        xs, ys = zip(*pts)
        return float(np.interp(t_days, xs, np.array(ys) / row[30]))

    def atm(self, d, und: str, t_days: float) -> float:
        """ATM vol in vol points for a maturity of t_days calendar days."""
        a30, a90 = self.atm30.at[d, und], self.atm90.at[d, und]
        if pd.isna(a90):
            return a30 * self._ts_ratio(d, t_days)
        if t_days <= 30:
            return a30 * self._ts_ratio(d, t_days) / self._ts_ratio(d, 30)
        if t_days <= 90:
            return float(np.interp(t_days, [30, 90], [a30, a90]))
        return a90 * self._ts_ratio(d, t_days) / self._ts_ratio(d, 91)

    def forward(self, d, und: str, t: float, spot: float | None = None) -> float:
        s = self.spot.at[d, und] if spot is None else spot
        return s * np.exp((self.rate - self.div_yield.get(und, 0.0)) * t)

    def vol(self, d, und: str, strike: float, t: float, spot: float | None = None) -> float:
        """Implied vol (decimal) at an absolute strike and a maturity in years."""
        t = max(t, 1 / 365)
        atm = self.atm(d, und, t * 365) / 100
        x = np.log(strike / self.forward(d, und, t, spot)) / np.sqrt(t)
        return float(np.clip(atm + self.beta.at[d, und] * x, 0.3 * atm, 3.0 * atm))

    def varswap(self, d, und: str, t_days: float) -> float:
        """Fair variance-swap strike, vol points."""
        t_days = max(t_days, 1.0)
        if und == INDEX:
            row = self.vixfam.loc[d]
            pts = [(a, row[a]) for a in ANCHORS if pd.notna(row[a])]
            xs, ys = zip(*pts)
            tv = np.interp(t_days, xs, [y**2 * x for x, y in pts])
            if t_days < xs[0]:
                return float(ys[0])
            if t_days > xs[-1]:
                return float(ys[-1])
            return float(np.sqrt(tv / t_days))
        return self.atm(d, und, t_days) * C_SINGLE_VS


def build_marks(closes: pd.DataFrame, names: list[str], vixfam: pd.DataFrame, skew_idx: pd.Series, vxo: pd.Series,
                cor1m: pd.Series, top50: pd.DataFrame, weights: pd.Series, live_single: pd.DataFrame,
                live_index: pd.DataFrame, div_yield: dict, start: str) -> Marks:
    """closes: ^GSPC and the single names. top50: closes of the 50 basket names (for the rebuild)."""
    spx = closes["^GSPC"].dropna()
    vix = vixfam[30].dropna()
    dates = spx.index.intersection(vix.index)
    dates = dates[dates >= pd.Timestamp(start)]
    cols = [INDEX] + names
    spot = pd.concat({INDEX: spx, **{n: closes[n] for n in names}}, axis=1).reindex(dates).ffill(limit=3)

    # --- model ATM, S&P 500: the vol dashboard's history
    atm_spx, _, _ = sp_atm_vol(vix, vxo, skew_idx)
    model = pd.DataFrame(index=dates, columns=cols, dtype=float)
    model[INDEX] = atm_spx.reindex(dates).ffill(limit=3)

    # --- model ATM, single names: the dispersion rebuild
    shape = basket_moments(top50, weights, spx, 63)
    cor = (cor1m.reindex(dates).ffill(limit=5) / 100)
    sh = shape.reindex(dates).ffill(limit=3)
    k2 = model[INDEX] ** 2 / (sh["B"] + cor * (sh["A"] - sh["B"]))
    trail = np.sqrt(np.log(top50 / top50.shift(1)).rolling(63).var() * 252 * 1e4).reindex(dates).ffill(limit=3)
    for n in names:
        model[n] = np.sqrt(k2) * trail[n]
    # d sigma_index / d rho at the ATM level, per correlation point (vol points)
    corr_factor = (k2 * (sh["A"] - sh["B"]) / (2 * model[INDEX])) * 0.01

    # --- live overrides
    atm30, atm90 = model.copy(), pd.DataFrame(np.nan, index=dates, columns=cols)
    rr30 = pd.DataFrame(np.nan, index=dates, columns=cols)
    source = pd.DataFrame("model", index=dates, columns=cols)
    li = live_index.dropna(subset=["atm_iv"])
    for tenor, target in ((30, atm30), (90, atm90)):
        s = li[li["tenor"] == tenor].set_index("date")
        for d, row in s.iterrows():
            if d in target.index:
                target.at[d, INDEX] = row["atm_iv"]
                if tenor == 30:
                    rr30.at[d, INDEX], source.at[d, INDEX] = row["rr25"], "live chain"
    ls = live_single[live_single["ticker"].isin(names)].dropna(subset=["atm_iv"])
    for tenor, target in ((30, atm30), (90, atm90)):
        s = ls[ls["tenor"] == tenor]
        for _, row in s.iterrows():
            if row["date"] in target.index:
                target.at[row["date"], row["ticker"]] = row["atm_iv"]
                if tenor == 30:
                    rr30.at[row["date"], row["ticker"]] = row["rr25"]
                    source.at[row["date"], row["ticker"]] = "live chain"

    live_beta = rr30 / (RR_TO_BETA * atm30)
    beta = pd.DataFrame(index=dates, columns=cols, dtype=float)
    for c in cols:
        med = live_beta[c].median()
        fallback = DEFAULT_BETA.get(c, DEFAULT_SINGLE_BETA) if pd.isna(med) else med
        beta[c] = live_beta[c].fillna(fallback)

    keep = atm30.notna().all(axis=1) & spot.notna().all(axis=1)
    sel = lambda f: f.loc[keep]  # noqa: E731
    return Marks(spot=sel(spot), atm30=sel(atm30), atm90=sel(atm90), beta=sel(beta), source=sel(source),
                 model_atm30=sel(model), vixfam=vixfam.reindex(dates).ffill(limit=3).loc[keep],
                 corr_factor=corr_factor.loc[keep], div_yield=div_yield)
