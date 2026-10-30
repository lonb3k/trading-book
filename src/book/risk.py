"""Limits, axes and the independent check of the marks.

Axes. The official marks stay at mid: they are what product control checks and what the P&L is
measured on. The axes only move the price of *new* deals. A desk long vega on a name wants to sell
vol on it, so it quotes that name's vol below mid on any product where the client buys vol, and less
generously where the client sells it. The shift grows with the share of the vega limit used:

    axe shift (vol points) = - max shift x clip(vega / vega limit, -1, 1)

Step 2 of the project feeds these shifts to the basket optimizer, which then proposes client baskets
that recycle the book's risk.

Independent price verification (IPV). On days with a live option chain, the official mark is the chain;
the model mark the book used before is kept next to it. The gap, times the vega, is the P&L the remark
moved, which is the number a product-control team asks the desk to explain.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import BookResult
from .marks import INDEX

VEGA_LIMIT = {INDEX: 250_000.0, "single": 50_000.0}       # USD per vol point, absolute
CORR01_LIMIT = 75_000.0                                     # USD per correlation point, absolute
MAX_SHIFT = {INDEX: 0.5, "single": 1.0}                     # vol points at 100% of the limit


def limit_of(und: str) -> float:
    return VEGA_LIMIT[INDEX] if und == INDEX else VEGA_LIMIT["single"]


def axe_shift(vega: float, und: str) -> float:
    cap = MAX_SHIFT[INDEX] if und == INDEX else MAX_SHIFT["single"]
    return float(-cap * np.clip(vega / limit_of(und), -1.0, 1.0))


def risk_today(res: BookResult) -> pd.DataFrame:
    last = res.daily.index[-1]
    r = res.risk[res.risk["date"] == last].set_index("underlying").copy()
    r["limit"] = [limit_of(u) for u in r.index]
    r["usage"] = r["vega"] / r["limit"]
    return r


def axes(res: BookResult) -> pd.DataFrame:
    """One row per underlying, ranked by how much of the limit the book uses."""
    m = res.marks
    last = res.daily.index[-1]
    r = risk_today(res)
    rows = []
    for u, row in r.iterrows():
        shift = axe_shift(row["vega"], u)
        mid3m = m.atm(last, u, 91)
        if abs(row["usage"]) < 0.05:
            direction = "flat"
        else:
            direction = "sell vol" if row["vega"] > 0 else "buy vol"
        rows.append({"underlying": u, "vega": row["vega"], "limit": row["limit"], "usage": row["usage"],
                     "direction": direction, "shift": shift, "mid_3m": mid3m, "axed_3m": mid3m + shift})
    out = pd.DataFrame(rows)
    return out.reindex(out["usage"].abs().sort_values(ascending=False).index).reset_index(drop=True)


def correlation_axe(res: BookResult) -> dict:
    c = float(res.daily["corr01"].iloc[-1])
    return {"corr01": c, "limit": CORR01_LIMIT, "usage": c / CORR01_LIMIT,
            "direction": "buy correlation" if c < 0 else "sell correlation" if c > 0 else "flat"}


def ipv(res: BookResult) -> pd.DataFrame:
    """Model mark against live-chain mark on the last day, with the P&L the gap represents."""
    m = res.marks
    last = res.daily.index[-1]
    r = risk_today(res)
    rows = []
    for u in m.underlyings:
        live = m.source.at[last, u] == "live chain"
        model, mark = m.model_atm30.at[last, u], m.atm30.at[last, u]
        rows.append({"underlying": u, "source": m.source.at[last, u], "model_atm30": model,
                     "live_atm30": mark if live else np.nan, "gap": (mark - model) if live else np.nan,
                     "pnl_impact": r.at[u, "vega"] * (mark - model) if live else np.nan})
    return pd.DataFrame(rows)
