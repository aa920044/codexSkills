#!/usr/bin/env python3
"""Quote-only wrapper for realtime Taiwan symbols."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import snapshot as snapshot_mod  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Return quote-only JSON for Taiwan stock symbols.")
    parser.add_argument("--stocks", required=True, help="Comma-separated Taiwan stock codes.")
    parser.add_argument("--mock", action="store_true", help="Use deterministic sample data.")
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args(argv)

    snapshot_args = argparse.Namespace(
        stock=None,
        stocks=args.stocks,
        sector=None,
        format="json",
        save_log=False,
        mock=args.mock,
        timeout=args.timeout,
        market_turnover_billion=None,
        market_turnover_time=None,
        market_baseline_billion=None,
    )
    data = snapshot_mod.build_snapshot(snapshot_args)
    print(json.dumps({"query": data["query"], "quotes": data["quotes"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
