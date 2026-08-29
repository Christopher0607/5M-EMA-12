"""Turn the results tables into a readable markdown summary."""

from __future__ import annotations

import pandas as pd

from src.report import md_table


def _params(frame: pd.DataFrame) -> pd.DataFrame:
    """Render the sizing parameter with %g so 0.0025 does not print as 0.00."""
    out = frame.copy()
    out["param"] = out["param"].map(lambda v: f"{v:g}")
    return out


def build(head_stats: dict, sweep: pd.DataFrame, ablation: pd.DataFrame,
          costs: pd.DataFrame, prop: pd.DataFrame, years: pd.DataFrame,
          head_key, best_key, span: tuple[str, str]) -> str:
    adverse = sweep[sweep["path"] == "adverse_first"]
    fav = sweep[sweep["path"] == "favorable_first"]

    L = []
    L.append(f"# Results\n")
    L.append(f"NQ 5-minute EMA12 opening-range strategy, {span[0]} to {span[1]}. "
             f"$50,000 account, MNQ micros ($2/point), 1% risk per trade, "
             f"$1.34 round-turn plus 1 tick slippage each way.\n")

    L.append("\n## Headline — ATR-normalised stop, k=%g\n" % head_key[1])
    L.append("The ATR variant is the headline because it is the only sizing rule that "
             "stays comparable across a period in which NQ went from ~1,800 to ~23,000.\n\n")
    rows = [
        ("Trades", f"{head_stats['trades']:,}"),
        ("Net P&L", f"${head_stats['net_pnl']:,.0f}"),
        ("**Total return on $50k**", f"**{head_stats['total_return_pct']:.1f}%**"),
        ("Annualised (arithmetic)", f"{head_stats['ann_return_pct']:.1f}%"),
        ("Win rate", f"{head_stats['win_rate_pct']:.1f}%"),
        ("Profit factor", f"{head_stats['profit_factor']:.2f}"),
        ("Expectancy per trade", f"${head_stats['expectancy']:.2f}"),
        ("Max drawdown", f"${head_stats['max_dd']:,.0f}"),
        ("Sharpe", f"{head_stats['sharpe']:.2f}"),
        ("Fees paid", f"${head_stats['fees']:,.0f}"),
    ]
    L.append("| Metric | Value |\n|---|---|\n")
    L.extend(f"| {k} | {v} |\n" for k, v in rows)

    L.append("\n## Stop-sizing sweep (adverse-first path)\n\n")
    sw = _params(adverse)[["variant", "param", "trades", "net_pnl", "total_return_pct",
                  "win_rate_pct", "profit_factor", "max_dd", "avg_contracts",
                  "avg_stop_pts"]].copy()
    sw.columns = ["variant", "param", "trades", "net P&L", "return %", "win %",
                  "PF", "max DD", "avg ctr", "avg stop pts"]
    L.append(md_table(sw, "{:,.2f}"))
    L.append("\nThese are **sensitivity, not optimisation**. The headline is the "
             "a-priori default; quoting the best cell of a sweep over a single "
             "dataset is how backtests get overfitted.\n")

    L.append("\n## Does the stop hold the drawdown together?\n\n")
    ab = _params(ablation)[["variant", "param", "exit_rule", "net_pnl", "total_return_pct",
                   "win_rate_pct", "max_dd"]].copy()
    ab.columns = ["variant", "param", "exit rule", "net P&L", "return %", "win %", "max DD"]
    L.append(md_table(ab, "{:,.1f}"))

    L.append("\n## Intrabar path sensitivity\n\n")
    merged = adverse.merge(fav, on=["variant", "param"], suffixes=("_adv", "_fav"))
    ps = _params(merged)[["variant", "param", "total_return_pct_adv", "total_return_pct_fav"]].copy()
    ps["spread"] = ps["total_return_pct_fav"] - ps["total_return_pct_adv"]
    ps.columns = ["variant", "param", "adverse-first %", "favorable-first %", "spread pp"]
    L.append(md_table(ps, "{:,.2f}"))
    L.append("\nThe two orderings are extreme path assumptions, not bounds — a "
             "within-bar ratchet can close a trade the other ordering keeps alive. "
             "The spread is the resolution limit of 1-minute bars on this strategy.\n")

    L.append("\n## Cost sensitivity\n\n")
    cs = _params(costs)[["variant", "param", "slippage_ticks", "net_pnl",
                "total_return_pct", "fees"]].copy()
    cs.columns = ["variant", "param", "slippage ticks", "net P&L", "return %", "fees"]
    L.append(md_table(cs, "{:,.1f}"))

    L.append("\n## Prop-firm evaluation\n\n")
    L.append("A fresh evaluation account is started on **every session** in the "
             "history and run until it passes, busts, or hits a 250-session cap. "
             "One account on one start date is a single path; this is the "
             "distribution a trader actually faces, since a blown evaluation is "
             "reset and retried.\n\n")
    pf = prop[["config", "firm", "accounts", "passed", "blown", "undecided",
               "pass_rate_pct", "median_days_to_pass", "median_days_to_bust"]].copy()
    pf.columns = ["config", "firm", "accounts", "passed", "blown", "undecided",
                  "pass rate %", "median days to pass", "median days to bust"]
    L.append(md_table(pf, "{:,.1f}"))

    L.append("\n## Year by year (headline)\n\n")
    yr = years[["year", "trades", "net_pnl", "return_pct", "win_rate",
                "profit_factor", "max_dd", "avg_contracts", "avg_stop_pts"]].copy()
    yr.columns = ["year", "trades", "net P&L", "return %", "win %", "PF",
                  "max DD", "avg ctr", "avg stop pts"]
    L.append(md_table(yr, "{:,.1f}"))
    return "".join(L)
