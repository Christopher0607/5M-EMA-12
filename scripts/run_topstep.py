#!/usr/bin/env python3
"""TopStep across account tiers, risk bases, payout paths, and parallel accounts."""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bars import build_signal_frame, restrict_to_nyse, signal_bars
from src.career import (losses_to_bust, risk_for, run_career, scale_accounts,
                        summarise_career)
from src.data import load_bars
from src.metrics import summarise
from src.propfirm import daily_frame, rolling_evaluation, summarise_evaluation
from src.strategy import Sizing, build_windows, run

OUT = Path("results")

CONFIGS = {
    "pct 0.5% (fixed stop)":  (Sizing("pct", 0.005), {"trailing": False}),
    "fixed N=2 (trailing)":   (Sizing("fixed", 2.0), {}),
    "ATR k=1 (原主口径)":      (Sizing("atr", 1.0), {}),
}


def tier_rules(tier: dict, path: dict, key: str) -> tuple[dict, dict]:
    """Split a tier into (evaluation rules, funded rules) for the given payout path."""
    common = dict(balance=tier["balance"], trailing_dd=tier["trailing_dd"],
                  trail_basis=tier["trail_basis"],
                  lock_at_initial=tier["lock_at_initial"],
                  daily_loss_limit=tier["daily_loss_limit"])
    ev = dict(common, profit_target=tier["profit_target"],
              consistency_max_day_vs_target=tier.get("consistency_max_day_vs_target"))
    fu = dict(common,
              min_trading_days=path["min_trading_days"],
              min_day_profit=path["min_day_profit"],
              safety_net=tier["balance"],
              payout_cap=path["caps"][key],
              capped_payouts=None,            # TopStep caps every payout
              consistency_max_day_share=path["consistency_max_day_share"],
              split_full_to=0.0, split_after=0.9)   # flat 90/10 for 2026 joiners
    return ev, fu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(open(args.config))
    OUT.mkdir(exist_ok=True)
    pv = float(cfg["contract"]["point_value"])
    fees = cfg["fees"]["promo"]["topstep_50k"]

    print("loading ...", flush=True)
    bars = load_bars(cfg)
    signals = restrict_to_nyse(signal_bars(build_signal_frame(bars, cfg), cfg))
    windows = build_windows(bars, cfg)
    print(f"  signals {len(signals):,}")

    rows, scal = [], []
    for cname, (sizing, kw) in CONFIGS.items():
        for tkey, tier in cfg["topstep_tiers"].items():
            for bname, basis in cfg["risk_bases"].items():
                risk = risk_for(tier, basis)
                log = run(signals, windows, cfg, sizing,
                          risk_dollars=risk, max_contracts=tier["max_micros"], **kw)
                perf = summarise(log, tier["balance"])
                days = daily_frame(log, pv)
                if days.empty:
                    continue
                for pname, path in cfg["payout_paths"].items():
                    ev, fu = tier_rules(tier, path, tkey)
                    ev_stats = summarise_evaluation(rolling_evaluation(days, ev))
                    car = run_career(days, ev, fu,
                                     cfg["withdrawal_policies"]["immediate"], fees)
                    rec = summarise_career(car, len(days))
                    rec.update(config=cname, tier=tkey, risk_basis=bname, path=pname,
                               risk_dollars=risk,
                               losses_to_bust=losses_to_bust(tier, basis),
                               max_micros=tier["max_micros"],
                               avg_contracts=perf.get("avg_contracts"),
                               strategy_pnl=perf["net_pnl"],
                               eval_pass_rate=ev_stats.get("pass_rate_pct"))
                    rows.append(rec)

                    # parallel accounts, exact multiples of this single career
                    for n in cfg["scaling"]["account_counts"]:
                        s = scale_accounts(car, n)
                        s.update(config=cname, tier=tkey, risk_basis=bname, path=pname)
                        scal.append(s)

    matrix = pd.DataFrame(rows)
    matrix.to_csv(OUT / "topstep_matrix.csv", index=False)
    scaling = pd.DataFrame(scal)
    scaling.to_csv(OUT / "topstep_scaling.csv", index=False)

    # ------------------------------------------------------------- console
    def show(df, cols, **flt):
        v = df
        for k, val in flt.items():
            v = v[v[k] == val]
        return v[cols].to_string(index=False, float_format=lambda x: f"{x:,.0f}")

    print("\n=== 每种风险基准下，各档位能承受几笔满损 ===")
    lb = matrix.drop_duplicates(["tier", "risk_basis"])[
        ["tier", "risk_basis", "risk_dollars", "losses_to_bust", "max_micros"]]
    print(lb.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

    for cname in CONFIGS:
        print(f"\n=== {cname} · Standard path · 单账户 ===")
        cols = ["tier", "risk_basis", "avg_contracts", "strategy_pnl",
                "eval_pass_rate", "payouts", "capped_pct", "withdrawn",
                "fees_paid", "net_to_trader"]
        print(show(matrix, cols, config=cname, path="standard"))

    print("\n=== 两条出金路径对比（pct 0.5% 固定止损，fixed_dollar 风险）===")
    cols = ["tier", "path", "payouts", "capped_pct", "withdrawn", "net_to_trader"]
    print(show(matrix, cols, config="pct 0.5% (fixed stop)", risk_basis="fixed_dollar"))

    print("\n=== 并行账户（pct 0.5% 固定止损, 150k, fixed_dollar, standard）===")
    v = scaling[(scaling.config == "pct 0.5% (fixed stop)") & (scaling.tier == "150k")
                & (scaling.risk_basis == "fixed_dollar") & (scaling.path == "standard")]
    print(v[["accounts", "payouts", "withdrawn", "fees_paid", "net_to_trader"]]
          .to_string(index=False, float_format=lambda x: f"{x:,.0f}"))

    print(f"\nresults written to {OUT}/")


if __name__ == "__main__":
    main()
