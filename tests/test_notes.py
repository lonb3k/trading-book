"""Monte Carlo notes: closed forms where they exist, life-cycle events, and the explain."""
import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from book.engine import LINES, run_book
from book.marks import INDEX
from book.mc import NoteSpec, note_greeks, note_pv, observation_dates, seed_of, solve_coupon
from book.trades import Trade, maturity_of
from test_baskets import NAMES, _market


def _closed_form(m, d, name, ki, t, n):
    """N if S_T >= ki S_0, else N S_T / S_0, discounted: 1 - N(-d2) + (F/S0) N(-d1)."""
    s0 = m.spot.at[d, name]
    sig = m.atm30.at[d, name] / 100
    f = s0 * np.exp(m.rate * t)
    k = ki * s0
    d1 = (np.log(f / k) + 0.5 * sig**2 * t) / (sig * np.sqrt(t))
    d2 = d1 - sig * np.sqrt(t)
    return n * np.exp(-m.rate * t) * (1 - norm.cdf(-d2) + f / s0 * norm.cdf(-d1))


def _spec(m, d, kind, names, months=12, ki=0.6, call=1.0, coupon=0.0, n=1e6, tid="X"):
    return NoteSpec(kind, names, {x: m.spot.at[d, x] for x in names}, observation_dates(d, months), coupon, ki, call,
                    n, seed=seed_of(tid))


def test_one_name_worst_of_matches_the_closed_form():
    m = _market()
    d = m.dates[0]
    spec = _spec(m, d, "worst_of", ["AAA"])
    pv, se = note_pv(m, d, spec)
    t = (spec.obs[-1] - d).days / 365
    assert abs(pv - _closed_form(m, d, "AAA", 0.6, t, 1e6)) < 3 * se


def test_an_autocall_that_can_never_be_called_is_the_same_note():
    m = _market()
    d = m.dates[0]
    spec = _spec(m, d, "autocall", ["AAA"], call=50.0)
    pv, se = note_pv(m, d, spec)
    t = (spec.obs[-1] - d).days / 365
    assert abs(pv - _closed_form(m, d, "AAA", 0.6, t, 1e6)) < 3 * se


def test_the_solved_coupon_leaves_exactly_the_fee():
    m = _market()
    d = m.dates[0]
    spec = _spec(m, d, "autocall", ["AAA"], months=24)
    spec.coupon = solve_coupon(m, d, spec, 0.02)
    assert spec.coupon > 0
    assert note_pv(m, d, spec)[0] == pytest.approx(0.98e6, rel=1e-9)


def test_the_desk_is_long_vol_and_short_correlation_on_a_worst_of():
    m = _market()
    d = m.dates[0]
    spec = _spec(m, d, "worst_of", NAMES[:3], coupon=0.05)
    g = note_greeks(m, d, spec, 0)
    assert all(v > 0 for v in g.vega.values())          # the desk owns the worst-of put
    assert g.corr01 < 0                                  # which is worth less when the names move together
    assert all(v < 0 for v in g.delta.values())          # and loses value as the names rise


def _rising_market():
    m = _market(n=200, seed=7)
    drift = np.exp(np.linspace(0, 0.25, len(m.dates)))  # +25% steadily: the index is above its start at every date
    m.spot[INDEX] = m.spot[INDEX].iloc[0] * drift
    return m


def test_an_autocall_is_called_pays_its_coupon_and_leaves_the_book():
    m = _rising_market()
    d0 = m.dates[0]
    tr = Trade(id="AC1", trade_date=d0, maturity=maturity_of(d0, 24), client="test", product="autocall", underlying=INDEX,
               strike_pct=None, notional=10e6, vega=None, sign=-1, note="", tenor_months=24, coupon=0.02, ki=0.6, call=1.0)
    res = run_book(m, [tr])
    pos = res.positions.set_index("id").loc["AC1"]
    assert pos["status"] == "expired" and "called" in pos["events"] and "102.00%" in pos["events"]
    assert np.allclose(res.daily[LINES].sum(axis=1), res.daily["pnl"], atol=1e-4)


def test_notes_are_explained_on_a_calm_market():
    m = _market(n=180, seed=11)
    d0 = m.dates[0]
    trades = [Trade(id="WO1", trade_date=d0, maturity=maturity_of(d0, 12), client="test", product="worst_of",
                    underlying="WORST_OF", strike_pct=None, notional=10e6, vega=None, sign=-1, note="", tenor_months=12,
                    coupon=0.03, ki=0.6, basket={n: 1 / 3 for n in NAMES[:3]})]
    res = run_book(m, trades)
    e = res.explain[res.explain["trade"] == "WO1"]
    gross = e[["delta", "gamma", "vega", "vanna", "theta"]].abs().sum().sum()
    assert e["unexplained"].abs().sum() < 0.05 * gross
    assert np.allclose(res.daily[LINES].sum(axis=1), res.daily["pnl"], atol=1e-4)
