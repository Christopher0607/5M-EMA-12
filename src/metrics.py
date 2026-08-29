"""Performance statistics for a trade log.

Position size is a function of *initial* capital, not current equity, so the
strategy is constant-size rather than compounding. Total return is therefore
reported against the initial balance and the annualised figure is arithmetic;
a CAGR would imply reinvestment the sizing rule never does.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def daily_pnl(trades: pd.DataFrame) -> pd.Series:
    """Realised P&L per session, indexed by date.

    session_date is coerced because a trade log round-tripped through CSV comes
    back as strings, and the date arithmetic downstream needs real dates.
    """
    done = trades[trades["skipped"].isna()]
    if done.empty:
        return pd.Series(dtype="float64")
    keyed = pd.to_datetime(done["session_date"]).dt.date
    return done.groupby(keyed)["pnl"].sum().sort_index()


def equity_curve(trades: pd.DataFrame, initial: float) -> pd.Series:
    return initial + daily_pnl(trades).cumsum()


def summarise(trades: pd.DataFrame, initial: float) -> dict:
    done = trades[trades["skipped"].isna()]
    n = len(done)
    out = {
        "trades": n,
        "skipped": int(trades["skipped"].notna().sum()),
        "net_pnl": float(done["pnl"].sum()) if n else 0.0,
        "fees": float(done["fees"].sum()) if n else 0.0,
    }
    if n == 0:
        return out

    wins, losses = done[done["pnl"] > 0], done[done["pnl"] < 0]
    daily = daily_pnl(trades)
    eq = initial + daily.cumsum()
    dd = eq - eq.cummax()
    days = max((pd.Timestamp(daily.index[-1]) - pd.Timestamp(daily.index[0])).days, 1)
    years = days / 365.25
    rets = daily / initial
    downside = rets[rets < 0]

    out.update({
        "gross_pnl": float(done["pnl"].sum() + done["fees"].sum()),
        "total_return_pct": 100.0 * done["pnl"].sum() / initial,
        "ann_return_pct": 100.0 * done["pnl"].sum() / initial / years,
        "years": years,
        "win_rate_pct": 100.0 * len(wins) / n,
        "avg_win": float(wins["pnl"].mean()) if len(wins) else 0.0,
        "avg_loss": float(losses["pnl"].mean()) if len(losses) else 0.0,
        "payoff": (abs(wins["pnl"].mean() / losses["pnl"].mean())
                   if len(wins) and len(losses) and losses["pnl"].mean() else np.nan),
        "profit_factor": (wins["pnl"].sum() / abs(losses["pnl"].sum())
                          if len(losses) and losses["pnl"].sum() else np.nan),
        "expectancy": float(done["pnl"].mean()),
        "max_dd": float(dd.min()),
        "max_dd_pct": 100.0 * float(dd.min()) / initial,
        "sharpe": (float(rets.mean() / rets.std() * np.sqrt(TRADING_DAYS))
                   if rets.std() else np.nan),
        "sortino": (float(rets.mean() / downside.std() * np.sqrt(TRADING_DAYS))
                    if len(downside) > 1 and downside.std() else np.nan),
        "mar": (abs(100.0 * done["pnl"].sum() / initial / years / (100.0 * dd.min() / initial))
                if dd.min() else np.nan),
        "avg_contracts": float(done["contracts"].mean()),
        "avg_stop_pts": float(done["stop_distance_pts"].mean()),
        "avg_risk_dollars": float(done["risk_dollars"].mean()),
        "avg_bars_held": float(done["bars_held"].mean()),
        "long_pnl": float(done[done["direction"] == "long"]["pnl"].sum()),
        "short_pnl": float(done[done["direction"] == "short"]["pnl"].sum()),
        "long_n": int((done["direction"] == "long").sum()),
        "short_n": int((done["direction"] == "short").sum()),
    })
    for reason, count in done["exit_reason"].value_counts().items():
        out[f"exit_{reason}"] = int(count)
    return out


def yearly_table(trades: pd.DataFrame, initial: float) -> pd.DataFrame:
    """Per-calendar-year breakdown — essential when the price level moves 12x."""
    done = trades[trades["skipped"].isna()].copy()
    if done.empty:
        return pd.DataFrame()
    done["year"] = pd.to_datetime(done["session_date"]).dt.year
    rows = []
    for year, group in done.groupby("year"):
        eq = group["pnl"].cumsum()
        wins = group[group["pnl"] > 0]
        losses = group[group["pnl"] < 0]
        rows.append({
            "year": int(year),
            "trades": len(group),
            "net_pnl": group["pnl"].sum(),
            "return_pct": 100.0 * group["pnl"].sum() / initial,
            "win_rate": 100.0 * len(wins) / len(group),
            "profit_factor": (wins["pnl"].sum() / abs(losses["pnl"].sum())
                              if len(losses) and losses["pnl"].sum() else np.nan),
            "max_dd": float((eq - eq.cummax()).min()),
            "avg_contracts": group["contracts"].mean(),
            "avg_stop_pts": group["stop_distance_pts"].mean(),
        })
    return pd.DataFrame(rows)
