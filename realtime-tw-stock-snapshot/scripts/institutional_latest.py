#!/usr/bin/env python3
"""Fetch the latest official TWSE institutional totals and stock flows.

No database or local history is created.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from typing import Any


TWSE_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86"
TWSE_BFI82U = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"


def integer(value: Any) -> int:
    return int(str(value or "0").replace(",", "").strip() or "0")


def fetch_json(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 realtime-tw-stock-snapshot/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def fetch_for_date(date: dt.date, symbols: list[str], timeout: int) -> dict[str, Any] | None:
    compact = date.strftime("%Y%m%d")
    t86_url = f"{TWSE_T86}?{urllib.parse.urlencode({'date': compact, 'selectType': 'ALLBUT0999', 'response': 'json'})}"
    total_url = f"{TWSE_BFI82U}?{urllib.parse.urlencode({'dayDate': compact, 'type': 'day', 'response': 'json'})}"
    t86 = fetch_json(t86_url, timeout)
    totals = fetch_json(total_url, timeout)
    if t86.get("stat") != "OK" or totals.get("stat") != "OK":
        return None

    wanted = set(symbols)
    stocks = []
    for row in t86.get("data") or []:
        symbol = row[0].strip()
        if symbol not in wanted:
            continue
        foreign = integer(row[4]) + integer(row[7])
        trust = integer(row[10])
        dealer = integer(row[11])
        stocks.append(
            {
                "symbol": symbol,
                "name": row[1].strip(),
                "foreign_net_lot": round(foreign / 1000, 1),
                "trust_net_lot": round(trust / 1000, 1),
                "dealer_net_lot": round(dealer / 1000, 1),
                "total_net_lot": round(integer(row[18]) / 1000, 1),
            }
        )

    market = {}
    key_map = {
        "自營商(自行買賣)": "dealer_proprietary",
        "自營商(避險)": "dealer_hedging",
        "投信": "trust",
        "外資及陸資(不含外資自營商)": "foreign",
        "合計": "total",
    }
    for row in totals.get("data") or []:
        key = key_map.get(row[0])
        if key:
            market[key] = round(integer(row[3]) / 100_000_000, 2)

    positive = sum(1 for item in stocks if item["total_net_lot"] > 0)
    negative = sum(1 for item in stocks if item["total_net_lot"] < 0)
    if positive and negative:
        state = "資金輪動"
    elif positive and not negative:
        state = "法人同步買進"
    elif negative and not positive:
        state = "法人同步賣出"
    else:
        state = "法人方向不明"

    return {
        "query": {"date": date.isoformat(), "symbols": symbols, "storage": "none"},
        "source": {"name": "TWSE", "endpoints": ["T86", "BFI82U"]},
        "market_net_100m_twd": market,
        "per_symbol": stocks,
        "summary": {
            "state": state,
            "positive_count": positive,
            "negative_count": negative,
            "missing_symbols": [symbol for symbol in symbols if symbol not in {item['symbol'] for item in stocks}],
        },
    }


def latest_available(start: dt.date, symbols: list[str], timeout: int, lookback: int) -> dict[str, Any]:
    errors = []
    for offset in range(lookback + 1):
        date = start - dt.timedelta(days=offset)
        try:
            result = fetch_for_date(date, symbols, timeout)
            if result:
                return result
        except Exception as exc:
            errors.append(f"{date.isoformat()}: {exc}")
    raise RuntimeError("No official TWSE institutional data found. " + "; ".join(errors[-2:]))


def markdown(data: dict[str, Any]) -> str:
    market = data["market_net_100m_twd"]
    lines = [
        f"## 三大法人｜{data['query']['date']}",
        "",
        f"- 外資：{market.get('foreign', 0):+,.2f} 億元",
        f"- 投信：{market.get('trust', 0):+,.2f} 億元",
        f"- 自營商自行：{market.get('dealer_proprietary', 0):+,.2f} 億元",
        f"- 自營商避險：{market.get('dealer_hedging', 0):+,.2f} 億元",
        f"- 合計：{market.get('total', 0):+,.2f} 億元",
        "",
        "| 股票 | 外資(張) | 投信(張) | 自營商(張) | 合計(張) |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in data["per_symbol"]:
        lines.append(
            f"| {item['symbol']} {item['name']} | {item['foreign_net_lot']:+,.1f} | "
            f"{item['trust_net_lot']:+,.1f} | {item['dealer_net_lot']:+,.1f} | {item['total_net_lot']:+,.1f} |"
        )
    lines.extend(["", "## 結論", data["summary"]["state"]])
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Latest official TWSE institutional flows without persistence.")
    parser.add_argument("--stocks", required=True, help="Comma-separated Taiwan stock codes.")
    parser.add_argument("--date", help="Target date YYYY-MM-DD; defaults to today with fallback.")
    parser.add_argument("--lookback", type=int, default=7, help="Calendar days to search backwards.")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--timeout", type=int, default=10)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    symbols = list(dict.fromkeys("".join(ch for ch in value if ch.isdigit()) for value in args.stocks.split(",")))
    symbols = [symbol for symbol in symbols if symbol]
    if not symbols:
        raise SystemExit("No valid Taiwan stock symbols provided.")
    start = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    try:
        data = latest_available(start, symbols, args.timeout, max(0, args.lookback))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "storage": "none"}, ensure_ascii=False, indent=2))
        return 1
    print(markdown(data) if args.format == "markdown" else json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
