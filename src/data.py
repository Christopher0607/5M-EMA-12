"""Databento fetch layer with an idempotent on-disk cache.

Historical data is billed per request, so this module is built around one rule:
never pay for the same bytes twice. Chunks already on disk are skipped, and the
projected spend is checked against a configured ceiling before anything is
downloaded.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import databento as db
import pandas as pd

RETRY_DELAYS = (2, 4, 8, 16)


class SpendGuardError(RuntimeError):
    """Raised when a fetch would cost more than the configured ceiling."""


@dataclass(frozen=True)
class Chunk:
    """One cacheable slice of history, [start, end)."""

    start: pd.Timestamp
    end: pd.Timestamp
    symbol: str = "NQ.v.0"

    @property
    def label(self) -> str:
        return self.start.strftime("%Y")

    def path(self, cache_dir: Path) -> Path:
        # The symbol is part of the filename: NQ.c.0 and NQ.v.0 are different
        # price series, and a cache keyed only by year would silently serve one
        # for the other after a config change.
        slug = self.symbol.replace(".", "_")
        return cache_dir / f"{slug}_1m_{self.label}.parquet"


def yearly_chunks(start: str, end: str, symbol: str = "NQ.v.0") -> list[Chunk]:
    """Split [start, end) into calendar-year chunks."""
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    chunks = []
    cursor = start_ts
    while cursor < end_ts:
        year_end = pd.Timestamp(f"{cursor.year + 1}-01-01", tz="UTC")
        chunks.append(Chunk(cursor, min(year_end, end_ts), symbol))
        cursor = year_end
    return chunks


def _retry(fn, what: str):
    """Run fn, retrying network failures with exponential backoff."""
    for attempt, delay in enumerate((*RETRY_DELAYS, None)):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - surface the final failure
            if delay is None:
                raise
            print(f"  {what} failed ({exc.__class__.__name__}: {exc}); "
                  f"retry {attempt + 1}/{len(RETRY_DELAYS)} in {delay}s")
            time.sleep(delay)
    raise AssertionError("unreachable")


class DataFetcher:
    def __init__(self, cfg: dict, api_key: str | None = None):
        self.cfg = cfg["data"]
        self.cache_dir = Path(self.cfg["cache_dir"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        key = api_key or os.environ.get("DATABENTO_API_KEY")
        if not key:
            raise RuntimeError("DATABENTO_API_KEY is not set")
        self.client = db.Historical(key)

    def _request_kwargs(self, chunk: Chunk) -> dict:
        return dict(
            dataset=self.cfg["dataset"],
            symbols=self.cfg["symbol"],
            stype_in=self.cfg["stype_in"],
            schema=self.cfg["schema"],
            start=chunk.start.isoformat(),
            end=chunk.end.isoformat(),
        )

    def estimate_cost(self, chunk: Chunk) -> float:
        return float(_retry(
            lambda: self.client.metadata.get_cost(**self._request_kwargs(chunk)),
            f"cost estimate {chunk.label}",
        ))

    def missing(self, chunks: list[Chunk]) -> list[Chunk]:
        return [c for c in chunks if not c.path(self.cache_dir).exists()]

    def fetch(self, chunks: list[Chunk] | None = None, dry_run: bool = False) -> float:
        """Download any chunks not already cached. Returns total USD spent."""
        chunks = chunks or yearly_chunks(self.cfg["start"], self.cfg["end"],
                                        self.cfg["symbol"])
        todo = self.missing(chunks)
        cached = len(chunks) - len(todo)
        if cached:
            print(f"cache: {cached}/{len(chunks)} chunks already on disk (free)")
        if not todo:
            print("nothing to fetch — cache is complete")
            return 0.0

        estimates = {c.label: self.estimate_cost(c) for c in todo}
        total = sum(estimates.values())
        for label, cost in estimates.items():
            print(f"  {label}: ${cost:.4f}")
        print(f"projected spend: ${total:.4f} across {len(todo)} chunks")

        ceiling = float(self.cfg["max_spend_usd"])
        if total > ceiling:
            raise SpendGuardError(
                f"projected ${total:.2f} exceeds max_spend_usd ${ceiling:.2f}; "
                "raise the ceiling in config.yaml if this is intended"
            )
        if dry_run:
            print("dry run — nothing downloaded")
            return 0.0

        spent = 0.0
        for chunk in todo:
            print(f"fetching {chunk.label} ...", flush=True)
            store = _retry(
                lambda c=chunk: self.client.timeseries.get_range(**self._request_kwargs(c)),
                f"fetch {chunk.label}",
            )
            frame = store.to_df(price_type="float", pretty_ts=True, map_symbols=False)
            frame = _normalise(frame)
            frame.to_parquet(chunk.path(self.cache_dir), index=False)
            spent += estimates[chunk.label]
            print(f"  {chunk.label}: {len(frame):,} bars -> {chunk.path(self.cache_dir).name}")
        print(f"total spent this run: ${spent:.4f}")
        return spent


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    """Reduce a raw ohlcv-1m frame to the columns the backtest needs, UTC-indexed."""
    out = frame.reset_index()
    ts_col = "ts_event" if "ts_event" in out.columns else out.columns[0]
    out = out.rename(columns={ts_col: "ts"})
    out["ts"] = pd.to_datetime(out["ts"], utc=True)
    keep = ["ts", "open", "high", "low", "close", "volume"]
    out = out[keep].sort_values("ts").reset_index(drop=True)
    # Continuous front-month can emit duplicate stamps around a roll; keep the
    # last observation for a given minute.
    out = out.drop_duplicates(subset="ts", keep="last").reset_index(drop=True)
    return out


def load_bars(cfg: dict) -> pd.DataFrame:
    """Load every cached chunk into one UTC-sorted 1-minute frame."""
    cache_dir = Path(cfg["data"]["cache_dir"])
    slug = cfg["data"]["symbol"].replace(".", "_")
    files = sorted(cache_dir.glob(f"{slug}_1m_*.parquet"))
    if not files:
        raise FileNotFoundError(
            f"no cached {cfg['data']['symbol']} data in {cache_dir}; "
            "run scripts/fetch_data.py")
    frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    frame = frame.sort_values("ts").drop_duplicates(subset="ts", keep="last")
    return frame.reset_index(drop=True)
