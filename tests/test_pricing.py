"""Pricing and Greeks: the numbers every line of the P&L explain is built on."""
import numpy as np
import pytest

from book.pricing import option_greeks, option_price, varswap_settle, varswap_value

ARGS = dict(strike=95.0, t=0.5, sigma=0.25, rate=0.04, div=0.01)


@pytest.mark.parametrize("is_call", [True, False])
def test_greeks_match_finite_differences(is_call):
    s, h = 100.0, 0.01
    g = option_greeks(s, is_call=is_call, **ARGS)
    p = lambda **kw: option_price(**{**dict(spot=s, is_call=is_call, **ARGS), **kw})  # noqa: E731
    assert g.delta == pytest.approx((p(spot=s + h) - p(spot=s - h)) / (2 * h), rel=1e-5)
    assert g.gamma == pytest.approx((p(spot=s + h) - 2 * p() + p(spot=s - h)) / h**2, rel=1e-3)
    assert g.vega == pytest.approx((p(sigma=0.2501) - p(sigma=0.2499)) / 0.02, rel=1e-4)
    assert g.theta == pytest.approx(p(t=0.5 - 1 / 365) - p(), rel=1e-9)


def test_put_call_parity():
    s, k, t, r, q = 100.0, 95.0, 0.5, 0.04, 0.01
    c = option_price(s, k, t, 0.3, r, q, True)
    p = option_price(s, k, t, 0.3, r, q, False)
    assert c - p == pytest.approx(s * np.exp(-q * t) - k * np.exp(-r * t), abs=1e-10)


def test_variance_swap_is_worth_zero_at_its_fair_strike_and_pays_rv2_minus_k2():
    assert varswap_value(1.0, 20.0, 0.0, 63, 63, 20.0, 0.99) == pytest.approx(0.0)
    r = np.full(63, 0.25 / np.sqrt(252))            # constant moves: realized vol exactly 25
    assert varswap_settle(1.0, 20.0, float((r**2).sum()), 63) == pytest.approx(25**2 - 20**2)
    # half-way: half the realized variance is locked in, half is still at the fair strike
    half = float((r[:31] ** 2).sum())
    v = varswap_value(1.0, 20.0, half, 62, 31, 20.0, 1.0)
    assert v == pytest.approx(0.5 * (25**2 - 20**2), rel=1e-9)
