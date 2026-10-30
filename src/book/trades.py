"""The fictitious trade blotter. Every trade is a client deal: the desk's side is the opposite of the client's.

Strikes are in percent of spot on the trade date and sizes in dollars (option notional, or variance-swap
vega), so the blotter never depends on the price level of the data.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .data import DATA_DIR

BLOTTER = DATA_DIR / "trades.csv"

# Half the bid-ask the desk charges, in vol points: client buys above mid, sells below mid.
SPREAD = {"option": {"SPX": 0.4, "single": 1.0}, "varswap": {"SPX": 0.5, "single": 1.0}}


@dataclass
class Trade:
    id: str
    trade_date: pd.Timestamp
    maturity: pd.Timestamp
    client: str
    product: str            # put, call, varswap
    underlying: str
    strike_pct: float | None
    notional: float | None  # options, USD
    vega: float | None      # variance swaps, USD per vol point
    sign: int               # +1 desk long, -1 desk short
    note: str

    @property
    def is_option(self) -> bool:
        return self.product in ("put", "call")

    def spread(self) -> float:
        kind = "option" if self.is_option else "varswap"
        return SPREAD[kind]["SPX" if self.underlying == "SPX" else "single"]

    def label(self) -> str:
        side = "long" if self.sign > 0 else "short"
        if self.is_option:
            return f"{side} {self.underlying} {self.strike_pct:g}% {self.product} {self.maturity:%b-%y}"
        return f"{side} {self.underlying} variance swap {self.maturity:%b-%y}"


def maturity_of(trade_date: pd.Timestamp, months: int) -> pd.Timestamp:
    m = trade_date + pd.DateOffset(months=months)
    while m.weekday() >= 5:
        m -= pd.Timedelta(days=1)
    return m


def load_trades(path=BLOTTER) -> list[Trade]:
    df = pd.read_csv(path, parse_dates=["trade_date"])
    out = []
    for r in df.itertuples(index=False):
        out.append(Trade(id=r.id, trade_date=r.trade_date, maturity=maturity_of(r.trade_date, int(r.tenor_months)),
                         client=r.client, product=r.product, underlying=r.underlying,
                         strike_pct=None if pd.isna(r.strike_pct) else float(r.strike_pct),
                         notional=None if pd.isna(r.notional_usd) else float(r.notional_usd),
                         vega=None if pd.isna(r.vega_usd) else float(r.vega_usd),
                         sign=1 if r.desk_side == "long" else -1, note=r.note))
    return sorted(out, key=lambda t: (t.trade_date, t.id))
