#!/usr/bin/env python3
"""USD/TWD noon snapshot series.

No database is used. Optional JSON logs are written only with --save-log.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/USDTWD=X"
TAIPEI = dt.timezone(dt.timedelta(hours=8))


def now_taipei() -> dt.datetime:
    return dt.datetime.now(TAIPEI)


def parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("--target-time must use HH:MM, e.g. 12:00") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("--target-time must be a valid HH:MM time")
    return hour, minute


def yahoo_range(days: int) -> str:
    if days <= 0:
        raise ValueError("--days must be positive")
    return f"{days}d"


def fetch_yahoo_hourly(days: int, timeout: int) -> dict[str, Any]:
    params = {
        "range": yahoo_range(days),
        "interval": "60m",
        "includePrePost": "true",
        "_": str(int(time.time() * 1000)),
    }
    url = f"{YAHOO_CHART_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 realtime-tw-stock-snapshot/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    error = (payload.get("chart") or {}).get("error")
    if error:
        raise RuntimeError(error.get("description") or str(error))
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError("Yahoo chart returned no result")
    return result


def build_hourly_points(result: dict[str, Any]) -> list[dict[str, Any]]:
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    points: list[dict[str, Any]] = []
    for timestamp, close in zip(timestamps, closes):
        if close is None:
            continue
        observed_at = dt.datetime.fromtimestamp(int(timestamp), TAIPEI)
        points.append(
            {
                "observed_at": observed_at,
                "date": observed_at.date().isoformat(),
                "time": observed_at.strftime("%H:%M"),
                "rate": float(close),
            }
        )
    return points


def nearest_noon_series(
    points: list[dict[str, Any]],
    target_time: str,
    max_minutes_from_target: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target_hour, target_minute = parse_hhmm(target_time)
    by_date: dict[str, list[dict[str, Any]]] = {}
    for point in points:
        by_date.setdefault(point["date"], []).append(point)

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    previous_rate: float | None = None
    for date_text in sorted(by_date):
        target = dt.datetime.fromisoformat(date_text).replace(
            hour=target_hour,
            minute=target_minute,
            tzinfo=TAIPEI,
        )
        candidates = sorted(
            by_date[date_text],
            key=lambda item: abs((item["observed_at"] - target).total_seconds()),
        )
        if not candidates:
            continue
        selected = candidates[0]
        minutes_from_target = int(round((selected["observed_at"] - target).total_seconds() / 60))
        if abs(minutes_from_target) > max_minutes_from_target:
            skipped.append(
                {
                    "date": date_text,
                    "target_time": target_time,
                    "nearest_observed_time": selected["time"],
                    "minutes_from_target": minutes_from_target,
                    "reason": "nearest observation too far from target time",
                }
            )
            continue
        rate = selected["rate"]
        change = None if previous_rate is None else rate - previous_rate
        change_percent = None if previous_rate in {None, 0} else change / previous_rate * 100
        rows.append(
            {
                "date": date_text,
                "target_time": target_time,
                "observed_time": selected["time"],
                "minutes_from_target": minutes_from_target,
                "rate": round(rate, 4),
                "change": round(change, 4) if change is not None else None,
                "change_percent": round(change_percent, 3) if change_percent is not None else None,
            }
        )
        previous_rate = rate
    return rows, skipped


def summarize(rows: list[dict[str, Any]], flat_threshold: float) -> dict[str, Any]:
    rates = [row["rate"] for row in rows if row.get("rate") is not None]
    if not rates:
        return {
            "state": "unavailable",
            "summary": "No USD/TWD noon values were available.",
            "latest_rate": None,
            "range": None,
            "net_change": None,
            "net_change_percent": None,
        }

    latest = rates[-1]
    first = rates[0]
    net_change = latest - first
    net_change_percent = net_change / first * 100 if first else None
    rate_range = max(rates) - min(rates)
    if abs(net_change_percent or 0) <= flat_threshold:
        state = "台幣匯率橫向"
    elif net_change < 0:
        state = "台幣偏升值"
    else:
        state = "台幣偏貶值"

    summary = (
        f"USD/TWD noon series latest {latest:.4f}; "
        f"net change {net_change:+.4f} ({net_change_percent:+.2f}%) across {len(rates)} observations."
    )
    return {
        "state": state,
        "summary": summary,
        "latest_rate": round(latest, 4),
        "first_rate": round(first, 4),
        "high": round(max(rates), 4),
        "low": round(min(rates), 4),
        "range": round(rate_range, 4),
        "net_change": round(net_change, 4),
        "net_change_percent": round(net_change_percent, 3) if net_change_percent is not None else None,
    }


def build_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    result = fetch_yahoo_hourly(args.days, args.timeout)
    points = build_hourly_points(result)
    rows, skipped = nearest_noon_series(points, args.target_time, args.max_minutes_from_target)
    if args.limit:
        rows = rows[-args.limit :]
    summary = summarize(rows, args.flat_threshold_percent)
    return {
        "query": {
            "pair": "USD/TWD",
            "symbol": "USDTWD=X",
            "days": args.days,
            "target_time": args.target_time,
            "time_zone": "Asia/Taipei",
            "query_time": now_taipei().isoformat(timespec="seconds"),
            "storage": "json-log" if args.save_log else "none",
        },
        "source": {
            "name": "Yahoo Finance chart",
            "url": YAHOO_CHART_URL,
            "interval": "60m",
            "note": "Intraday reference series, not an official central bank fixing.",
        },
        "series": rows,
        "skipped_dates": skipped,
        "summary": summary,
        "conclusion": {
            "state": summary["state"],
            "confidence": "medium" if rows else "low",
            "summary": summary["summary"],
            "watch_points": [
                "台幣明顯升值加上外資買超，較像新增外資流入。",
                "台幣橫向加上權值內輪動，較像場內資金切換。",
                "台幣貶值但指數上漲時，要檢查是否少數權值撐盤。",
            ],
        },
    }


def save_log(snapshot: dict[str, Any]) -> pathlib.Path:
    today = now_taipei().strftime("%Y-%m-%d")
    stamp = now_taipei().strftime("%H%M%S")
    directory = LOG_DIR / today
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"usdtwd_noon_{stamp}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2)
    return path


def format_number(value: Any, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        text = f"{value:,.4f}".rstrip("0").rstrip(".")
        return f"{text}{suffix}"
    return f"{value}{suffix}"


def to_markdown(snapshot: dict[str, Any]) -> str:
    summary = snapshot["summary"]
    conclusion = snapshot["conclusion"]
    lines = [
        "## 匯率結論",
        conclusion["summary"],
        "",
        "## 連續中午值",
        "| 日期 | 目標時間 | 實際時間 | USD/TWD | 日變化 | 日變化% |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in snapshot["series"]:
        lines.append(
            f"| {row['date']} | {row['target_time']} | {row['observed_time']} | "
            f"{format_number(row['rate'])} | {format_number(row['change'])} | "
            f"{format_number(row['change_percent'], '%')} |"
        )
    lines.extend(
        [
            "",
            "## 區間摘要",
            "| 欄位 | 數值 |",
            "|---|---:|",
            f"| 狀態 | {summary.get('state')} |",
            f"| 最新 | {format_number(summary.get('latest_rate'))} |",
            f"| 最高 | {format_number(summary.get('high'))} |",
            f"| 最低 | {format_number(summary.get('low'))} |",
            f"| 區間 | {format_number(summary.get('range'))} |",
            f"| 淨變化 | {format_number(summary.get('net_change'))} |",
            f"| 淨變化% | {format_number(summary.get('net_change_percent'), '%')} |",
            "",
            "## 觀察點",
        ]
    )
    for index, point in enumerate(conclusion["watch_points"], start=1):
        lines.append(f"{index}. {point}")
    lines.extend(["", f"資料源：{snapshot['source']['name']}，{snapshot['source']['note']}"])
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="USD/TWD noon series without persistence.")
    parser.add_argument("--days", type=int, default=10, help="Yahoo chart lookback in calendar days.")
    parser.add_argument("--limit", type=int, help="Keep only the latest N noon observations.")
    parser.add_argument("--target-time", default="12:00", help="Target Taipei time, HH:MM.")
    parser.add_argument(
        "--max-minutes-from-target",
        type=int,
        default=90,
        help="Skip a date when the nearest observation is farther than this many minutes from target time.",
    )
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument(
        "--flat-threshold-percent",
        type=float,
        default=0.25,
        help="Absolute net-change percent treated as sideways.",
    )
    parser.add_argument("--save-log", action="store_true", help="Optionally write one JSON log under logs/.")
    parser.add_argument("--timeout", type=int, default=8, help="Network timeout in seconds.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        snapshot = build_snapshot(args)
        if args.save_log:
            snapshot["query"]["log_path"] = str(save_log(snapshot))
    except Exception as exc:
        error = {
            "query": {
                "pair": "USD/TWD",
                "query_time": now_taipei().isoformat(timespec="seconds"),
                "storage": "none",
            },
            "source": {"name": "Yahoo Finance chart"},
            "series": [],
            "skipped_dates": [],
            "summary": {"state": "查詢失敗", "summary": str(exc)},
            "conclusion": {
                "state": "查詢失敗",
                "confidence": "low",
                "summary": str(exc),
                "watch_points": ["檢查網路連線", "縮短 --days", "改用 json 確認錯誤訊息"],
            },
        }
        print(json.dumps(error, ensure_ascii=False, indent=2))
        return 1

    if args.format == "markdown":
        print(to_markdown(snapshot))
    else:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
