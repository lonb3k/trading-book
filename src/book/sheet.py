"""The book's morning sheet: the same JSON contract as the three research projects, rendered by the
Next.js front end at /book. No financial logic here: every number comes from engine.py and risk.py."""
from __future__ import annotations

import datetime as dt
import json
import math
from typing import Any

import numpy as np
import pandas as pd
import plotly.io as pio

from . import charts, risk
from .engine import LINES, BookResult

SPARK_POINTS = 60
LINE_NAMES = {"new_deals": "New deals (day-one margin)", "delta": "Delta", "hedge": "Delta hedge",
              "gamma": "Gamma", "vega": "Vega", "theta": "Theta", "hedge_costs": "Hedging costs",
              "unexplained": "Unexplained"}


def _num(x: Any, digits: int = 2) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, digits) if math.isfinite(v) else None


def _spark(s: pd.Series, points: int = SPARK_POINTS) -> list[float]:
    s = s.dropna().iloc[-points:]
    return [round(float(v), 3) for v in s.values]


def _compact(obj):
    if isinstance(obj, list):
        if obj and all(isinstance(v, str) and v.endswith("T00:00:00") for v in obj):
            return [v[:10] for v in obj]
        if obj and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in obj):
            return [round(v, 3) if isinstance(v, float) else v for v in obj]
        return [_compact(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _compact(v) for k, v in obj.items()}
    return obj


def _fig(fig, chart_id: str) -> dict:
    d = _compact(json.loads(pio.to_json(fig, validate=False)))
    d["layout"].pop("template", None)
    return {"id": chart_id, "title": fig.layout.title.text, "figure": d}


def tile(label, value, unit="", sub="", spark=None, tone="neutral", digits=1) -> dict:
    return {"label": label, "value": _num(value, digits), "unit": unit, "sub": sub, "tone": tone,
            "spark": _spark(spark) if spark is not None else []}


def _tone(v: float) -> str:
    return "pos" if v > 0 else "neg" if v < 0 else "neutral"


def _k(v: float, digits: int = 0) -> str:
    """Signed thousands of dollars, e.g. +85k / -1,204k."""
    if v is None or not math.isfinite(v):
        return "–"
    sign = "+" if v > 0 else "−" if v < 0 else ""
    return f"{sign}${abs(v) / 1e3:,.{digits}f}k"


def _m(v: float) -> str:
    sign = "+" if v > 0 else "−" if v < 0 else ""
    return f"{sign}${abs(v) / 1e6:,.2f}m"


def build_sheet(res: BookResult) -> dict:
    d = res.daily
    last = d.index[-1]
    today = d.iloc[-1]
    month = d[d.index >= last.replace(day=1)]
    ax = risk.axes(res)
    corr = risk.correlation_axe(res)
    rt = risk.risk_today(res)
    ipv = risk.ipv(res)
    m = res.marks
    warnings = []
    model_today = [u for u in m.underlyings if m.source.at[last, u] != "live chain"]
    if model_today:
        warnings.append(f"no live chain captured today for {', '.join(model_today)}: marked by the model")

    biggest = max([(abs(r["usage"]), r["underlying"], r["usage"]) for _, r in ax.iterrows()] +
                  [(abs(corr["usage"]), "Correlation", corr["usage"])])
    headline = (f"{last:%A %d %B %Y}. The simulated book made {_k(today['pnl'])} today and {_m(today['total_pnl'])} since "
                f"{d.index[0]:%B %Y} on {len(res.trades)} fictitious client trades ({int(today['live_trades'])} live). "
                f"Net vega {_k(today['net_vega'])} per vol point; Corr01 {_k(corr['corr01'])} per correlation point "
                f"({abs(corr['usage']) * 100:.0f}% of its limit), so the first axe is to {corr['direction']}.")

    tiles = [
        tile("P&L today", today["pnl"] / 1e3, "k$", f"month to date {_k(month['pnl'].sum())}",
             d["pnl"] / 1e3, _tone(today["pnl"]), 0),
        tile("P&L since inception", today["total_pnl"] / 1e6, "m$", f"since {d.index[0]:%d %b %Y}",
             d["total_pnl"] / 1e6, _tone(today["total_pnl"]), 2),
        tile("Net vega", today["net_vega"] / 1e3, "k$/pt", f"index {_k(today['index_vega'])}, singles {_k(today['single_vega'])}",
             d["net_vega"] / 1e3, "neutral", 0),
        tile("Corr01", corr["corr01"] / 1e3, "k$/pt", f"{abs(corr['usage']) * 100:.0f}% of the ${corr['limit'] / 1e3:.0f}k limit",
             d["corr01"] / 1e3, "neg" if abs(corr["usage"]) > 0.8 else "neutral", 0),
        tile("Live trades", today["live_trades"], "trades", f"{len(res.trades)} booked since inception",
             d["live_trades"], "neutral", 0),
        tile("Largest limit usage", abs(biggest[2]) * 100, "%", f"{biggest[1]}, {'long' if biggest[2] > 0 else 'short'}",
             None, "neg" if abs(biggest[2]) > 0.8 else "neutral", 0),
    ]

    # ----- ideas: the axes, ranked by limit usage
    rows = [{"underlying": "Correlation", "usage": corr["usage"], "vega": corr["corr01"], "direction": corr["direction"],
             "shift": None, "mid_3m": None, "axed_3m": None, "limit": corr["limit"]}] + ax.to_dict("records")
    rows = sorted(rows, key=lambda r: -abs(r["usage"]))
    ideas = []
    for r in rows[:4]:
        u = r["underlying"]
        n_trades = int(sum(1 for t in res.positions.itertuples() if t.status == "live" and (u == "Correlation" and t.underlying == "SPX" or t.underlying == u)))
        if u == "Correlation":
            title = f"{r['direction'].capitalize()}: Corr01 {_k(r['vega'])} per point"
            instrument = "Worst-of or dispersion structures where the client sells correlation (step 2)"
            condition = f"index vega {_k(today['index_vega'])}, Corr01 at {abs(r['usage']) * 100:.0f}% of the limit"
            thesis = ("The client puts sold on the S&P 500 leave the desk short index vol with single-name vols unchanged, "
                      "which is short correlation: the book loses if stocks start moving together, as in a sell-off. "
                      "The dispersion project measured that risk; this is the desk carrying it.")
            stats = {"expected": None, "expected_unit": "", "hit": _num(abs(r["usage"]) * 100, 0),
                     "worst": _num(r["vega"] / 1e3, 0), "worst_unit": "k$ per correlation point", "n": n_trades,
                     "sample": "live index trades", "labels": {"expected": "Axe", "hit": "Limit used", "hit_unit": "of the Corr01 limit",
                                                                "worst": "Corr01", "sample": "Trades behind it"}}
        else:
            title = f"{r['direction'].capitalize()} on {u}: quote {r['axed_3m']:.1f} against a {r['mid_3m']:.1f} mid (3M ATM)"
            instrument = ("Products where the client buys vol on the name: call spreads, capital-protected notes"
                          if r["vega"] > 0 else "Products where the client sells vol on the name: reverse convertibles, put writing")
            condition = f"vega {_k(r['vega'])} per vol point, {abs(r['usage']) * 100:.0f}% of the ${r['limit'] / 1e3:.0f}k limit"
            thesis = (f"The book is {'long' if r['vega'] > 0 else 'short'} {u} vol. New deals that "
                      f"{'sell' if r['vega'] > 0 else 'buy'} it back are priced {abs(r['shift']):.2f} vol point "
                      f"{'below' if r['shift'] < 0 else 'above'} mid; the official mark stays at mid.")
            stats = {"expected": _num(r["shift"], 2), "expected_unit": "vol points on new quotes", "hit": _num(abs(r["usage"]) * 100, 0),
                     "worst": _num(r["vega"] / 1e3, 0), "worst_unit": "k$ per vol point", "n": n_trades, "sample": "live trades",
                     "labels": {"expected": "Axe vs mid", "hit": "Limit used", "hit_unit": "of the vega limit",
                                "worst": "Book vega", "sample": "Trades behind it"}}
        ideas.append({"rank": len(ideas) + 1, "title": title, "direction": r["direction"], "instrument": instrument,
                      "condition": condition, "thesis": thesis, "stats": stats, "score": _num(abs(r["usage"]), 2)})

    # ----- sections
    explain_rows = []
    for k in ["new_deals", "delta", "hedge", "gamma", "vega", "theta", "hedge_costs", "unexplained"]:
        explain_rows.append([LINE_NAMES[k], _num(today[k] / 1e3, 1), _num(month[k].sum() / 1e3, 1), _num(d[k].sum() / 1e3, 1)])
    explain_rows.append(["Total", _num(today["pnl"] / 1e3, 1), _num(month["pnl"].sum() / 1e3, 1), _num(d["pnl"].sum() / 1e3, 1)])
    big = res.explain.loc[res.explain["unexplained"].abs().sort_values(ascending=False).index[:3]]
    jumps = []
    for r in big.itertuples():
        s = m.spot[r.underlying]
        ret = s.loc[r.date] / s.shift(1).loc[r.date] - 1
        jumps.append(f"{r.trade} on {r.date:%d %b} ({r.underlying} {ret * 100:+.1f}%, {_k(r.unexplained)})")
    sections = [
        {"title": "Today's P&L, explained (k$)",
         "paragraphs": [
             "Greeks are taken at yesterday's close and applied to today's moves; the unexplained line is what they miss. "
             "Delta and its hedge cancel because the desk re-hedges every underlying at the close.",
             f"The largest unexplained days are earnings jumps, where a second-order expansion misses the convexity: {'; '.join(jumps)}."],
         "table": {"columns": ["Line", "Today", "Month to date", "Since inception"], "rows": explain_rows}},
        {"title": "Risk by underlying",
         "paragraphs": ["Vega in k$ per vol point, gamma as the P&L of a 1% move, theta per day, after today's deals. "
                        "Delta is hedged to zero at every close; the column shows what the hedge offsets."],
         "table": {"columns": ["Underlying", "Spot", "ATM 1M", "Mark", "Delta hedged (m$)", "Vega", "Gamma 1%", "Theta", "Limit used"],
                   "rows": [[u, _num(r["spot"], 2), _num(r["atm30"], 1), r["source"], _num(r["delta_usd"] / 1e6, 1),
                             _num(r["vega"] / 1e3, 1), _num(r["gamma_1pct"] / 1e3, 1), _num(r["theta"] / 1e3, 1),
                             f"{r['usage'] * 100:+.0f}%"] for u, r in rt.iterrows()]}},
        {"title": "Marks: model against live chains",
         "paragraphs": ["The official mark is the live chain whenever the sister projects captured it that evening. "
                        "The model mark is kept next to it, as a product-control team would: the gap times the vega is "
                        "the P&L the remark moved. Single-name gaps are largest around earnings, which a trailing-vol model cannot see."],
         "table": {"columns": ["Underlying", "Mark", "Model ATM 1M", "Live ATM 1M", "Gap (pts)", "P&L impact (k$)"],
                   "rows": [[r["underlying"], r["source"], _num(r["model_atm30"], 1), _num(r["live_atm30"], 1), _num(r["gap"], 1),
                             _num(r["pnl_impact"] / 1e3, 0) if pd.notna(r["pnl_impact"]) else None] for _, r in ipv.iterrows()]}},
        {"title": "Positions",
         "paragraphs": ["Every trade is a fictitious client deal; the desk holds the other side. P&L per trade is before "
                        "delta hedging, which is run across the book."],
         "table": {"columns": ["Id", "Client", "Desk position", "Status", "Value (k$)", "P&L (k$)", "Vega (k$/pt)"],
                   "rows": [[p.id, p.client, p.trade, p.status, _num(p.value / 1e3, 0), _num(p.pnl / 1e3, 0),
                             _num(p.vega / 1e3, 1)] for p in res.positions.itertuples()]}},
    ]

    method = ("Axes ranked by the share of the risk limit the book uses. Official marks stay at mid; the axe only shifts "
              "the price of new deals, by up to one vol point on a single name and half a point on the index at 100% of the limit.")
    caveats = [
        "Simulated book: the trades and clients are fictitious, the market data and the marks are real.",
        "Before the sister projects started capturing option chains (27 Oct 2026), the marks come from models: the S&P 500 ATM "
        "history of the vol dashboard and the dispersion project's single-name rebuild from COR1M. That rebuild cannot see "
        "earnings, so single-name history is marked too low before results and too high after.",
        "The surface is a parametrisation: an ATM term structure borrowed from the VIX family beyond the live tenors and a linear "
        "skew in standardised moneyness, calibrated on the live 25-delta risk reversal.",
        "Variance swaps on single names are marked at ATM x 1.10, the ratio measured on the 50 chains; no cap is modelled.",
        "No funding cost on cash or on the delta hedge, flat 4% rate, constant dividend yields.",
    ]
    return {
        "project": "trading_book", "slug": "book", "title": "Trading book",
        "subtitle": "Simulated equity-derivatives book on the S&P 500 and five Mag 7 names: marks, P&L explain, risk, axes",
        "as_of": f"{last:%Y-%m-%d}", "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "headline": headline, "tiles": tiles, "sections": sections, "ideas": ideas,
        "ideas_title": "Axes, ranked by limit usage",
        "charts": [_fig(charts.pnl_explain(res), "pnl_explain"), _fig(charts.vega_usage(ax, corr), "limits"),
                   _fig(charts.vega_history(res), "vega_history"), _fig(charts.marks_history(res), "marks")],
        "method": method, "caveats": caveats, "warnings": warnings,
        "links": {"repo": "https://github.com/lonb3k/trading-book",
                  "streamlit": "no separate app: this sheet is the book's front end"},
    }
