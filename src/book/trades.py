"""The fictitious trade blotter. Every trade is a client deal: the desk's side is the opposite of the client's.

Two files: data/trades.csv, the deals written by hand (step 1), and data/trades_generated.csv, the
basket deals clients accepted from the desk's pitches (step 2). A booked trade is a fact: the second file
is appended to, never recomputed.

Strikes are in percent of spot (of each name's spot for a basket) on the trade date and sizes in dollars
(option notional, or variance-swap vega), so the blotter never depends on the price level of the data.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .data import DATA_DIR

BLOTTER = DATA_DIR / "trades.csv"
GENERATED = DATA_DIR / "trades_generated.csv"
COLUMNS = ["id", "trade_date", "client", "product", "underlying", "strike_pct", "tenor_months", "notional_usd",
           "vega_usd", "desk_side", "basket", "trade_vol", "coupon_pct_q", "ki_pct", "call_pct", "note"]

# Half the bid-ask the desk charges, in vol points: client buys above mid, sells below mid.
SPREAD = {"option": {"SPX": 0.4, "single": 1.0}, "varswap": {"SPX": 0.5, "single": 1.0}, "basket": {"single": 1.0}}


@dataclass
class Trade:
    id: str
    trade_date: pd.Timestamp
    maturity: pd.Timestamp
    client: str
    product: str            # put, call, varswap, basket_put, basket_call
    underlying: str         # SPX, a ticker, or BASKET
    strike_pct: float | None
    notional: float | None  # options, USD
    vega: float | None      # variance swaps, USD per vol point
    sign: int               # +1 desk long, -1 desk short
    note: str
    basket: dict = field(default_factory=dict)   # name -> weight, for basket options (names only for worst-ofs)
    trade_vol: float | None = None               # basket vol the client dealt at (decimal), set at the pitch
    tenor_months: int = 0
    coupon: float | None = None                  # notes: coupon per quarter, fraction of notional
    ki: float | None = None                      # notes: knock-in barrier, fraction of initial
    call: float | None = None                    # autocalls: call barrier, fraction of initial

    @property
    def is_note(self) -> bool:
        return self.product in ("autocall", "worst_of")

    @property
    def is_option(self) -> bool:
        return self.product in ("put", "call")

    @property
    def is_basket(self) -> bool:
        return self.product.startswith("basket")

    @property
    def is_call(self) -> bool:
        return self.product in ("call", "basket_call")

    def spread(self) -> float:
        if self.is_basket:
            return SPREAD["basket"]["single"]
        kind = "option" if self.is_option else "varswap"
        return SPREAD[kind]["SPX" if self.underlying == "SPX" else "single"]

    def note_names(self) -> list[str]:
        return list(self.basket) if self.product == "worst_of" else [self.underlying]

    def basket_label(self) -> str:
        return " / ".join(f"{n} {w * 100:.0f}" for n, w in self.basket.items())

    def label(self) -> str:
        side = "long" if self.sign > 0 else "short"
        if self.product == "autocall":
            return (f"{side} {self.underlying} autocall {self.maturity:%b-%y} ({4 * self.coupon * 100:.2f}% a year, "
                    f"call {self.call * 100:g}%, knock-in {self.ki * 100:g}%)")
        if self.product == "worst_of":
            return (f"{side} worst-of {'/'.join(self.basket)} {self.maturity:%b-%y} ({4 * self.coupon * 100:.2f}% a year, "
                    f"knock-in {self.ki * 100:g}%)")
        if self.is_basket:
            kind = "call" if self.is_call else "put"
            return f"{side} basket {self.strike_pct:g}% {kind} {self.maturity:%b-%y} ({self.basket_label()})"
        if self.is_option:
            return f"{side} {self.underlying} {self.strike_pct:g}% {self.product} {self.maturity:%b-%y}"
        return f"{side} {self.underlying} variance swap {self.maturity:%b-%y}"


def maturity_of(trade_date: pd.Timestamp, months: int) -> pd.Timestamp:
    m = trade_date + pd.DateOffset(months=months)
    while m.weekday() >= 5:
        m -= pd.Timedelta(days=1)
    return m


def parse_basket(text) -> dict:
    if not isinstance(text, str) or not text:
        return {}
    return {k: float(v) for k, v in (part.split(":") for part in text.split(";"))}


def format_basket(basket: dict) -> str:
    return ";".join(f"{n}:{w:.4f}" for n, w in basket.items())


def _from_frame(df: pd.DataFrame) -> list[Trade]:
    out = []
    for r in df.to_dict("records"):
        get = lambda k: None if k not in r or pd.isna(r[k]) else r[k]  # noqa: E731
        out.append(Trade(id=r["id"], trade_date=pd.Timestamp(r["trade_date"]),
                         maturity=maturity_of(pd.Timestamp(r["trade_date"]), int(r["tenor_months"])),
                         client=r["client"], product=r["product"], underlying=r["underlying"],
                         strike_pct=None if get("strike_pct") is None else float(r["strike_pct"]),
                         notional=None if get("notional_usd") is None else float(r["notional_usd"]),
                         vega=None if get("vega_usd") is None else float(r["vega_usd"]),
                         sign=1 if r["desk_side"] == "long" else -1, note=r.get("note", "") or "",
                         basket=parse_basket(get("basket")),
                         trade_vol=None if get("trade_vol") is None else float(r["trade_vol"]),
                         tenor_months=int(r["tenor_months"]),
                         coupon=None if get("coupon_pct_q") is None else float(r["coupon_pct_q"]) / 100,
                         ki=None if get("ki_pct") is None else float(r["ki_pct"]) / 100,
                         call=None if get("call_pct") is None else float(r["call_pct"]) / 100))
    return out


def load_trades(path=BLOTTER, generated=GENERATED, include_generated: bool = True) -> list[Trade]:
    frames = [pd.read_csv(path)]
    if include_generated and generated.exists():
        frames.append(pd.read_csv(generated))
    return sorted(_from_frame(pd.concat(frames, ignore_index=True)), key=lambda t: (t.trade_date, t.id))


def to_row(t: Trade, tenor_months: int) -> dict:
    return {"id": t.id, "trade_date": t.trade_date.date(), "client": t.client, "product": t.product,
            "underlying": t.underlying, "strike_pct": t.strike_pct, "tenor_months": tenor_months,
            "notional_usd": t.notional, "vega_usd": None, "desk_side": "long" if t.sign > 0 else "short",
            "basket": format_basket(t.basket), "trade_vol": round(t.trade_vol, 6), "coupon_pct_q": None, "ki_pct": None,
            "call_pct": None, "note": t.note}
