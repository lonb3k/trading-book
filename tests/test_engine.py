"""The book on a synthetic market: the accounting identities a desk checks every evening."""
import numpy as np
import pandas as pd
import pytest

from book import risk
from book.engine import LINES, run_book
from book.marks import ANCHORS, INDEX, Marks, beta_from_rr
from book.trades import Trade, maturity_of


def _market(n=180, vol=0.20, seed=3, jump_day=None):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2026-01-02", periods=n)
    und = [INDEX, "AAA"]
    rets = rng.standard_normal((n, 2)) * vol / np.sqrt(252)
    if jump_day is not None:
        rets[jump_day, 1] = 0.15
    spot = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=und)
    spot[INDEX] *= 50
    atm = pd.DataFrame({INDEX: 18 + rng.standard_normal(n).cumsum() * 0.2, "AAA": 30.0}, index=dates).clip(lower=8)
    vixfam = pd.DataFrame({a: atm[INDEX] * 1.2 for a in ANCHORS}, index=dates)
    return Marks(spot=spot, atm30=atm, atm90=pd.DataFrame(np.nan, index=dates, columns=und),
                 beta=pd.DataFrame(-0.2, index=dates, columns=und), source=pd.DataFrame("model", index=dates, columns=und),
                 model_atm30=atm.copy(), vixfam=vixfam, corr_factor=pd.Series(0.08, index=dates), div_yield={})


def _trade(i, d, product, und, side, strike=None, notional=None, vega=None, months=6):
    d = pd.Timestamp(d)
    return Trade(id=f"T{i}", trade_date=d, maturity=maturity_of(d, months), client="test", product=product,
                 underlying=und, strike_pct=strike, notional=notional, vega=vega, sign=side, note="")


TRADES = [_trade(1, "2026-01-05", "put", INDEX, -1, 95, 50e6),
          _trade(2, "2026-01-20", "put", "AAA", 1, 85, 10e6, months=3),
          _trade(3, "2026-02-02", "varswap", INDEX, 1, vega=100_000, months=3),
          _trade(4, "2026-02-02", "varswap", "AAA", -1, vega=30_000, months=4)]


def test_daily_pnl_is_exactly_the_sum_of_its_explain_lines():
    res = run_book(_market(), TRADES)
    d = res.daily
    assert np.allclose(d[LINES].sum(axis=1), d["pnl"], atol=1e-6)
    assert d["pnl"].sum() == pytest.approx(d["total_pnl"].iloc[-1], abs=1e-6)


def test_delta_hedge_offsets_the_delta_line_every_day():
    d = run_book(_market(), TRADES).daily
    assert np.allclose(d["delta"] + d["hedge"], 0, atol=1e-6)


def test_new_deals_pay_the_spread_and_nothing_else():
    res = run_book(_market(), TRADES)
    day_one = res.explain[res.explain["new_deals"] != 0].set_index("trade")["new_deals"]
    assert (day_one > 0).all() and set(day_one.index) == {t.id for t in TRADES}
    # a variance swap struck half a vol point off mid earns about half its vega
    assert day_one["T3"] == pytest.approx(0.5 * 100_000, rel=0.03)
    assert day_one["T4"] == pytest.approx(1.0 * 30_000, rel=0.06)


def test_greeks_explain_small_moves_and_flag_jumps():
    calm = run_book(_market(), TRADES).daily
    gross = calm[["delta", "gamma", "vega", "theta"]].abs().sum().sum()
    assert calm["unexplained"].abs().sum() < 0.05 * gross
    jumpy = run_book(_market(jump_day=60), TRADES)
    worst = jumpy.explain.loc[jumpy.explain["unexplained"].abs().idxmax()]
    assert worst["underlying"] == "AAA" and worst["date"] == jumpy.marks.dates[60]


def test_expired_trades_leave_the_book_with_their_cash():
    res = run_book(_market(), TRADES)
    pos = res.positions.set_index("id")
    assert pos.loc["T2", "status"] == "expired" and pos.loc["T2", "value"] == 0
    assert res.daily["live_trades"].iloc[-1] == (pos["status"] == "live").sum()


def test_short_index_vega_is_short_correlation_and_the_axe_points_the_right_way():
    res = run_book(_market(), [_trade(9, "2026-01-05", "put", INDEX, -1, 95, 50e6, months=12)])
    assert res.daily["corr01"].iloc[-1] < 0
    ax = risk.axes(res).set_index("underlying")
    assert ax.loc[INDEX, "direction"] == "buy vol" and ax.loc[INDEX, "shift"] > 0
    assert risk.correlation_axe(res)["direction"] == "buy correlation"


def test_axe_shift_is_capped_and_signed():
    assert risk.axe_shift(+10 * risk.VEGA_LIMIT["single"], "AAA") == pytest.approx(-risk.MAX_SHIFT["single"])
    assert risk.axe_shift(-10 * risk.VEGA_LIMIT[INDEX], INDEX) == pytest.approx(risk.MAX_SHIFT[INDEX])
    assert risk.axe_shift(0.0, "AAA") == 0.0


def test_skew_calibration_reproduces_the_risk_reversal():
    m = _market()
    d = m.dates[10]
    atm, rr = 25.0, -5.0
    m.atm30.loc[d, "AAA"], m.beta.loc[d, "AAA"] = atm, beta_from_rr(rr, atm)
    t = 30 / 365
    f = m.forward(d, "AAA", t)
    sig = atm / 100
    k_put = f * np.exp(-0.674 * sig * np.sqrt(t) + 0.5 * sig**2 * t)
    k_call = f * np.exp(0.674 * sig * np.sqrt(t) + 0.5 * sig**2 * t)
    got = (m.vol(d, "AAA", k_call, t) - m.vol(d, "AAA", k_put, t)) * 100
    assert got == pytest.approx(rr, rel=0.02)
