#!/usr/bin/env python3
"""Download NQ 1-minute bars into the local parquet cache.

Chunks already on disk are skipped, so re-running never re-bills. Use --dry-run
to see the projected spend without downloading.
"""

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data import DataFetcher, yearly_chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--years", nargs="*", type=int,
                    help="limit to these calendar years (default: all configured)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    chunks = yearly_chunks(cfg["data"]["start"], cfg["data"]["end"],
                           cfg["data"]["symbol"])
    if args.years:
        wanted = {str(y) for y in args.years}
        chunks = [c for c in chunks if c.label in wanted]
        if not chunks:
            sys.exit(f"no chunks match years {args.years}")

    fetcher = DataFetcher(cfg)
    fetcher.fetch(chunks, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
