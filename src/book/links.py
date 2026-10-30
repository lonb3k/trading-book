"""The book is built on the three research projects, imported from their sibling checkouts.

    trd/vol_dashboard     Black-76, the S&P 500 ATM-vol history (VXO, then a VIX + SKEW model), the
                          daily SPY skew snapshot used as the live index mark
    trd/dispersion        the top-50 basket, its realized moments, the single-name implied-vol rebuild
                          from COR1M, the daily 50-chain snapshot used as live single-name marks
    trd/basket_optimizer  (step 2) the optimizer that proposes client baskets from the book's axes

Locally the four folders sit side by side. The daily GitHub Actions job checks the three repos out
next to this one, so the same relative paths hold there.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # trading_book/
WORKSPACE = ROOT.parent                              # folder holding the sister projects
VOL_DIR = WORKSPACE / "vol_dashboard"
DISP_DIR = WORKSPACE / "dispersion"
BASKET_DIR = WORKSPACE / "basket_optimizer"

for _d in (VOL_DIR, DISP_DIR, BASKET_DIR):
    _src = str(_d / "src")
    if (_d / "src").exists() and _src not in sys.path:
        sys.path.append(_src)

from vol_dashboard.atm import load_vxo, sp_atm_vol  # noqa: E402
from vol_dashboard.charts import C, GRID, LAYOUT, MUTED, SERIES, TEXT  # noqa: E402
from vol_dashboard.options import RISK_FREE, black76_price  # noqa: E402
from dispersion.decomposition import C_SINGLE_VS, basket_moments  # noqa: E402

VOL_SKEW_HISTORY = VOL_DIR / "data" / "skew_history.csv"
DISP_DATA = DISP_DIR / "data"
TOP50_WEIGHTS = DISP_DATA / "weights_top50.csv"

__all__ = ["C", "GRID", "LAYOUT", "MUTED", "SERIES", "TEXT", "ROOT", "WORKSPACE", "VOL_DIR", "DISP_DIR", "BASKET_DIR", "load_vxo", "sp_atm_vol", "RISK_FREE",
           "black76_price", "C_SINGLE_VS", "basket_moments", "VOL_SKEW_HISTORY", "DISP_DATA", "TOP50_WEIGHTS"]
