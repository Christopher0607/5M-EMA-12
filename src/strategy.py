"""Signal generation and the trailing-stop trade engine.

Intrabar path assumption
------------------------
With 1-minute OHLC we cannot know whether a bar's high or its low came first,
and for a *trailing* stop that ordering changes the outcome. Two extremes:

  adverse_first    check the stop against the low using the stop carried in from
                   prior bars, then ratchet with this bar's high
  favorable_first  ratchet with this bar's high first, then check the low

Neither dominates the other in P&L: favorable_first can close a trade at a
ratcheted level that adverse_first keeps alive for a better or worse outcome
later. They are two extreme path assumptions used to measure path sensitivity,
not upper and lower bounds. adverse_first is the headline because it never
credits a within-bar ratchet that protects a position the same bar could have
stopped out.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

LONG, SHORT = 1, -1


@dataclass
class Sizing:
    """How a variant turns a signal into (stop distance, contract count)."""

    kind: str          # "atr" | "pct" | "fixed"
    param: float       # k, p, or N

    def resolve(self, *, atr_pts: float, entry: float, risk_dollars: float,
                point_value: float, tick: float, max_contracts: int
                ) -> tuple[float, int]:
        """Return (stop distance in points rounded to the tick grid, contracts)."""
        if self.kind == "fixed":
            contracts = int(self.param)
            distance = risk_dollars / (contracts * point_value)
        else:
            if self.kind == "atr":
                distance = self.param * atr_pts
            elif self.kind == "pct":
                distance = self.param * entry
            else:
                raise ValueError(f"unknown sizing kind {self.kind!r}")
            contracts = 0
        distance = round(distance / tick) * tick
        if distance <= 0:
            return 0.0, 0
        if self.kind != "fixed":
            contracts = int(math.floor(risk_dollars / (distance * point_value)))
            contracts = min(contracts, max_contracts)
        return distance, contracts


def _simulate(direction: int, entry: float, distance: float,
              highs: np.ndarray, lows: np.ndarray, opens: np.ndarray,
              closes: np.ndarray, favorable_first: bool,
              trailing: bool = True, use_stop: bool = True
              ) -> tuple[float, str, int, float, float]:
    """Walk the management window bar by bar.

    Fill convention: a bar that *opens* already through the stop carried in from
    prior bars is a gap and fills at the open. A stop reached only after this bar
    ratcheted (favorable_first) fills at the stop level itself, because the open
    preceded the ratchet and is not a valid gap reference.

    Returns (exit price before slippage, reason, bars held, max favorable
    excursion, max adverse excursion) with excursions in points.
    """
    n = len(closes)
    if n == 0:
        return entry, "no_data", 0, 0.0, 0.0

    long = direction == LONG
    stop = entry - distance if long else entry + distance
    stop_peak = entry      # drives the ratchet
    mfe_peak = entry       # best price seen; always sees the whole bar
    mae_trough = entry     # worst price seen; feeds intraday equity troughs

    for i in range(n):
        stop_in = stop    # level in force at this bar's open

        if favorable_first and trailing:
            stop_peak = max(stop_peak, highs[i]) if long else min(stop_peak, lows[i])
            stop = (max(stop, stop_peak - distance) if long
                    else min(stop, stop_peak + distance))

        mfe_peak = max(mfe_peak, highs[i]) if long else min(mfe_peak, lows[i])
        mae_trough = min(mae_trough, lows[i]) if long else max(mae_trough, highs[i])

        if use_stop and ((lows[i] <= stop) if long else (highs[i] >= stop)):
            gapped = (opens[i] <= stop_in) if long else (opens[i] >= stop_in)
            fill = opens[i] if gapped else stop
            mfe = (mfe_peak - entry) if long else (entry - mfe_peak)
            mae = (entry - mae_trough) if long else (mae_trough - entry)
            return fill, "stop", i + 1, mfe, mae

        if not favorable_first and trailing:
            stop_peak = max(stop_peak, highs[i]) if long else min(stop_peak, lows[i])
            stop = (max(stop, stop_peak - distance) if long
                    else min(stop, stop_peak + distance))

    mfe = (mfe_peak - entry) if long else (entry - mfe_peak)
    mae = (entry - mae_trough) if long else (mae_trough - entry)
    return closes[-1], "time", n, mfe, mae


def build_windows(bars_1m: pd.DataFrame, cfg: dict) -> dict:
    """Per-session numpy arrays for the management window, built once and reused.

    The window runs from the first minute after the signal bar closes (09:35 ET)
    through entry + max_hold_hours (15:35 ET), so every exit lands inside the
    regular session and the strategy never carries overnight gap risk.
    """
    s = cfg["strategy"]
    local = bars_1m["ts"].dt.tz_convert(s["timezone"])
    minutes = local.dt.hour * 60 + local.dt.minute
    sig_h, sig_m = (int(x) for x in s["signal_local_time"].split(":"))
    start = sig_h * 60 + sig_m + s["bar_minutes"]           # 09:35
    end = start + int(s["max_hold_hours"] * 60)             # 15:35, exclusive
    mask = (minutes >= start) & (minutes < end)

    sub = bars_1m.loc[mask].copy()
    sub["session_date"] = local[mask].dt.date
    windows = {}
    for date, group in sub.groupby("session_date", sort=False):
        windows[date] = (
            group["open"].to_numpy(dtype="float64"),
            group["high"].to_numpy(dtype="float64"),
            group["low"].to_numpy(dtype="float64"),
            group["close"].to_numpy(dtype="float64"),
            group["ts"].to_numpy(),
        )
    return windows


def run(signals: pd.DataFrame, windows: dict, cfg: dict, sizing: Sizing, *,
        favorable_first: bool = False, trailing: bool = True,
        use_stop: bool = True) -> pd.DataFrame:
    """Backtest one configuration and return the trade log."""
    c, a, k = cfg["contract"], cfg["account"], cfg["costs"]
    point_value = float(c["point_value"])
    tick = float(c["tick_size"])
    risk_dollars = float(a["initial_capital"]) * float(a["risk_pct"])
    max_contracts = int(a["max_contracts"])
    slip = float(k["slippage_ticks"]) * tick
    commission = float(k["commission_rt"])

    rows = []
    for sig in signals.itertuples(index=False):
        if sig.close > sig.ema:
            direction = LONG
        elif sig.close < sig.ema:
            direction = SHORT
        else:
            rows.append(_skip(sig, "ema_tie"))
            continue

        window = windows.get(sig.session_date)
        if window is None or len(window[3]) == 0:
            rows.append(_skip(sig, "no_window"))
            continue

        entry_ref = float(sig.close)
        distance, contracts = sizing.resolve(
            atr_pts=float(sig.atr), entry=entry_ref, risk_dollars=risk_dollars,
            point_value=point_value, tick=tick, max_contracts=max_contracts,
        )
        if contracts < 1 or distance <= 0:
            rows.append(_skip(sig, "risk_too_large"))
            continue

        opens, highs, lows, closes, stamps = window
        full_len = int(cfg["strategy"]["max_hold_hours"] * 60)
        entry_fill = entry_ref + direction * slip
        exit_ref, reason, bars_held, mfe, mae = _simulate(
            direction, entry_fill, distance, highs, lows, opens, closes,
            favorable_first=favorable_first, trailing=trailing, use_stop=use_stop,
        )
        if reason == "time" and len(closes) < full_len:
            # NYSE early close (1pm ET half-days): the 6-hour clock never ran out,
            # the session did. Labelled separately so the exit mix stays honest.
            reason = "session_end"
        exit_fill = exit_ref - direction * slip

        gross_pts = (exit_fill - entry_fill) * direction
        fees = commission * contracts
        pnl = gross_pts * point_value * contracts - fees
        rows.append({
            "session_date": sig.session_date,
            "ts_signal": sig.ts,
            "direction": "long" if direction == LONG else "short",
            "entry": entry_fill,
            "exit": exit_fill,
            "stop_distance_pts": distance,
            "contracts": contracts,
            "risk_dollars": distance * point_value * contracts,
            "gross_pts": gross_pts,
            "fees": fees,
            "pnl": pnl,
            "exit_reason": reason,
            "bars_held": bars_held,
            "mfe_pts": mfe,
            "mae_pts": mae,
            "atr_pts": float(sig.atr),
            "skipped": None,
        })
    return pd.DataFrame(rows)


def _skip(sig, why: str) -> dict:
    return {
        "session_date": sig.session_date, "ts_signal": sig.ts, "direction": None,
        "entry": np.nan, "exit": np.nan, "stop_distance_pts": np.nan,
        "contracts": 0, "risk_dollars": np.nan, "gross_pts": np.nan,
        "fees": 0.0, "pnl": 0.0, "exit_reason": None, "bars_held": 0,
        "mfe_pts": np.nan, "atr_pts": float(getattr(sig, "atr", np.nan)),
        "skipped": why,
    }
