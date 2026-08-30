#!/usr/bin/env python3
"""Four-firm comparison: which platform, which strategy, and when to withdraw.

Passing an evaluation and holding a funded account are different problems, so
they are scored separately here rather than collapsed into one number.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bars import build_signal_frame, restrict_to_nyse, signal_bars
from src.career import (funded_distribution, risk_for, run_career,
                        run_funded, summarise_career)
from src.data import load_bars
from src.metrics import summarise
from src.propfirm import daily_frame, rolling_evaluation, summarise_evaluation
from src.strategy import Sizing, build_windows, run

OUT = Path("results")

STRATS = {
    "pct 0.5% 固定止损":  (Sizing("pct", 0.005), {"trailing": False}),
    "pct 0.5% 移动止损":  (Sizing("pct", 0.005), {}),
    "pct 0.75% 固定止损": (Sizing("pct", 0.0075), {"trailing": False}),
    "fixed N=2 移动止损":  (Sizing("fixed", 2.0), {}),
    "fixed N=1 移动止损":  (Sizing("fixed", 1.0), {}),
    "ATR k=4 移动止损":    (Sizing("atr", 4.0), {}),
}


def rules_for(firm: dict, tier: dict, tkey: str) -> tuple[dict, dict]:
    """Split a firm+tier into (evaluation rules, funded rules)."""
    base = dict(balance=tier["balance"], trailing_dd=tier["trailing_dd"],
                daily_loss_limit=tier.get("daily_loss_limit"))
    ev = dict(base, profit_target=tier["profit_target"], **firm["eval"])
    fu = dict(base, **{k: v for k, v in firm["funded"].items()
                       if k != "safety_net_offset"})
    fu["safety_net"] = tier["balance"] + firm["funded"].get("safety_net_offset", 0.0)
    fu["payout_cap"] = tier.get("payout_cap", firm["funded"].get("payout_cap"))
    fu["split_full_to"] = firm["split_full_to"]
    fu["split_after"] = firm["split_after"]
    return ev, fu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(open(args.config))
    OUT.mkdir(exist_ok=True)
    pv = float(cfg["contract"]["point_value"])

    print("loading ...", flush=True)
    bars = load_bars(cfg)
    signals = restrict_to_nyse(signal_bars(build_signal_frame(bars, cfg), cfg))
    windows = build_windows(bars, cfg)
    print(f"  signals {len(signals):,}")

    rows = []
    for sname, (sizing, kw) in STRATS.items():
        for fkey, firm in cfg["firms"].items():
            for tkey, tier in firm["tiers"].items():
                # Fixed $500 risk: the basis shown earlier to dominate, and the
                # only one that keeps the comparison across tiers meaningful.
                risk = 500.0
                log = run(signals, windows, cfg, sizing, risk_dollars=risk,
                          max_contracts=tier["max_micros"], **kw)
                perf = summarise(log, tier["balance"])
                days = daily_frame(log, pv)
                if days.empty:
                    continue
                ev, fu = rules_for(firm, tier, tkey)
                # step=5: ~700 restart samples instead of 3,529. The pass rate
                # is stable to a tenth of a point at this density and the full
                # sweep is 72 rolling evaluations, so the cost matters.
                ev_stats = summarise_evaluation(rolling_evaluation(days, ev, step=5))

                # Funded phase in isolation, started on many dates: a single run
                # from 2010 would report how the strategy did that year, not how
                # a funded account behaves.
                fd = funded_distribution(days, fu,
                                         cfg["withdrawal_policies"]["immediate"], 0.0)
                fund_net = float(fd["net"].median())
                fund_mean = float(fd["net"].mean())
                fund_pay = float(fd["payouts"].median())
                fund_surv = 100.0 * float(fd["survived"].mean())

                # A tier may override the fee (TopStep prices its Combine
                # subscription per tier), so tier keys win over firm defaults.
                tier_fees = dict(cfg["firm_fees"][fkey])
                if "monthly_eval" in tier:
                    tier_fees["monthly_eval"] = tier["monthly_eval"]

                for pol_name, policy in cfg["withdrawal_policies"].items():
                    car = run_career(days, ev, fu, policy, tier_fees)
                    rec = summarise_career(car, len(days))
                    rec.update(strategy=sname, firm=fkey, firm_label=firm["label"],
                               tier=tkey, policy=pol_name,
                               eval_pass_rate=ev_stats.get("pass_rate_pct"),
                               eval_pass_rate_decided=ev_stats.get("pass_rate_decided_pct"),
                               eval_undecided_pct=ev_stats.get("undecided_pct"),
                               eval_days_to_pass=ev_stats.get("median_days_to_pass"),
                               eval_days_to_bust=ev_stats.get("median_days_to_bust"),
                               strategy_pnl=perf["net_pnl"],
                               avg_contracts=perf.get("avg_contracts"),
                               funded_med_net=fund_net,
                               funded_mean_net=fund_mean,
                               funded_med_payouts=fund_pay,
                               funded_survive_pct=fund_surv,
                               max_micros=tier["max_micros"],
                               split=firm["split_after"] or 1.0)
                    rows.append(rec)

    m = pd.DataFrame(rows)
    m.to_csv(OUT / "firms_matrix.csv", index=False)
    print(f"\n{len(m)} rows -> {OUT}/firms_matrix.csv")

    imm = m[m.policy == "immediate"]
    fmt = lambda x: f"{x:,.0f}"

    print("\n=== 1. 考试阶段：哪个平台 + 哪个策略最容易过？（150K，通过率%）===")
    ev = imm[imm.tier == "150k"].pivot_table(index="strategy", columns="firm_label",
                                             values="eval_pass_rate")
    print(ev.to_string(float_format=lambda x: f"{x:,.1f}"))

    print("\n=== 2. 资金阶段：已拿到账户后，2年期净出金中位数（150K, $）===")
    fu = imm[imm.tier == "150k"].pivot_table(index="strategy", columns="firm_label",
                                             values="funded_med_net")
    print(fu.to_string(float_format=fmt))
    print("\n    对应的 2 年存活率（%）：")
    sv = imm[imm.tier == "150k"].pivot_table(index="strategy", columns="firm_label",
                                             values="funded_survive_pct")
    print(sv.to_string(float_format=lambda x: f"{x:,.0f}"))

    print("\n=== 3. 完整生涯净到手（150K, 一达标就提, $）===")
    ca = imm[imm.tier == "150k"].pivot_table(index="strategy", columns="firm_label",
                                             values="net_to_trader")
    print(ca.to_string(float_format=fmt))

    print("\n=== 4. 出金时机：三种策略下的净到手（最佳策略, 150K, $）===")
    best = ca.mean(axis=1).idxmax()
    w = m[(m.strategy == best) & (m.tier == "150k")].pivot_table(
        index="policy", columns="firm_label", values="net_to_trader")
    print(f"（策略 = {best}）")
    print(w.to_string(float_format=fmt))

    print("\n=== 5. 平台总排名（全部档位与策略的中位净到手）===")
    rank = imm.groupby("firm_label").agg(
        中位净到手=("net_to_trader", "median"),
        最好净到手=("net_to_trader", "max"),
        中位通过率=("eval_pass_rate", "median"),
        中位出金次数=("payouts", "median"))
    print(rank.sort_values("中位净到手", ascending=False).to_string(float_format=fmt))


if __name__ == "__main__":
    main()
