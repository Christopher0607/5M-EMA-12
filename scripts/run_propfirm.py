#!/usr/bin/env python3
"""Prop-firm career economics and out-of-sample validation of the parameter choice."""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bars import build_signal_frame, restrict_to_nyse, signal_bars
from src.career import career_distribution, run_career, summarise_career
from src.data import load_bars
from src.metrics import summarise
from src.propfirm import daily_frame, rolling_evaluation, summarise_evaluation
from src.strategy import Sizing, build_windows, run
from src.walkforward import holdout, walk_forward

OUT = Path("results")

# The configs the user asked to compare: the sweep winner, a structurally
# stationary alternative, and the non-trailing version of each.
CONFIGS = {
    "fixed N=2 (trailing)":   (Sizing("fixed", 2.0), {}),
    "fixed N=2 (fixed stop)": (Sizing("fixed", 2.0), {"trailing": False}),
    "pct 0.5% (trailing)":    (Sizing("pct", 0.005), {}),
    "pct 0.5% (fixed stop)":  (Sizing("pct", 0.005), {"trailing": False}),
}

SWEEP = ([("atr", k) for k in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)]
         + [("pct", p) for p in (0.0025, 0.005, 0.0075, 0.01)]
         + [("fixed", n) for n in (1.0, 2.0, 5.0, 10.0)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(open(args.config))
    OUT.mkdir(exist_ok=True)
    pv = float(cfg["contract"]["point_value"])
    init = float(cfg["account"]["initial_capital"])

    print("loading ...", flush=True)
    bars = load_bars(cfg)
    signals = restrict_to_nyse(signal_bars(build_signal_frame(bars, cfg), cfg))
    windows = build_windows(bars, cfg)
    print(f"  signals {len(signals):,}  {signals.session_date.min()} -> {signals.session_date.max()}")

    # ---------------------------------------------------------- trade logs
    print("building trade logs ...", flush=True)
    logs = {name: run(signals, windows, cfg, sizing, **kw)
            for name, (sizing, kw) in CONFIGS.items()}
    sweep_logs = {f"{k} {p:g}": run(signals, windows, cfg, Sizing(k, p))
                  for k, p in SWEEP}

    # ------------------------------------------------- out-of-sample checks
    print("walk-forward ...", flush=True)
    oos, picks = walk_forward(sweep_logs,
                              min_train_years=int(cfg["walkforward"]["min_train_years"]))
    picks.to_csv(OUT / "walkforward_picks.csv", index=False)
    hold = holdout(sweep_logs, int(cfg["walkforward"]["holdout_split_year"]))

    logs["walk-forward (out of sample)"] = oos
    logs[f"holdout: {hold['picked']} (out of sample)"] = hold["oos_trades"]

    perf = []
    for name, log in logs.items():
        s = summarise(log, init)
        s["config"] = name
        perf.append(s)
    pd.DataFrame(perf).to_csv(OUT / "career_configs.csv", index=False)

    # --------------------------------------------------------- career matrix
    print("career simulations ...", flush=True)
    rows, dist_rows, checks = [], [], []
    for name, log in logs.items():
        days = daily_frame(log, pv)
        if days.empty:
            continue
        for firm in ("apex_50k", "topstep_50k"):
            eval_rules = cfg["propfirm"][firm]
            fund_rules = cfg["funded"][firm]
            # Cross-check: the evaluation phase must still reproduce the
            # standalone rolling evaluation, or the reused code has drifted.
            # Printed, because a check nobody sees is not a check.
            ev = summarise_evaluation(rolling_evaluation(days, eval_rules))
            checks.append({"config": name, "firm": firm,
                           "eval_pass_rate_pct": ev.get("pass_rate_pct")})
            for pol_name, policy in cfg["withdrawal_policies"].items():
                for fee_name, table in cfg["fees"].items():
                    car = run_career(days, eval_rules, fund_rules, policy,
                                     table[firm])
                    rec = summarise_career(car, len(days))
                    rec.update(config=name, firm=firm, policy=pol_name,
                               fees=fee_name, eval_pass_rate=ev.get("pass_rate_pct"))
                    rows.append(rec)
            # distribution of 2-year careers, promo fees, immediate withdrawal
            d = career_distribution(days, eval_rules, fund_rules,
                                    cfg["withdrawal_policies"]["immediate"],
                                    cfg["fees"]["promo"][firm])
            d["config"], d["firm"] = name, firm
            dist_rows.append(d)

    careers = pd.DataFrame(rows)
    careers.to_csv(OUT / "careers.csv", index=False)
    pd.DataFrame(checks).drop_duplicates().to_csv(OUT / "eval_crosscheck.csv", index=False)

    # ---- like-for-like on a common window -------------------------------
    # The holdout log only covers 2018+, so comparing its career totals against
    # logs that span 2010-2026 is apples to oranges. Re-run every config over the
    # same years so the comparison means something.
    since = int(cfg["walkforward"]["holdout_split_year"])
    common_rows, common_dist = [], []
    for name, log in logs.items():
        done = log[log["skipped"].isna()].copy()
        done = done[pd.to_datetime(done["session_date"]).dt.year >= since]
        days = daily_frame(done, pv)
        if days.empty:
            continue
        firm = "apex_50k"
        car = run_career(days, cfg["propfirm"][firm], cfg["funded"][firm],
                         cfg["withdrawal_policies"]["immediate"],
                         cfg["fees"]["promo"][firm])
        rec = summarise_career(car, len(days))
        rec.update(config=name, firm=firm, since=since,
                   years=len(days) / 252.0,
                   net_per_year=car.net_to_trader / max(len(days) / 252.0, 1e-9))
        common_rows.append(rec)
        d = career_distribution(days, cfg["propfirm"][firm], cfg["funded"][firm],
                                cfg["withdrawal_policies"]["immediate"],
                                cfg["fees"]["promo"][firm])
        common_dist.append(d.assign(config=name))
    common = pd.DataFrame(common_rows)
    common.to_csv(OUT / "careers_common.csv", index=False)
    cdist = pd.concat(common_dist, ignore_index=True)
    cdist.to_csv(OUT / "career_distribution_common.csv", index=False)
    dist = pd.concat(dist_rows, ignore_index=True)
    dist.to_csv(OUT / "career_distribution.csv", index=False)

    # ------------------------------------------------------------- console
    print("\n=== WALK-FORWARD vs HINDSIGHT ===")
    wf = summarise(oos, init)["net_pnl"]
    n2 = summarise(logs["fixed N=2 (trailing)"], init)["net_pnl"]
    ceiling = picks["best_pnl"].sum()
    print(f"  walk-forward (implementable)   ${wf:>10,.0f}")
    print(f"  fixed N=2 (hindsight)          ${n2:>10,.0f}")
    print(f"  per-year best (unreachable)    ${ceiling:>10,.0f}")
    print(f"  average OOS rank {picks['oos_rank'].mean():.1f}/{len(SWEEP)}"
          f"   picked-the-winner {int((picks['oos_rank']==1).sum())}/{len(picks)}")
    print(f"  holdout: picked {hold['picked']} on <{cfg['walkforward']['holdout_split_year']}"
          f" -> ${hold['test_pnl']:,.0f} OOS (rank {hold['test_rank']}/{hold['n_configs']})")

    print("\n=== CAREERS (one 16-year career, Apex, promo fees) ===")
    view = careers[(careers.firm == "apex_50k") & (careers.fees == "promo")]
    cols = ["config", "policy", "evals_bought", "evals_passed", "funded_accounts",
            "payouts", "withdrawn", "fees_paid", "net_to_trader", "pct_time_funded"]
    print(view[cols].to_string(index=False, float_format=lambda x: f"{x:,.0f}"))
    print("\n=== EVALUATION CROSS-CHECK (must match phase 1: 53.1 / 44.1 for N=2) ===")
    cc = pd.DataFrame(checks).drop_duplicates()
    n2 = cc[cc.config == "fixed N=2 (trailing)"]
    print(n2.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))

    print(f"\n=== LIKE-FOR-LIKE from {since} (Apex, promo, immediate) ===")
    cv = common[["config", "evals_bought", "evals_passed", "payouts", "withdrawn",
                 "fees_paid", "net_to_trader", "net_per_year"]]
    print(cv.sort_values("net_to_trader", ascending=False)
            .to_string(index=False, float_format=lambda x: f"{x:,.0f}"))

    print(f"\n=== 2-YEAR CAREERS started throughout {since}+ (Apex, promo, immediate) ===")
    g = cdist.groupby("config").agg(
        careers=("payouts", "size"),
        zero_payout_pct=("payouts", lambda s: 100.0 * (s == 0).mean()),
        median_payouts=("payouts", "median"),
        median_net=("net_to_trader", "median"),
        losing_pct=("net_to_trader", lambda s: 100.0 * (s < 0).mean()))
    print(g.sort_values("median_net", ascending=False)
           .to_string(float_format=lambda x: f"{x:,.1f}"))

    print(f"\nresults written to {OUT}/")


if __name__ == "__main__":
    main()
