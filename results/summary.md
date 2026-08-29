# Results
NQ 5-minute EMA12 opening-range strategy, 2010-06-07 to 2026-08-28. $50,000 account, MNQ micros ($2/point), 1% risk per trade, $1.34 round-turn plus 1 tick slippage each way.

## Headline — ATR-normalised stop, k=1
The ATR variant is the headline because it is the only sizing rule that stays comparable across a period in which NQ went from ~1,800 to ~23,000.

| Metric | Value |
|---|---|
| Trades | 3,529 |
| Net P&L | $-33,688 |
| **Total return on $50k** | **-67.4%** |
| Annualised (arithmetic) | -4.2% |
| Win rate | 34.5% |
| Profit factor | 0.90 |
| Expectancy per trade | $-9.55 |
| Max drawdown | $-34,079 |
| Sharpe | -0.51 |
| Fees paid | $45,847 |

## Stop-sizing sweep (adverse-first path)

| variant | param | trades | net P&L | return % | win % | PF | max DD | avg ctr | avg stop pts |
|---|---|---|---|---|---|---|---|---|---|
| atr | 0.5 | 3529 | -40,597.10 | -81.19 | 33.38 | 0.84 | -40,645.30 | 9.99 | 5.74 |
| atr | 1 | 3529 | -33,687.76 | -67.38 | 34.51 | 0.90 | -34,078.76 | 9.70 | 11.47 |
| atr | 1.5 | 3529 | -24,339.26 | -48.68 | 34.80 | 0.94 | -27,224.64 | 9.11 | 17.21 |
| atr | 2 | 3529 | -3,417.72 | -6.84 | 35.62 | 0.99 | -23,573.28 | 8.45 | 22.95 |
| atr | 3 | 3525 | 39,396.00 | 78.79 | 36.14 | 1.09 | -18,835.64 | 7.37 | 34.16 |
| atr | 4 | 3520 | 52,169.24 | 104.34 | 36.73 | 1.11 | -19,521.90 | 6.64 | 45.21 |
| pct | 0.0025 | 3529 | 36,926.74 | 73.85 | 37.15 | 1.08 | -16,320.60 | 8.13 | 26.41 |
| pct | 0.005 | 3529 | 39,270.14 | 78.54 | 39.93 | 1.08 | -14,189.60 | 5.95 | 52.82 |
| pct | 0.0075 | 3529 | 42,685.76 | 85.37 | 44.06 | 1.09 | -15,960.18 | 4.37 | 79.22 |
| pct | 0.01 | 3344 | 28,966.66 | 57.93 | 46.62 | 1.08 | -20,590.04 | 3.48 | 96.33 |
| fixed | 1 | 3529 | 37,091.64 | 74.18 | 50.07 | 1.16 | -5,862.48 | 1.00 | 250.00 |
| fixed | 2 | 3529 | 52,562.28 | 105.12 | 46.67 | 1.14 | -11,129.96 | 2.00 | 125.00 |
| fixed | 5 | 3529 | 38,250.70 | 76.50 | 42.31 | 1.07 | -14,612.60 | 5.00 | 50.00 |
| fixed | 10 | 3529 | 13,421.40 | 26.84 | 39.19 | 1.02 | -25,528.00 | 10.00 | 25.00 |

These are **sensitivity, not optimisation**. The headline is the a-priori default; quoting the best cell of a sweep over a single dataset is how backtests get overfitted.

## Does the stop hold the drawdown together?

| variant | param | exit rule | net P&L | return % | win % | max DD |
|---|---|---|---|---|---|---|
| atr | 1 | trailing stop | -33,687.8 | -67.4 | 34.5 | -34,078.8 |
| atr | 1 | fixed stop | 179,253.2 | 358.5 | 12.0 | -18,864.0 |
| atr | 1 | no stop (6h only) | 339,059.2 | 678.1 | 51.0 | -68,799.2 |
| pct | 0.005 | trailing stop | 39,270.1 | 78.5 | 39.9 | -14,189.6 |
| pct | 0.005 | fixed stop | 70,612.1 | 141.2 | 40.7 | -27,410.2 |
| pct | 0.005 | no stop (6h only) | 113,506.6 | 227.0 | 51.0 | -30,945.0 |
| fixed | 1 | trailing stop | 37,091.6 | 74.2 | 50.1 | -5,862.5 |
| fixed | 1 | fixed stop | 41,663.1 | 83.3 | 50.7 | -6,119.8 |
| fixed | 1 | no stop (6h only) | 38,791.1 | 77.6 | 51.0 | -7,040.8 |
| atr | 3 | trailing stop | 39,396.0 | 78.8 | 36.1 | -18,835.6 |
| atr | 3 | fixed stop | 107,171.0 | 214.3 | 28.2 | -26,942.8 |
| atr | 3 | no stop (6h only) | 157,704.0 | 315.4 | 51.0 | -37,247.1 |
| atr | 4 | trailing stop | 52,169.2 | 104.3 | 36.7 | -19,521.9 |
| atr | 4 | fixed stop | 98,301.7 | 196.6 | 35.0 | -30,209.0 |
| atr | 4 | no stop (6h only) | 121,855.2 | 243.7 | 50.9 | -30,131.4 |

## Intrabar path sensitivity

| variant | param | adverse-first % | favorable-first % | spread pp |
|---|---|---|---|---|
| atr | 0.5 | -81.19 | 74.00 | 155.19 |
| atr | 1 | -67.38 | -430.15 | -362.78 |
| atr | 1.5 | -48.68 | -398.10 | -349.42 |
| atr | 2 | -6.84 | -195.21 | -188.37 |
| atr | 3 | 78.79 | 23.19 | -55.60 |
| atr | 4 | 104.34 | 85.57 | -18.77 |
| pct | 0.0025 | 73.85 | -74.95 | -148.80 |
| pct | 0.005 | 78.54 | 72.15 | -6.39 |
| pct | 0.0075 | 85.37 | 79.82 | -5.56 |
| pct | 0.01 | 57.93 | 53.91 | -4.02 |
| fixed | 1 | 74.18 | 74.18 | 0.00 |
| fixed | 2 | 105.12 | 98.03 | -7.09 |
| fixed | 5 | 76.50 | 6.61 | -69.89 |
| fixed | 10 | 26.84 | -260.68 | -287.52 |

The two orderings are extreme path assumptions, not bounds — a within-bar ratchet can close a trade the other ordering keeps alive. The spread is the resolution limit of 1-minute bars on this strategy.

## Cost sensitivity

| variant | param | slippage ticks | net P&L | return % | fees |
|---|---|---|---|---|---|
| atr | 1 | 0 | -288.3 | -0.6 | 45,846.8 |
| pct | 0.005 | 0 | 60,177.1 | 120.4 | 28,145.4 |
| fixed | 1 | 0 | 40,619.6 | 81.2 | 4,728.9 |
| atr | 4 | 0 | 76,071.2 | 152.1 | 31,341.3 |
| atr | 1 | 1 | -33,687.8 | -67.4 | 45,846.8 |
| pct | 0.005 | 1 | 39,270.1 | 78.5 | 28,145.4 |
| fixed | 1 | 1 | 37,091.6 | 74.2 | 4,728.9 |
| atr | 4 | 1 | 52,169.2 | 104.3 | 31,341.3 |
| atr | 1 | 2 | -67,686.8 | -135.4 | 45,846.8 |
| pct | 0.005 | 2 | 18,449.6 | 36.9 | 28,145.4 |
| fixed | 1 | 2 | 33,563.6 | 67.1 | 4,728.9 |
| atr | 4 | 2 | 27,465.2 | 54.9 | 31,341.3 |

## Prop-firm evaluation

A fresh evaluation account is started on **every session** in the history and run until it passes, busts, or hits a 250-session cap. One account on one start date is a single path; this is the distribution a trader actually faces, since a blown evaluation is reset and retried.

| config | firm | accounts | passed | blown | undecided | pass rate % | median days to pass | median days to bust |
|---|---|---|---|---|---|---|---|---|
| headline ATR k=1 | apex_50k | 3528 | 388 | 3119 | 21 | 11.1 | 27.0 | 93.0 |
| headline ATR k=1 | topstep_50k | 3528 | 367 | 3157 | 4 | 10.4 | 26.0 | 76.0 |
| best sweep fixed=2 | apex_50k | 3528 | 1554 | 1370 | 604 | 53.1 | 65.0 | 32.0 |
| best sweep fixed=2 | topstep_50k | 3528 | 1343 | 1703 | 482 | 44.1 | 54.0 | 33.0 |

## Year by year (headline)

| year | trades | net P&L | return % | win % | PF | max DD | avg ctr | avg stop pts |
|---|---|---|---|---|---|---|---|---|
| 2,010.0 | 31.0 | -895.4 | -1.8 | 19.4 | 0.2 | -871.8 | 10.0 | 1.8 |
| 2,011.0 | 68.0 | -1,666.2 | -3.3 | 22.1 | 0.3 | -1,906.8 | 10.0 | 2.5 |
| 2,012.0 | 107.0 | -2,533.8 | -5.1 | 18.7 | 0.3 | -2,748.6 | 10.0 | 2.2 |
| 2,013.0 | 212.0 | -4,160.8 | -8.3 | 28.3 | 0.4 | -4,170.2 | 10.0 | 2.1 |
| 2,014.0 | 207.0 | -3,318.8 | -6.6 | 29.5 | 0.6 | -3,352.0 | 10.0 | 2.8 |
| 2,015.0 | 225.0 | -3,725.0 | -7.4 | 35.6 | 0.6 | -4,047.4 | 10.0 | 3.9 |
| 2,016.0 | 252.0 | -2,456.8 | -4.9 | 33.7 | 0.8 | -3,308.0 | 10.0 | 3.5 |
| 2,017.0 | 251.0 | -2,238.4 | -4.5 | 33.9 | 0.7 | -3,250.0 | 10.0 | 3.0 |
| 2,018.0 | 251.0 | -3,792.1 | -7.6 | 37.1 | 0.8 | -3,874.9 | 10.0 | 7.1 |
| 2,019.0 | 252.0 | 653.2 | 1.3 | 34.5 | 1.0 | -2,971.4 | 10.0 | 6.6 |
| 2,020.0 | 253.0 | 4,837.0 | 9.7 | 40.7 | 1.2 | -6,542.8 | 9.7 | 15.1 |
| 2,021.0 | 252.0 | 1,636.3 | 3.3 | 40.5 | 1.1 | -3,870.6 | 9.9 | 14.3 |
| 2,022.0 | 251.0 | 519.4 | 1.0 | 40.6 | 1.0 | -7,143.2 | 9.2 | 22.7 |
| 2,023.0 | 250.0 | -1,191.3 | -2.4 | 35.2 | 1.0 | -4,041.1 | 9.9 | 15.4 |
| 2,024.0 | 252.0 | -1,720.5 | -3.4 | 37.3 | 1.0 | -10,604.4 | 9.7 | 18.3 |
| 2,025.0 | 250.0 | -7,604.1 | -15.2 | 32.4 | 0.8 | -10,185.1 | 9.0 | 24.1 |
| 2,026.0 | 165.0 | -6,030.4 | -12.1 | 33.9 | 0.8 | -8,577.2 | 7.5 | 33.1 |
