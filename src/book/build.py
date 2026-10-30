"""Assemble the market for the book from the data layer and the sister projects."""
from __future__ import annotations

import pandas as pd

from .data import VIX_FAMILY, live_index_marks, live_single_marks, load_cboe, load_closes, top50_weights
from .engine import BookResult, run_book
from .links import load_vxo
from .marks import Marks, build_marks
from .trades import load_trades

NAMES = ["AAPL", "NVDA", "MSFT", "AMZN", "TSLA"]
DIV_YIELD = {"SPX": 0.012, "AAPL": 0.004, "MSFT": 0.007, "NVDA": 0.0, "AMZN": 0.0, "TSLA": 0.0}
HISTORY_START = "2025-01-01"   # 63-day trailing vols need a few months before the first trade
VOL_START = "2004-01-01"       # the ATM / VIX model is fitted on the VXO years


def load_market(offline: bool = False, start: str | None = None) -> Marks:
    trades = load_trades()
    first = start or str(min(t.trade_date for t in trades).date())
    w = top50_weights()
    tickers = sorted(set(w.index) | set(NAMES))
    eq = load_closes(tickers, HISTORY_START, "closes_equities", offline)
    spx = load_closes(["^GSPC"], HISTORY_START, "closes_spx", offline)
    vol = load_closes(list(VIX_FAMILY) + ["^SKEW"], VOL_START, "closes_vol_indices", offline)
    vixfam = pd.DataFrame({days: vol[t] for t, days in VIX_FAMILY.items()})
    closes = eq.join(spx, how="outer")
    return build_marks(closes=closes, names=NAMES, vixfam=vixfam, skew_idx=vol["^SKEW"], vxo=load_vxo(offline=True),
                       cor1m=load_cboe("COR1M", offline), top50=eq[[c for c in w.index if c in eq]],
                       weights=w[[c for c in w.index if c in eq]], live_single=live_single_marks(),
                       live_index=live_index_marks(), div_yield=DIV_YIELD, start=first)


def run(offline: bool = False) -> BookResult:
    return run_book(load_market(offline), load_trades())
