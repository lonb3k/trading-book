"""Plotly figures, in the sister projects' palette and layout (one y-axis per chart, fixed colour order)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from .engine import BookResult
from .links import C, GRID, LAYOUT, MUTED, SERIES, TEXT

UND_COLOR = {u: SERIES[i] for i, u in enumerate(["SPX", "AAPL", "NVDA", "MSFT", "AMZN", "TSLA"])}


def _base(title: str, height: int = 380, **overrides) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(title=dict(text=title, x=0, y=0.98, yanchor="top", font=dict(size=14)), height=height,
                      **{**LAYOUT, **overrides})
    return fig


def pnl_explain(res: BookResult) -> go.Figure:
    d = res.daily.copy()
    groups = {"New deals (day-one margin)": d["new_deals"], "Gamma": d["gamma"], "Vega": d["vega"],
              "Theta": d["theta"], "Hedging costs": d["hedge_costs"], "Unexplained": d["unexplained"]}
    fig = _base("Cumulative P&L and what explains it, $m (delta is hedged to zero every close)",
                yaxis=dict(gridcolor=GRID, zeroline=True, zerolinecolor=MUTED, ticksuffix=""))
    for i, (name, s) in enumerate(groups.items()):
        fig.add_trace(go.Scatter(x=d.index, y=s.cumsum() / 1e6, name=name, mode="lines",
                                 line=dict(width=1.5, color=SERIES[i]), hovertemplate="%{y:.2f}m"))
    fig.add_trace(go.Scatter(x=d.index, y=d["total_pnl"] / 1e6, name="Total", mode="lines",
                             line=dict(width=2.5, color=TEXT), hovertemplate="%{y:.2f}m"))
    return fig


def vega_usage(axes: pd.DataFrame, corr: dict) -> go.Figure:
    names = list(axes["underlying"]) + ["Correlation"]
    usage = list(axes["usage"] * 100) + [corr["usage"] * 100]
    fig = _base("Risk against limits today: vega by underlying, and Corr01, % of limit",
                yaxis=dict(gridcolor=GRID, zeroline=True, zerolinecolor=MUTED, ticksuffix="%"), hovermode="closest")
    fig.add_trace(go.Bar(x=names, y=usage, marker_color=[C["blue"] if v >= 0 else C["orange"] for v in usage],
                         hovertemplate="%{x}: %{y:.0f}% of limit<extra></extra>"))
    for lvl in (100, -100):
        fig.add_hline(y=lvl, line=dict(color=C["red"], width=1, dash="dot"))
    fig.update_layout(showlegend=False)
    return fig


def vega_history(res: BookResult) -> go.Figure:
    v = res.risk.pivot(index="date", columns="underlying", values="vega")
    fig = _base("Vega by underlying, $k per vol point",
                yaxis=dict(gridcolor=GRID, zeroline=True, zerolinecolor=MUTED, ticksuffix=""))
    for u in v.columns:
        fig.add_trace(go.Scatter(x=v.index, y=v[u] / 1e3, name=u, mode="lines",
                                 line=dict(width=1.5, color=UND_COLOR.get(u, MUTED)), hovertemplate="%{y:.0f}k"))
    return fig


def marks_history(res: BookResult) -> go.Figure:
    a = res.marks.atm30
    fig = _base("One-month ATM marks, vol points (model until the live chains, then the chains)",
                yaxis=dict(gridcolor=GRID, zeroline=False, ticksuffix=""))
    for u in a.columns:
        fig.add_trace(go.Scatter(x=a.index, y=a[u], name=u, mode="lines",
                                 line=dict(width=1.5, color=UND_COLOR.get(u, MUTED)), hovertemplate="%{y:.1f}"))
    return fig
