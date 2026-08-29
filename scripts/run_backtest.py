#!/usr/bin/env python3
"""Run the full backtest matrix and write results to results/."""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bars import build_signal_frame, restrict_to_nyse, signal_bars
from src.data import load_bars
from src.metrics import daily_pnl, summarise, yearly_table
from src.propfirm import daily_frame, rolling_evaluation, summarise_evaluation
from src.report import equity_chart, md_table, sweep_chart, yearly_chart
from src.summary import build as build_summary
from src.strategy import Sizing, build_windows, run

OUT = Path("results")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(open(args.config))
    OUT.mkdir(exist_ok=True)

    initial = float(cfg["account"]["initial_capital"])
    pv = float(cfg["contract"]["point_value"])

    print("loading bars ...", flush=True)
    bars = load_bars(cfg)
    frame = build_signal_frame(bars, cfg)
    signals = restrict_to_nyse(signal_bars(frame, cfg))
    windows = build_windows(bars, cfg)
    print(f"  1m bars {len(bars):,} | 5m bars {len(frame):,} | signals {len(signals):,}")
    print(f"  span {signals.session_date.min()} -> {signals.session_date.max()}")
    assert (signals["local_time"] == "09:30").all(), "signal bar is not 09:30 ET"

    def backtest(sizing, **kw):
        return run(signals, windows, cfg, sizing, **kw)

    # ---------------------------------------------------------- sweeps
    print("running parameter sweeps ...", flush=True)
    sweep_rows, trade_logs = [], {}
    # Params are normalised to float so sweep-table lookups (which round-trip
    # through a DataFrame) match the trade-log keys for the integer-N variant.
    specs = ([("atr", float(k)) for k in cfg["variants"]["atr"]["k"]]
             + [("pct", float(p)) for p in cfg["variants"]["pct"]["p"]]
             + [("fixed", float(n)) for n in cfg["variants"]["fixed"]["n"]])
    for kind, param in specs:
        for favorable in (False, True):
            trades = backtest(Sizing(kind, param), favorable_first=favorable)
            stats = summarise(trades, initial)
            stats.update(variant=kind, param=param,
                         path="favorable_first" if favorable else "adverse_first")
            sweep_rows.append(stats)
            if not favorable:
                trade_logs[(kind, param)] = trades
    sweep = pd.DataFrame(sweep_rows)
    sweep.to_csv(OUT / "sweep.csv", index=False)

    # ---------------------------------------------------------- ablation
    print("running stop ablation ...", flush=True)
    ablation_rows = []
    defaults = [("atr", float(cfg["variants"]["atr"]["default_k"])),
                ("pct", float(cfg["variants"]["pct"]["default_p"])),
                ("fixed", float(cfg["variants"]["fixed"]["default_n"]))]
    for kind, param in defaults + [("atr", 3.0), ("atr", 4.0)]:
        for label, kw in [("trailing stop", {}),
                          ("fixed stop", {"trailing": False}),
                          ("no stop (6h only)", {"use_stop": False})]:
            trades = backtest(Sizing(kind, param), **kw)
            stats = summarise(trades, initial)
            stats.update(variant=kind, param=param, exit_rule=label)
            ablation_rows.append(stats)
    ablation = pd.DataFrame(ablation_rows)
    ablation.to_csv(OUT / "ablation.csv", index=False)

    # ---------------------------------------------------------- cost sensitivity
    print("running cost sensitivity ...", flush=True)
    cost_rows = []
    base_slip = cfg["costs"]["slippage_ticks"]
    for slip in (0, 1, 2):
        cfg["costs"]["slippage_ticks"] = slip
        for kind, param in defaults + [("atr", 4.0)]:
            stats = summarise(backtest(Sizing(kind, param)), initial)
            stats.update(variant=kind, param=param, slippage_ticks=slip)
            cost_rows.append(stats)
    cfg["costs"]["slippage_ticks"] = base_slip
    costs = pd.DataFrame(cost_rows)
    costs.to_csv(OUT / "cost_sensitivity.csv", index=False)

    # ---------------------------------------------------------- headline
    head_key = ("atr", float(cfg["variants"]["atr"]["default_k"]))
    head_trades = trade_logs[head_key]
    head_trades.to_csv(OUT / "trades_headline.csv", index=False)
    head_stats = summarise(head_trades, initial)
    years = yearly_table(head_trades, initial)
    years.to_csv(OUT / "yearly_headline.csv", index=False)

    # best-returning config, reported as a sweep observation, not a recommendation
    adverse = sweep[sweep["path"] == "adverse_first"]
    best = adverse.loc[adverse["total_return_pct"].idxmax()]
    best_key = (str(best["variant"]), float(best["param"]))
    best_trades = trade_logs[best_key]
    best_trades.to_csv(OUT / "trades_best.csv", index=False)
    yearly_table(best_trades, initial).to_csv(OUT / "yearly_best.csv", index=False)

    # ---------------------------------------------------------- prop firm
    print("running prop-firm evaluations ...", flush=True)
    prop_rows = []
    for label, key in [("headline ATR k=%g" % head_key[1], head_key),
                       ("best sweep %s=%g" % best_key, best_key)]:
        days = daily_frame(trade_logs[key], pv)
        for firm, rules in cfg["propfirm"].items():
            res = rolling_evaluation(days, rules)
            stats = summarise_evaluation(res)
            stats.update(config=label, firm=firm)
            prop_rows.append(stats)
            res.to_csv(OUT / f"eval_{firm}_{key[0]}_{key[1]:g}.csv", index=False)
    prop = pd.DataFrame(prop_rows)
    prop.to_csv(OUT / "propfirm.csv", index=False)

    # ---------------------------------------------------------- charts
    print("drawing charts ...", flush=True)
    curves = {}
    for label, key in [(f"ATR k={head_key[1]:g} (headline)", head_key),
                       (f"{best_key[0]} {best_key[1]:g} (best in sweep)", best_key)]:
        curves[label] = initial + daily_pnl(trade_logs[key]).cumsum()
    equity_chart(curves, initial, OUT / "equity.png",
                 "NQ 5-min EMA12 open — $50K account, MNQ micros, 1% risk per trade")
    yearly_chart(years, OUT / "yearly.png",
                 f"Net P&L by year — ATR k={head_key[1]:g}")
    sweep_chart(adverse[["variant", "param", "total_return_pct"]],
                OUT / "sweep.png", "Total return by stop-sizing parameter")

    span = (str(signals.session_date.min()), str(signals.session_date.max()))
    (OUT / "summary.md").write_text(build_summary(
        head_stats, sweep, ablation, costs, prop, years, head_key, best_key, span))

    print("\n=== HEADLINE (ATR k=%g, adverse-first) ===" % head_key[1])
    for k in ("trades", "net_pnl", "total_return_pct", "ann_return_pct",
              "win_rate_pct", "profit_factor", "max_dd", "sharpe", "expectancy"):
        print(f"  {k:>18}: {head_stats.get(k)}")
    print(f"\nresults written to {OUT}/")


if __name__ == "__main__":
    main()
