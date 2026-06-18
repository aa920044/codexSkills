#!/usr/bin/env python3
"""Compare Taiwan stock volume, institutional activity, and margin financing.

The script fetches data on demand from official TWSE endpoints. It does not
create a database or persist history.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any


TWSE_STOCK_DAY = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
TWSE_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86"
TWSE_MARGIN = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"


def fetch_json(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 realtime-tw-stock-snapshot/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def integer(value: Any) -> int:
    text = str(value or "0").replace(",", "").strip()
    return int(text or "0")


def roc_to_date(value: str) -> dt.date:
    year_text, month_text, day_text = value.split("/")
    return dt.date(int(year_text) + 1911, int(month_text), int(day_text))


def month_starts(end_date: dt.date, months: int) -> list[dt.date]:
    values: list[dt.date] = []
    year, month = end_date.year, end_date.month
    for _ in range(months):
        values.append(dt.date(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(values))


def fetch_stock_days(symbol: str, end_date: dt.date, months: int, timeout: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for month_start in month_starts(end_date, months):
        params = {
            "date": month_start.strftime("%Y%m%d"),
            "stockNo": symbol,
            "response": "json",
        }
        payload = fetch_json(f"{TWSE_STOCK_DAY}?{urllib.parse.urlencode(params)}", timeout)
        if payload.get("stat") != "OK":
            continue
        for row in payload.get("data") or []:
            date = roc_to_date(row[0])
            if date > end_date:
                continue
            output.append(
                {
                    "date": date.isoformat(),
                    "volume_shares": integer(row[1]),
                    "volume_lot": round(integer(row[1]) / 1000, 3),
                    "turnover_twd": integer(row[2]),
                    "open": float(row[3].replace(",", "")),
                    "high": float(row[4].replace(",", "")),
                    "low": float(row[5].replace(",", "")),
                    "close": float(row[6].replace(",", "")),
                    "change": float(row[7].replace(",", "").replace("X", "0")),
                    "trade_count": integer(row[8]),
                }
            )
        time.sleep(0.08)
    deduplicated = {row["date"]: row for row in output}
    return [deduplicated[key] for key in sorted(deduplicated)]


def fetch_t86(symbol: str, date: str, timeout: int) -> dict[str, Any] | None:
    compact_date = date.replace("-", "")
    params = {"date": compact_date, "selectType": "ALLBUT0999", "response": "json"}
    payload = fetch_json(f"{TWSE_T86}?{urllib.parse.urlencode(params)}", timeout)
    if payload.get("stat") != "OK":
        return None
    row = next((item for item in payload.get("data") or [] if item[0].strip() == symbol), None)
    if not row:
        return None

    foreign_buy = integer(row[2]) + integer(row[5])
    foreign_sell = integer(row[3]) + integer(row[6])
    trust_buy = integer(row[8])
    trust_sell = integer(row[9])
    dealer_buy = integer(row[12]) + integer(row[15])
    dealer_sell = integer(row[13]) + integer(row[16])
    return {
        "institutional_buy_shares": foreign_buy + trust_buy + dealer_buy,
        "institutional_sell_shares": foreign_sell + trust_sell + dealer_sell,
        "institutional_net_shares": integer(row[18]),
        "foreign_net_shares": foreign_buy - foreign_sell,
        "trust_net_shares": trust_buy - trust_sell,
        "dealer_net_shares": dealer_buy - dealer_sell,
    }


def fetch_margin(symbol: str, date: str, timeout: int) -> dict[str, Any] | None:
    compact_date = date.replace("-", "")
    params = {"date": compact_date, "selectType": "ALL", "response": "json"}
    payload = fetch_json(f"{TWSE_MARGIN}?{urllib.parse.urlencode(params)}", timeout)
    if payload.get("stat") != "OK":
        return None
    tables = payload.get("tables") or []
    if len(tables) < 2:
        return None
    row = next((item for item in tables[1].get("data") or [] if item[0].strip() == symbol), None)
    if not row:
        return None
    return {
        "margin_buy_lot": integer(row[2]),
        "margin_sell_lot": integer(row[3]),
        "margin_cash_repay_lot": integer(row[4]),
        "margin_previous_balance_lot": integer(row[5]),
        "margin_balance_lot": integer(row[6]),
        "short_sell_lot": integer(row[9]),
        "short_buy_lot": integer(row[10]),
        "short_balance_lot": integer(row[13]),
    }


def fetch_daily_aux(symbol: str, row: dict[str, Any], timeout: int) -> dict[str, Any]:
    date = row["date"]
    result = dict(row)
    try:
        result.update(fetch_t86(symbol, date, timeout) or {})
    except Exception as exc:
        result["institutional_error"] = str(exc)
    try:
        result.update(fetch_margin(symbol, date, timeout) or {})
    except Exception as exc:
        result["margin_error"] = str(exc)
    return result


def enrich_rows(symbol: str, rows: list[dict[str, Any]], timeout: int, workers: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_daily_aux, symbol, row, timeout) for row in rows]
        for future in as_completed(futures):
            output.append(future.result())
    output.sort(key=lambda item: item["date"])

    previous_close: float | None = None
    for row in output:
        if previous_close:
            row["change_percent"] = round((row["close"] - previous_close) / previous_close * 100, 2)
        else:
            row["change_percent"] = None
        previous_close = row["close"]

        volume_shares = row["volume_shares"]
        institutional_edges = row.get("institutional_buy_shares", 0) + row.get("institutional_sell_shares", 0)
        row["institutional_edge_ratio"] = (
            round(institutional_edges / (2 * volume_shares), 3) if volume_shares else None
        )
        row["institutional_net_volume_ratio"] = (
            round(row.get("institutional_net_shares", 0) / volume_shares, 3) if volume_shares else None
        )
        row["margin_buy_volume_ratio"] = (
            round(row.get("margin_buy_lot", 0) / row["volume_lot"], 3) if row["volume_lot"] else None
        )
        if "margin_balance_lot" in row and "margin_previous_balance_lot" in row:
            row["margin_balance_change_lot"] = row["margin_balance_lot"] - row["margin_previous_balance_lot"]
        else:
            row["margin_balance_change_lot"] = None
    return output


def period_rows(rows: list[dict[str, Any]], start: str, end: str) -> list[dict[str, Any]]:
    return [row for row in rows if start <= row["date"] <= end]


def average(values: list[float | int | None]) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    return statistics.mean(cleaned) if cleaned else None


def summarize_period(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"name": name, "days": 0}
    total_volume_shares = sum(row["volume_shares"] for row in rows)
    institutional_net_shares = sum(row.get("institutional_net_shares", 0) for row in rows)
    institutional_coverage = sum(1 for row in rows if "institutional_net_shares" in row)
    margin_coverage = sum(1 for row in rows if "margin_balance_lot" in row)
    return {
        "name": name,
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "days": len(rows),
        "average_volume_lot": round(average([row["volume_lot"] for row in rows]) or 0, 1),
        "average_trade_count": round(average([row["trade_count"] for row in rows]) or 0, 1),
        "average_institutional_edge_ratio": round(
            average([row.get("institutional_edge_ratio") for row in rows]) or 0, 3
        ),
        "institutional_net_lot": round(institutional_net_shares / 1000, 1),
        "institutional_net_volume_ratio": round(
            institutional_net_shares / total_volume_shares if total_volume_shares else 0, 3
        ),
        "institutional_coverage_days": institutional_coverage,
        "average_margin_buy_volume_ratio": round(
            average([row.get("margin_buy_volume_ratio") for row in rows]) or 0, 3
        ),
        "margin_balance_change_lot": sum(row.get("margin_balance_change_lot") or 0 for row in rows),
        "margin_coverage_days": margin_coverage,
        "price_change_percent": round((rows[-1]["close"] / rows[0]["open"] - 1) * 100, 2),
    }


def ignition_score(summary: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    if not summary.get("days") or not baseline.get("days"):
        return {"score": 0, "label": "insufficient-data", "signals": []}
    signals: list[str] = []
    score = 0
    baseline_volume = baseline.get("average_volume_lot") or 1
    volume_ratio = summary.get("average_volume_lot", 0) / baseline_volume
    if volume_ratio >= 1.5:
        score += 1
        signals.append("volume_expansion")
    if summary.get("margin_balance_change_lot", 0) > 0:
        score += 1
        signals.append("margin_balance_increase")
    if summary.get("average_margin_buy_volume_ratio", 0) >= 0.12:
        score += 1
        signals.append("high_margin_buy_ratio")
    if summary.get("price_change_percent", 0) >= 5:
        score += 1
        signals.append("rapid_price_increase")
    institutional_net_ratio = summary.get("institutional_net_volume_ratio", 0)
    if summary.get("institutional_net_lot", 0) > 0:
        signals.append("institutional_net_buy")
    if (
        volume_ratio >= 1.5
        and summary.get("price_change_percent", 0) >= 5
        and institutional_net_ratio >= 0.15
        and summary.get("margin_balance_change_lot", 0) <= 0
    ):
        label = "法人方向性點火，非融資主導"
    elif score >= 3:
        label = "可能融資點火"
    elif score >= 2:
        label = "多方資金共同放大"
    else:
        label = "接近常態"
    return {"score": score, "label": label, "signals": signals, "volume_ratio_vs_baseline": round(volume_ratio, 2)}


def markdown(data: dict[str, Any]) -> str:
    lines = [
        "## 結構結論",
        data["conclusion"],
        "",
        "## 期間比較",
        "| 期間 | 天數 | 均量 | 法人交易邊占比 | 法人淨買賣 | 法人淨額/總量 | 融資買進占比 | 融資餘額變化 | 價格變化 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in data["periods"]:
        lines.append(
            f"| {item.get('name')} | {item.get('days', 0)} | {item.get('average_volume_lot', '-'):,.0f} 張 | "
            f"{(item.get('average_institutional_edge_ratio', 0) * 100):.1f}% | "
            f"{item.get('institutional_net_lot', 0):,.0f} 張 | "
            f"{(item.get('institutional_net_volume_ratio', 0) * 100):.1f}% | "
            f"{(item.get('average_margin_buy_volume_ratio', 0) * 100):.1f}% | "
            f"{item.get('margin_balance_change_lot', 0):,} 張 | "
            f"{item.get('price_change_percent', 0):.2f}% |"
        )
    lines.extend(
        [
            "",
            "## 點火判斷",
            f"- 異常期標籤：{data['ignition']['label']}",
            f"- 分數：{data['ignition']['score']} / 4",
            f"- 相對常態量：{data['ignition'].get('volume_ratio_vs_baseline', 0):.2f} 倍",
            f"- 訊號：{', '.join(data['ignition'].get('signals', [])) or '-'}",
            f"- 異常期法人資料覆蓋：{data['periods'][1].get('institutional_coverage_days', 0)} / {data['periods'][1].get('days', 0)} 日",
            f"- 異常期融資資料覆蓋：{data['periods'][1].get('margin_coverage_days', 0)} / {data['periods'][1].get('days', 0)} 日",
            "",
            "## 限制",
            "- 法人交易邊占比是估算值；法人對法人交易可能在買賣兩側重複計入。",
            "- 融資增加代表信用資金增加，不等於可識別的特定主力。",
            "- 僅靠公開日資料不能證明散戶、主力或法人之間的協同行為。",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Taiwan stock participation structures.")
    parser.add_argument("--stock", required=True, help="Taiwan stock code, e.g. 3231.")
    parser.add_argument("--months", type=int, default=3, help="Calendar months to fetch.")
    parser.add_argument("--baseline-start", help="Baseline period start YYYY-MM-DD.")
    parser.add_argument("--baseline-end", help="Baseline period end YYYY-MM-DD.")
    parser.add_argument("--event-start", required=True, help="Event period start YYYY-MM-DD.")
    parser.add_argument("--event-end", required=True, help="Event period end YYYY-MM-DD.")
    parser.add_argument("--recent-days", type=int, default=3, help="Number of latest trading days to compare.")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    end_date = dt.date.today()
    stock_rows = fetch_stock_days(args.stock, end_date, args.months, args.timeout)
    if not stock_rows:
        raise SystemExit("No official TWSE daily data returned.")

    rows = enrich_rows(args.stock, stock_rows, args.timeout, max(1, min(args.workers, 6)))
    baseline_start = args.baseline_start or rows[0]["date"]
    baseline_end = args.baseline_end or (
        (dt.date.fromisoformat(args.event_start) - dt.timedelta(days=1)).isoformat()
    )
    baseline_rows = period_rows(rows, baseline_start, baseline_end)
    event_rows = period_rows(rows, args.event_start, args.event_end)
    recent_rows = rows[-args.recent_days :]

    baseline = summarize_period("三個月常態期", baseline_rows)
    event = summarize_period("指定異常期", event_rows)
    recent = summarize_period(f"最近{len(recent_rows)}日", recent_rows)
    ignition = ignition_score(event, baseline)

    conclusion = (
        f"{args.stock} 的指定期間標記為「{ignition['label']}」。"
        f"異常期均量約為常態的 {ignition.get('volume_ratio_vs_baseline', 0):.2f} 倍；"
        "是否屬融資點火需同時看到融資餘額增加、融資買進占比升高與價格快速上漲。"
    )
    output = {
        "query": {
            "stock": args.stock,
            "months": args.months,
            "event_start": args.event_start,
            "event_end": args.event_end,
            "recent_days": args.recent_days,
            "storage": "none",
        },
        "periods": [baseline, event, recent],
        "ignition": ignition,
        "conclusion": conclusion,
        "daily": rows,
    }
    print(markdown(output) if args.format == "markdown" else json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
