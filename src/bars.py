"""Bar aggregation and indicators on the 24-hour continuous Globex session."""

from __future__ import annotations

import numpy as np
import pandas as pd


def resample_5m(bars_1m: pd.DataFrame, minutes: int = 5) -> pd.DataFrame:
    """Aggregate 1-minute bars into N-minute bars on UTC boundaries.

    UTC alignment is safe here: the NY open (09:30 ET) lands on 13:30Z in EDT and
    14:30Z in EST, both exact 5-minute multiples, so UTC-aligned buckets coincide
    with ET-aligned ones year-round.

    Periods with no trading (the daily 17:00-18:00 ET break, weekends, holidays)
    produce no bar at all, matching how a charting platform draws the series.
    """
    agg = (
        bars_1m.resample(f"{minutes}min", on="ts", origin="epoch",
                         label="left", closed="left")
        .agg(open=("open", "first"), high=("high", "max"),
             low=("low", "min"), close=("close", "last"),
             volume=("volume", "sum"))
    )
    agg = agg.dropna(subset=["open"]).reset_index()
    return agg


def ema(values: np.ndarray | pd.Series, period: int) -> pd.Series:
    """Exponential moving average, alpha = 2/(period+1), seeded with SMA(period).

    Seeding with the simple average of the first `period` observations is what
    charting platforms do. Values before the seed index are NaN.
    """
    series = pd.Series(np.asarray(values, dtype="float64"))
    if len(series) < period:
        return pd.Series(np.nan, index=series.index)
    alpha = 2.0 / (period + 1.0)
    seeded = series.copy()
    seeded.iloc[period - 1] = series.iloc[:period].mean()
    tail = seeded.iloc[period - 1:].ewm(alpha=alpha, adjust=False).mean()
    out = pd.Series(np.nan, index=series.index)
    out.iloc[period - 1:] = tail.to_numpy()
    return out


def true_range(frame: pd.DataFrame) -> pd.Series:
    """max(H-L, |H-prevC|, |L-prevC|). First bar falls back to H-L."""
    prev_close = frame["close"].shift(1)
    spans = pd.concat(
        [frame["high"] - frame["low"],
         (frame["high"] - prev_close).abs(),
         (frame["low"] - prev_close).abs()],
        axis=1,
    )
    return spans.max(axis=1)


def atr(frame: pd.DataFrame, period: int) -> pd.Series:
    """Wilder's ATR: alpha = 1/period, seeded with SMA(period) of true range."""
    tr = true_range(frame)
    if len(tr) < period:
        return pd.Series(np.nan, index=frame.index)
    alpha = 1.0 / period
    seeded = tr.copy()
    seeded.iloc[period - 1] = tr.iloc[:period].mean()
    tail = seeded.iloc[period - 1:].ewm(alpha=alpha, adjust=False).mean()
    out = pd.Series(np.nan, index=frame.index)
    out.iloc[period - 1:] = tail.to_numpy()
    return out


def build_signal_frame(bars_1m: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """5-minute bars with a continuous EMA and ATR attached, plus ET local time.

    The EMA/ATR run continuously across the whole history and are never reset per
    day — that is what "24-hour continuous" means for this strategy.
    """
    s = cfg["strategy"]
    frame = resample_5m(bars_1m, s["bar_minutes"])
    frame["ema"] = ema(frame["close"], s["ema_period"])
    frame["atr"] = atr(frame, s["atr_period"])
    local = frame["ts"].dt.tz_convert(s["timezone"])
    frame["local_time"] = local.dt.strftime("%H:%M")
    frame["session_date"] = local.dt.date
    return frame


def signal_bars(frame: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """The one bar per day that generates a signal: 09:30-09:35 ET.

    Selected by New York local time via zoneinfo, never by a hardcoded UTC hour,
    so the DST transitions are handled by construction.
    """
    s = cfg["strategy"]
    hits = frame[frame["local_time"] == s["signal_local_time"]].copy()
    hits = hits.dropna(subset=["ema", "atr"])
    return hits.reset_index(drop=True)


def nyse_sessions(start, end) -> pd.DataFrame:
    """NYSE trading sessions with their close times, indexed by date."""
    import pandas_market_calendars as mcal

    sched = mcal.get_calendar("NYSE").schedule(start_date=start, end_date=end)
    out = pd.DataFrame({
        "session_date": [d.date() for d in sched.index],
        "nyse_close": sched["market_close"].dt.tz_convert("America/New_York").to_numpy(),
    })
    close_local = pd.to_datetime(out["nyse_close"], utc=True).dt.tz_convert("America/New_York")
    out["early_close"] = close_local.dt.hour < 16
    return out


def restrict_to_nyse(signals: pd.DataFrame) -> pd.DataFrame:
    """Keep only days the NYSE actually opened.

    CME equity futures trade through several NYSE holidays (Juneteenth, Labor
    Day, Thanksgiving, ...) on a few percent of normal volume. There is no New
    York open on those days, so the strategy's premise does not hold and the
    thin tape would produce fictional fills. Dropping them is a correctness fix,
    not a filter on results.
    """
    if signals.empty:
        return signals.assign(early_close=pd.Series(dtype=bool))
    cal = nyse_sessions(min(signals["session_date"]), max(signals["session_date"]))
    merged = signals.merge(cal, on="session_date", how="inner")
    return merged.reset_index(drop=True)
