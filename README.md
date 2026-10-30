# Trading Book: a simulated derivatives desk on top of three research projects

**Live morning sheet: [https://morning-sheet-olive.vercel.app/book](https://morning-sheet-olive.vercel.app/book)**, rerun every weekday after the US close.

The three sister projects study the market: the [volatility dashboard](https://github.com/lonb3k/vol-dashboard)
(ATM vol, skew, the VIX), the [dispersion study](https://github.com/lonb3k/dispersion) (implied correlation, single-name
vols from 50 option chains) and the [basket optimizer](https://github.com/lonb3k/basket-optimizer) (covariance, risk-based
baskets). This repo runs a desk on them. A blotter of fictitious client trades on the S&P 500 and five Mag 7 names is
booked, marked every evening on real market data, hedged, its P&L explained line by line, its risk aggregated against
limits, and turned into **axes**: the shifts a trader applies to new quotes to recycle the risk the book already carries.
Every week the basket optimizer then builds client baskets from those axes, and fictitious clients take the notes that
beat the street.

**Everything about the trades is fictitious: clients, sizes, dates, coupons. The market data and the marks are real.**

## The loop, every evening

```
vol_dashboard    ── S&P 500 ATM vol history, Black-76, live SPY smile ──┐
dispersion       ── single-name vol rebuild, live 50-chain snapshot ────┼─> marks ─> revalue ─> P&L explain
basket_optimizer ── Ledoit-Wolf correlation, six weighting schemes ─────┘     │
                        ▲                                                     └─> risk vs limits ─> axes
                        └──────────── weekly pitch: axed client baskets <──────────────────────────────┘
```

1. **Mark.** One volatility surface per underlying: a one-month ATM level, a term structure and a skew slope.
   The ATM level is the live option chain when a sister project captured it that evening, the model otherwise.
   The correlation between single names is marked at the basket optimizer's Ledoit-Wolf estimate of the last year.
2. **Book new deals.** At the client price (mid vol plus or minus half a bid-ask: 0.4 vol point on the index,
   1 on single names and on basket vol). The same evening they are revalued at mid; the difference is the day-one P&L.
3. **Revalue and explain.** For every trade alive the evening before, the Greeks of yesterday's close applied to
   today's moves: delta, gamma, vega, correlation, theta. What they do not cover is the unexplained line.
4. **Settle and hedge.** Expired options pay their intrinsic value, variance swaps their realized variance against
   the strike. Each underlying is then delta-hedged at the close (1 bp per trade on the index, 2 bp on single names).
5. **Aggregate risk** by underlying and maturity bucket, plus Corr01, and compare it to limits.
6. **Axes**, then, on the first trading day of the week, **the pitch** (below), then the sheet.

The identity `daily P&L = new deals + delta + gamma + vega + correlation + theta + unexplained + hedge + hedge costs`
holds to the cent every day, and is tested.

## Where the book stands (30 October 2026)

Sixteen hand-written trades since November 2025: pension funds and a macro fund buying S&P 500 puts, private banks
selling single-name puts through reverse convertibles, an asset manager overwriting calls, a hedge fund buying
dispersion through variance swaps. Since January, 27 basket notes pitched by the desk, accepted by four fictitious
clients. 43 trades, 39 live.

| Since 3 Nov 2025, $k | Whole book | Hand-written trades only |
|---|---|---|
| New deals (day-one margin) | +1,914 | +896 |
| Gamma | +183 | +902 |
| Vega | −1,729 | −927 |
| Correlation | −486 | 0 |
| Theta | +4,382 | +1,027 |
| Hedging costs | −158 | −120 |
| Unexplained | −141 | −25 |
| **Total** | **+3,965** | **+1,753** |

Delta and its hedge cancel every day and are left out.

- **On the hand-written trades, the margin pays for half, the index variance premium for the rest.** On the S&P 500,
  the puts the desk sold earned $3.7m of theta against $1.8m of gamma: the variance premium the vol dashboard
  measures, collected by the side of the trade that sells protection. On single names, the puts bought from reverse
  convertibles earned $2.7m of gamma, paid it back in theta and lost $1.2m of vega as single-name vol came off.
- **The unexplained is small, and where it is not, it is a jump.** The largest days are earnings: Microsoft +15.5% on
  30 July (+$637k on the call the desk was long), Amazon +15.3% on 31 July. A second-order expansion cannot price a
  15% gap. A desk reads that line to find exactly those days.
- **The book is short correlation.** Short $138k of S&P 500 vega with long single-name vega is short correlation:
  Corr01 is −$59k per correlation point, 79% of its limit (87% without the pitched notes). That is the risk the
  dispersion project measured, carried by a desk.

## Axes

Official marks stay at mid: they are what the P&L is measured on and what product control checks. The axes move
only the price of new deals:

    axe shift (vol points)          = − max shift × clip(vega / vega limit, −1, 1)       1 point on a name, 0.5 on the index
    axe shift (correlation points)  = − 3 × clip(Corr01 / Corr01 limit, −1, 1)

A book long vega on a name quotes that name's vol below mid, which makes the desk the best price on notes where the
client buys vol, and the worst where the client sells it. On 30 October the largest axes are to buy correlation
(79% of the limit), buy S&P 500 vol (55%) and sell Tesla vol (53%).

## Recycling with axed baskets (step 2)

On the first trading day of each week, sales call the one client whose note best recycles the book's risk.

- **Four fictitious clients, two one-year notes.** Two private banks buy **basket reverse convertibles**: they want a
  coupon (9% and 7%), the desk solves for the strike that pays it, the client sells the desk a put on the basket. An
  insurer and an asset manager buy **capital-protected notes**: an at-the-money call on the basket, judged on its
  participation (minimums 22% and 25%).
- **Candidate baskets.** Every 3, 4 and 5-name subset of the book's names, weighted by each of the basket optimizer's
  six schemes run on a forward-looking covariance (tonight's one-year implied vols and the Ledoit-Wolf correlation).
- **Pricing.** Basket options on a lognormal matched to the basket's first two moments (Levy 1992), each name at its
  own vol for its strike. The desk prices with its axes, the street the same note at mid without; same spread.
- **Choice.** Among the notes a client would take (a lower strike than the street, or a better participation), the
  desk pitches the one that most reduces its **risk score**: the sum of squared limit usages, vega by name and Corr01.
  No pitch if none does. Accepted notes are appended to `data/trades_generated.csv`, never recomputed.

| Since 5 January 2026 | With the pitched notes | Without |
|---|---|---|
| Notes accepted | 27 of 43 weeks (18 reverse convertibles, 9 protected notes), $540m | |
| Risk score, average | 1.00 | 2.40 |
| Days with a vega or Corr01 limit breached | 22 of 209 | 63 of 209 |
| NVDA vega today, share of its limit | 9% | 71% |
| Corr01 today, share of its limit | 79% | 87% |
| Day-one margin on the notes, after the axe concession | +$1,018k | |
| P&L of the notes, delta-hedged | +$2,249k | |

- **The axes do the selection.** The insurer's first note, on 12 January, was a call on Apple 60%, Nvidia 32%,
  Tesla 8% (min-variance weights): the book was long all three vols, so the desk quoted them low and paid a 24.0%
  participation against 23.7% on the street. The risk score fell from 4.34 to 1.24.
- **The two products pull in opposite directions.** A reverse convertible buys back correlation but adds single-name
  vol; a protected note sells single-name vol but sells correlation too. The optimizer trades one against the other.
  Sixteen weeks ended without a pitch: in twelve, no note the desk could win reduced the risk; in four, it could win none.
- **Recycling is not free.** The axe gives part of the spread back. The notes then carry their own market risk:
  delta-hedged, they earned $3.4m of theta net (mostly the protected notes' short calls) and lost $0.7m of gamma,
  $0.8m of vega and $0.5m of correlation as vol and correlation came off.

## Marks, and how they are checked

| | Live chain (from 27 Oct 2026) | Model (before) |
|---|---|---|
| S&P 500 ATM | SPY chain, vol dashboard's daily snapshot | Vol dashboard: VXO / √(30/22) to 2021, then VIX × (a + b ln VIX + c SKEW) |
| Single-name ATM | 50 chains, dispersion project's daily snapshot | Dispersion rebuild: ATM_spx² = k² [B + COR1M (A − B)], name = k × trailing 63-day vol |
| Term structure | 30 and 90 days from the chains | VIX9D / VIX / VIX3M / VIX6M shape, flat beyond six months |
| Skew | Slope from the live 25-delta risk reversal | Median of the live slopes |
| Variance swaps | S&P 500: VIX family, model-free. Single names: ATM × 1.10 | same |
| Correlation between names | Basket optimizer's Ledoit-Wolf, last 252 days | same |

On live days the model mark is kept next to the official one. The gap times the vega is the P&L the remark moves,
the number an independent price verification asks the desk to explain. On 30 October the model had Amazon at 34.0
and the chain at 46.5: the chain prices the earnings, a trailing-vol model cannot.

## Decisions, and why

- **Strikes in percent of spot, sizes in dollars.** The blotter never depends on the price level, so a split or a
  rebased data series changes no P&L.
- **Greek-based explain, not full revaluation.** Full revaluation makes the unexplained line zero by construction and
  hides what the Greeks miss. A desk wants to see the jump days. Baskets are the exception for gamma: with cross-gammas
  between names, their gamma line is a spot revaluation minus the delta.
- **The marks are the market's, the axes are the trader's.** Shifting the marks to suit the book is mismarking. Only
  the quotes for new deals move.
- **Live marks win when they exist.** The model fills history and is kept as a check, not the other way round.
- **A booked trade is a fact.** Pitches are logged and accepted notes appended; a later run reloads them instead of
  pitching again, so the history never changes when the data is revised.
- **The best price wins.** A client takes the desk's note only if it beats the street by 0.1 point; ties go to the
  street. Without axes the desk never wins, which is tested.
- **No funding cost, flat 4% rate, constant dividend yields.** Second order at these sizes, and stated.

## Tests

```bash
.venv/bin/python -m pytest -q tests
```

Seventeen tests. Black-76 Greeks match finite differences and put-call parity holds; a variance swap is worth zero at
its fair strike, pays RV² − K² at maturity and half of it half-way; on a synthetic market the daily P&L equals the
sum of its explain lines, the hedge cancels the delta line, new deals earn the spread, expired trades leave the book
with their cash, small moves are explained and a 15% jump lands in the unexplained line on the right day and name;
short index vega is short correlation and the axe points the right way; the skew calibration reproduces the risk
reversal it was fitted on. Baskets: a one-name basket is the single option, basket vol rises with correlation and the
per-name vegas add up to a parallel shift, basket put-call parity holds on the basket forward, the street wins every
tie when the desk has no axe, and a book long single-name vol wins a protected note that lowers its risk score.

## Run it

The three sister repos must sit next to this one (`../vol_dashboard`, `../dispersion`, `../basket_optimizer`).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/run_book.py            # or --offline on the mirrored data
```

Outputs in `data/out/` (daily P&L, explain by trade, risk by underlying, positions, marks, axes), the pitch log in
`data/pitches.csv` and the sheet in `sheet/latest.json`. The hand-written blotter is `data/trades.csv`: add a line to
book a trade.

## Layout

```
data/trades.csv            the hand-written blotter
data/trades_generated.csv  notes the clients accepted from the weekly pitch
data/pitches.csv           every pitch, accepted or not
src/book/
  links.py                 imports from the three sister projects
  data.py                  prices, VIX family, COR1M, the sister projects' live snapshots
  marks.py                 the daily surface: ATM, term structure, skew, variance-swap levels, correlation
  pricing.py               Black-76 Greeks, variance-swap valuation
  basket.py                basket options: moment-matched pricing, per-name Greeks, Corr01
  trades.py                blotter, spreads
  engine.py                the daily loop: book, explain, settle, pitch, hedge, aggregate
  risk.py                  limits, axes, risk score, independent check of the marks
  clients.py               the fictitious clients and the terms they compare
  pitch.py                 candidate baskets, axed and street quotes, the weekly choice
  sheet.py, charts.py      the morning sheet
scripts/run_book.py
.github/workflows/book.yml   weekdays 23:00 UTC, after the sister projects
```

## Next

- Step 3: an autocall, then a worst-of priced by Monte Carlo, whose correlation risk links back to the dispersion study.
