"""Monte Carlo pricing of the two exotic notes: an autocall on the S&P 500 and a worst-of on three names.

The desk sells the note: the client pays the notional N on day one and receives the note's payoff. The desk
puts N on deposit at the risk-free rate and owes the note, so its position is

    value = deposit - PV(note)

The deposit accrues every day (that carry is in the theta line), coupons and redemptions are paid out of
it, and what is left when the note ends is the desk's realised P&L.

Notes, observed quarterly on the trade date's anniversaries:
- Autocall (Athena). If the index closes at or above `call` x initial on an observation date, the note
  redeems at N x (1 + coupon x number of quarters since inception). At maturity, if never called:
  N if the index is above `ki` x initial (the knock-in barrier, observed at maturity only), else
  N x final / initial: the client has sold a down-and-in put.
- Worst-of reverse convertible. A fixed coupon every quarter. At maturity N back if the worst of the
  three names is above `ki` x its initial level, else N x the worst performance.

Model: correlated geometric Brownian motions, simulated exactly on the observation dates. Each name at
one flat vol, its mark at the knock-in strike for the remaining maturity (the put is what drives the
desk's risk; a local-vol model would let the vol move with spot), correlations at the Ledoit-Wolf mark.
20,000 paths (10,000 antithetic pairs), drawn once per trade from a seed fixed by the trade id and reused
every evening and in every bump: the daily P&L moves with the market, not with the random numbers.

Greeks are bumps on the same paths, for the whole position (desk side):
delta and gamma per name (1% moves), vega per name (1 vol point), vanna per name (how the vega moves with
spot), Corr01 (every pair up 1 point), theta (the valuation date moved one day, plus the deposit's carry).
Vanna gets its own line in the P&L explain: an autocall's vega grows as the index falls towards the
knock-in, so a sell-off with rising vol earns or costs a cross term that neither the delta nor the vega
line sees. The explain revalues it in full (the vol move at today's spot) rather than extrapolating the
1% vanna to an earnings jump; the bumped vanna is kept for the risk report.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .marks import Marks

N_PAIRS = 10_000


def observation_dates(trade_date: pd.Timestamp, months: int, every: int = 3) -> list[pd.Timestamp]:
    out = []
    for k in range(every, months + 1, every):
        o = trade_date + pd.DateOffset(months=k)
        while o.weekday() >= 5:
            o -= pd.Timedelta(days=1)
        out.append(o)
    return out


@dataclass
class NoteSpec:
    kind: str                      # autocall or worst_of
    names: list[str]
    ref: dict                      # initial spots
    obs: list[pd.Timestamp]        # all observation dates, the last one is maturity
    coupon: float                  # per quarter, fraction of N
    ki: float                      # knock-in barrier, fraction of initial
    call: float = 1.0              # autocall barrier, fraction of initial
    notional: float = 1.0
    seed: int = 0
    z: np.ndarray = field(default=None, repr=False)

    def __post_init__(self):
        if self.z is None:
            rng = np.random.default_rng(self.seed)
            z = rng.standard_normal((N_PAIRS, len(self.obs), len(self.names)))
            self.z = np.concatenate([z, -z])


def seed_of(trade_id: str) -> int:
    return zlib.crc32(trade_id.encode())


@dataclass
class NoteGreeks:
    value: float                   # desk side, deposit excluded
    stderr: float
    delta: dict
    gamma_1pct: dict
    vega: dict
    vanna: dict                    # d vega / d spot, per vol point per dollar of the name
    corr01: float
    theta: float                   # note only; the engine adds the deposit carry
    vols: dict
    avg_corr: float


def remaining(spec: NoteSpec, asof: pd.Timestamp, done: int) -> list[pd.Timestamp]:
    return [o for i, o in enumerate(spec.obs) if i >= done and o > asof]


def note_vols(m: Marks, d, spec: NoteSpec, asof, spots=None) -> dict:
    t = max((spec.obs[-1] - asof).days, 1) / 365
    spots = spots or {}
    return {n: m.vol(d, n, spec.ki * spec.ref[n], t, spot=spots.get(n)) for n in spec.names}


def note_pv(m: Marks, d, spec: NoteSpec, done: int = 0, asof=None, spots: dict | None = None,
            vol_bump: dict | None = None, corr_bump: float = 0.0, vols: dict | None = None,
            corr: np.ndarray | None = None, coupon: float | None = None) -> tuple[float, float]:
    """PV of what the desk still owes on the note (coupons and redemption), and its Monte Carlo standard
    error. Marks of date d; time measured from `asof` (default d); `done` observations already settled."""
    asof = d if asof is None else asof
    c = spec.coupon if coupon is None else coupon
    obs = remaining(spec, asof, done)
    if not obs:
        return 0.0, 0.0
    k0 = len(spec.obs) - len(obs)                          # observations already behind
    names = spec.names
    s_now = np.array([(spots or {}).get(n, m.spot.at[d, n]) for n in names])
    x0 = np.log(s_now / np.array([spec.ref[n] for n in names]))
    vols = vols or note_vols(m, d, spec, asof, spots)
    sig = np.array([vols[n] + (vol_bump or {}).get(n, 0.0) / 100 for n in names])
    mu = np.array([m.rate - m.div_yield.get(n, 0.0) for n in names]) - 0.5 * sig**2
    times = np.array([(o - asof).days / 365 for o in obs])
    dt = np.diff(np.concatenate([[0.0], times]))
    z = spec.z[:, k0:, :]
    if len(names) > 1:
        rho = (m.corr_matrix(d, names) if corr is None else corr).copy()
        off = ~np.eye(len(names), dtype=bool)
        rho[off] = np.clip(rho[off] + corr_bump / 100, -0.95, 0.99)
        z = z @ np.linalg.cholesky(rho).T
    x = x0 + np.cumsum(mu * dt[:, None] + sig * np.sqrt(dt)[:, None] * z, axis=1)
    df = np.exp(-m.rate * times)
    n = spec.notional
    if spec.kind == "worst_of":
        perf_t = np.exp(x[:, -1, :].min(axis=1))
        redemption = np.where(perf_t >= spec.ki, 1.0, perf_t) * df[-1]
        pay = n * (redemption + c * df.sum())
    else:
        perf = np.exp(x[:, :, 0])
        called = perf >= spec.call
        first = np.where(called.any(axis=1), called.argmax(axis=1), -1)
        k_global = k0 + first + 1
        pay_call = (1 + c * k_global) * df[np.maximum(first, 0)]
        p_t = perf[:, -1]
        pay_end = np.where(p_t >= spec.ki, 1.0, p_t) * df[-1]
        pay = n * np.where(first >= 0, pay_call, pay_end)
    return float(pay.mean()), float(pay.std() / np.sqrt(len(pay)))


def solve_coupon(m: Marks, d, spec: NoteSpec, fee: float) -> float:
    """Quarterly coupon at which the note is worth N x (1 - fee) at mid: the payoff is linear in the coupon."""
    p0, _ = note_pv(m, d, spec, coupon=0.0)
    p1, _ = note_pv(m, d, spec, coupon=0.01)
    return 0.01 * (spec.notional * (1 - fee) - p0) / (p1 - p0)


def note_greeks(m: Marks, d, spec: NoteSpec, done: int, sign: int = -1) -> NoteGreeks:
    """Greeks of the desk's position in the note (sign -1: the desk owes it)."""
    vols = note_vols(m, d, spec, d)
    corr = m.corr_matrix(d, spec.names) if len(spec.names) > 1 else None
    pv = lambda **kw: note_pv(m, d, spec, done, **kw)[0]  # noqa: E731
    base, se = note_pv(m, d, spec, done, vols=vols, corr=corr)
    delta, gamma, vega, vanna = {}, {}, {}, {}
    for n in spec.names:
        s = m.spot.at[d, n]
        up, dn = pv(spots={n: s * 1.01}, corr=corr), pv(spots={n: s * 0.99}, corr=corr)
        delta[n] = sign * (up - dn) / (0.02 * s)
        gamma[n] = sign * 0.5 * (up - 2 * base + dn)
        vega[n] = sign * (pv(vols=vols, corr=corr, vol_bump={n: 1.0}) - pv(vols=vols, corr=corr, vol_bump={n: -1.0})) / 2
        v_up = (pv(spots={n: s * 1.01}, vols=vols, corr=corr, vol_bump={n: 1.0})
                - pv(spots={n: s * 1.01}, vols=vols, corr=corr, vol_bump={n: -1.0})) / 2
        v_dn = (pv(spots={n: s * 0.99}, vols=vols, corr=corr, vol_bump={n: 1.0})
                - pv(spots={n: s * 0.99}, vols=vols, corr=corr, vol_bump={n: -1.0})) / 2
        vanna[n] = sign * (v_up - v_dn) / (0.02 * s)
    corr01 = 0.0
    if len(spec.names) > 1:
        corr01 = sign * (pv(vols=vols, corr=corr, corr_bump=1.0) - pv(vols=vols, corr=corr, corr_bump=-1.0)) / 2
    nxt = remaining(spec, d, done)
    asof = min(d + pd.Timedelta(days=1), nxt[0] - pd.Timedelta(days=1)) if nxt else d
    theta = sign * (pv(asof=max(asof, d), vols=vols, corr=corr) - base)
    off = ~np.eye(len(spec.names), dtype=bool)
    return NoteGreeks(value=sign * base, stderr=se, delta=delta, gamma_1pct=gamma, vega=vega, vanna=vanna, corr01=corr01,
                      theta=theta, vols=vols, avg_corr=float(corr[off].mean()) if corr is not None else 1.0)
