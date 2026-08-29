# NQ 5-Minute EMA12 Opening-Range Strategy

A full-history backtest of a Nasdaq-futures opening-range strategy, evaluated as a
futures prop-firm account.

## The strategy

At the close of the **09:30–09:35 ET** bar (the first five minutes of the New York
equity open):

- close **above** EMA12 → **go long**
- close **below** EMA12 → **go short**

Manage with a **trailing stop** sized so the loss at the stop equals **1% of initial
capital**, and exit no later than **6 hours** after entry.

Because entry is 09:35 ET, the six-hour cap expires at **15:35 ET** — inside the
regular session. The strategy is therefore always flat before the close and never
carries overnight gap risk.

## Setup

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
export DATABENTO_API_KEY=<your key>
./.venv/bin/python scripts/fetch_data.py          # --dry-run to price it first
./.venv/bin/python scripts/run_backtest.py
./.venv/bin/python -m pytest tests/ -q
./.venv/bin/python scripts/spot_check.py          # re-derives trades from raw bars
```

Every parameter lives in `config.yaml`. The API key is read from the environment
and is never written to disk or committed.

## Data

| | |
|---|---|
| Source | Databento `GLBX.MDP3` (CME Globex), `ohlcv-1m` |
| Symbol | `NQ.v.0` — continuous **volume rank** |
| Range | 2010-06-06 → 2026-08-28 |
| Contract simulated | **MNQ** micro, $2/point, 0.25 tick |
| Account | $50,000, 1% risk, 10-micro cap |

### Why `NQ.v.0` and not `NQ.c.0`

`.c.0` is *calendar* rank — it holds the front month until expiry, including the
week everyone has already rolled away from it. On 2024-09-20, `.c.0` traded **380**
contracts in the 09:30 hour; `.v.0` traded **68,278**. Backtesting fills in the
expiring contract during roll week is fiction, so this uses volume rank, which
follows the liquid contract.

### Why NQ data for an MNQ account

MNQ and NQ track the same underlying at the same price; the micro differs only in
point value. MNQ itself has no data before May 2019, so simulating micro contract
specs on NQ prices is both exact and the only way to reach back to 2010.

### NYSE sessions only

CME equity futures trade through several NYSE holidays (Juneteenth, Labor Day,
Thanksgiving, …) at a few percent of normal volume. There is no New York open on
those days, so the premise of the strategy fails and the thin tape would produce
fictional fills. Signals are restricted to real NYSE sessions. NYSE half-days are
kept, with their exits labelled `session_end` rather than `time`.

## Method

**Indicators.** EMA12 (α = 2/13, seeded with SMA-12) and Wilder ATR14 run
continuously over the 24-hour Globex 5-minute series and are never reset per day —
so at 09:35 the EMA reflects the overnight session, which is what a chart with
extended hours shows.

**DST.** The signal bar is located by New York local time via `zoneinfo`, never a
hardcoded UTC hour. The same 09:30 ET bar is 13:30Z in summer and 14:30Z in winter;
a test asserts both appear.

**Stop sizing.** One free variable has to be pinned, since "1% risk" alone fixes
only the product of stop distance and contract count. Three readings are tested:

| Variant | Stop distance `D` | Contracts |
|---|---|---|
| **ATR** (headline) | `k × ATR14` | `floor(risk$ / (D × $2))`, capped at 10 |
| **Percent** | `p × entry` | same |
| **Fixed** (literal) | `risk$ / (N × $2)` | fixed `N` |

The ATR variant is the headline because it is the only one that stays comparable
across the period. A fixed-dollar stop is not stationary: $500 on one MNQ is 250
points, which is 14% of price in 2010 and 1.1% today — the same rule is a
different strategy in each era.

**Intrabar path.** With 1-minute OHLC we cannot know whether a bar's high or low
came first, and for a *trailing* stop that ordering changes the result. Both
extremes are simulated. They are **not** upper and lower bounds: a within-bar
ratchet can close a trade the other ordering keeps alive. Worked example — long,
entry 100, D = 10, bar H = 115 / L = 95: adverse-first leaves the stop at 90,
survives, and ratchets to 105; favorable-first ratchets to 105 first and exits
there. `adverse_first` is the headline because it never credits a within-bar
ratchet that protects a position the same bar could have stopped out.

**Fills.** A bar that opens through the stop carried in from prior bars is a gap
and fills at the open. A stop reached only after the current bar ratcheted fills at
the stop level, since the open preceded the ratchet.

**Costs.** $1.34 round-turn per micro, plus 1 tick of slippage on entry and exit.
Both are swept.

---

# Results

**2010-06-07 → 2026-08-28 · 3,529 trades · 4.81M 1-minute bars · $50,000 account**

## Headline — the strategy as specified

ATR-normalised stop, k=1.0, adverse-first path:

| | |
|---|---|
| **Total return** | **−67.4%** (−$33,688) |
| Annualised | −4.2% |
| Win rate | 34.5% |
| Profit factor | 0.90 |
| Max drawdown | −$34,079 |
| Sharpe | −0.51 |
| Exits via stop | **100%** — the 6-hour cap never once bound |

The P&L bridge is the whole story:

| | |
|---|---|
| Gross P&L | **+$12,159** |
| Commissions (3,529 trades × ~9.7 micros) | **−$45,847** |
| **Net** | **−$33,688** |

Fees are **3.8× gross profit**. A tighter stop forces a larger position to keep risk at 1%,
and the position size is what sets the commission bill. The losses are mostly a transaction-cost
problem, not a signal problem.

## The result is resolution-limited — read this before quoting the number

1-minute OHLC cannot say whether a bar's high or low came first, and for a *trailing* stop that
ordering decides the outcome. The two extreme path assumptions give **−67.4%** and **−430.2%** —
a 363 percentage-point spread.

The reason is structural, not a one-off: **the ATR k=1 stop is only 1.6–2.1× the median
1-minute bar range in every one of the 17 years.** The stop sits inside a single bar's noise.

| Stop width | Path spread | Trustworthy? |
|---|---|---|
| 250 pts (fixed N=1) | 0.0 pp | yes |
| 53–96 pts (pct 0.5–1%) | 4–6 pp | yes |
| 45 pts (ATR k=4) | 19 pp | yes |
| 23–34 pts (ATR k=2–3) | 56–188 pp | no |
| 11–17 pts (ATR k=1–1.5) | 349–363 pp | no |

Direction is robust for k ≥ 1 (both assumptions lose money); **magnitude is not**. At k=0.5 the
two assumptions disagree even in sign. Resolving the tight-stop rows needs 1-second data
(~$468 for the full history, or ~$35–40 for recent years, RTH only).

## Does the stop hold the drawdown together?

Yes — and that is exactly the problem. Same signals, three exit rules:

| Config | Trailing | Fixed stop | No stop (6h) |
|---|---|---|---|
| ATR k=1 | **−$33,688** | +$179,253 | +$339,059 |
| ATR k=4 | **+$52,169** | +$98,302 | +$121,855 |
| pct 0.5% | **+$39,270** | +$70,612 | +$113,507 |
| fixed N=2 | **+$52,562** | +$71,919 | +$77,582 |

**Trailing < fixed < no-stop in 4 configs × 2 path assumptions — 8 of 8, no exceptions.**

The trailing stop does cut drawdown roughly in half (ATR k=1: −$34,079 vs −$68,799 unstopped;
pct 0.5%: −$14,190 vs −$30,945). The instinct behind "the stop held the drawdown together" is
correct. But it buys that by cutting winners that were still running, and it gives up more than
it saves in every configuration tested.

Note that the fixed-stop and no-stop columns are **identical under both path assumptions** —
neither ratchets inside a bar, so neither has any path ambiguity. Only the trailing stop is
path-sensitive, which means this ranking is clean and unaffected by the resolution problem above.

## Prop-firm evaluation

A fresh evaluation account is started on **every session** and run to pass, bust, or a 250-session cap.

| Config | Firm | Accounts | Passed | Blown | Pass rate |
|---|---|---|---|---|---|
| ATR k=1 (as specified) | Apex $50K | 3,528 | 388 | **3,119** | **11.1%** |
| ATR k=1 (as specified) | TopStep $50K | 3,528 | 367 | 3,157 | 10.4% |
| fixed N=2 (best in sweep) | Apex $50K | 3,528 | 1,554 | 1,370 | 53.1% |
| fixed N=2 (best in sweep) | TopStep $50K | 3,528 | 1,343 | 1,703 | 44.1% |

As specified, the strategy busts **88% of evaluation accounts**, median 93 sessions to bust.

## Year by year

2010–2018 lost money every single year; 2019–2022 turned positive; 2023–2026 turned negative
again, with 2025 (−15.2%) and 2026-to-date (−12.1%) the worst of the whole period. There is no
stable edge.

## What I would do next

1. **Drop the trailing stop.** 8-of-8 evidence says it is net negative. A fixed stop controls
   drawdown better *and* carries no path ambiguity.
2. **Position size is the lever, not the stop parameter.** Same signals at 1 micro (fixed N=1)
   pay $4,729 in fees and net +$37,092; at ~9.7 micros they pay $45,847 and net −$33,688.
3. **Buy 1-second data** if the tight-stop rows matter — that is the only way to resolve them.
4. **The signal deserves separate study.** Stripped of the stop, the plain 6-hour hold is
   solidly positive, but its −$68,799 drawdown would bust any prop account. The real question
   is how to control drawdown without killing the edge — not how to tune a trailing stop.

## Caveats

Single market, single session, no regime filter. Sweeps are sensitivity analysis, not
optimisation — the headline is the a-priori default, because quoting the best cell of a sweep
over one dataset is how backtests get overfitted. Commissions and slippage are modelled but a
real fill at the open in a fast tape can be worse. Past results do not predict future returns.

---

# Getting paid: the funded phase

Passing an evaluation is not the goal. This section simulates the whole journey — buy an
evaluation, pass, trade funded, withdraw, bust, buy another — across the full history.
Run it with `scripts/run_propfirm.py`.

## `fixed N=2` as asked

Apex $50K, promotional fees, withdraw as soon as eligible, 2010-06 → 2026-08:

| | |
|---|---|
| Evaluations bought | 37 |
| Evaluations passed | 15 (40.5%; the rolling-restart pass rate is 53.1%) |
| **Payouts** | **32** |
| Total withdrawn | $29,577 |
| Fees paid | $6,905 |
| **Net to trader** | **$22,672** (~$1,400/yr over 16.2 years) |
| Average payout | $924 (largest $2,546) |
| **First payout** | **2018-10-25 — session 1,559, 8.5 years in** |
| Time funded | 36% (the other 64% is spent re-testing) |

The 8.5-year wait is the finding, not the total. 2010–2017 earns almost nothing, so the career
never escapes the evaluation loop. Fees swing the result meaningfully: at list price rather than
promo, the same career nets $17,788 instead of $22,672.

The two pass-rate numbers differ because they answer different questions. 53.1% is the share of
*decided* accounts among rolling restarts; 40.5% is 15 passes out of 37 evaluations actually
bought in one sequential career, which includes an undecided final attempt.

## The parameter choice does not survive out of sample

`fixed N=2` won a 14-config sweep on the same 16 years it was then judged on. Two independent checks:

| | Total P&L |
|---|---|
| Walk-forward — reselect each year on prior data only | **$34,803** |
| `fixed N=2` — hindsight | $52,562 |
| Per-year best — unreachable ceiling | $115,551 |

**A 34% discount.** Last year's best config lands at rank **6.4 / 14** the next year, where random
is 7.5, and is genuinely #1 only 2 times in 15.

The single holdout is kinder: selecting on 2010–2017 *does* pick `fixed 2`, which then earns
$50,280 out of sample at rank 3/14. Two honest tests disagree about how much to discount, so the
range — not either endpoint — is the answer.

## `N=2` is not the best configuration

Like-for-like from 2018 (Apex, promo, immediate withdrawal — same window for every row, since the
holdout log only starts in 2018):

| Config | Payouts | Withdrawn | Net | Per year |
|---|---|---|---|---|
| **pct 0.5% (fixed stop)** | **42** | $59,369 | **$50,629** | **$5,863** |
| fixed N=2 (fixed stop) | 24 | $43,474 | $36,759 | $4,257 |
| walk-forward (out of sample) | 27 | $29,269 | $23,284 | $2,705 |
| fixed N=2 (trailing) | 33 | $28,539 | $22,099 | $2,559 |
| pct 0.5% (trailing) | 23 | $27,061 | $21,701 | $2,513 |

Over 80 two-year careers started throughout that window:

| Config | Median payouts | Median net | Losing careers |
|---|---|---|---|
| **pct 0.5% (fixed stop)** | 8 | **$6,553** | **0.0%** |
| fixed N=2 (trailing) | 6 | $2,981 | 26.2% |
| walk-forward | 4 | $2,250 | 35.0% |
| pct 0.5% (trailing) | 3 | $2,135 | 31.2% |
| fixed N=2 (fixed stop) | 4 | $1,030 | 8.8% |

**0% losing careers is a 2018-onward figure and must be read as such** — over the full 16 years
that config's losing share is 11.7%. 2018+ was a favourable era for this strategy.

`pct 0.5% (fixed stop)` also resists overfitting *structurally*, which matters more than winning a
sweep: the stop scales with price, so it has no "never triggers for eight years" artifact; its
intrabar path divergence is 6.4pp, small enough that 1-minute data resolves it; and a non-trailing
exit has no within-bar path ambiguity at all.

## Rules modelled

Apex and TopStep $50K programmes as publicly documented for 2024–2025: qualifying days
(8 at $50+ / 5 at $200+), safety net ($52,600 / $50,000), Apex's 30% single-day consistency rule
and $2,000 cap on the first three payouts, and profit splits (100% to $25k / 100% of the first
$10k then 90%). Fees are modelled twice, promotional and list.

**These terms change often.** Every number lives in `config.yaml` with a comment naming what it
models, so it can be corrected without touching the simulator.
