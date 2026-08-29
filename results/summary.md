# Results
NQ 5-minute EMA12 opening-range strategy, 2010-06-07 to 2026-08-28. $50,000 account, MNQ micros ($2/point), 1% risk per trade, $1.34 round-turn plus 1 tick slippage each way.

## Headline — ATR-normalised stop, k=1
The ATR variant is the headline because it is the only sizing rule that stays comparable across a period in which NQ went from ~1,800 to ~23,000.

| Metric | Value |
|---|---|
| Trades | 3,529 |
| Net P&L | $-125,414 |
| **Total return on $50k** | **-250.8%** |
| Annualised (arithmetic) | -15.5% |
| Win rate | 34.5% |
| Profit factor | 0.82 |
| Expectancy per trade | $-35.54 |
| Max drawdown | $-125,591 |
| Sharpe | -1.09 |
| Fees paid | $149,189 |

## Stop-sizing sweep (adverse-first path)

| variant | param | trades | net P&L | return % | win % | PF | max DD | avg ctr | avg stop pts |
|---|---|---|---|---|---|---|---|---|---|
| atr | 0.5 | 3529 | -159,526.38 | -319.05 | 33.38 | 0.80 | -159,506.56 | 40.16 | 5.74 |
| atr | 1 | 3529 | -125,414.40 | -250.83 | 34.51 | 0.82 | -125,591.28 | 31.55 | 11.47 |
| atr | 1.5 | 3529 | -90,615.94 | -181.23 | 34.80 | 0.87 | -99,609.38 | 26.52 | 17.21 |
| atr | 2 | 3529 | -55,803.78 | -111.61 | 35.62 | 0.92 | -83,881.00 | 22.71 | 22.95 |
| atr | 3 | 3525 | 14,036.26 | 28.07 | 36.14 | 1.02 | -56,998.16 | 16.63 | 34.16 |
| atr | 4 | 3520 | 27,238.30 | 54.48 | 36.73 | 1.04 | -53,139.92 | 12.59 | 45.21 |
| pct | 0.0025 | 3529 | 16,398.12 | 32.80 | 37.15 | 1.02 | -43,510.90 | 14.77 | 26.41 |
| pct | 0.005 | 3529 | 33,348.08 | 66.70 | 39.93 | 1.06 | -20,278.60 | 7.14 | 52.82 |
| pct | 0.0075 | 3529 | 39,957.66 | 79.92 | 44.06 | 1.08 | -18,633.56 | 4.60 | 79.22 |
| pct | 0.01 | 3344 | 28,132.74 | 56.27 | 46.62 | 1.08 | -21,374.94 | 3.51 | 96.33 |
| fixed | 1 | 3529 | 37,091.64 | 74.18 | 50.07 | 1.16 | -5,862.48 | 1.00 | 250.00 |
| fixed | 2 | 3529 | 52,562.28 | 105.12 | 46.67 | 1.14 | -11,129.96 | 2.00 | 125.00 |
| fixed | 5 | 3529 | 38,250.70 | 76.50 | 42.31 | 1.07 | -14,612.60 | 5.00 | 50.00 |
| fixed | 10 | 3529 | 13,421.40 | 26.84 | 39.19 | 1.02 | -25,528.00 | 10.00 | 25.00 |

These are **sensitivity, not optimisation**. The headline is the a-priori default; quoting the best cell of a sweep over a single dataset is how backtests get overfitted.

## Does the stop hold the drawdown together?

| variant | param | exit rule | net P&L | return % | win % | max DD |
|---|---|---|---|---|---|---|
| atr | 1 | trailing stop | -125,414.4 | -250.8 | 34.5 | -125,591.3 |
| atr | 1 | fixed stop | 309,231.6 | 618.5 | 12.0 | -74,365.9 |
| atr | 1 | no stop (6h only) | 568,806.1 | 1,137.6 | 51.0 | -149,123.2 |
| pct | 0.005 | trailing stop | 33,348.1 | 66.7 | 39.9 | -20,278.6 |
| pct | 0.005 | fixed stop | 56,006.6 | 112.0 | 40.7 | -43,928.8 |
| pct | 0.005 | no stop (6h only) | 96,399.1 | 192.8 | 51.0 | -51,001.1 |
| fixed | 1 | trailing stop | 37,091.6 | 74.2 | 50.1 | -5,862.5 |
| fixed | 1 | fixed stop | 41,663.1 | 83.3 | 50.7 | -6,119.8 |
| fixed | 1 | no stop (6h only) | 38,791.1 | 77.6 | 51.0 | -7,040.8 |
| atr | 3 | trailing stop | 14,036.3 | 28.1 | 36.1 | -56,998.2 |
| atr | 3 | fixed stop | 65,631.3 | 131.3 | 28.2 | -87,381.2 |
| atr | 3 | no stop (6h only) | 156,964.3 | 313.9 | 51.0 | -98,443.2 |
| atr | 4 | trailing stop | 27,238.3 | 54.5 | 36.7 | -53,139.9 |
| atr | 4 | fixed stop | 62,451.8 | 124.9 | 35.0 | -71,154.5 |
| atr | 4 | no stop (6h only) | 108,145.3 | 216.3 | 50.9 | -75,392.0 |

## Intrabar path sensitivity

| variant | param | adverse-first % | favorable-first % | spread pp |
|---|---|---|---|---|
| atr | 0.5 | -319.05 | 283.80 | 602.86 |
| atr | 1 | -250.83 | -948.50 | -697.67 |
| atr | 1.5 | -181.23 | -859.78 | -678.55 |
| atr | 2 | -111.61 | -502.11 | -390.50 |
| atr | 3 | 28.07 | -83.97 | -112.04 |
| atr | 4 | 54.48 | 19.41 | -35.07 |
| pct | 0.0025 | 32.80 | -144.71 | -177.51 |
| pct | 0.005 | 66.70 | 60.30 | -6.39 |
| pct | 0.0075 | 79.92 | 74.36 | -5.56 |
| pct | 0.01 | 56.27 | 52.24 | -4.02 |
| fixed | 1 | 74.18 | 74.18 | 0.00 |
| fixed | 2 | 105.12 | 98.03 | -7.09 |
| fixed | 5 | 76.50 | 6.61 | -69.89 |
| fixed | 10 | 26.84 | -260.68 | -287.52 |

The two orderings are extreme path assumptions, not bounds — a within-bar ratchet can close a trade the other ordering keeps alive. The spread is the resolution limit of 1-minute bars on this strategy.

## Cost sensitivity

| variant | param | slippage ticks | net P&L | return % | fees |
|---|---|---|---|---|---|
| atr | 1 | 0 | -17,159.4 | -34.3 | 149,188.9 |
| pct | 0.005 | 0 | 58,451.1 | 116.9 | 33,785.4 |
| fixed | 1 | 0 | 40,619.6 | 81.2 | 4,728.9 |
| atr | 4 | 0 | 73,860.8 | 147.7 | 59,368.7 |
| atr | 1 | 1 | -125,414.4 | -250.8 | 149,188.9 |
| pct | 0.005 | 1 | 33,348.1 | 66.7 | 33,785.4 |
| fixed | 1 | 1 | 37,091.6 | 74.2 | 4,728.9 |
| atr | 4 | 1 | 27,238.3 | 54.5 | 59,368.7 |
| atr | 1 | 2 | -238,175.9 | -476.4 | 149,188.9 |
| pct | 0.005 | 2 | 8,369.6 | 16.7 | 33,785.4 |
| fixed | 1 | 2 | 33,563.6 | 67.1 | 4,728.9 |
| atr | 4 | 2 | -20,383.2 | -40.8 | 59,368.7 |

## Prop-firm evaluation

A fresh evaluation account is started on **every session** in the history and run until it passes, busts, or hits a 250-session cap. One account on one start date is a single path; this is the distribution a trader actually faces, since a blown evaluation is reset and retried.

| config | firm | accounts | passed | blown | undecided | pass rate % | median days to pass | median days to bust |
|---|---|---|---|---|---|---|---|---|
| headline ATR k=1 | apex_50k | 3528 | 497 | 3027 | 4 | 14.1 | 15.0 | 15.0 |
| headline ATR k=1 | topstep_50k | 3528 | 494 | 3031 | 3 | 14.0 | 15.0 | 14.0 |
| best sweep fixed=2 | apex_50k | 3528 | 1554 | 1370 | 604 | 53.1 | 65.0 | 32.0 |
| best sweep fixed=2 | topstep_50k | 3528 | 1343 | 1703 | 482 | 44.1 | 54.0 | 33.0 |

## Year by year (headline)

| year | trades | net P&L | return % | win % | PF | max DD | avg ctr | avg stop pts |
|---|---|---|---|---|---|---|---|---|
| 2,010.0 | 31.0 | -4,477.0 | -9.0 | 19.4 | 0.2 | -4,359.0 | 50.0 | 1.8 |
| 2,011.0 | 68.0 | -8,471.9 | -16.9 | 22.1 | 0.3 | -9,674.9 | 49.7 | 2.5 |
| 2,012.0 | 107.0 | -12,669.0 | -25.3 | 18.7 | 0.3 | -13,743.0 | 50.0 | 2.2 |
| 2,013.0 | 212.0 | -20,804.0 | -41.6 | 28.3 | 0.4 | -20,851.0 | 50.0 | 2.1 |
| 2,014.0 | 207.0 | -16,744.6 | -33.5 | 29.5 | 0.5 | -16,910.6 | 49.7 | 2.8 |
| 2,015.0 | 225.0 | -16,440.8 | -32.9 | 35.6 | 0.6 | -17,943.4 | 47.7 | 3.9 |
| 2,016.0 | 252.0 | -12,189.4 | -24.4 | 33.7 | 0.7 | -16,181.8 | 48.2 | 3.5 |
| 2,017.0 | 251.0 | -11,236.5 | -22.5 | 33.9 | 0.7 | -15,530.9 | 49.5 | 3.0 |
| 2,018.0 | 251.0 | -12,677.0 | -25.4 | 37.1 | 0.8 | -13,062.3 | 38.1 | 7.1 |
| 2,019.0 | 252.0 | -41.6 | -0.1 | 34.5 | 1.0 | -11,530.8 | 39.7 | 6.6 |
| 2,020.0 | 253.0 | 12,353.1 | 24.7 | 40.7 | 1.2 | -9,339.2 | 20.4 | 15.1 |
| 2,021.0 | 252.0 | 7,612.5 | 15.2 | 40.5 | 1.2 | -5,688.4 | 19.7 | 14.3 |
| 2,022.0 | 251.0 | -86.8 | -0.2 | 40.6 | 1.0 | -10,640.2 | 11.6 | 22.7 |
| 2,023.0 | 250.0 | -6,066.5 | -12.1 | 35.2 | 0.9 | -7,736.9 | 17.4 | 15.4 |
| 2,024.0 | 252.0 | -4,076.4 | -8.2 | 37.3 | 0.9 | -13,902.8 | 14.7 | 18.3 |
| 2,025.0 | 250.0 | -13,755.8 | -27.5 | 32.4 | 0.8 | -15,230.1 | 11.7 | 24.1 |
| 2,026.0 | 165.0 | -5,642.7 | -11.3 | 33.9 | 0.8 | -8,532.6 | 7.8 | 33.1 |
