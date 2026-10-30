"""The daily loop: book new deals, revalue, explain the P&L, settle expiries, re-hedge.

Every evening, for each trade alive the evening before:

    actual P&L  = value today - value yesterday              (cash at expiry counts as value)
    delta       = Delta x dS                                 Greeks taken yesterday evening
    gamma       = 1/2 x Gamma x dS^2
    vega        = Vega x (vol today - vol yesterday)         same strike, each evening's surface
    theta       = repricing yesterday's position one day later, nothing else moved
    unexplained = actual - (delta + gamma + vega + theta)

Variance swaps have no delta; their gamma is the day's squared return accruing to the payoff, their
theta the day's share of the strike, their vega the change in the fair strike for the remaining life.

New deals are booked at the client price (mid vol plus or minus the spread) and revalued at mid the
same evening: the difference is the day-one P&L. The desk then delta-hedges every underlying at the
close with the underlying itself, paying `HEDGE_COST_BP` on what it trades. No funding cost on cash.
The identity  daily P&L = new deals + sum of the explain lines + hedge P&L - hedge costs  holds to the
cent, unexplained included; a large unexplained is the warning sign a desk looks for.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .marks import INDEX, Marks
from .pricing import option_greeks, option_price, varswap_settle, varswap_value
from .trades import Trade

HEDGE_COST_BP = {"SPX": 1.0, "single": 2.0}
LINES = ["new_deals", "delta", "gamma", "vega", "theta", "unexplained", "hedge", "hedge_costs"]
BUCKETS = [(0, 31, "<1M"), (31, 92, "1-3M"), (92, 183, "3-6M"), (183, 366, "6-12M"), (366, 10**6, ">1Y")]


def bucket_of(days: float) -> str:
    return next(lbl for lo, hi, lbl in BUCKETS if lo <= days < hi)


@dataclass
class Position:
    trade: Trade
    booked: pd.Timestamp
    qty: float = 0.0           # options: signed units of underlying; varswaps: signed variance notional
    strike: float = 0.0        # options: absolute strike; varswaps: strike in vol points
    trade_vol: float = 0.0     # vol the client dealt at (options, decimal)
    n_total: int = 0
    n_obs: int = 0
    sum_r2: float = 0.0
    value: float = 0.0
    cash: float = 0.0          # premiums and settlements of this trade
    alive: bool = True
    expired_on: pd.Timestamp | None = None


@dataclass
class BookResult:
    daily: pd.DataFrame        # one row per day: P&L lines, totals, risk
    explain: pd.DataFrame      # one row per (day, trade): P&L lines
    risk: pd.DataFrame         # one row per (day, underlying): delta$, gamma, vega, theta, hedge units
    vega_buckets: pd.DataFrame # last day: underlying x maturity bucket
    positions: pd.DataFrame    # last day, every trade ever booked
    marks: Marks
    trades: list[Trade] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)   # data problems the sheet should show


def _t(maturity: pd.Timestamp, d: pd.Timestamp) -> float:
    return max((maturity - d).days, 0) / 365


def _option_eval(m: Marks, d, p: Position, spot: float | None = None):
    tr = p.trade
    t = _t(tr.maturity, d)
    s = m.spot.at[d, tr.underlying] if spot is None else spot
    vol = m.vol(d, tr.underlying, p.strike, t, spot=s)
    g = option_greeks(s, p.strike, t, vol, m.rate, m.div_yield.get(tr.underlying, 0.0), tr.product == "call")
    return vol, g


def _varswap_state(m: Marks, d, p: Position, n_obs: int, sum_r2: float):
    tr = p.trade
    days_rem = max((tr.maturity - d).days, 0)
    n_rem = max(p.n_total - n_obs, 0)
    k_rem = m.varswap(d, tr.underlying, days_rem) if n_rem > 0 else 0.0
    df = np.exp(-m.rate * days_rem / 365)
    value = p.qty * varswap_value(1.0, p.strike, sum_r2, p.n_total, n_rem, k_rem, df)
    return value, k_rem, n_rem, df


def _book(m: Marks, d, tr: Trade) -> tuple[Position, float]:
    """Open a position at the client price. Returns it and the day-one P&L."""
    p = Position(trade=tr, booked=d)
    s0 = m.spot.at[d, tr.underlying]
    if tr.is_option:
        p.strike = tr.strike_pct / 100 * s0
        p.qty = tr.sign * tr.notional / s0
        t = _t(tr.maturity, d)
        mid = m.vol(d, tr.underlying, p.strike, t)
        p.trade_vol = mid - tr.sign * tr.spread() / 100       # desk buys below mid, sells above
        q = m.div_yield.get(tr.underlying, 0.0)
        is_call = tr.product == "call"
        traded = option_price(s0, p.strike, t, p.trade_vol, m.rate, q, is_call)
        fair = option_price(s0, p.strike, t, mid, m.rate, q, is_call)
        p.cash = -p.qty * traded
        p.value = p.qty * fair
        return p, p.value + p.cash
    days = (tr.maturity - d).days
    k_mid = m.varswap(d, tr.underlying, days)
    p.strike = k_mid - tr.sign * tr.spread()                   # desk pays less fixed when long, more when short
    p.qty = tr.sign * tr.vega / (2 * p.strike)
    p.n_total = max(len(pd.bdate_range(d + pd.Timedelta(days=1), tr.maturity)), 1)
    p.value, *_ = _varswap_state(m, d, p, 0, 0.0)
    return p, p.value


def run_book(m: Marks, trades: list[Trade], until: pd.Timestamp | None = None) -> BookResult:
    dates = m.dates if until is None else m.dates[m.dates <= until]
    pending = list(trades)
    live: list[Position] = []
    done: list[Position] = []
    hedge = {u: 0.0 for u in m.underlyings}
    totals = {"cash": 0.0, "hedge_cum": 0.0, "cost_cum": 0.0}
    prev_total = 0.0
    daily_rows, explain_rows, risk_rows = [], [], []

    for i, d in enumerate(dates):
        lines = dict.fromkeys(LINES, 0.0)
        prev = dates[i - 1] if i > 0 else None
        spot = m.spot.loc[d]

        # 1. explain yesterday's positions
        if prev is not None:
            sp = m.spot.loc[prev]
            for p in live:
                tr = p.trade
                u = tr.underlying
                ds = spot[u] - sp[u]
                e = dict.fromkeys(["delta", "gamma", "vega", "theta"], 0.0)
                v_prev = p.value
                expired = d >= tr.maturity
                if tr.is_option:
                    vol_prev, g = _option_eval(m, prev, p)
                    e["delta"] = p.qty * g.delta * ds
                    e["gamma"] = 0.5 * p.qty * g.gamma * ds**2
                    q = m.div_yield.get(u, 0.0)
                    days = (d - prev).days
                    t_prev = _t(tr.maturity, prev)
                    e["theta"] = p.qty * (option_price(sp[u], p.strike, max(t_prev - days / 365, 0.0), vol_prev, m.rate, q,
                                                       tr.product == "call") - g.price)
                    if expired:
                        payoff = max(spot[u] - p.strike, 0.0) if tr.product == "call" else max(p.strike - spot[u], 0.0)
                        v_now = p.qty * payoff
                    else:
                        vol_now, g_now = _option_eval(m, d, p)
                        e["vega"] = p.qty * g.vega * (vol_now - vol_prev) * 100
                        v_now = p.qty * g_now.price
                else:
                    r = np.log(spot[u] / sp[u])
                    _, k_prev, n_rem_prev, df_prev = _varswap_state(m, prev, p, p.n_obs, p.sum_r2)
                    p.n_obs += 1
                    p.sum_r2 += r**2
                    e["gamma"] = p.qty * df_prev * r**2 * 252 * 1e4 / p.n_total
                    n_rem_now = max(p.n_total - p.n_obs, 0)
                    e["theta"] = p.qty * df_prev * (n_rem_now - n_rem_prev) / p.n_total * k_prev**2
                    if expired:
                        v_now = p.qty * varswap_settle(1.0, p.strike, p.sum_r2, p.n_obs)
                    else:
                        v_now, k_now, _, _ = _varswap_state(m, d, p, p.n_obs, p.sum_r2)
                        e["vega"] = p.qty * df_prev * n_rem_now / p.n_total * (k_now**2 - k_prev**2)
                e["unexplained"] = (v_now - v_prev) - sum(e.values())
                p.value = v_now
                if expired:
                    p.cash += v_now
                    totals["cash"] += v_now
                    p.value, p.alive, p.expired_on = 0.0, False, d
                for k, v in e.items():
                    lines[k] += v
                explain_rows.append({"date": d, "trade": tr.id, "underlying": u, "actual": v_now - v_prev, **e})
            lines["hedge"] = sum(hedge[u] * (spot[u] - sp[u]) for u in hedge)
            done += [p for p in live if not p.alive]
            live = [p for p in live if p.alive]

        # 2. book today's deals
        while pending and pending[0].trade_date <= d:
            tr = pending.pop(0)
            if tr.maturity <= d:
                continue
            p, day_one = _book(m, d, tr)
            totals["cash"] += p.cash
            lines["new_deals"] += day_one
            live.append(p)
            explain_rows.append({"date": d, "trade": tr.id, "underlying": tr.underlying, "actual": day_one,
                                 "new_deals": day_one})

        # 3. risk at today's close, then re-hedge
        agg = {u: dict.fromkeys(["delta_units", "vega", "gamma_1pct", "theta"], 0.0) for u in m.underlyings}
        for p in live:
            tr = p.trade
            u = tr.underlying
            if tr.is_option:
                _, g = _option_eval(m, d, p)
                agg[u]["delta_units"] += p.qty * g.delta
                agg[u]["vega"] += p.qty * g.vega
                agg[u]["gamma_1pct"] += 0.5 * p.qty * g.gamma * (0.01 * spot[u]) ** 2
                agg[u]["theta"] += p.qty * g.theta
            else:
                _, k_rem, n_rem, df = _varswap_state(m, d, p, p.n_obs, p.sum_r2)
                agg[u]["vega"] += p.qty * df * n_rem / p.n_total * 2 * k_rem
                agg[u]["gamma_1pct"] += p.qty * df * 0.01**2 * 252 * 1e4 / p.n_total
                agg[u]["theta"] += -p.qty * df * k_rem**2 / p.n_total
        for u in m.underlyings:
            new_h = -agg[u]["delta_units"]
            bp = HEDGE_COST_BP["SPX" if u == INDEX else "single"]
            lines["hedge_costs"] -= bp * 1e-4 * abs(new_h - hedge[u]) * spot[u]
            hedge[u] = new_h
            risk_rows.append({"date": d, "underlying": u, "spot": spot[u], "delta_usd": agg[u]["delta_units"] * spot[u],
                              "hedge_units": new_h, "vega": agg[u]["vega"], "gamma_1pct": agg[u]["gamma_1pct"],
                              "theta": agg[u]["theta"], "atm30": m.atm30.at[d, u], "source": m.source.at[d, u]})

        totals["hedge_cum"] += lines["hedge"]
        totals["cost_cum"] += lines["hedge_costs"]
        mtm = sum(p.value for p in live)
        total = mtm + totals["cash"] + totals["hedge_cum"] + totals["cost_cum"]
        index_vega = agg[INDEX]["vega"]
        daily_rows.append({"date": d, **lines, "pnl": total - prev_total, "total_pnl": total, "mtm": mtm,
                           "cash": totals["cash"], "live_trades": len(live),
                           "net_vega": sum(a["vega"] for a in agg.values()), "index_vega": index_vega,
                           "single_vega": sum(a["vega"] for u, a in agg.items() if u != INDEX),
                           "corr01": index_vega * m.corr_factor.loc[d]})
        prev_total = total

    daily = pd.DataFrame(daily_rows).set_index("date")
    explain = pd.DataFrame(explain_rows).fillna(0.0)
    risk = pd.DataFrame(risk_rows)
    last = dates[-1]
    vb = pd.DataFrame(0.0, index=m.underlyings, columns=[b[2] for b in BUCKETS])
    pos_rows = []
    for p in done + live:
        tr = p.trade
        row = {"id": tr.id, "client": tr.client, "trade": tr.label(), "underlying": tr.underlying,
               "booked": p.booked.date(), "maturity": tr.maturity.date(), "status": "live" if p.alive else "expired",
               "value": p.value, "pnl": p.value + p.cash, "vega": 0.0, "delta_usd": 0.0, "note": tr.note}
        if p.alive:
            if tr.is_option:
                _, g = _option_eval(m, last, p)
                row["vega"], row["delta_usd"] = p.qty * g.vega, p.qty * g.delta * m.spot.at[last, tr.underlying]
            else:
                _, k_rem, n_rem, df = _varswap_state(m, last, p, p.n_obs, p.sum_r2)
                row["vega"] = p.qty * df * n_rem / p.n_total * 2 * k_rem
            vb.at[tr.underlying, bucket_of((tr.maturity - last).days)] += row["vega"]
        pos_rows.append(row)
    positions = pd.DataFrame(pos_rows).sort_values(["status", "id"], ascending=[False, True]).reset_index(drop=True)
    return BookResult(daily=daily, explain=explain, risk=risk, vega_buckets=vb, positions=positions, marks=m, trades=trades)
