#!/usr/bin/env python3
"""Approximate price-band volume profile for Taiwan stocks.

This uses official TWSE daily OHLCV data and distributes each day's volume
across overlapped price bands. It is an estimate, not tick-level cost data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import urllib.parse
import urllib.request
from typing import Any


TWSE_STOCK_DAY = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"


def fetch_json(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 volume-profile/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def integer(value: Any) -> int:
    return int(str(value or "0").replace(",", "").strip() or "0")


def roc_to_date(value: str) -> dt.date:
    y, m, d = value.split("/")
    return dt.date(int(y) + 1911, int(m), int(d))


def month_starts(start: dt.date, end: dt.date) -> list[dt.date]:
    values: list[dt.date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        values.append(dt.date(year, month, 1))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return values


def fetch_stock_days(symbol: str, start: dt.date, end: dt.date, timeout: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for month_start in month_starts(start, end):
        params = {"date": month_start.strftime("%Y%m%d"), "stockNo": symbol, "response": "json"}
        payload = fetch_json(f"{TWSE_STOCK_DAY}?{urllib.parse.urlencode(params)}", timeout)
        if payload.get("stat") != "OK":
            continue
        for row in payload.get("data") or []:
            date = roc_to_date(row[0])
            if start <= date <= end:
                rows.append(
                    {
                        "date": date.isoformat(),
                        "volume_lot": integer(row[1]) / 1000,
                        "open": float(row[3].replace(",", "")),
                        "high": float(row[4].replace(",", "")),
                        "low": float(row[5].replace(",", "")),
                        "close": float(row[6].replace(",", "")),
                        "trade_count": integer(row[8]),
                    }
                )
    dedup = {row["date"]: row for row in rows}
    return [dedup[key] for key in sorted(dedup)]


def make_bins(low: float, high: float, step: float) -> list[dict[str, float]]:
    start = math.floor(low / step) * step
    end = math.ceil(high / step) * step
    bins = []
    value = start
    while value < end:
        bins.append({"low": round(value, 4), "high": round(value + step, 4), "volume_lot": 0.0})
        value += step
    return bins


def allocate_volume(rows: list[dict[str, Any]], step: float) -> list[dict[str, Any]]:
    if not rows:
        return []
    bins = make_bins(min(row["low"] for row in rows), max(row["high"] for row in rows), step)
    for row in rows:
        day_low = row["low"]
        day_high = row["high"]
        day_range = max(day_high - day_low, step)
        for item in bins:
            overlap = max(0.0, min(day_high, item["high"]) - max(day_low, item["low"]))
            if overlap > 0:
                item["volume_lot"] += row["volume_lot"] * (overlap / day_range)
            elif day_high == day_low and item["low"] <= day_high < item["high"]:
                item["volume_lot"] += row["volume_lot"]
    for item in bins:
        item["volume_lot"] = round(item["volume_lot"], 1)
    return bins


def summarize(rows: list[dict[str, Any]], bins: list[dict[str, Any]], current_price: float | None) -> dict[str, Any]:
    total_volume = sum(row["volume_lot"] for row in rows)
    above_volume = 0.0
    below_volume = 0.0
    if current_price is not None:
        for item in bins:
            mid = (item["low"] + item["high"]) / 2
            if mid > current_price:
                above_volume += item["volume_lot"]
            else:
                below_volume += item["volume_lot"]
    top_bins = sorted(bins, key=lambda item: item["volume_lot"], reverse=True)[:5]
    return {
        "days": len(rows),
        "total_volume_lot": round(total_volume, 1),
        "current_price": current_price,
        "estimated_above_price_volume_lot": round(above_volume, 1),
        "estimated_above_price_ratio": round(above_volume / total_volume, 3) if total_volume else None,
        "estimated_at_or_below_price_volume_lot": round(below_volume, 1),
        "top_volume_bins": top_bins,
    }


def markdown(data: dict[str, Any]) -> str:
    summary = data["summary"]
    lines = [
        "## 區間成交結構",
        data["conclusion"],
        "",
        "## 摘要",
        "| 項目 | 數值 |",
        "|---|---:|",
        f"| 期間 | {data['query']['start']} ~ {data['query']['end']} |",
        f"| 交易日數 | {summary['days']} |",
        f"| 區間總量 | {summary['total_volume_lot']:,.0f} 張 |",
        f"| 目前參考價 | {summary['current_price'] if summary['current_price'] is not None else '-'} |",
        f"| 估計上方成交量 | {summary['estimated_above_price_volume_lot']:,.0f} 張 |",
        f"| 上方成交量占比 | {(summary['estimated_above_price_ratio'] or 0) * 100:.1f}% |",
        "",
        "## 最大成交價格帶",
        "| 價格帶 | 估計成交量 |",
        "|---|---:|",
    ]
    for item in summary["top_volume_bins"]:
        lines.append(f"| {item['low']:g} ~ {item['high']:g} | {item['volume_lot']:,.0f} 張 |")
    lines.extend(
        [
            "",
            "## 限制",
            "- 這是日K高低區間分配估算，不是逐筆成交或真實持倉成本。",
            "- 若價格直上直下，估算能判斷是否有長時間平台，但不能辨識誰被套牢。",
            "- 需要搭配法人、融資與成交筆數判讀。",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estimate price-band volume profile from TWSE daily data.")
    parser.add_argument("--stock", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--current-price", type=float)
    parser.add_argument("--step", type=float, default=5.0, help="Price band width.")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--timeout", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    rows = fetch_stock_days(args.stock, start, end, args.timeout)
    bins = allocate_volume(rows, args.step)
    summary = summarize(rows, bins, args.current_price)
    ratio = summary.get("estimated_above_price_ratio")
    if ratio is None:
        conclusion = "缺少目前參考價，僅提供區間成交量分布。"
    elif ratio >= 0.45:
        conclusion = "目前參考價上方仍有較厚成交區，可能存在明顯壓力。"
    elif ratio >= 0.25:
        conclusion = "目前參考價上方有中等成交區，壓力存在但不算極厚。"
    else:
        conclusion = "目前參考價上方估計成交量不厚，壓力更可能來自主動賣盤而非平台套牢。"
    output = {
        "query": {
            "stock": args.stock,
            "start": args.start,
            "end": args.end,
            "step": args.step,
            "storage": "none",
        },
        "summary": summary,
        "bins": bins,
        "daily": rows,
        "conclusion": conclusion,
    }
    print(markdown(output) if args.format == "markdown" else json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
