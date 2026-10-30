"""Basket options and the weekly pitch, on a synthetic four-name market."""
import numpy as np
import pandas as pd
import pytest

from book import risk
from book.basket import basket_greeks, basket_price_at, basket_value
from book.clients import CLIENTS
from book.engine import LINES, run_book
from book.marks import ANCHORS, INDEX, Marks
from book.pitch import Pitcher, quote
from book.pricing import option_price
from book.trades import Trade, maturity_of

NAMES = ["AAA", "BBB", "CCC", "DDD"]


def _market(n=200, seed=5, rho=0.4):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2026-01-02", periods=n)
    und = [INDEX] + NAMES
    f = rng.standard_normal(n)
    e = rng.standard_normal((n, len(und)))
    rets = (np.sqrt(rho) * f[:, None] + np.sqrt(1 - rho) * e) * 0.3 / np.sqrt(252)
    spot = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=und)
    atm = pd.DataFrame({u: 30.0 for u in und}, index=dates)
    atm[INDEX] = 18.0
    c = pd.DataFrame(np.full((4, 4), rho) + np.eye(4) * (1 - rho), index=NAMES, columns=NAMES)
    return Marks(spot=spot, atm30=atm, atm90=pd.DataFrame(np.nan, index=dates, columns=und),
                 beta=pd.DataFrame(0.0, index=dates, columns=und), source=pd.DataFrame("model", index=dates, columns=und),
                 model_atm30=atm.copy(), vixfam=pd.DataFrame({a: 21.0 for a in ANCHORS}, index=dates),
                 corr_factor=pd.Series(0.08, index=dates), div_yield={}, corr={d: c for d in dates})


def test_one_name_basket_is_the_single_option():
    m = _market()
    d = m.dates[0]
    v, sb = basket_value(m, d, ["AAA"], np.array([1.0]), {"AAA": m.spot.at[d, "AAA"]}, 0.9, 1.0, False, 1.0)
    assert sb == pytest.approx(0.30, abs=1e-9)
    assert v == pytest.approx(option_price(1.0, 0.9, 1.0, 0.30, m.rate, 0.0, False), rel=1e-9)


def test_basket_vol_falls_with_correlation_and_corr01_is_positive_for_a_long_option():
    m = _market()
    d = m.dates[0]
    args = dict(names=NAMES, weights=np.full(4, 0.25), ref={n: m.spot.at[d, n] for n in NAMES}, k=1.0, t=1.0, is_call=True)
    low = basket_value(m, d, **args, notional=1.0, corr_bump=-30)[1]
    high = basket_value(m, d, **args, notional=1.0, corr_bump=+30)[1]
    assert low < basket_value(m, d, **args, notional=1.0)[1] < high < 0.30
    g = basket_greeks(m, d, **args, notional=1e6)
    assert g.corr01 > 0 and all(v > 0 for v in g.vega.values())
    # the per-name vegas add up to a parallel shift of every vol
    par = (basket_value(m, d, **args, notional=1e6, vol_bump={n: 1 for n in NAMES})[0]
           - basket_value(m, d, **args, notional=1e6, vol_bump={n: -1 for n in NAMES})[0]) / 2
    assert sum(g.vega.values()) == pytest.approx(par, rel=0.01)


def test_basket_put_call_parity_on_the_forward():
    m = _market()
    d = m.dates[0]
    args = dict(names=NAMES, weights=np.full(4, 0.25), ref={n: m.spot.at[d, n] for n in NAMES}, k=0.95, t=1.0)
    c = basket_price_at(m, d, **args, is_call=True, notional=1.0, sigma_b=0.25)
    p = basket_price_at(m, d, **args, is_call=False, notional=1.0, sigma_b=0.25)
    assert c - p == pytest.approx(np.exp(-m.rate) * (np.exp(m.rate) - 0.95), abs=1e-12)


def test_without_axes_the_street_wins_every_tie():
    m = _market()
    d = m.dates[0]
    for cl in CLIENTS:
        args = dict(names=NAMES[:3], weights=np.full(3, 1 / 3), ref={n: m.spot.at[d, n] for n in NAMES}, k=1.0, t=1.0,
                    is_call=cl.product == "basket_call")
        q = quote(m, d, cl, args, {n: 0.0 for n in NAMES}, 0.0)
        assert q is None or (q["desk"] == pytest.approx(q["street"], abs=1e-6) and not q["won"])


def test_a_book_long_single_name_vol_wins_a_protected_note_and_its_risk_falls():
    m = _market()
    d0 = m.dates[0]
    longs = [Trade(id=f"T{i}", trade_date=d0, maturity=maturity_of(d0, 12), client="test", product="put", underlying=n,
                   strike_pct=90, notional=40e6, vega=None, sign=1, note="") for i, n in enumerate(NAMES)]
    pitcher = Pitcher(m.dates, NAMES)
    pitcher.days = [m.dates[5]]
    res = run_book(m, longs, pitcher=pitcher)
    log = res.pitches[0]
    assert log["result"] == "accepted" and log["note"] == "capital-protected note"
    assert log["score_after"] < log["score_before"]
    assert np.allclose(res.daily[LINES].sum(axis=1), res.daily["pnl"], atol=1e-4)
