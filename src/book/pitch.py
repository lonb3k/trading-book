"""Step 2: the basket optimizer proposes client baskets from the book's axes.

Once a week, at the close of the first trading day, sales call the one client whose note best recycles
the book's risk:

1. Candidate baskets. Every 3, 4 and 5-name subset of the book's single names, weighted by each of the
   basket optimizer's six schemes (equal weight, inverse vol, min variance, risk parity, max
   diversification, HRP), run on a forward-looking covariance: the names' one-year implied vols from
   tonight's marks and the Ledoit-Wolf correlation. Weights under 5% are dropped.
2. Quotes. The desk prices each note with its axes: each name's vol moved by its axe shift, the
   correlation by the correlation axe, then its usual one-point spread on the basket vol. The street
   prices the same note at mid with the same spread and no axe. Reverse convertibles are quoted as the
   strike that pays the client's coupon; capital-protected notes as a participation.
3. Winnable notes. Those the client would take: a lower strike than the street (reverse convertibles), or
   a participation above the client's minimum and above the street (capital-protected notes).
4. Choice. Among winnable notes, every client and ticket size, the desk pitches the one that most reduces
   the book's risk score (sum of squared limit usages, vega per name and Corr01). No pitch if none does.
   The trade is booked that evening.

The axes do the selection, the optimizer supplies sensible baskets: a name the book is long vol on is
quoted below mid, so the desk wins capital-protected notes on it and loses reverse convertibles on it.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .basket import basket_greeks, basket_price_at, basket_value
from .clients import BEAT_STREET, CLIENTS, STRIKE_RANGE, Client
from .links import WEIGHT_SCHEMES
from .marks import Marks
from .risk import axe_shift, corr_axe_shift, risk_score
from .trades import Trade, maturity_of

PITCH_START = pd.Timestamp("2026-01-05")
MIN_WEIGHT = 0.05


def pitch_days(dates: pd.DatetimeIndex) -> set:
    """First trading day of each week."""
    s = pd.Series(dates, index=dates)
    return set(s.groupby(dates.to_period("W")).min())


def candidate_baskets(m: Marks, d, names: list[str], t: float) -> list[tuple[str, dict]]:
    out, seen = [], set()
    vols = pd.Series({n: m.atm(d, n, t * 365) / 100 for n in names})
    corr = pd.DataFrame(m.corr_matrix(d, names), index=names, columns=names)
    for size in (3, 4, 5):
        for combo in combinations(names, size):
            c = list(combo)
            cov = corr.loc[c, c] * np.outer(vols[c], vols[c])
            for scheme, fn in WEIGHT_SCHEMES.items():
                try:
                    w = fn(cov, max_weight=0.6)
                except Exception:
                    continue
                w = w[w >= MIN_WEIGHT]
                w = (w / w.sum()).round(4)
                key = tuple(sorted(w.items()))
                if len(w) < 3 or key in seen:
                    continue
                seen.add(key)
                out.append((scheme, w.to_dict()))
    return out


def quote(m: Marks, d, cl: Client, args: dict, shifts: dict, c_shift: float) -> dict | None:
    """Desk and street terms for one note on one basket. None if the desk cannot build it."""
    t = args["t"]
    sign = cl.desk_sign

    def sigma(k, axed):
        a = {**args, "k": k}
        if axed:
            return basket_value(m, d, **a, notional=1.0, vol_bump=shifts, corr_bump=c_shift)[1] - 0.01 * sign
        return basket_value(m, d, **a, notional=1.0)[1] - 0.01 * sign

    def terms(k, axed):
        a = {**args, "k": k}
        return cl.terms(basket_price_at(m, d, **a, notional=1.0, sigma_b=sigma(k, axed)), t, m.rate)

    if cl.product == "basket_put":
        lo, hi = STRIKE_RANGE[0] / 100, STRIKE_RANGE[1] / 100
        out = {}
        for side in ("desk", "street"):
            f = lambda k: terms(k, side == "desk") - cl.target  # noqa: E731
            if f(hi) < 0 or f(lo) > 0:
                return None
            out[side] = brentq(f, lo, hi, xtol=1e-5)
        k = out["desk"]
        return {"k": k, "desk": 100 * k, "street": 100 * out["street"], "won": 100 * (out["street"] - k) >= BEAT_STREET[cl.product],
                "sig_desk": sigma(k, True), "sig_mid": basket_value(m, d, **{**args, "k": k}, notional=1.0)[1]}
    k = cl.strike_pct / 100
    desk, street = terms(k, True), terms(k, False)
    return {"k": k, "desk": desk, "street": street, "won": desk >= cl.target and desk - street >= BEAT_STREET[cl.product],
            "sig_desk": sigma(k, True), "sig_mid": basket_value(m, d, **{**args, "k": k}, notional=1.0)[1]}


class Pitcher:
    """Callable for run_book. Pitches on the first trading day of each week on or after `start`."""

    def __init__(self, dates: pd.DatetimeIndex, names: list[str], after: pd.Timestamp | None = None):
        start = PITCH_START if after is None else max(PITCH_START, after + pd.Timedelta(days=1))
        self.days = sorted(d for d in pitch_days(dates) if d >= start)
        self.names = names
        self.booked: list[Trade] = []   # the trades clients accepted during this run

    def __call__(self, d, m: Marks, agg: dict, corr01: float, live) -> list:
        if d not in self.days:
            return []
        vegas = {u: a["vega"] for u, a in agg.items()}
        before = risk_score(vegas, corr01)
        shifts = {n: axe_shift(agg[n]["vega"], n) for n in self.names}
        c_shift = corr_axe_shift(corr01)
        ref = {n: m.spot.at[d, n] for n in self.names}
        mat = maturity_of(d, CLIENTS[0].tenor_months)
        t = (mat - d).days / 365
        baskets = candidate_baskets(m, d, self.names, t)
        best, n_quoted, n_won = None, 0, 0
        for cl in CLIENTS:
            for scheme, w in baskets:
                names = list(w)
                args = dict(names=names, weights=np.array([w[n] for n in names]), ref={n: ref[n] for n in names},
                            k=1.0, t=t, is_call=cl.product == "basket_call")
                q = quote(m, d, cl, args, shifts, c_shift)
                if q is None:
                    continue
                n_quoted += 1
                if not q["won"]:
                    continue
                n_won += 1
                g = basket_greeks(m, d, **{**args, "k": q["k"]}, notional=cl.desk_sign)   # per dollar, desk side
                for size in cl.sizes:
                    after = risk_score({u: v + size * g.vega.get(u, 0.0) for u, v in vegas.items()}, corr01 + size * g.corr01)
                    if best is None or before - after > best["gain"]:
                        best = dict(client=cl, scheme=scheme, basket=w, size=size, gain=before - after, after=after,
                                    corr01=size * g.corr01, **q)
        log = {"date": d.date(), "score_before": round(before, 4), "notes_quoted": n_quoted, "notes_winnable": n_won}
        if best is None or best["gain"] <= 0:
            reason = "no winnable note" if n_won == 0 else "no winnable note reduces the book's risk"
            return [(None, {**log, "result": f"no pitch: {reason}"})]
        cl = best["client"]
        unit = "% strike" if cl.product == "basket_put" else "% participation"
        log.update({"client": cl.name, "note": cl.note, "target": cl.target,
                    "basket": ";".join(f"{n}:{v:.4f}" for n, v in best["basket"].items()), "scheme": best["scheme"],
                    "size": best["size"], "desk_terms": round(best["desk"], 2), "street_terms": round(best["street"], 2),
                    "terms_unit": unit, "basket_vol_mid": round(100 * best["sig_mid"], 2),
                    "basket_vol_desk": round(100 * best["sig_desk"], 2), "score_after": round(best["after"], 4),
                    "corr01": round(best["corr01"], 0), "result": "accepted"})
        what = (f"{cl.target:g}% coupon struck at {best['desk']:.1f}% against {best['street']:.1f}% on the street"
                if cl.product == "basket_put" else
                f"{best['desk']:.1f}% participation against {best['street']:.1f}% on the street (minimum {cl.target:g}%)")
        tr = Trade(id=f"P{d:%y%m%d}", trade_date=d, maturity=mat, client=cl.name, product=cl.product, underlying="BASKET",
                   strike_pct=round(100 * best["k"], 2), notional=best["size"], vega=None, sign=cl.desk_sign,
                   note=f"{cl.note.capitalize()} pitched on {d:%d %b %Y}: {what}; {best['scheme']} weights; "
                        f"risk score {before:.2f} to {best['after']:.2f}",
                   basket=best["basket"], trade_vol=round(best["sig_desk"], 6))
        log["trade"] = tr.id
        self.booked.append(tr)
        log["strike_pct"] = tr.strike_pct
        return [(tr, log)]
