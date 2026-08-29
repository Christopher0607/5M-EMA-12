"""Out-of-sample validation of the *parameter choice* itself.

A sweep tells you which setting won on the data you already have. It cannot tell
you whether picking a winner is a repeatable act. This module answers that: for
each year, choose a configuration using only data that existed before that year,
then trade it through the year and never revise it.

The whole exercise is worthless if selection can see the year it is judged on, so
`select_upto` slices strictly below the boundary and a test asserts it.
"""

from __future__ import annotations

import pandas as pd


def yearly_pnl_matrix(trade_logs: dict) -> pd.DataFrame:
    """Year x configuration matrix of net P&L, from prebuilt trade logs."""
    cols = {}
    for name, log in trade_logs.items():
        done = log[log["skipped"].isna()].copy()
        year = pd.to_datetime(done["session_date"]).dt.year
        cols[name] = done.groupby(year)["pnl"].sum()
    return pd.DataFrame(cols).fillna(0.0).sort_index()


def select_upto(matrix: pd.DataFrame, year: int, min_train_years: int = 2,
                lookback: int | None = None) -> str | None:
    """Best configuration judged only on years strictly before `year`.

    `lookback` limits training to the most recent N years; None means an
    expanding window over all prior history.
    """
    train = matrix.loc[matrix.index < year]
    if lookback is not None:
        train = train.tail(lookback)
    if len(train) < min_train_years:
        return None
    return str(train.sum().idxmax())


def walk_forward(trade_logs: dict, min_train_years: int = 2,
                 lookback: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stitch each year's out-of-sample trades into one log.

    Returns (oos_trades, selection_history). The history is reported because a
    choice that flips every year is itself evidence the selection is noise.
    """
    matrix = yearly_pnl_matrix(trade_logs)
    picks, frames = [], []
    for year in matrix.index:
        pick = select_upto(matrix, year, min_train_years, lookback)
        if pick is None:
            continue
        log = trade_logs[pick]
        done = log[log["skipped"].isna()].copy()
        mask = pd.to_datetime(done["session_date"]).dt.year == year
        slice_ = done[mask]
        frames.append(slice_)
        picks.append({
            "year": int(year),
            "picked": pick,
            "oos_pnl": float(slice_["pnl"].sum()),
            "oos_rank": int(matrix.loc[year].rank(ascending=False)[pick]),
            "best_that_year": str(matrix.loc[year].idxmax()),
            "best_pnl": float(matrix.loc[year].max()),
        })
    oos = (pd.concat(frames, ignore_index=True) if frames
           else pd.DataFrame(columns=list(next(iter(trade_logs.values())).columns)))
    return oos, pd.DataFrame(picks)


def holdout(trade_logs: dict, split_year: int) -> dict:
    """Select on everything before `split_year`, report on everything from it on."""
    matrix = yearly_pnl_matrix(trade_logs)
    pick = select_upto(matrix, split_year, min_train_years=1)
    train = matrix.loc[matrix.index < split_year]
    test = matrix.loc[matrix.index >= split_year]
    log = trade_logs[pick]
    done = log[log["skipped"].isna()].copy()
    mask = pd.to_datetime(done["session_date"]).dt.year >= split_year
    return {
        "picked": pick,
        "train_pnl": float(train[pick].sum()),
        "test_pnl": float(test[pick].sum()),
        "test_best": str(test.sum().idxmax()),
        "test_best_pnl": float(test.sum().max()),
        "test_rank": int(test.sum().rank(ascending=False)[pick]),
        "n_configs": matrix.shape[1],
        "oos_trades": done[mask],
    }
