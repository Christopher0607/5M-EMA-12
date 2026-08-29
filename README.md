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
