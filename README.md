# Trading Book: a simulated derivatives desk on top of three research projects

**Live morning sheet: [https://morning-sheet-olive.vercel.app/book](https://morning-sheet-olive.vercel.app/book)**, rerun every weekday after the US close.

The three sister projects study the market: the [volatility dashboard](https://github.com/lonb3k/vol-dashboard)
(ATM vol, skew, the VIX), the [dispersion study](https://github.com/lonb3k/dispersion) (implied correlation, single-name
vols from 50 option chains) and the [basket optimizer](https://github.com/lonb3k/basket-optimizer) (covariance, risk-based
baskets). This repo runs a desk on them. A blotter of fictitious client trades on the S&P 500 and five Mag 7 names,
from vanilla puts to autocalls and worst-ofs priced by Monte Carlo, is booked, marked every evening on real market
data, hedged, its P&L explained line by line, its risk aggregated against limits, and turned into **axes**: the shifts
a trader applies to new quotes to recycle the risk the book already carries. Every week the basket optimizer builds
client baskets from those axes, and fictitious clients take the notes that beat the street.

**Everything about the trades is fictitious: clients, sizes, dates, coupons. The market data and the marks are real.**

## The loop, every evening

```
vol_dashboard    ── S&P 500 ATM vol history, Black-76, live SPY smile ──┐
dispersion       ── single-name vol rebuild, live 50-chain snapshot ────┼─> marks ─> revalue ─> P&L explain
basket_optimizer ── Ledoit-Wolf correlation, six weighting schemes ─────┘     │      (Monte Carlo for notes)
                        ▲                                                     └─> risk vs limits ─> axes
                        └──────────── weekly pitch: axed client baskets <──────────────────────────────┘
```

1. **Mark.** One volatility surface per underlying: a one-month ATM level, a term structure and a skew slope.
   The ATM level is the live option chain when a sister project captured it that evening, the model otherwise.
   The correlation between single names is marked at the basket optimizer's Ledoit-Wolf estimate of the last year.
2. **Book new deals.** At the client price (mid vol plus or minus half a bid-ask: 0.4 vol point on the index,
   1 on single names and on basket vol; notes carry a 1.5-2% fee built into their coupon). The same evening they
   are revalued at mid; the difference is the day-one P&L.
3. **Revalue and explain.** For every trade alive the evening before, the Greeks of yesterday's close applied to
   today's moves: delta, gamma, vega, vanna (notes), correlation, theta. What they do not cover is the unexplained line.
4. **Settle and hedge.** Expired options pay their intrinsic value, variance swaps their realized variance against
   the strike; notes pay coupons, autocall or redeem on their observation dates. Each underlying is then
   delta-hedged at the close (1 bp per trade on the index, 2 bp on single names).
5. **Aggregate risk** by underlying and maturity bucket, plus Corr01, and compare it to limits.
6. **Axes**, then, on the first trading day of the week, **the pitch** (below), then the sheet.

The identity `daily P&L = new deals + delta + gamma + vega + vanna + correlation + theta + unexplained + hedge +
hedge costs` holds to the cent every day, and is tested.

## Where the book stands (30 October 2026)

Twenty hand-written trades since November 2025: pension funds and a macro fund buying S&P 500 puts, private banks
selling single-name puts through reverse convertibles, an asset manager overwriting calls, a hedge fund buying
dispersion through variance swaps, two autocalls on the S&P 500 and two worst-ofs on three names. Since January,
32 basket notes pitched by the desk and accepted by four fictitious clients. 52 trades, 47 live.

| Since 3 Nov 2025, $k, delta-hedged | P&L |
|---|---|
| Hand-written vanillas and variance swaps | +1,873 |
| Autocalls and worst-ofs | −1,593 |
| Pitched basket notes | +8,108 |
| Hedging costs | −187 |
| **Total** | **+8,202** |

- **On the vanillas, the margin pays for half, the index variance premium for the rest.** On the S&P 500, the puts
  the desk sold earned $3.7m of theta against $1.8m of gamma: the variance premium the vol dashboard measures,
  collected by the side of the trade that sells protection.
- **The notes made the desk long vol, and vol came off.** The autocalls and worst-ofs leave the desk owning the
  knock-in puts the clients sold. They earned $2.5m of fees on day one, then paid $3.8m of theta and lost $2.1m of
  vega as single-name vol came off.
- **The pitched notes sold that vol back, and earned the premium.** The capital-protected notes the desk pitched
  are short basket calls: $5.3m of theta and $3.1m of vega against $1.4m of gamma.
- **The unexplained is small, and where it is not, it is a jump.** The largest days are earnings: Microsoft +15.5%
  on 30 July (+$637k on the call the desk was long), Amazon +15.3% on 31 July. A second-order expansion cannot price
  a 15% gap. A desk reads that line to find exactly those days.

## Axes

Official marks stay at mid: they are what the P&L is measured on and what product control checks. The axes move
only the price of new deals:

    axe shift (vol points)          = − max shift × clip(vega / vega limit, −1, 1)       1 point on a name, 0.5 on the index
    axe shift (correlation points)  = − 3 × clip(Corr01 / Corr01 limit, −1, 1)

A book long vega on a name quotes that name's vol below mid, which makes the desk the best price on notes where the
client buys vol, and the worst where the client sells it. On 30 October the largest axes are to sell Amazon vol
(114% of its limit), buy correlation (98%) and sell Nvidia vol (56%).

## Exotic notes, priced by Monte Carlo (step 3)

| Note | Coupon a year | Desk vega, $k per vol point | Corr01, $k | Status on 30 Oct |
|---|---|---|---|---|
| S&P 500 autocall, Jan 2026, 2 years, $50m | 9.40% | – | – | called on 10 Jul at 108.6%, paid 104.70% |
| Worst-of Nvidia / Tesla / Amazon, Jun 2026, 1 year, $20m | 27.90% | +142 | −10.4 | coupon paid 15 Sep |
| S&P 500 autocall, Sep 2026, 2 years, $50m | 9.64% | +167 | – | live |
| Worst-of Apple / Microsoft / Amazon, Oct 2026, 1 year, $15m | 22.82% | +136 | −7.4 | live |

- **The desk sells the note.** The client's notional sits on deposit at the risk-free rate and the desk owes the
  payoff, so the position is deposit minus the note's present value. Coupons were solved on the trade date so that
  the note is worth 98-98.5% of notional at mid: the structurer's fee.
- **Monte Carlo.** Correlated lognormal paths simulated exactly on the quarterly observation dates, 20,000 of them
  (antithetic), one flat vol per name taken at the knock-in strike, the Ledoit-Wolf correlation. The paths are drawn
  once per trade and reused every evening and in every bump, so the P&L moves with the market, not with the random
  numbers. Standard error: about 0.1-0.2% of notional.
- **The Greeks match what desks report.** An autocall leaves the desk long vol (it owns the knock-in put) and short
  delta; a worst-of leaves it long vol and short correlation, because the put on the worst name is worth more when
  the names drift apart.
- **The autocall's unexplained was vanna.** In the March-April sell-off the S&P 500 fell while its vol rose, and the
  autocall's vega grew as the index moved towards the barrier. Delta and vega lines alone left $0.8m unexplained; a
  vanna line, the vol move revalued at the new spot, brought it to $0.2m. On all the notes, the unexplained is now
  1.7% of the gross Greek P&L, mostly on observation days when the call digital resolves.

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
| Notes accepted | 32 of 43 weeks (22 reverse convertibles, 10 protected notes), $620m | |
| Risk score, average | 1.22 | 4.08 |
| Days with a vega or Corr01 limit breached | 42 of 209 | 159 of 209 |
| Amazon vega today, share of its limit | 114% | 236% |
| Corr01 today, share of its limit | 98% | 9% |
| Day-one margin on the notes, after the axe concession | +$1,230k | |
| P&L of the notes, delta-hedged | +$8,108k | |

- **The axes do the selection.** The insurer's first note, on 12 January, was a call on Apple 60%, Nvidia 32%,
  Tesla 8% (min-variance weights): the book was long all three vols, so the desk quoted them low and paid a 24.2%
  participation against 23.7% on the street. The risk score fell from 3.66 to 0.09.
- **Recycling trades one risk for another.** The worst-ofs pushed single-name vega far over its limits. The
  protected notes that sold it back are short basket calls, so they also sold correlation: Corr01 sits at 98% of its
  limit with the notes, 9% without. The risk score weighs both and still prefers it; the next pitches should be
  notes that buy correlation back.
- **Recycling is not free.** The axe gives part of the spread back, and the notes carry their own market risk once
  booked. Here the short basket calls earned the variance premium; that is a result of this year's market, not a
  property of the method.

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
  hides what the Greeks miss. A desk wants to see the jump days. Baskets and notes are the exception for gamma and
  vanna: with cross-gammas between names, those lines are revaluations minus the first-order lines.
- **The marks are the market's, the axes are the trader's.** Shifting the marks to suit the book is mismarking. Only
  the quotes for new deals move.
- **Notes are funded.** The client's notional earns the risk-free rate inside the position; without it the note's
  accretion would show up as a fake theta loss of 4% a year.
- **Same paths every evening.** Monte Carlo noise would otherwise appear as daily P&L.
- **A booked trade is a fact.** Pitches are logged and accepted notes appended; a later run reloads them instead of
  pitching again. Adding the step-3 notes, dated in the past, was the one time the pitch history was replayed.
- **The best price wins.** A client takes the desk's note only if it beats the street by 0.1 point; ties go to the
  street. Without axes the desk never wins, which is tested.
- **No funding cost on hedges, flat 4% rate, constant dividend yields.** Second order at these sizes, and stated.

## Tests

```bash
.venv/bin/python -m pytest -q tests
```

Twenty-three tests. Black-76 Greeks match finite differences and put-call parity holds; a variance swap is worth zero
at its fair strike, pays RV² − K² at maturity and half of it half-way; on a synthetic market the daily P&L equals the
sum of its explain lines, the hedge cancels the delta line, new deals earn the spread, expired trades leave the book
with their cash, small moves are explained and a 15% jump lands in the unexplained line on the right day and name;
short index vega is short correlation and the axe points the right way; the skew calibration reproduces the risk
reversal it was fitted on. Baskets: a one-name basket is the single option, basket vol rises with correlation and the
per-name vegas add up to a parallel shift, basket put-call parity holds, the street wins every tie when the desk has
no axe, and a book long single-name vol wins a protected note that lowers its risk score. Notes: a one-name worst-of
and an autocall that can never be called match the closed form within three standard errors, the solved coupon
leaves exactly the fee, the desk is long vol, short delta and short correlation on a worst-of, an autocall in a
rising market is called at its first observation with its coupon, and notes are explained on a calm market.

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
data/trades.csv            the hand-written blotter (vanillas, variance swaps, autocalls, worst-ofs)
data/trades_generated.csv  notes the clients accepted from the weekly pitch
data/pitches.csv           every pitch, accepted or not
src/book/
  links.py                 imports from the three sister projects
  data.py                  prices, VIX family, COR1M, the sister projects' live snapshots
  marks.py                 the daily surface: ATM, term structure, skew, variance-swap levels, correlation
  pricing.py               Black-76 Greeks, variance-swap valuation
  basket.py                basket options: moment-matched pricing, per-name Greeks, Corr01
  mc.py                    autocalls and worst-ofs: Monte Carlo pricing, coupon solving, bumped Greeks
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

- Local volatility for the notes, so the skew moves with spot instead of being frozen at the knock-in strike.
- Autocalls and worst-ofs in the weekly pitch, and notes that buy correlation back now that Corr01 is the binding limit.
