"""Funded-phase, career-loop, and walk-forward tests.

Payout economics are easy to get quietly wrong in a way that flatters the
result, so every rule here is checked against a hand-computed number.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.career import (Career, _split, run_career, run_funded,
                        summarise_career)
from src.walkforward import holdout, select_upto, walk_forward, yearly_pnl_matrix

APEX_F = {"balance": 50000.0, "trailing_dd": 2500.0, "trail_basis": "intraday",
          "lock_at_initial": True, "daily_loss_limit": None,
          "min_trading_days": 8, "min_day_profit": 50.0, "safety_net": 52600.0,
          "payout_cap": 2000.0, "capped_payouts": 3,
          "consistency_max_day_share": 0.30,
          "split_full_to": 25000.0, "split_after": 1.0}
APEX_E = {"balance": 50000.0, "trailing_dd": 2500.0, "profit_target": 3000.0,
          "trail_basis": "intraday", "lock_at_initial": True, "daily_loss_limit": None}
ALL = {"kind": "all"}
NOFEE = {"evaluation": 0.0, "activation": 0.0, "monthly_funded": 0.0}


def days(rows):
    return pd.DataFrame(rows, columns=["session_date", "pnl", "up", "down"])


def win(n, amt, tag="d"):
    return [(f"{tag}{i}", amt, max(amt, 0.0), 0.0) for i in range(n)]


# ----------------------------------------------------------------- profit split

def test_split_is_full_below_the_tier_then_reduced():
    assert _split(1000.0, 0.0, 25000.0, 1.0) == pytest.approx(1000.0)
    # TopStep shape: 100% of the first 10k, 90% after
    assert _split(4000.0, 8000.0, 10000.0, 0.9) == pytest.approx(2000.0 + 2000.0 * 0.9)
    assert _split(1000.0, 20000.0, 10000.0, 0.9) == pytest.approx(900.0)


# --------------------------------------------------------------- payout gating

def test_no_payout_before_the_minimum_qualifying_days():
    # 7 days of +$500 clears the safety net but not the 8-day requirement.
    r = run_funded(days(win(7, 500.0)), APEX_F, ALL, 0.0, 0)
    assert r["payouts"] == []


def test_payout_once_qualifying_days_and_safety_net_are_both_met():
    r = run_funded(days(win(8, 500.0)), APEX_F, ALL, 0.0, 0)
    assert len(r["payouts"]) == 1
    # balance 54,000; safety net 52,600 -> excess 1,400, under the 2,000 cap
    assert r["payouts"][0].gross == pytest.approx(1400.0)
    assert r["payouts"][0].balance_after == pytest.approx(52600.0)


def test_small_days_do_not_count_toward_qualifying_days():
    # $40/day is below the $50 minimum, so no day qualifies however many there are.
    r = run_funded(days(win(20, 40.0)), APEX_F, ALL, 0.0, 0)
    assert r["payouts"] == []


def test_no_payout_while_below_the_safety_net():
    # 8 qualifying days but only +$800 total: balance 50,800 < 52,600.
    r = run_funded(days(win(8, 100.0)), APEX_F, ALL, 0.0, 0)
    assert r["payouts"] == []


# ------------------------------------------------------------ consistency rule

def test_one_lumpy_day_blocks_an_otherwise_eligible_payout():
    rows = win(7, 100.0) + [("big", 5000.0, 5000.0, 0.0)]
    r = run_funded(days(rows), APEX_F, ALL, 0.0, 0)
    # 8 qualifying days and balance 55,700 clears the net, but the big day is
    # 5000/5700 = 88% of profit, far above the 30% ceiling.
    assert r["payouts"] == []


def test_the_block_lifts_once_the_lumpy_day_is_diluted():
    rows = win(7, 100.0) + [("big", 5000.0, 5000.0, 0.0)] + win(30, 700.0, "x")
    r = run_funded(days(rows), APEX_F, ALL, 0.0, 0)
    assert len(r["payouts"]) >= 1


def test_consistency_rule_is_skipped_when_the_firm_has_none():
    firm = dict(APEX_F, consistency_max_day_share=None)
    rows = win(7, 100.0) + [("big", 5000.0, 5000.0, 0.0)]
    r = run_funded(days(rows), firm, ALL, 0.0, 0)
    assert len(r["payouts"]) == 1


# -------------------------------------------------------------- caps and split

def test_first_payouts_are_capped_then_uncapped():
    # Long run of good days; each payout cycle needs 8 fresh qualifying days.
    r = run_funded(days(win(80, 800.0)), APEX_F, ALL, 0.0, 0)
    sizes = [p.gross for p in r["payouts"]]
    assert len(sizes) >= 4
    assert all(s <= 2000.0 + 1e-9 for s in sizes[:3]), "first three are capped"
    assert sizes[3] > 2000.0, "the fourth is uncapped"


def test_withdrawal_resets_the_qualifying_day_counter():
    r = run_funded(days(win(9, 800.0)), APEX_F, ALL, 0.0, 0)
    assert len(r["payouts"]) == 1, "one payout, not one per day after day 8"


# ------------------------------------------------- withdrawal raises bust risk

def test_taking_money_out_moves_the_account_toward_a_locked_threshold():
    """The same losing day survives without a payout and busts after one.

    Eight +$500 days take the balance to 54,000 and lock the threshold at 50,100.
    A later -$2,600 day leaves 51,400 if the money stayed in - but only 50,000 if
    1,400 was withdrawn first, which is below the threshold. Withdrawing is not
    free; it spends the cushion.
    """
    good = win(8, 500.0)
    drop = [("bad", -2600.0, 0.0, 2600.0)]

    never_pays = dict(APEX_F, min_trading_days=99)
    kept = run_funded(days(good + drop), never_pays, ALL, 0.0, 0)
    assert kept["payouts"] == []
    assert kept["outcome"] == "survived"
    assert kept["balance"] == pytest.approx(51400.0)

    paid = run_funded(days(good + drop), APEX_F, ALL, 0.0, 0)
    assert len(paid["payouts"]) == 1
    assert paid["payouts"][0].balance_after == pytest.approx(52600.0)
    assert paid["outcome"] == "blown", "the withdrawal is what makes this day fatal"


def test_funded_account_busts_on_the_trailing_threshold():
    rows = win(8, 500.0) + [("crash", -4000.0, 0.0, 4000.0)]
    r = run_funded(days(rows), APEX_F, ALL, 0.0, 0)
    assert r["outcome"] == "blown" and r["reason"] == "trailing_drawdown"


# ------------------------------------------------------- withdrawal policies

def test_half_buffer_withdraws_half_the_excess():
    r = run_funded(days(win(8, 500.0)), APEX_F, {"kind": "fraction", "value": 0.5}, 0.0, 0)
    assert r["payouts"][0].gross == pytest.approx(700.0)   # half of 1,400


def test_accumulate_waits_for_the_threshold():
    r = run_funded(days(win(8, 500.0)), APEX_F,
                   {"kind": "threshold", "value": 2000.0}, 0.0, 0)
    assert r["payouts"] == [], "excess of 1,400 is below the 2,000 trigger"
    r2 = run_funded(days(win(8, 900.0)), APEX_F,
                    {"kind": "threshold", "value": 2000.0}, 0.0, 0)
    assert len(r2["payouts"]) == 1


# ------------------------------------------------------------------- career

def test_career_buys_a_new_evaluation_after_a_bust():
    # Day 1 wipes out the evaluation; then a clean run passes and gets funded.
    rows = [("bust", -3000.0, 0.0, 3000.0)] + win(8, 500.0, "p") + win(12, 500.0, "f")
    car = run_career(days(rows), APEX_E, APEX_F, ALL, NOFEE)
    assert car.evals_bought >= 2, "must re-buy after the first evaluation busts"
    assert car.evals_passed >= 1


def test_career_charges_a_fee_for_every_evaluation_bought():
    rows = [("b1", -3000.0, 0.0, 3000.0), ("b2", -3000.0, 0.0, 3000.0)]
    fees = {"evaluation": 35.0, "activation": 0.0, "monthly_funded": 0.0}
    car = run_career(days(rows), APEX_E, APEX_F, ALL, fees)
    assert car.fees_paid == pytest.approx(35.0 * car.evals_bought)
    assert car.payouts == [] and car.net_to_trader < 0


def test_career_net_is_withdrawals_minus_fees():
    rows = win(6, 600.0, "e") + win(40, 600.0, "f")
    fees = {"evaluation": 35.0, "activation": 10.0, "monthly_funded": 85.0}
    car = run_career(days(rows), APEX_E, APEX_F, ALL, fees)
    assert car.net_to_trader == pytest.approx(car.withdrawn - car.fees_paid)
    s = summarise_career(car, len(rows))
    assert s["payouts"] == len(car.payouts)
    assert s["withdrawn"] == pytest.approx(sum(p.net for p in car.payouts))


# -------------------------------------------------------------- walk-forward

def _logs():
    """Two configs: 'early' wins 2010-2011, 'late' wins 2012-2013."""
    def mk(pnls):
        rows = []
        for year, v in pnls.items():
            rows.append({"session_date": f"{year}-06-01", "pnl": v, "skipped": None})
        return pd.DataFrame(rows)
    return {"early": mk({2010: 100, 2011: 100, 2012: -50, 2013: -50}),
            "late":  mk({2010: -50, 2011: -50, 2012: 300, 2013: 300})}


def test_selection_cannot_see_the_year_it_is_judged_on():
    """The look-ahead regression test: a peeking walk-forward is worse than none."""
    m = yearly_pnl_matrix(_logs())
    # The load-bearing assertion: judged at 2012 only 2010-2011 are visible, so
    # the pick is 'early' - which goes on to LOSE in 2012 while 'late' wins it.
    # A selector that peeked at 2012 would have picked 'late' here.
    assert select_upto(m, 2012, min_train_years=2) == "early"
    # Once 2012 is legitimately inside the training window, 'late' takes over.
    assert select_upto(m, 2013, min_train_years=2) == "late"
    assert select_upto(m, 2014, min_train_years=2) == "late"


def test_walk_forward_skips_years_without_enough_training_history():
    oos, picks = walk_forward(_logs(), min_train_years=2)
    assert set(picks["year"]) == {2012, 2013}, "2010 and 2011 cannot be traded"


def test_walk_forward_reports_the_regret_against_hindsight():
    oos, picks = walk_forward(_logs(), min_train_years=2)
    row = picks[picks["year"] == 2012].iloc[0]
    assert row["picked"] == "early" and row["oos_pnl"] == pytest.approx(-50)
    assert row["best_that_year"] == "late" and row["best_pnl"] == pytest.approx(300)
    assert row["oos_rank"] == 2


def test_lookback_window_forgets_old_history():
    m = yearly_pnl_matrix(_logs())
    assert select_upto(m, 2014, min_train_years=1, lookback=1) == "late"


def test_holdout_selects_on_train_only():
    h = holdout(_logs(), split_year=2012)
    assert h["picked"] == "early"
    assert h["train_pnl"] == pytest.approx(200)
    assert h["test_pnl"] == pytest.approx(-100)
    assert h["test_best"] == "late"
