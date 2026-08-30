"""Futures prop-firm account rules: trailing drawdown, daily loss limits, pass/fail.

A prop account is not a margin account. What kills it is not a bad year but a
single trailing-drawdown breach, and the threshold ratchets up behind every new
equity high. Evaluating the strategy therefore means asking how long an account
survives, not only what the strategy returns.

Intraday ordering: within a day the equity peak is applied to the trailing
threshold *before* the trough is tested against it. For a stopped-out trade that
is also the true order — the favourable excursion is what dragged the trailing
stop up before price reversed into it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def daily_frame(trades: pd.DataFrame, point_value: float) -> pd.DataFrame:
    """Per-session realised P&L plus the intraday equity swing around it."""
    done = trades[trades["skipped"].isna()].copy()
    if done.empty:
        return pd.DataFrame(columns=["session_date", "pnl", "up", "down"])
    done["up"] = done["mfe_pts"] * point_value * done["contracts"]
    done["down"] = done["mae_pts"] * point_value * done["contracts"] + done["fees"]
    agg = done.groupby("session_date").agg(
        pnl=("pnl", "sum"), up=("up", "sum"), down=("down", "sum"))
    return agg.reset_index().sort_values("session_date").reset_index(drop=True)


def run_account(days: pd.DataFrame, rules: dict, start_idx: int = 0,
                max_days: int = 250) -> dict:
    """Run one evaluation account forward from start_idx until pass, fail, or cap."""
    balance = float(rules["balance"])
    trail = float(rules["trailing_dd"])
    target = float(rules["profit_target"])
    dll = rules.get("daily_loss_limit")
    intraday = rules.get("trail_basis", "intraday") == "intraday"
    # TopStep's Combine consistency rule gates *passing* the evaluation, not
    # withdrawing: the best day must stay at or below a share of the profit
    # target. A strategy with lumpy daily P&L can hit the target and still be
    # held back by it, so it is enforced here rather than in the funded phase.
    # Two consistency forms, because firms write the rule differently:
    #   vs_target - TopStep: best day <= 50% of the PROFIT TARGET (absolute)
    #   vs_total  - TPT:     best day <= 50% of PROFIT SO FAR (relative)
    consistency_vs_target = rules.get("consistency_max_day_vs_target")
    consistency_vs_total = rules.get("consistency_max_day_share")
    best_day = 0.0
    won = 0.0
    # Lucid's daily loss limit is a *soft* breach: it stops you trading for the
    # rest of the session but does not end the account. Treating it as a bust,
    # the way TopStep's works, would badly understate Lucid.
    dll_soft = bool(rules.get("daily_loss_soft", False))
    min_days = int(rules.get("min_days_to_pass") or 0)
    blocked_days = 0
    # Apex locks the threshold just above the start balance; TopStep locks at it.
    lock_at = balance + (100.0 if intraday else 0.0) if rules.get("lock_at_initial") else np.inf

    equity = balance
    threshold = balance - trail
    peak = balance

    window = days.iloc[start_idx:start_idx + max_days]
    for n, row in enumerate(window.itertuples(index=False), start=1):
        incoming = threshold          # level in force when the day opens
        day_high = equity + row.up
        day_low = equity - row.down
        day_close = equity + row.pnl

        # The intraday trough is tested against the threshold as it stood coming
        # into the day. Testing it against a level the same day's peak dragged up
        # would bust an account on its own opening balance.
        if day_low <= incoming:
            return {"outcome": "blown", "days": n, "final": day_low,
                    "reason": "trailing_drawdown"}
        if dll is not None and row.pnl <= -dll:
            if not dll_soft:
                return {"outcome": "blown", "days": n, "final": day_close,
                        "reason": "daily_loss_limit"}
            blocked_days += 1

        # Apex trails the intraday high; TopStep trails the closing balance.
        peak = max(peak, day_high if intraday else day_close)
        threshold = max(threshold, min(peak - trail, lock_at))

        if day_close <= threshold:
            return {"outcome": "blown", "days": n, "final": day_close,
                    "reason": "trailing_drawdown"}

        equity = day_close
        best_day = max(best_day, row.pnl)
        if row.pnl > 0:
            won += row.pnl
        if equity >= balance + target and n >= min_days:
            if (consistency_vs_target is not None
                    and best_day > float(consistency_vs_target) * target):
                # Target reached but one day carried too much of it: keep
                # trading until the rest of the record dilutes that day.
                continue
            if (consistency_vs_total is not None and won > 0
                    and best_day / won > float(consistency_vs_total)):
                continue
            return {"outcome": "passed", "days": n, "final": equity,
                    "reason": "profit_target"}

    return {"outcome": "undecided", "days": len(window),
            "final": equity, "reason": "max_days"}


def rolling_evaluation(days: pd.DataFrame, rules: dict, max_days: int = 250,
                       step: int = 1) -> pd.DataFrame:
    """Start a fresh account on every Nth session and record how each ends.

    One account on one start date is a single path and says little. Restarting
    across the whole history gives the distribution a trader actually faces,
    since a blown evaluation is reset and retried.
    """
    starts = range(0, max(len(days) - 1, 0), step)
    rows = []
    for i in starts:
        res = run_account(days, rules, start_idx=i, max_days=max_days)
        res["start_date"] = days.iloc[i]["session_date"]
        rows.append(res)
    return pd.DataFrame(rows)


def summarise_evaluation(results: pd.DataFrame) -> dict:
    if results.empty:
        return {}
    counts = results["outcome"].value_counts()
    decided = results[results["outcome"].isin(["passed", "blown"])]
    passed = results[results["outcome"] == "passed"]
    blown = results[results["outcome"] == "blown"]
    out = {
        "accounts": len(results),
        "passed": int(counts.get("passed", 0)),
        "blown": int(counts.get("blown", 0)),
        "undecided": int(counts.get("undecided", 0)),
        # Two denominators, because the difference is not cosmetic. A slow
        # configuration can run out the window without either passing or
        # busting, and those attempts vanish from `pass_rate_decided_pct`.
        # `fixed N=1` reads 68.5% on that basis and 13.9% on this one, because
        # 79.7% of its evaluations never reach a decision at all - it is the
        # WORST config at getting funded, not the best. Ranking on the decided
        # basis produced exactly that wrong conclusion once already, so
        # `pass_rate_pct` is the all-attempts number: the probability a trader
        # who buys one evaluation is funded before the window runs out.
        "pass_rate_pct": 100.0 * len(passed) / len(results),
        "pass_rate_decided_pct": (100.0 * len(passed) / len(decided)
                                  if len(decided) else np.nan),
        "undecided_pct": 100.0 * int(counts.get("undecided", 0)) / len(results),
        "median_days_to_pass": float(passed["days"].median()) if len(passed) else np.nan,
        "median_days_to_bust": float(blown["days"].median()) if len(blown) else np.nan,
    }
    if len(blown):
        for reason, count in blown["reason"].value_counts().items():
            out[f"bust_{reason}"] = int(count)
    return out
