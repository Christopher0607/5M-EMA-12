#!/usr/bin/env python3
"""Expected trades, for checking the Pine script against the Python backtest.

The two will NOT agree to the tick, and that is expected: TradingView's continuous
contract is not Databento's NQ.v.0, Pine's intrabar stop-fill convention is not the
adverse-first one used here, and the commission and slippage models differ.

What must agree is the **signal set** - the same days, the same directions. A
direction mismatch means the chart is misconfigured, and in practice that almost
always means extended hours is switched off, which changes the EMA.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bars import build_signal_frame, restrict_to_nyse, signal_bars
from src.data import load_bars
from src.strategy import Sizing, build_windows, run

OUT = Path("results")

PRESETS = {
    "pct0.5":   (Sizing("pct", 0.005), {"trailing": False}, "Percent of price = 0.5"),
    "pct0.75":  (Sizing("pct", 0.0075), {"trailing": False}, "Percent of price = 0.75"),
    "fixed125": (Sizing("fixed", 2.0), {}, "Fixed points = 125 (N=2)"),
    "fixed250": (Sizing("fixed", 1.0), {}, "Fixed points = 250 (N=1)"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--preset", default="pct0.5", choices=list(PRESETS))
    ap.add_argument("--since", type=int, default=2025,
                    help="first year to export (TradingView free plans hold limited history)")
    ap.add_argument("--max-contracts", type=int, default=40,
                    help="firm cap; Lucid 50K=40, TopStep 50K=50, Apex 50K=100")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    sizing, kw, pine_setting = PRESETS[args.preset]

    bars = load_bars(cfg)
    signals = restrict_to_nyse(signal_bars(build_signal_frame(bars, cfg), cfg))
    windows = build_windows(bars, cfg)
    log = run(signals, windows, cfg, sizing, risk_dollars=500.0,
              max_contracts=args.max_contracts, **kw)

    done = log[log["skipped"].isna()].copy()
    done["year"] = pd.to_datetime(done["session_date"]).dt.year
    done = done[done["year"] >= args.since]
    out = done[["session_date", "direction", "entry", "exit", "stop_distance_pts",
                "contracts", "pnl", "exit_reason", "bars_held"]].copy()
    out = out.rename(columns={"stop_distance_pts": "stop_pts"})
    path = OUT / "tv_expected_trades.csv"
    out.to_csv(path, index=False)

    print(f"preset {args.preset}  ->  Pine setting: {pine_setting}")
    print(f"                          Max contracts = {args.max_contracts}")
    print(f"{len(out)} trades from {args.since} -> {path}\n")
    print(out.head(12).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"\n方向分布: {out.direction.value_counts().to_dict()}")
    print(f"出场原因: {out.exit_reason.value_counts().to_dict()}")
    print(f"手数: 中位 {out.contracts.median():.0f}  范围 {out.contracts.min()}-{out.contracts.max()}")
    print("\n对照方法：TradingView 策略测试器 → 成交列表，逐日核对『日期 + 方向』。")
    print("成交价差几个跳是正常的（数据源和成交假设不同）；方向对不上说明图表设置错了。")


if __name__ == "__main__":
    main()
