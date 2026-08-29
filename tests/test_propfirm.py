"""Prop-firm rule tests: the trailing threshold is what actually kills accounts."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.propfirm import daily_frame, run_account, rolling_evaluation, summarise_evaluation

APEX = {"balance": 50000.0, "trailing_dd": 2500.0, "profit_target": 3000.0,
        "trail_basis": "intraday", "lock_at_initial": True, "daily_loss_limit": None}
TOPSTEP = {"balance": 50000.0, "trailing_dd": 2000.0, "profit_target": 3000.0,
           "trail_basis": "eod", "lock_at_initial": True, "daily_loss_limit": 1000.0}


def days(rows):
    return pd.DataFrame(rows, columns=["session_date", "pnl", "up", "down"])


def test_hitting_the_profit_target_passes():
    d = days([("d1", 3000.0, 3000.0, 0.0)])
    assert run_account(d, APEX)["outcome"] == "passed"


def test_losing_the_initial_buffer_blows_the_account():
    d = days([("d1", -2500.0, 0.0, 2500.0)])
    r = run_account(d, APEX)
    assert r["outcome"] == "blown" and r["reason"] == "trailing_drawdown"


def test_threshold_trails_up_so_a_profitable_account_can_still_bust():
    """Up 1000 then down 2600 busts, even though equity never fell below start-2500."""
    d = days([("d1", 1000.0, 1000.0, 0.0), ("d2", -2600.0, 0.0, 2600.0)])
    r = run_account(d, APEX)
    assert r["outcome"] == "blown"
    assert r["final"] == pytest.approx(48400.0), "still above the original 47,500 floor"


def test_intraday_peak_trails_the_threshold_even_if_the_day_closes_flat():
    """A round trip to +2000 and back ratchets the threshold to 49,500."""
    d = days([("d1", 0.0, 2000.0, 0.0), ("d2", -600.0, 0.0, 600.0)])
    r = run_account(d, APEX)
    assert r["outcome"] == "blown", "intraday high must drag the threshold up"


def test_threshold_locks_and_stops_trailing():
    d = days([("d1", 2700.0, 2700.0, 0.0), ("d2", -2000.0, 0.0, 2000.0),
              ("d3", 2400.0, 2400.0, 0.0)])
    r = run_account(d, APEX)
    # threshold locks at 50,100; equity dips to 50,700 (survives) then passes.
    assert r["outcome"] == "passed"


def test_daily_loss_limit_busts_topstep():
    d = days([("d1", -1000.0, 0.0, 1000.0)])
    r = run_account(d, TOPSTEP)
    assert r["outcome"] == "blown" and r["reason"] == "daily_loss_limit"


def test_topstep_trails_on_close_not_intraday_high():
    """A 1,500 intraday spike that closes flat must not move the EOD threshold.

    The same day/loss pair busts an intraday-trailing account and survives an
    EOD-trailing one, which is the whole difference between the two rulesets.
    """
    d = days([("d1", 0.0, 1500.0, 0.0), ("d2", -900.0, 0.0, 900.0)])
    assert run_account(d, TOPSTEP)["outcome"] != "blown"

    intraday_variant = dict(TOPSTEP, trail_basis="intraday", daily_loss_limit=None)
    assert run_account(d, intraday_variant)["outcome"] == "blown"


def test_undecided_when_neither_bound_is_reached():
    d = days([("d1", 10.0, 10.0, 0.0)] * 5)
    r = run_account(d, APEX, max_days=5)
    assert r["outcome"] == "undecided"


def test_rolling_evaluation_covers_every_start():
    d = days([("d%d" % i, 100.0, 100.0, 0.0) for i in range(40)])
    res = rolling_evaluation(d, APEX, max_days=30)
    assert len(res) == 39
    s = summarise_evaluation(res)
    assert s["accounts"] == 39 and s["passed"] > 0


def test_daily_frame_scales_excursions_by_contracts_and_point_value():
    trades = pd.DataFrame([{
        "session_date": "d1", "pnl": 100.0, "mfe_pts": 10.0, "mae_pts": 5.0,
        "contracts": 3, "fees": 4.02, "skipped": None,
    }])
    d = daily_frame(trades, point_value=2.0)
    assert d.iloc[0]["up"] == pytest.approx(60.0)
    assert d.iloc[0]["down"] == pytest.approx(34.02)
