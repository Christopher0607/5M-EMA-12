"""Unit tests for indicators, sizing, and the trailing-stop engine."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bars import atr, ema, resample_5m, true_range, build_signal_frame, signal_bars
from src.strategy import LONG, SHORT, Sizing, _simulate, build_windows

TICK = 0.25


# ---------------------------------------------------------------- indicators

def test_ema_seeds_with_sma_and_recurses():
    v = pd.Series(np.arange(1.0, 21.0))
    got = ema(v, 12)
    assert got.iloc[:11].isna().all()
    seed = v[:12].mean()
    assert got.iloc[11] == pytest.approx(seed)
    expect = seed
    for x in v[12:]:
        expect = (2 / 13) * x + (11 / 13) * expect
    assert got.iloc[-1] == pytest.approx(expect)


def test_ema_constant_series_is_that_constant():
    got = ema(pd.Series([7.0] * 50), 12)
    assert got.iloc[11:].to_numpy() == pytest.approx(7.0)


def test_true_range_uses_previous_close():
    f = pd.DataFrame({"high": [10.0, 12.0], "low": [9.0, 11.5], "close": [9.5, 12.0]})
    # bar 2: H-L=0.5, |H-prevC|=2.5, |L-prevC|=2.0 -> 2.5
    assert true_range(f).iloc[1] == pytest.approx(2.5)


def test_atr_is_wilder_smoothed():
    rng = np.random.default_rng(0)
    close = pd.Series(rng.normal(100, 1, 60)).cumsum() / 10 + 100
    f = pd.DataFrame({"high": close + 1, "low": close - 1, "close": close})
    got = atr(f, 14)
    tr = true_range(f)
    expect = tr[:14].mean()
    assert got.iloc[13] == pytest.approx(expect)
    for i in range(14, 60):
        expect = (1 / 14) * tr.iloc[i] + (13 / 14) * expect
    assert got.iloc[-1] == pytest.approx(expect)


# ------------------------------------------------------------------- bars

def test_resample_drops_empty_periods_and_aggregates_ohlc():
    ts = pd.to_datetime(["2024-03-05T14:30", "2024-03-05T14:31", "2024-03-05T14:32",
                         "2024-03-05T18:00"], utc=True)
    f = pd.DataFrame({"ts": ts, "open": [1.0, 2, 3, 9], "high": [5.0, 6, 7, 9],
                      "low": [0.5, 1, 2, 9], "close": [2.0, 3, 4, 9],
                      "volume": [1, 1, 1, 1]})
    out = resample_5m(f, 5)
    assert len(out) == 2, "empty 5-min buckets must not produce bars"
    first = out.iloc[0]
    assert (first.open, first.high, first.low, first.close) == (1.0, 7.0, 0.5, 4.0)
    assert first.volume == 3


# ------------------------------------------------------------------ sizing

def test_atr_sizing_targets_one_percent_risk():
    s = Sizing("atr", 1.0)
    d, n = s.resolve(atr_pts=25.0, entry=20000.0, risk_dollars=500.0,
                     point_value=2.0, tick=TICK, max_contracts=10)
    assert d == 25.0
    assert n == 10  # floor(500/(25*2)) = 10
    assert d * 2.0 * n <= 500.0


def test_sizing_respects_contract_cap():
    s = Sizing("atr", 1.0)
    d, n = s.resolve(atr_pts=2.0, entry=20000.0, risk_dollars=500.0,
                     point_value=2.0, tick=TICK, max_contracts=10)
    assert n == 10, "floor would be 125; cap must bind"


def test_sizing_returns_zero_contracts_when_stop_too_wide():
    s = Sizing("atr", 1.0)
    d, n = s.resolve(atr_pts=400.0, entry=20000.0, risk_dollars=500.0,
                     point_value=2.0, tick=TICK, max_contracts=10)
    assert n == 0, "a 400pt stop cannot fit $500 risk on one $2/pt contract"


def test_fixed_sizing_holds_dollar_risk_exactly():
    for n_contracts in (1, 2, 5, 10):
        d, n = Sizing("fixed", n_contracts).resolve(
            atr_pts=25.0, entry=20000.0, risk_dollars=500.0,
            point_value=2.0, tick=TICK, max_contracts=10)
        assert n == n_contracts
        assert d * 2.0 * n == pytest.approx(500.0)


def test_stop_distance_lands_on_the_tick_grid():
    d, _ = Sizing("pct", 0.005).resolve(
        atr_pts=0.0, entry=20001.0, risk_dollars=500.0,
        point_value=2.0, tick=TICK, max_contracts=10)
    assert (d / TICK) == pytest.approx(round(d / TICK))


# ------------------------------------------------------- trailing stop engine

def _bars(oh_lc):
    o, h, l, c = (np.array(x, dtype="float64") for x in zip(*oh_lc))
    return o, h, l, c


def test_long_stops_on_first_bar_that_breaches():
    # bar 1 high 101 ratchets the stop to 91 before bar 2 breaches it
    o, h, l, c = _bars([(100, 101, 95, 96), (96, 97, 88, 89)])
    px, why, held, _, _ = _simulate(LONG, 100.0, 10.0, h, l, o, c, favorable_first=False)
    assert why == "stop" and held == 2 and px == pytest.approx(91.0)


def test_long_time_exit_when_stop_never_hit():
    o, h, l, c = _bars([(100, 102, 99, 101), (101, 103, 100, 102)])
    px, why, held, mfe, mae = _simulate(LONG, 100.0, 10.0, h, l, o, c, favorable_first=False)
    assert why == "time" and held == 2 and px == pytest.approx(102.0)
    assert mfe == pytest.approx(3.0)
    assert mae == pytest.approx(1.0), "worst price seen was 99"


def test_trailing_stop_ratchets_up_and_locks_a_profit():
    # Runs to 130 (stop trails to 120), then collapses.
    o, h, l, c = _bars([(100, 130, 100, 129), (129, 129, 100, 101)])
    px, why, held, _, _ = _simulate(LONG, 100.0, 10.0, h, l, o, c, favorable_first=False)
    assert why == "stop" and held == 2
    assert px == pytest.approx(120.0), "stop must trail to peak-distance, not stay at entry"


def test_trailing_stop_never_ratchets_down():
    o, h, l, c = _bars([(100, 130, 100, 129), (129, 131, 130, 130), (130, 130, 105, 106)])
    px, why, _, _, _ = _simulate(LONG, 100.0, 10.0, h, l, o, c, favorable_first=False)
    assert px == pytest.approx(121.0), "stop follows the running peak (131-10)"


def test_gap_through_stop_fills_at_the_open_not_the_stop():
    o, h, l, c = _bars([(80, 81, 79, 80)])   # opens far below the 90 stop
    px, why, _, _, _ = _simulate(LONG, 100.0, 10.0, h, l, o, c, favorable_first=False)
    assert why == "stop"
    assert px == pytest.approx(80.0), "a gap-through must fill at the open, not the stop level"


def test_short_mirrors_long():
    # falls to 70 (stop trails down to 80), then rallies back through it
    o, h, l, c = _bars([(100, 101, 70, 71), (71, 85, 70, 84)])
    px, why, held, mfe, _ = _simulate(SHORT, 100.0, 10.0, h, l, o, c, favorable_first=False)
    assert why == "stop" and held == 2 and px == pytest.approx(80.0)
    assert mfe == pytest.approx(30.0)


def test_mae_tracks_the_worst_excursion_before_a_stop():
    o, h, l, c = _bars([(100, 101, 88, 89)])
    _, why, _, _, mae = _simulate(LONG, 100.0, 10.0, h, l, o, c, favorable_first=False)
    assert why == "stop" and mae == pytest.approx(12.0)


def test_path_assumption_changes_the_outcome():
    """The documented worked example: neither ordering dominates."""
    o, h, l, c = _bars([(100, 115, 95, 114), (114, 114, 113, 113)])
    adv = _simulate(LONG, 100.0, 10.0, h, l, o, c, favorable_first=False)
    fav = _simulate(LONG, 100.0, 10.0, h, l, o, c, favorable_first=True)
    assert adv[1] == "time" and adv[0] == pytest.approx(113.0)
    assert fav[1] == "stop" and fav[0] == pytest.approx(105.0)


def test_non_trailing_stop_stays_at_entry_distance():
    o, h, l, c = _bars([(100, 130, 100, 129), (129, 129, 85, 86)])
    px, why, _, _, _ = _simulate(LONG, 100.0, 10.0, h, l, o, c,
                              favorable_first=False, trailing=False)
    assert why == "stop" and px == pytest.approx(90.0)


def test_no_stop_always_exits_on_time():
    o, h, l, c = _bars([(100, 101, 1, 2)])
    px, why, _, _, _ = _simulate(LONG, 100.0, 10.0, h, l, o, c,
                              favorable_first=False, use_stop=False)
    assert why == "time" and px == pytest.approx(2.0)


# --------------------------------------------------------------- DST / timing

def _synthetic_1m(days, cfg):
    """One minute bar per minute of 13:00-21:00 UTC for the given dates."""
    frames = []
    for day in days:
        idx = pd.date_range(f"{day}T12:00", f"{day}T21:00", freq="1min",
                            tz="UTC", inclusive="left")
        frames.append(pd.DataFrame({
            "ts": idx, "open": 100.0, "high": 100.5, "low": 99.5,
            "close": 100.0, "volume": 10,
        }))
    return pd.concat(frames, ignore_index=True)


CFG = {
    "strategy": {"signal_local_time": "09:30", "timezone": "America/New_York",
                 "bar_minutes": 5, "ema_period": 12, "atr_period": 14,
                 "max_hold_hours": 6},
}


def test_signal_bar_is_0930_et_across_the_dst_boundary():
    # 2024-03-05 is EST (09:30 ET = 14:30Z); 2024-07-10 is EDT (= 13:30Z).
    bars = _synthetic_1m(["2024-03-05", "2024-07-10"], CFG)
    frame = build_signal_frame(bars, CFG)
    sig = signal_bars(frame, CFG)
    assert len(sig) == 2
    utc_hours = sorted(sig["ts"].dt.hour.tolist())
    assert utc_hours == [13, 14], "the same ET time must map to two different UTC hours"
    assert (sig["local_time"] == "09:30").all()


def test_window_is_360_minutes_ending_at_1535_et():
    bars = _synthetic_1m(["2024-07-10"], CFG)
    windows = build_windows(bars, CFG)
    (_, _, _, closes, stamps) = windows[pd.Timestamp("2024-07-10").date()]
    assert len(closes) == 360, "6 hours of 1-minute bars"
    first = pd.Timestamp(stamps[0]).tz_convert("America/New_York")
    last = pd.Timestamp(stamps[-1]).tz_convert("America/New_York")
    assert first.strftime("%H:%M") == "09:35"
    assert last.strftime("%H:%M") == "15:34", "last managed bar closes at 15:35 ET"


def test_nyse_filter_drops_holidays_cme_trades_through():
    """2024-06-19 (Juneteenth) is a CME session but not an NYSE one."""
    from src.bars import restrict_to_nyse
    sig = pd.DataFrame({
        "session_date": [pd.Timestamp(d).date() for d in
                         ["2024-06-18", "2024-06-19", "2024-06-20"]],
        "close": [1.0, 2.0, 3.0], "ema": [0.5, 0.5, 0.5], "atr": [1.0, 1.0, 1.0],
        "ts": pd.to_datetime(["2024-06-18", "2024-06-19", "2024-06-20"], utc=True),
    })
    kept = restrict_to_nyse(sig)
    dates = {str(d) for d in kept["session_date"]}
    assert dates == {"2024-06-18", "2024-06-20"}
    assert "2024-06-19" not in dates


def test_nyse_filter_flags_half_days():
    from src.bars import restrict_to_nyse
    sig = pd.DataFrame({
        "session_date": [pd.Timestamp(d).date() for d in ["2024-07-03", "2024-07-05"]],
        "close": [1.0, 2.0], "ema": [0.5, 0.5], "atr": [1.0, 1.0],
        "ts": pd.to_datetime(["2024-07-03", "2024-07-05"], utc=True),
    })
    kept = restrict_to_nyse(sig).set_index("session_date")
    assert bool(kept.loc[pd.Timestamp("2024-07-03").date(), "early_close"]) is True
    assert bool(kept.loc[pd.Timestamp("2024-07-05").date(), "early_close"]) is False
