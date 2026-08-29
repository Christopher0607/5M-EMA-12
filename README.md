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

> **Correction (contract cap).** Earlier revisions of this file capped position size at
> **10 micros**. TopStep's real limit is **50 on a $50K** (100 / 150 on the larger tiers). The wrong
> cap bound on **89% of trades**, so it — not the 1% risk rule — was setting position size, and it
> was quietly shielding the strategy from its own commission bill. Everything below is re-run at
> the correct cap. The headline moved from **−67.4% to −250.8%**. `fixed N=2` is unaffected
> (pinned at 2 contracts) and the ranking of configurations is unchanged.

**2010-06-07 → 2026-08-28 · 3,529 trades · 4.81M 1-minute bars · $50,000 account**

## Headline — the strategy as specified

ATR-normalised stop, k=1.0, adverse-first path:

| | |
|---|---|
| **Total return** | **−250.8%** (−$125,414) |
| Annualised | −15.5% |
| Win rate | 34.5% |
| Profit factor | 0.82 |
| Max drawdown | −$125,591 |
| Sharpe | −1.09 |
| Exits via stop | **100%** — the 6-hour cap never once bound |

The P&L bridge is the whole story:

| | |
|---|---|
| Gross P&L | **+$23,775** |
| Commissions (3,529 trades × ~32 micros) | **−$149,189** |
| **Net** | **−$125,414** |

Fees are **6.3× gross profit**. A tighter stop forces a larger position to keep risk at 1%,
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

---

# TopStep: tiers, risk bases, and scaling to maximum capital

Run with `scripts/run_topstep.py`. Models the 2026 published terms: 50/100/150 micro caps,
$150 qualifying days, the Combine consistency rule (best day ≤ 50% of target, which gates
*passing*, not withdrawing), per-payout caps of $2,000/$3,000/$5,000, and a flat 90/10 split.

## The risk basis decides whether a bigger account helps

An MLL scales 2.25× from $50K to $150K while a 1%-of-balance risk scales 3×, so the sizing rule —
not the account size — sets how much room you actually have:

| Risk basis | $50K | $100K | $150K |
|---|---|---|---|
| Fixed $500 | 4 losses | 6 | **9** |
| 1% of balance | 4 | 3 | **3** ← *bigger account is tighter* |
| 25% of MLL | 4 | 4 | 4 |

## Scaling one account (pct 0.5% fixed stop, Standard path, net to trader over 16 years)

| Tier | Fixed $500 | 1% of balance | 25% of MLL |
|---|---|---|---|
| $50K | $2,670 | $2,670 | $2,670 |
| $100K | $17,650 | $31,224 | $9,418 |
| **$150K** | **$39,525** | $46,563 | $13,458 |

Pass rate is what drives this: 13.3% on a $50K against **30.9%** on a $150K under fixed risk.
`pct_balance` posts the single highest number ($46,563) but on a **8.8% pass rate** with **79% of
payouts hitting the cap** — it rarely passes, and when it does the firm's cap, not the strategy,
limits the income.

## One big account beats several small ones

For the same 150-micro capacity:

| | Capacity | Total MLL | Total payout cap | Pass rate | Net |
|---|---|---|---|---|---|
| 1 × $150K | 150 | $4,500 | $5,000 | 30.9% | **$39,525** |
| 3 × $50K | 150 | $6,000 | $6,000 | 13.3% | $8,009 |

The three small accounts have **more** aggregate drawdown room and **more** total payout cap, yet
net 20% as much. Copied accounts are perfectly correlated — one busts, they all bust — so what
matters is the room a *single* account has, never the sum.

## Maximum capital: pick the biggest tier, then copy it

| Accounts | Funded capital | Payouts | Net over 16 yrs | Per year |
|---|---|---|---|---|
| 1 × $150K | $150,000 | 29 | $39,525 | $2,440 |
| 3 × $150K | $450,000 | 87 | $118,576 | $7,319 |
| 5 × $150K | $750,000 | 145 | $197,626 | $12,199 |
| 10 × $150K | $1,500,000 | 290 | $395,252 | $24,398 |

**Exactly linear, and that is the warning.** Copies multiply income, fees, and ruin risk together
and diversify nothing. Three practical limits the arithmetic does not show: TopStep permits
multiple Express Funded accounts but only **one Live Funded account** at a time; 10 × 150 micros is
1,500 MNQ (150 NQ-equivalent) hitting the open in one clip, which is a market-impact question this
backtest does not model; and every copy needs its own evaluation fees paid through the same losing
stretches.

## Payout path

Consistency (3 days, 40% target, higher caps) beats Standard on the smaller tiers — $4,919 vs
$2,670 on a $50K — but loses badly on a $150K ($19,933 vs $39,525), where the 40% share rule blocks
more than the higher cap returns.

## TopStep vs Apex

TopStep is materially harder: `fixed N=2` passes 44.1% at Apex against 37% at TopStep once the
Combine consistency rule is enforced, because of the $1,000 daily loss limit and that rule. Best
single-account TopStep result (~$39.5k over 16 years) trails the best Apex result (~$50.6k).

---

# Four-firm comparison and execution playbook

Run with `scripts/run_firms.py`. Adds **Lucid (LucidPro)** and **Take Profit Trader (PRO)**
alongside Apex and TopStep, modelled on 2026 published terms.

## The firms differ structurally, not just numerically

| Firm | Eval drawdown | Funded drawdown | Daily loss | Split | Payout cap | Consistency |
|---|---|---|---|---|---|---|
| Apex | intraday high | intraday high | none | 100% to $25k | first 3 at $2,000 | 30% per cycle |
| Lucid (LucidPro) | close | close, then locks | **soft — no bust** | 90/10 | none | 40% per cycle |
| TopStep | close | close | hard — busts | 90/10 | $2,000/$3,000/$5,000 | 50% of target |
| Take Profit Trader | close | **intraday high** | none (PRO) | 80/20 | none | 50% of lifetime |

**TPT is the only firm that gets harder after you pass** — the evaluation trails end-of-day but
the funded PRO account switches to intraday. Lucid is the opposite: the funded threshold stops
following profits and its daily limit is a *soft* breach that only stops you trading for the day.

## The three questions have three different answers

Apex $50K, immediate withdrawal:

| Goal | Strategy | Number | Cost |
|---|---|---|---|
| Pass fastest | `fixed N=1` | 60% pass rate ($50K), 73.7% ($150K) | nets only $17,481 |
| Survive funded | `fixed N=1` | 52% two-year survival | same — earns little |
| **Most money** | **`pct 0.5% fixed stop`** | **$58,176–62,458** | **0% two-year funded survival** |
| Middle ground | `fixed N=2` | 54% pass, 19% survival | $22,672 |

**The money-maximising strategy is the one that repeatedly blows the funded account.** It earns
fast, withdraws, busts, and buys another evaluation. That is a real cost in fees and grind, not
just a number.

All three winners use a **non-trailing** stop. The trailing stop ranked last in 4 configs × 2 path
assumptions — 8 of 8.

## Smaller accounts win at three of four firms

`pct 0.5% fixed stop`, immediate withdrawal, net to trader:

| Tier | Apex | Lucid | TopStep | TPT |
|---|---|---|---|---|
| $50K | **$58,176** | **$48,950** | $2,670 | **$37,605** |
| $100K | $24,686 | $41,306 | $17,650 | $17,087 |
| $150K | $10,030 | $27,717 | **$39,525** | $18,239 |

Profit targets scale **3×** across tiers while loss limits scale about **2×**, so a $150K needs
proportionally more profit in proportionally less room. Median time to pass runs **16 days at $50K
against 89 at $150K**, and a 16-year window therefore holds far fewer funded cycles. TopStep is the
exception: its $50K pairs a worse target/MLL ratio (1.50 vs Apex's 1.20) with half the contract
capacity (50 vs 100 micros).

## Withdrawal timing is firm-specific

| Firm | Best policy | Evidence |
|---|---|---|
| Apex | accumulate to $2,000 | $62,458 vs $58,176 immediate, but 81% hit the cap |
| Lucid | immediate | $35,557; no payout cap, so take it early |
| TopStep | immediate | $39,525 vs $15,511 accumulating — the cap makes waiting pointless |
| **TPT** | **half, keep a buffer** | **$29,433 vs $19,175 immediate (+53%)** — funded is intraday-trailing |

## Platform ranking

| Firm | Best combo | Median | Best pass rate | Median days to pass |
|---|---|---|---|---|
| **Apex** | **$62,458** | $16,286 | 74% | 74 |
| **Lucid** | $48,950 | **$20,623** | 69% | 78 |
| TopStep | $39,525 | $11,857 | 69% | 77 |
| TPT | $37,605 | $13,194 | 69% | 78 |

**Apex has the highest ceiling; Lucid is the most consistent** and has the most forgiving rules.

## Daily execution

1. **Before 09:30 ET** — 5-minute chart with **extended hours on**, EMA(12). The backtest uses the
   24-hour continuous session; an RTH-only chart gives different signals.
2. **09:35:00 ET** — first 5-minute bar closes. Above EMA12 → market long; below → market short.
   Exact tie → skip.
3. **Place the stop immediately** at 0.5% of entry (~115 points with NQ at 23,000). Size =
   $500 ÷ (stop points × $2), about 2 micros today. **Do not move it.**
4. **15:35 ET** — flat if not stopped. Always inside the session, so no overnight gap risk.
5. **One trade per day.** Every result here assumes exactly that.

## Stop-loss criteria for the whole plan

- **5 consecutive failed evaluations** — at a 34% pass rate that has a 12.5% chance of happening
  by luck; beyond it, assume the regime no longer matches the backtest.
- **Live drawdown exceeding 1.5× the backtest's worst for the same window** — the model is broken.
- Fees spent with no first payout: the best combo's first payout lands on session **867**, but that
  is inflated by 2010–2017 when the strategy earned nothing. Judge against post-2018 behaviour.

## Not modelled

Market impact (10 copied accounts = 1,500 MNQ into the open), rule changes (TopStep revised payouts
in April 2026), the 1-minute resolution limit (which is why every recommendation above uses a wide
stop with <20pp path divergence), and execution discipline across 3,529 consecutive sessions.

## Honest summary

Best combination earns **$62,458 over 16.2 years — about $3,855 a year** — and that is with
hindsight knowledge of the best parameter. The walk-forward test says discount roughly a third.
This is worth a small live validation, not a business plan.

---

# TradingView script and automation routing

`pine/nq_ema12_open.pine` — Pine v6 strategy reproducing the backtest. Setup, inputs and alert
wiring are in [`pine/README.md`](pine/README.md).

## Which firm can actually run this automatically

| Firm | Evaluation | Funded | Path |
|---|---|---|---|
| **Lucid** | allowed | **allowed** | native TradingView; Python/Java/C++ API; TradersPost |
| **TopStep** | allowed | allowed | TopstepX / ProjectX official API; PickMyTrade |
| Apex | allowed | **prohibited** | funded account bans fully autonomous bots |
| Take Profit Trader | **prohibited** | **prohibited** | bots not permitted at all |

**This reverses the platform recommendation above.** Apex produced the best career result
($62,458), but it prohibits automation on the funded account — so that number is unreachable if you
intend to automate; the funded phase would have to be traded by hand.

**Lucid becomes the answer**: second best economically ($48,950), the only firm permitting
automation in *both* phases, and the only one treating TradingView as a first-class platform.

All three permissive firms ban HFT and latency arbitrage. One trade a day is nowhere near that.
Policies change — verify before going live.

## The script

Switchable stop (percent-of-price, fixed points, ATR multiple), defaulting to the 0.5% fixed stop.
Risk-based sizing at $500 per trade, capped per firm. Flat at 15:35 ET.

**No take profit** — the tested design exits on the stop or the clock, and the time exit is drawn
distinctly so it never reads as a stop-out. **The stop does not trail**, because trailing ranked
last in 8 of 8 configurations.

Marked on the chart: signal bar shading, direction arrows, a label with size / stop distance / risk
dollars, the stop line, the time-exit marker, skipped signals, and a live status table.

### The one setting that fails silently

The EMA runs on the **24-hour continuous session**. With extended hours off, TradingView computes a
different EMA and produces different signals **with no error**. The script checks whether the bar
before the 09:30 signal bar is 09:25 and raises a visible warning — a runtime guard rather than a
line of documentation, because this is the mistake that would quietly invalidate everything.

### Verifying the script against the backtest

```bash
./.venv/bin/python scripts/export_tv_check.py --since 2025 --max-contracts 40
```

Compare the Strategy Tester's trade list against `results/tv_expected_trades.csv` on **date and
direction**. Prices will not match — different continuous contract, different intrabar fill
convention, different cost model. A few ticks of difference is expected; a **direction** mismatch
means the chart is misconfigured, almost always extended hours.

Reference: 415 trades in 2025-to-date, 215 short / 200 long, exits 225 time / 187 stop / 3 session end.
