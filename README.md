# Trading Book: a simulated derivatives desk on top of three research projects

**Live morning sheet: [https://morning-sheet-olive.vercel.app/book](https://morning-sheet-olive.vercel.app/book)**, rerun every weekday after the US close.

The three sister projects study the market: the [volatility dashboard](https://github.com/lonb3k/vol-dashboard)
(ATM vol, skew, the VIX), the [dispersion study](https://github.com/lonb3k/dispersion) (implied correlation, single-name
vols from 50 option chains) and the [basket optimizer](https://github.com/lonb3k/basket-optimizer) (covariance, risk-based
baskets). This repo runs a desk on them. A blotter of fictitious client trades on the S&P 500 and five Mag 7 names is
booked, marked every evening on real market data, hedged, its P&L explained line by line, its risk aggregated against
limits, and turned into **axes**: the shifts a trader applies to new quotes to recycle the risk the book already carries.

**Everything about the trades is fictitious: clients, sizes, dates. The market data and the marks are real.**

## The loop, every evening

```
vol_dashboard  ── S&P 500 ATM vol history, Black-76, live SPY smile ──┐
dispersion     ── single-name vol rebuild, live 50-chain snapshot ────┼─> marks ─> revalue ─> P&L explain
basket (step 2)── optimizer that proposes client baskets <── axes <───┘           └─> risk vs limits ─> axes
```

1. **Mark.** One volatility surface per underlying: a one-month ATM level, a term structure and a skew slope.
   The ATM level is the live option chain when a sister project captured it that evening, the model otherwise.
2. **Book new deals.** At the client price (mid vol plus or minus half a bid-ask: 0.4 vol point on the index,
   1 on single names). The same evening they are revalued at mid; the difference is the day-one P&L.
3. **Revalue and explain.** For every trade alive the evening before, the Greeks of yesterday's close applied to
   today's moves: delta, gamma, vega, theta. What they do not cover is the unexplained line.
4. **Settle and hedge.** Expired options pay their intrinsic value, variance swaps their realized variance against
   the strike. Each underlying is then delta-hedged at the close (1 bp per trade on the index, 2 bp on single names).
5. **Aggregate risk** by underlying and maturity bucket, plus Corr01, and compare it to limits.
6. **Axes**, then the sheet.

The identity `daily P&L = new deals + delta + gamma + vega + theta + unexplained + hedge + hedge costs` holds to
the cent every day, and is tested.

## Where the book stands (30 October 2026)

Sixteen trades since November 2025, twelve live: pension funds and a macro fund buying S&P 500 puts, private banks
selling single-name puts through reverse convertibles, an asset manager overwriting calls, a hedge fund buying
dispersion through variance swaps.

| Since 3 Nov 2025, $k | |
|---|---|
| New deals (day-one margin) | +896 |
| Gamma | +902 |
| Vega | −927 |
| Theta | +1,027 |
| Hedging costs | −120 |
| Unexplained | −25 |
| Delta and its hedge | +189 and −189 |
| **Total** | **+1,753** |

- **The margin pays for half, the index variance premium for the rest.** Half the P&L is the bid-ask charged on
  day one. On the S&P 500, the puts the desk sold earned $3.7m of theta against $1.8m of gamma: the variance premium
  the vol dashboard measures, collected by the side of the trade that sells protection. On single names, the puts
  bought from reverse convertibles earned $2.7m of gamma, paid it back in theta and lost $1.2m of vega as single-name
  vol came off.
- **The unexplained is small, and where it is not, it is a jump.** It is 3.4% of the gross Greek P&L. The three
  largest days are earnings: Microsoft +15.5% on 30 July (+$637k on the call the desk was long), Amazon +15.3% on
  31 July. A second-order expansion cannot price a 15% gap. A desk reads that line to find exactly those days.
- **The book is short correlation.** Short $138k of S&P 500 vega with long single-name vega is short correlation:
  Corr01 is −$65k per correlation point, 87% of its limit. That is the risk the dispersion project measured, carried
  by a desk.

## Axes

Official marks stay at mid: they are what the P&L is measured on and what product control checks. The axes move
only the price of new deals:

    axe shift (vol points) = − max shift × clip(vega / vega limit, −1, 1)

with a maximum of 1 vol point on a single name and 0.5 on the index. On 30 October the book is long NVDA vega at 71%
of its $50k limit, so the desk quotes NVDA three-month vol 0.71 point below mid on products where the client buys
vol (call spreads, capital-protected notes), to get rid of it. It is short S&P 500 vega and short correlation, so it
pays up for the opposite. Step 2 gives these shifts to the basket optimizer, which then proposes client baskets that
recycle the book's risk.

## Marks, and how they are checked

| | Live chain (from 27 Oct 2026) | Model (before) |
|---|---|---|
| S&P 500 ATM | SPY chain, vol dashboard's daily snapshot | Vol dashboard: VXO / √(30/22) to 2021, then VIX × (a + b ln VIX + c SKEW) |
| Single-name ATM | 50 chains, dispersion project's daily snapshot | Dispersion rebuild: ATM_spx² = k² [B + COR1M (A − B)], name = k × trailing 63-day vol |
| Term structure | 30 and 90 days from the chains | VIX9D / VIX / VIX3M / VIX6M shape, flat beyond six months |
| Skew | Slope from the live 25-delta risk reversal | Median of the live slopes |
| Variance swaps | S&P 500: VIX family, model-free. Single names: ATM × 1.10 | same |

On live days the model mark is kept next to the official one. The gap times the vega is the P&L the remark moves,
the number an independent price verification asks the desk to explain. On 30 October the model had Amazon at 34.0
and the chain at 46.5: the chain prices the earnings, a trailing-vol model cannot.

## Decisions, and why

- **Strikes in percent of spot, sizes in dollars.** The blotter never depends on the price level, so a split or a
  rebased data series changes no P&L.
- **Greek-based explain, not full revaluation.** Full revaluation makes the unexplained line zero by construction and
  hides what the Greeks miss. A desk wants to see the jump days.
- **The marks are the market's, the axes are the trader's.** Shifting the marks to suit the book is mismarking. Only
  the quotes for new deals move.
- **Live marks win when they exist.** The model fills history and is kept as a check, not the other way round.
- **No funding cost, flat 4% rate, constant dividend yields.** Second order at these sizes, and stated.

## Tests

```bash
.venv/bin/python -m pytest -q tests
```

Twelve tests. Black-76 Greeks match finite differences and put-call parity holds; a variance swap is worth zero at
its fair strike, pays RV² − K² at maturity and half of it half-way; on a synthetic market the daily P&L equals the
sum of its explain lines, the hedge cancels the delta line, new deals earn the spread (half a vega for a variance
swap struck half a point off mid), expired trades leave the book with their cash, small moves are explained and a
15% jump lands in the unexplained line on the right day and name; short index vega is short correlation and the axe
points the right way; the skew calibration reproduces the risk reversal it was fitted on.

## Run it

The three sister repos must sit next to this one (`../vol_dashboard`, `../dispersion`, `../basket_optimizer`).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/run_book.py            # or --offline on the mirrored data
```

Outputs in `data/out/` (daily P&L, explain by trade, risk by underlying, positions, marks, axes) and the sheet in
`sheet/latest.json`. The blotter is `data/trades.csv`: add a line to book a trade.

## Layout

```
data/trades.csv          the fictitious blotter
src/book/
  links.py               imports from the three sister projects
  data.py                prices, VIX family, COR1M, the sister projects' live snapshots
  marks.py               the daily surface: ATM, term structure, skew, variance-swap levels
  pricing.py             Black-76 Greeks, variance-swap valuation
  trades.py              blotter, spreads
  engine.py              the daily loop: book, explain, settle, hedge, aggregate
  risk.py                limits, axes, Corr01, independent check of the marks
  sheet.py, charts.py    the morning sheet
scripts/run_book.py
.github/workflows/book.yml   weekdays 23:00 UTC, after the sister projects
```

## Next

- Step 2: axed baskets. The basket optimizer proposes the underlyings and weights of new client products from the
  book's axes, priced with the shifted vols; fictitious clients accept when the coupon clears a threshold.
- Step 3: an autocall, then a worst-of priced by Monte Carlo, whose correlation risk links back to the dispersion study.
