"""Options on a basket of single names: the products the desk pitches to recycle its axes.

The basket is fixed at the trade date: B_t = sum_i w_i S_i,t / S_i,0, so B_0 = 1, and the option pays
N x max(B_T - k, 0) (call) or N x max(k - B_T, 0) (put) on a notional N.

Pricing is the standard first approximation, a lognormal matched on the first two moments (Levy 1992):

    F_B      = sum_i a_i,                 a_i = w_i F_i / S_i,0
    E[B_T^2] = sum_ij a_i a_j exp(rho_ij sigma_i sigma_j T)
    sigma_B  = sqrt( ln(E[B_T^2] / F_B^2) / T )

then Black-76 on (F_B, k, sigma_B). Each sigma_i is the name's own mark at its strike k x S_i,0, so the
single-name skews pass through; rho_ij is the correlation mark (the basket optimizer's Ledoit-Wolf matrix).

Greeks are bumps of the full price, for the whole position:
    delta_i   (V(S_i x 1.005) - V(S_i x 0.995)) / (0.01 S_i)         per dollar of name i
    gamma_i   V(S_i x 1.01) - 2V + V(S_i x 0.99), halved              P&L of a 1% move of name i
    vega_i    (V(sigma_i + 1pt) - V(sigma_i - 1pt)) / 2                per vol point of name i
    corr01    (V(rho + 1pt) - V(rho - 1pt)) / 2                        every pair moved by one point
    theta     V(T - one day) - V
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .links import black76_price
from .marks import Marks


@dataclass
class BasketGreeks:
    value: float
    sigma_b: float
    delta: dict          # name -> dollars of P&L per dollar move of that name
    gamma_1pct: dict     # name -> P&L of a 1% move of that name, second order
    vega: dict           # name -> per vol point
    corr01: float
    theta: float
    vols: dict           # name -> vol at its strike (decimal)
    avg_corr: float


def basket_vols(m: Marks, d, names, ref, k, t, spots=None) -> dict:
    spots = spots or {}
    return {n: m.vol(d, n, k * ref[n], t, spot=spots.get(n)) for n in names}


def basket_value(m: Marks, d, names: list[str], weights: np.ndarray, ref: dict, k: float, t: float, is_call: bool,
                 notional: float, spots: dict | None = None, vol_bump: dict | None = None, corr_bump: float = 0.0,
                 vols: dict | None = None, corr: np.ndarray | None = None) -> tuple[float, float]:
    """Value of `notional` of the option (long), and sigma_B. Bumps in vol points / correlation points."""
    spots = spots or {}
    s = np.array([spots.get(n, m.spot.at[d, n]) for n in names])
    s0 = np.array([ref[n] for n in names])
    if t <= 0:
        b = float((weights * s / s0).sum())
        return notional * (max(b - k, 0.0) if is_call else max(k - b, 0.0)), 0.0
    vols = vols or basket_vols(m, d, names, ref, k, t, spots)
    sig = np.array([vols[n] + (vol_bump or {}).get(n, 0.0) / 100 for n in names])
    rho = (m.corr_matrix(d, names) if corr is None else corr).copy()
    off = ~np.eye(len(names), dtype=bool)
    rho[off] = np.clip(rho[off] + corr_bump / 100, -0.99, 0.99)
    fwd = np.array([m.forward(d, n, t, spot=si) for n, si in zip(names, s)])
    a = weights * fwd / s0
    fb = a.sum()
    m2 = (np.outer(a, a) * np.exp(rho * np.outer(sig, sig) * t)).sum()
    sig_b = float(np.sqrt(max(np.log(m2 / fb**2), 1e-12) / t))
    return notional * float(black76_price(fb, k, t, sig_b, is_call, np.exp(-m.rate * t))), sig_b


def basket_price_at(m: Marks, d, names, weights, ref, k, t, is_call, notional, sigma_b: float) -> float:
    """Value of the option at a given basket vol (the client price is quoted as a basket vol)."""
    s = np.array([m.spot.at[d, n] for n in names])
    s0 = np.array([ref[n] for n in names])
    fb = float((weights * np.array([m.forward(d, n, t, spot=si) for n, si in zip(names, s)]) / s0).sum())
    return notional * float(black76_price(fb, k, t, sigma_b, is_call, np.exp(-m.rate * t)))


def basket_greeks(m: Marks, d, names, weights, ref, k, t, is_call, notional) -> BasketGreeks:
    base = dict(m=m, d=d, names=names, weights=weights, ref=ref, k=k, t=t, is_call=is_call, notional=notional)
    vols = basket_vols(m, d, names, ref, k, t)
    corr = m.corr_matrix(d, names)
    v0, sb = basket_value(**base, vols=vols, corr=corr)
    delta, gamma, vega = {}, {}, {}
    for n in names:
        s = m.spot.at[d, n]
        up, _ = basket_value(**base, spots={n: s * 1.01}, corr=corr)
        dn, _ = basket_value(**base, spots={n: s * 0.99}, corr=corr)
        u5, _ = basket_value(**base, spots={n: s * 1.005}, corr=corr)
        d5, _ = basket_value(**base, spots={n: s * 0.995}, corr=corr)
        delta[n] = (u5 - d5) / (0.01 * s)
        gamma[n] = 0.5 * (up - 2 * v0 + dn)
        vu, _ = basket_value(**base, vols=vols, corr=corr, vol_bump={n: 1.0})
        vd, _ = basket_value(**base, vols=vols, corr=corr, vol_bump={n: -1.0})
        vega[n] = (vu - vd) / 2
    cu, _ = basket_value(**base, vols=vols, corr=corr, corr_bump=1.0)
    cd, _ = basket_value(**base, vols=vols, corr=corr, corr_bump=-1.0)
    th, _ = basket_value(**{**base, "t": max(t - 1 / 365, 0.0)}, vols=vols, corr=corr)
    off = ~np.eye(len(names), dtype=bool)
    return BasketGreeks(value=v0, sigma_b=sb, delta=delta, gamma_1pct=gamma, vega=vega, corr01=(cu - cd) / 2,
                        theta=th - v0, vols=vols, avg_corr=float(corr[off].mean()) if len(names) > 1 else 1.0)
