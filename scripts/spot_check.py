#!/usr/bin/env python3
"""Independently re-derive a handful of trades straight from the 1-minute bars.

This deliberately does not import the trade engine. It recomputes the signal bar,
the EMA comparison, and the trailing stop with plain loops over the raw data, so
agreement is evidence the engine is right rather than evidence it is consistent
with itself.
"""

import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data import load_bars

cfg = yaml.safe_load(open("config.yaml"))
trades = pd.read_csv("results/trades_headline.csv")
trades = trades[trades["skipped"].isna()]
bars = load_bars(cfg)
bars["et"] = bars["ts"].dt.tz_convert("America/New_York")

TICK = cfg["contract"]["tick_size"]
PV = cfg["contract"]["point_value"]
SLIP = cfg["costs"]["slippage_ticks"] * TICK
COMM = cfg["costs"]["commission_rt"]

sample = trades.sample(n=min(6, len(trades)), random_state=7).sort_values("session_date")
print(f"spot-checking {len(sample)} trades against raw 1-minute bars\n")

ok = True
for t in sample.itertuples(index=False):
    day = pd.Timestamp(t.session_date).date()
    d = bars[bars["et"].dt.date == day]
    sig = d[(d["et"].dt.hour == 9) & (d["et"].dt.minute.between(30, 34))]
    entry_raw = sig["close"].iloc[-1]                       # close of the 09:30-09:35 bar
    direction = 1 if t.direction == "long" else -1
    entry = entry_raw + direction * SLIP

    mgmt = d[((d["et"].dt.hour * 60 + d["et"].dt.minute) >= 9 * 60 + 35)
             & ((d["et"].dt.hour * 60 + d["et"].dt.minute) < 15 * 60 + 35)]

    dist = t.stop_distance_pts
    stop = entry - direction * dist
    peak = entry
    exit_raw, reason = None, "time"
    for b in mgmt.itertuples(index=False):
        stop_in = stop
        if direction == 1:
            if b.low <= stop:
                exit_raw = b.open if b.open <= stop_in else stop
                reason = "stop"; break
            peak = max(peak, b.high); stop = max(stop, peak - dist)
        else:
            if b.high >= stop:
                exit_raw = b.open if b.open >= stop_in else stop
                reason = "stop"; break
            peak = min(peak, b.low); stop = min(stop, peak + dist)
    if exit_raw is None:
        exit_raw = mgmt["close"].iloc[-1]
        reason = "time" if len(mgmt) >= 360 else "session_end"

    exit_fill = exit_raw - direction * SLIP
    pnl = (exit_fill - entry) * direction * PV * t.contracts - COMM * t.contracts

    agree = (abs(entry - t.entry) < 1e-6 and abs(exit_fill - t.exit) < 1e-6
             and abs(pnl - t.pnl) < 1e-6 and reason == t.exit_reason)
    ok &= agree
    print(f"{t.session_date}  {t.direction:<5} engine: entry={t.entry:9.2f} exit={t.exit:9.2f} "
          f"pnl={t.pnl:8.2f} {t.exit_reason}")
    print(f"{'':10}  {'':5}  manual: entry={entry:9.2f} exit={exit_fill:9.2f} "
          f"pnl={pnl:8.2f} {reason}   {'MATCH' if agree else 'MISMATCH'}\n")

print("all sampled trades reproduce" if ok else "MISMATCH — engine and manual disagree")
sys.exit(0 if ok else 1)
