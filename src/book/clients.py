"""Fictitious clients and the terms they compare.

Two structured products, both one-year notes on a basket the desk proposes:

- Basket reverse convertible (the client sells the desk a put on the basket, struck at k):
      coupon (% a year) = ((1 - DF) + put price) / (T x DF) - fee
  The note returns 100 plus the coupon unless the basket ends below k, in which case the client takes
  the loss below k. The desk is long the put: long vol on every name and long correlation.
- Capital-protected note (the client buys an at-the-money call on the basket):
      participation = ((1 - DF) - fee) / call price
  100 back at maturity plus that share of the basket's rise. The desk is short the call: short vol on
  every name and short correlation.

Each client asks for one product, with a ticket size, and always checks the street: the same note quoted
by competitors at mid plus the standard spread, without any axe.
- Reverse convertible clients fix the coupon they want. The desk solves for the strike that pays it;
  the client takes the desk's note if that strike is lower than the street's: the same coupon, more
  protection.
- Capital-protected note clients take the at-the-money call and compare participations: the desk must
  clear the client's minimum and beat the street.
As in a request for quote, the best price wins; it must be better by 0.1 point, ties go to the street.
One-year notes on these baskets pay a 9% coupon struck around 85-95%, or a 22-29% participation.
Clients, sizes, coupons and minimums are fictitious; the prices are not.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FEE = 0.005            # issuer fee: 0.5% a year off the coupon, 0.5% upfront off the call budget
BEAT_STREET = {"basket_put": 0.1, "basket_call": 0.1}    # best price wins the request for quote; ties go to the street
STRIKE_RANGE = (50.0, 100.0)                              # reverse convertible strikes the desk will solve in


@dataclass(frozen=True)
class Client:
    name: str
    product: str          # basket_put (reverse convertible) or basket_call (capital-protected note)
    strike_pct: float     # capital-protected notes: the call strike; reverse convertibles: solved, this is unused
    tenor_months: int
    target: float         # reverse convertibles: the coupon asked, % a year; notes: the minimum participation, %
    sizes: tuple          # notionals the client can take, USD

    @property
    def note(self) -> str:
        return "reverse convertible" if self.product == "basket_put" else "capital-protected note"

    @property
    def desk_sign(self) -> int:
        return 1 if self.product == "basket_put" else -1

    def terms(self, option_price: float, t: float, rate: float) -> float:
        """Coupon (% a year) or participation (%) from the option price per unit of notional."""
        df = np.exp(-rate * t)
        if self.product == "basket_put":
            return 100 * (((1 - df) + option_price) / (t * df) - FEE)
        return 100 * ((1 - df) - FEE) / option_price

    def unit(self) -> str:
        return "% coupon" if self.product == "basket_put" else "% participation"


CLIENTS = (
    Client("Private bank C", "basket_put", 0, 12, 9.0, (10e6, 20e6, 30e6)),
    Client("Insurer H", "basket_call", 100, 12, 22.0, (20e6, 40e6)),
    Client("Private bank D", "basket_put", 0, 12, 7.0, (10e6, 20e6)),
    Client("Asset manager F", "basket_call", 100, 12, 25.0, (10e6, 25e6)),
)
