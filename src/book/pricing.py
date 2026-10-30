"""Pricing and Greeks, per unit of underlying (options) or per position (variance swaps).

Options: Black-76 on the forward F = S exp((r - q) T), discounted at r, through the vol dashboard's
`black76_price`. Greeks are the Black ones, so the skew's dependence on spot is not in the delta; when
spot moves along the skew the vol at a fixed strike changes, and that shows up in the vega line of the
P&L explain.

Variance swaps, notional N_var = vega / (2 K) per vol point squared, on n_total daily returns:
    value = N_var x DF x [ sum(r_i^2) x 252e4 / n_total + (n_rem / n_total) x K_rem^2 - K^2 ]
where sum(r_i^2) runs over the returns already realized and K_rem is today's fair strike for the
remaining life. At maturity it is N_var (RV^2 - K^2).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from .links import black76_price

DAY = 1 / 365


@dataclass
class OptionGreeks:
    price: float     # per unit of underlying
    delta: float     # d price / d spot
    gamma: float     # d delta / d spot
    vega: float      # per vol point
    theta: float     # one calendar day, all else equal


def option_price(spot: float, strike: float, t: float, sigma: float, rate: float, div: float, is_call: bool) -> float:
    if t <= 0:
        return max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
    fwd = spot * np.exp((rate - div) * t)
    return float(black76_price(fwd, strike, t, sigma, is_call, np.exp(-rate * t)))


def option_greeks(spot: float, strike: float, t: float, sigma: float, rate: float, div: float, is_call: bool) -> OptionGreeks:
    price = option_price(spot, strike, t, sigma, rate, div, is_call)
    if t <= 0:
        itm = (spot > strike) if is_call else (spot < strike)
        return OptionGreeks(price, (1.0 if is_call else -1.0) * float(itm), 0.0, 0.0, 0.0)
    fwd = spot * np.exp((rate - div) * t)
    sq = sigma * np.sqrt(t)
    d1 = (np.log(fwd / strike) + 0.5 * sigma**2 * t) / sq
    carry = np.exp(-div * t)
    delta = carry * (norm.cdf(d1) if is_call else norm.cdf(d1) - 1)
    gamma = carry * norm.pdf(d1) / (spot * sq)
    vega = spot * carry * norm.pdf(d1) * np.sqrt(t) * 0.01
    theta = option_price(spot, strike, max(t - DAY, 0.0), sigma, rate, div, is_call) - price
    return OptionGreeks(price, float(delta), float(gamma), float(vega), float(theta))


def varswap_value(n_var: float, strike: float, sum_r2: float, n_total: int, n_rem: int, k_rem: float, df: float) -> float:
    """Value of a long variance swap. Strikes and k_rem in vol points, sum_r2 = sum of squared daily
    log returns since the start (decimal)."""
    accrued = sum_r2 * 252 * 1e4 / n_total
    return n_var * df * (accrued + n_rem / n_total * k_rem**2 - strike**2)


def varswap_settle(n_var: float, strike: float, sum_r2: float, n_obs: int) -> float:
    rv2 = sum_r2 * 252 * 1e4 / max(n_obs, 1)
    return n_var * (rv2 - strike**2)
