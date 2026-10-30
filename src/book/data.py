"""Market data for the book, mirrored to data/ so a run can be replayed offline.

Prices are Yahoo closes adjusted for splits but not for dividends (`auto_adjust=False`): they are the
prices options are struck on. Positions are sized in percent of spot and dollars of notional, so a
split later on rescales a whole history without changing any P&L.
"""
from __future__ import annotations

import warnings

import pandas as pd
import requests
import yfinance as yf

from .links import DISP_DATA, ROOT, TOP50_WEIGHTS, VOL_SKEW_HISTORY

DATA_DIR = ROOT / "data"
CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{index}_History.csv"
VIX_FAMILY = {"^VIX9D": 9, "^VIX": 30, "^VIX3M": 91, "^VIX6M": 182}


def _merge_save(new: pd.DataFrame, path) -> pd.DataFrame:
    if path.exists():
        old = pd.read_csv(path, index_col=0, parse_dates=True)
        new = new.combine_first(old) if not new.empty else old
    new = new.sort_index()
    new.index.name = "Date"
    new.to_csv(path)
    return new


def load_closes(tickers: list[str], start: str, name: str, offline: bool = False) -> pd.DataFrame:
    """Daily closes, one column per ticker, mirrored to data/<name>.csv."""
    path = DATA_DIR / f"{name}.csv"
    if offline and path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = yf.download(tickers, start=start, auto_adjust=False, progress=False, threads=True)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].rename(columns={"Close": tickers[0]})
        close.index = pd.to_datetime(close.index).tz_localize(None)
        close = close.dropna(how="all")
    except Exception:
        close = pd.DataFrame()
    return _merge_save(close, path)


def load_cboe(index: str, offline: bool = False) -> pd.Series:
    """Daily close of a CBOE index (COR1M...), mirrored to data/cboe_<index>.csv."""
    path = DATA_DIR / f"cboe_{index}.csv"
    if not offline or not path.exists():
        try:
            r = requests.get(CBOE_URL.format(index=index), timeout=30)
            r.raise_for_status()
            path.write_bytes(r.content)
        except Exception:
            pass
    if not path.exists():
        return pd.Series(dtype=float, name=index)
    df = pd.read_csv(path)
    df["DATE"] = pd.to_datetime(df["DATE"])
    return df.set_index("DATE")["CLOSE"].rename(index)


def top50_weights() -> pd.Series:
    """Today's top-50 S&P 500 weights from the dispersion project (re-weighted to sum to one)."""
    w = pd.read_csv(TOP50_WEIGHTS).set_index("ticker")["weight"]
    return w / w.sum()


def live_single_marks() -> pd.DataFrame:
    """Per-name ATM vol and 25-delta risk reversal from the dispersion project's daily 50-chain snapshot.
    One row per (date, ticker, tenor): the files are implied_snapshot_<date>_<30|90>d.csv."""
    rows = []
    for f in sorted(DISP_DATA.glob("implied_snapshot_*_*d.csv")):
        parts = f.stem.split("_")
        date, tenor = pd.Timestamp(parts[2]), int(parts[3].rstrip("d"))
        df = pd.read_csv(f)
        df["date"], df["tenor"] = date, tenor
        rows.append(df[["date", "tenor", "ticker", "atm_iv", "rr25", "days", "stale"]])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["date", "tenor", "ticker", "atm_iv", "rr25", "days", "stale"])


def live_index_marks() -> pd.DataFrame:
    """S&P 500 ATM vol and risk reversal from the vol dashboard's daily SPY skew snapshot."""
    if not VOL_SKEW_HISTORY.exists():
        return pd.DataFrame(columns=["date", "tenor", "atm_iv", "rr25", "days", "stale"])
    df = pd.read_csv(VOL_SKEW_HISTORY, parse_dates=["date"])
    df = df[df["asset"] == "S&P 500"].rename(columns={"tenor_target": "tenor"})
    return df[["date", "tenor", "atm_iv", "rr25", "days", "stale"]].reset_index(drop=True)
