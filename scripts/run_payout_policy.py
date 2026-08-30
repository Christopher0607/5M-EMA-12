#!/usr/bin/env python3
"""Which withdrawal policy actually wins, across many career start dates.

`firms_matrix.csv` reports one career per (strategy, tier, policy): a single
path from 2010. The evaluation columns in that file are already distribution-
based (rolling_evaluation restarts every 5 sessions), but `net_to_trader` is
not, and a 2.5x gap between policies on one path can be luck rather than
mechanism. This restarts the whole career on many dates and compares the
distributions, which is the only way the question can be answered honestly.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_backtest import load_bars                      # noqa: E402
from scripts.run_firms import STRATS, rules_for                 # noqa: E402
from src.bars import build_signal_frame, restrict_to_nyse, signal_bars  # noqa: E402
from src.career import career_distribution                      # noqa: E402
from src.propfirm import daily_frame                            # noqa: E402
from src.strategy import build_windows, run                     # noqa: E402

OUT = Path("results")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--firm", default="topstep")
    ap.add_argument("--tier", default="150k")
    ap.add_argument("--horizon", type=int, default=1260,
                    help="sessions per career (~5.8 years at 218/yr)")
    ap.add_argument("--step", type=int, default=42, help="restart every N sessions")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    pv = float(cfg["contract"]["point_value"])
    firm = cfg["firms"][args.firm]
    tier = firm["tiers"][args.tier]
    ev, fu = rules_for(firm, tier, args.tier)
    fees = cfg["firm_fees"][args.firm]

    bars = load_bars(cfg)
    signals = restrict_to_nyse(signal_bars(build_signal_frame(bars, cfg), cfg))
    windows = build_windows(bars, cfg)
    print(f"signals {len(signals):,}", flush=True)

    rows = []
    for sname, (sizing, kw) in STRATS.items():
        log = run(signals, windows, cfg, sizing, risk_dollars=500.0,
                  max_contracts=tier["max_micros"], **kw)
        days = daily_frame(log, pv)
        if days.empty:
            continue
        for pol_name, policy in cfg["withdrawal_policies"].items():
            dist = career_distribution(days, ev, fu, policy, fees,
                                       step=args.step, horizon=args.horizon)
            dist["strategy"] = sname
            dist["policy"] = pol_name
            rows.append(dist)
            net = dist["net_to_trader"]
            print(f"  {sname:<18} {pol_name:<12} n={len(dist):>3} "
                  f"median=${net.median():>9,.0f}  mean=${net.mean():>9,.0f}  "
                  f"win%={100 * (net > 0).mean():>5.1f}", flush=True)

    out = pd.concat(rows, ignore_index=True)
    out["firm"], out["tier"] = args.firm, args.tier
    path = OUT / f"payout_policy_{args.firm}_{args.tier}.csv"
    out.to_csv(path, index=False)
    print(f"\nwrote {path}  ({len(out):,} careers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
