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


# ------------------------------------- TopStep: tiers, consistency, caps

TS_50K = {"balance": 50000.0, "trailing_dd": 2000.0, "profit_target": 3000.0,
          "trail_basis": "eod", "lock_at_initial": True, "daily_loss_limit": 1000.0,
          "consistency_max_day_vs_target": 0.50}
TS_FUNDED = {"balance": 50000.0, "trailing_dd": 2000.0, "trail_basis": "eod",
             "lock_at_initial": True, "daily_loss_limit": 1000.0,
             "min_trading_days": 5, "min_day_profit": 150.0, "safety_net": 50000.0,
             "payout_cap": 2000.0, "capped_payouts": None,
             "consistency_max_day_share": None,
             "split_full_to": 0.0, "split_after": 0.9}


def test_combine_consistency_blocks_a_pass_carried_by_one_day():
    """Reaching the target is not enough if one day carried more than half of it."""
    from src.propfirm import run_account
    # +$2,000 in one day (66% of the $3,000 target) then +$1,100 spread out.
    rows = [("big", 2000.0, 2000.0, 0.0)] + win(11, 100.0, "s")
    r = run_account(days(rows), TS_50K, max_days=40)
    assert r["outcome"] != "passed", "one day at 66% of target must block the pass"

    no_rule = dict(TS_50K, consistency_max_day_vs_target=None)
    assert run_account(days(rows), no_rule, max_days=40)["outcome"] == "passed"


def test_combine_consistency_lets_a_balanced_run_pass():
    from src.propfirm import run_account
    rows = win(30, 200.0, "e")          # no day above 6.7% of the target
    assert run_account(days(rows), TS_50K, max_days=40)["outcome"] == "passed"


def test_topstep_caps_every_payout_not_just_the_first_three():
    """capped_payouts: null means the cap always applies."""
    r = run_funded(days(win(60, 900.0)), TS_FUNDED, ALL, 0.0, 0)
    sizes = [p.gross for p in r["payouts"]]
    assert len(sizes) >= 5
    assert all(s <= 2000.0 + 1e-9 for s in sizes), "TopStep caps every payout"
    assert all(p.capped for p in r["payouts"][:5]), "and they are flagged as capped"


def test_flat_ninety_ten_split_applies_from_the_first_dollar():
    r = run_funded(days(win(6, 400.0)), TS_FUNDED, ALL, 0.0, 0)
    p = r["payouts"][0]
    assert p.net == pytest.approx(p.gross * 0.9)


def test_topstep_qualifying_day_threshold_is_150():
    below = run_funded(days(win(10, 140.0)), TS_FUNDED, ALL, 0.0, 0)
    assert below["payouts"] == [], "$140 days do not qualify"
    above = run_funded(days(win(10, 160.0)), TS_FUNDED, ALL, 0.0, 0)
    assert len(above["payouts"]) >= 1, "$160 days do"


# ----------------------------------------------- risk bases and scaling

TIERS = {
    "50k":  {"balance": 50000.0,  "trailing_dd": 2000.0, "max_micros": 50},
    "100k": {"balance": 100000.0, "trailing_dd": 3000.0, "max_micros": 100},
    "150k": {"balance": 150000.0, "trailing_dd": 4500.0, "max_micros": 150},
}


def test_fixed_risk_gives_bigger_tiers_more_room():
    from src.career import losses_to_bust
    b = {"kind": "fixed", "value": 500.0}
    assert losses_to_bust(TIERS["50k"], b) == pytest.approx(4.0)
    assert losses_to_bust(TIERS["150k"], b) == pytest.approx(9.0)


def test_pct_balance_makes_the_big_account_relatively_tighter():
    """The finding worth surfacing: 1%-of-balance punishes the larger tier."""
    from src.career import losses_to_bust
    b = {"kind": "pct_balance", "value": 0.01}
    assert losses_to_bust(TIERS["50k"], b) == pytest.approx(4.0)
    assert losses_to_bust(TIERS["150k"], b) == pytest.approx(3.0)
    assert losses_to_bust(TIERS["150k"], b) < losses_to_bust(TIERS["50k"], b)


def test_pct_mll_holds_the_cushion_constant_across_tiers():
    from src.career import losses_to_bust
    b = {"kind": "pct_mll", "value": 0.25}
    for t in TIERS.values():
        assert losses_to_bust(t, b) == pytest.approx(4.0)


def test_scaling_is_exactly_linear_under_a_flat_split():
    from src.career import scale_accounts
    rows = win(6, 600.0, "e") + win(40, 600.0, "f")
    car = run_career(days(rows), APEX_E, APEX_F, ALL, NOFEE)
    one = scale_accounts(car, 1)
    five = scale_accounts(car, 5)
    for k in ("payouts", "withdrawn", "fees_paid", "net_to_trader"):
        assert five[k] == pytest.approx(one[k] * 5), f"{k} must scale exactly"


def test_legacy_split_threshold_does_not_multiply_across_accounts():
    """The $10k 100%-share is per trader, so five accounts do not get five of it."""
    from src.career import scale_accounts
    rows = win(6, 600.0, "e") + win(60, 600.0, "f")
    car = run_career(days(rows), APEX_E, APEX_F, ALL, NOFEE)
    flat = scale_accounts(car, 5, legacy_split_full_to=0.0)
    legacy = scale_accounts(car, 5, legacy_split_full_to=10000.0, split_after=0.9)
    one = scale_accounts(car, 1, legacy_split_full_to=10000.0, split_after=0.9)
    assert legacy["withdrawn"] < one["withdrawn"] * 5, "threshold must not multiply"
    assert legacy["withdrawn_gross"] == pytest.approx(one["withdrawn_gross"] * 5)


# ------------------------------- Lucid / TPT: the three structural differences

LUCID_F = {"balance": 50000.0, "trailing_dd": 2000.0, "trail_basis": "eod",
           "lock_at_initial": True, "daily_loss_limit": 1200.0, "daily_loss_soft": True,
           "static_floor": True, "min_trading_days": 0, "min_day_profit": 0.0,
           "safety_net": 50000.0, "payout_cap": None, "capped_payouts": 0,
           "consistency_max_day_share": 0.40, "split_full_to": 0.0, "split_after": 0.9}
TPT_F = dict(LUCID_F, static_floor=False, trail_basis="intraday",
             daily_loss_limit=None, daily_loss_soft=False,
             consistency_max_day_share=0.50, consistency_lifetime=True,
             min_trading_days=5, split_after=0.8)


def test_static_floor_keeps_the_cushion_a_locking_threshold_gives_away():
    """A static floor stays at balance-MLL; a locking one climbs to the balance.

    Both stop following profits, so the difference only shows in the cushion:
    after eight +$500 days the static floor is still 48,000 while the locking
    threshold has ratcheted to 50,000. Giving back $5,000 separates them.
    """
    rows = win(8, 500.0) + [("give_back", -5000.0, 0.0, 5000.0)]
    never = {"kind": "threshold", "value": 1e9}     # suppress payouts

    static = run_funded(days(rows), LUCID_F, never, 0.0, 0)
    assert static["outcome"] == "survived", "floor stays at 48,000, balance 49,000"

    locking = run_funded(days(rows), dict(LUCID_F, static_floor=False), never, 0.0, 0)
    assert locking["outcome"] == "blown", "threshold locked at 50,000, balance 49,000"


def test_soft_daily_limit_blocks_the_day_but_keeps_the_account():
    from src.propfirm import run_account
    ev_soft = {"balance": 50000.0, "trailing_dd": 2000.0, "profit_target": 3000.0,
               "trail_basis": "eod", "lock_at_initial": True,
               "daily_loss_limit": 1200.0, "daily_loss_soft": True}
    rows = [("hit_dll", -1300.0, 0.0, 1300.0)] + win(20, 400.0, "r")
    assert run_account(days(rows), ev_soft, max_days=40)["outcome"] == "passed"

    ev_hard = dict(ev_soft, daily_loss_soft=False)
    r = run_account(days(rows), ev_hard, max_days=40)
    assert r["outcome"] == "blown" and r["reason"] == "daily_loss_limit"


def test_tpt_minimum_trading_days_delays_an_otherwise_instant_pass():
    from src.propfirm import run_account
    ev = {"balance": 50000.0, "trailing_dd": 2000.0, "profit_target": 3000.0,
          "trail_basis": "eod", "lock_at_initial": True, "daily_loss_limit": None,
          "min_days_to_pass": 5}
    one_day = [("boom", 3500.0, 3500.0, 0.0)]
    assert run_account(days(one_day), ev, max_days=10)["outcome"] != "passed"

    no_min = dict(ev, min_days_to_pass=0)
    assert run_account(days(one_day), no_min, max_days=10)["outcome"] == "passed"


def test_lifetime_consistency_is_not_reset_by_taking_a_payout():
    """TPT measures against lifetime profit, so a payout does not clear the record."""
    rows = win(5, 400.0, "a") + [("big", 6000.0, 6000.0, 0.0)] + win(5, 400.0, "b")
    cycle = run_funded(days(rows), dict(TPT_F, consistency_lifetime=False), ALL, 0.0, 0)
    life = run_funded(days(rows), TPT_F, ALL, 0.0, 0)
    assert len(life["payouts"]) <= len(cycle["payouts"]), \
        "a lifetime basis can only be at least as restrictive as a per-cycle one"


def test_lucid_ninety_ten_beats_tpt_eighty_twenty_on_the_same_gross():
    lucid = run_funded(days(win(12, 500.0)), LUCID_F, ALL, 0.0, 0)
    tpt = run_funded(days(win(12, 500.0)), dict(TPT_F, static_floor=True,
                                                trail_basis="eod"), ALL, 0.0, 0)
    if lucid["payouts"] and tpt["payouts"]:
        lg = sum(p.gross for p in lucid["payouts"])
        tg = sum(p.gross for p in tpt["payouts"])
        if lg == pytest.approx(tg):
            assert sum(p.net for p in lucid["payouts"]) > sum(p.net for p in tpt["payouts"])
