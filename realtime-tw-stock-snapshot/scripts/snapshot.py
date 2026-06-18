#!/usr/bin/env python3
"""Realtime Taiwan stock snapshot.

No database is used. Optional JSON logs are written only with --save-log.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import sys
import time
import urllib.parse
import urllib.request
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
LOG_DIR = ROOT / "logs"
TWSE_MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TWSE_FMTQIK_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"


def now_taipei() -> dt.datetime:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))


def load_json(path: pathlib.Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in {"", "-", "--", "NaN"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    number = parse_number(value)
    if number is None or math.isnan(number):
        return None
    return int(number)


def split_book(value: Any, numeric: bool = True) -> list[Any]:
    if value is None:
        return []
    items = [item for item in str(value).split("_") if item not in {"", "-"}]
    if numeric:
        return [parse_number(item) for item in items if parse_number(item) is not None]
    return items


def normalize_symbol(symbol: str) -> str:
    digits = "".join(ch for ch in symbol.strip() if ch.isdigit())
    if not digits:
        raise ValueError(f"Invalid Taiwan stock symbol: {symbol!r}")
    return digits


def build_ex_ch(symbols: list[str]) -> str:
    channels: list[str] = []
    for symbol in symbols:
        channels.append(f"tse_{symbol}.tw")
        channels.append(f"otc_{symbol}.tw")
    return "|".join(channels)


def fetch_twse_mis(symbols: list[str], timeout: int = 8) -> list[dict[str, Any]]:
    params = {
        "ex_ch": build_ex_ch(symbols),
        "json": "1",
        "delay": "0",
        "_": str(int(time.time() * 1000)),
    }
    url = f"{TWSE_MIS_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 realtime-tw-stock-snapshot/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8-sig")
    payload = json.loads(raw)
    if payload.get("rtmessage") not in {None, "OK"} and payload.get("rtcode") not in {None, "0000"}:
        raise RuntimeError(f"TWSE MIS returned {payload.get('rtmessage') or payload.get('rtcode')}")
    rows = payload.get("msgArray") or []
    return [row for row in rows if row.get("c") in set(symbols)]


def fetch_recent_market_turnover(timeout: int = 8) -> list[dict[str, Any]]:
    today = now_taipei().strftime("%Y%m%d")
    url = f"{TWSE_FMTQIK_URL}?{urllib.parse.urlencode({'date': today, 'response': 'json'})}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 realtime-tw-stock-snapshot/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8-sig"))
    if payload.get("stat") != "OK":
        raise RuntimeError(f"TWSE FMTQIK returned {payload.get('stat')}")
    rows = []
    for row in payload.get("data") or []:
        if len(row) < 3:
            continue
        turnover_twd = parse_number(row[2])
        if turnover_twd is None:
            continue
        rows.append(
            {
                "date": row[0],
                "turnover_twd": int(turnover_twd),
                "turnover_billion": round(turnover_twd / 100_000_000, 2),
            }
        )
    return rows


def trading_progress(at_time: dt.datetime) -> float:
    minutes = at_time.hour * 60 + at_time.minute + at_time.second / 60
    start = 9 * 60
    end = 13 * 60 + 30
    if minutes <= start:
        return 0.0
    if minutes >= end:
        return 1.0
    return (minutes - start) / (end - start)


def build_market_turnover_context(
    current_billion: float | None,
    observed_time: str | None,
    baseline_override_billion: float | None,
    rules: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    lookback = int(rules.get("market_turnover_lookback_days", 5))
    history: list[dict[str, Any]] = []
    source_status = "official-history"
    try:
        history = fetch_recent_market_turnover(timeout=timeout)
    except Exception as exc:
        source_status = f"history-unavailable: {exc}"

    completed_history = history[-lookback:] if history else []
    history_values = [row["turnover_billion"] for row in completed_history]
    if baseline_override_billion is not None:
        baseline = float(baseline_override_billion)
        baseline_source = "manual"
    elif history_values:
        sorted_values = sorted(history_values)
        midpoint = len(sorted_values) // 2
        baseline = (
            sorted_values[midpoint]
            if len(sorted_values) % 2
            else (sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2
        )
        baseline_source = f"TWSE recent {len(history_values)}-day median"
    else:
        baseline = None
        baseline_source = "unavailable"

    now = now_taipei()
    observation = now
    if observed_time:
        try:
            hour_text, minute_text = observed_time.split(":", 1)
            observation = now.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)
        except (ValueError, TypeError):
            raise ValueError("--market-turnover-time must use HH:MM, e.g. 12:00")
    progress = trading_progress(observation)
    projected_close = None
    projected_ratio = None
    status = "缺少盤中成交值"
    if current_billion is not None and progress > 0:
        projected_close = float(current_billion) / progress
        if baseline:
            projected_ratio = projected_close / baseline
            low_ratio = float(rules.get("market_turnover_low_ratio", 0.85))
            high_ratio = float(rules.get("market_turnover_high_ratio", 1.15))
            if projected_ratio < low_ratio:
                status = "相對縮量"
            elif projected_ratio > high_ratio:
                status = "相對放量"
            else:
                status = "接近近期常態"

    return {
        "current_turnover_billion": float(current_billion) if current_billion is not None else None,
        "query_time": now.isoformat(timespec="seconds"),
        "observed_time": observation.isoformat(timespec="minutes") if current_billion is not None else None,
        "trading_progress": round(progress, 4),
        "projected_close_billion": round(projected_close, 2) if projected_close is not None else None,
        "recent_baseline_billion": round(baseline, 2) if baseline is not None else None,
        "projected_vs_baseline_ratio": round(projected_ratio, 3) if projected_ratio is not None else None,
        "status": status,
        "baseline_source": baseline_source,
        "history_source": source_status,
        "recent_history": completed_history,
        "projection_method": "linear by trading-session progress; intraday estimate only",
    }


def mock_rows(symbols: list[str]) -> list[dict[str, Any]]:
    names = {
        "2330": "台積電",
        "3231": "緯創",
        "2317": "鴻海",
        "2382": "廣達",
        "2356": "英業達",
        "2324": "仁寶",
    }
    base = {
        "2330": (1170.0, 1135.0, 1165.0, 1180.0, 1160.0, 25021),
        "3231": (189.5, 191.0, 192.0, 194.0, 188.5, 105000),
        "2317": (218.0, 214.0, 215.5, 220.0, 214.5, 68000),
        "2382": (302.5, 296.0, 298.0, 305.0, 297.0, 42000),
        "2356": (58.4, 59.1, 59.0, 59.6, 58.1, 36000),
        "2324": (41.2, 41.0, 41.1, 41.8, 40.9, 22000),
    }
    rows = []
    for symbol in symbols:
        price, prev, open_, high, low, vol = base.get(symbol, (100.0, 99.0, 99.5, 101.0, 98.5, 12000))
        rows.append(
            {
                "c": symbol,
                "n": names.get(symbol, symbol),
                "ex": "tse",
                "z": str(price),
                "y": str(prev),
                "o": str(open_),
                "h": str(high),
                "l": str(low),
                "v": str(vol),
                "tv": "200",
                "b": f"{price - 0.5}_{price - 1.0}_",
                "a": f"{price}_{price + 0.5}_",
                "g": "120_95_",
                "f": "80_140_",
                "t": "10:12:00",
                "d": now_taipei().strftime("%Y%m%d"),
                "tlong": str(int(now_taipei().timestamp() * 1000)),
            }
        )
    return rows


def normalize_quote(row: dict[str, Any]) -> dict[str, Any]:
    bid_prices = split_book(row.get("b"))
    ask_prices = split_book(row.get("a"))
    last_trade_price = parse_number(row.get("z")) or parse_number(row.get("pz"))
    price_source = "last_trade"
    price = last_trade_price
    if price is None and bid_prices and ask_prices:
        price = round((bid_prices[0] + ask_prices[0]) / 2, 4)
        price_source = "best_bid_ask_midpoint"
    previous_close = parse_number(row.get("y"))
    change = price - previous_close if price is not None and previous_close is not None else None
    change_percent = (change / previous_close * 100) if change is not None and previous_close else None
    return {
        "symbol": row.get("c"),
        "name": row.get("n"),
        "exchange": row.get("ex"),
        "price": price,
        "price_source": price_source if price is not None else "unavailable",
        "last_trade_price": last_trade_price,
        "change": round(change, 4) if change is not None else None,
        "change_percent": round(change_percent, 2) if change_percent is not None else None,
        "open": parse_number(row.get("o")),
        "high": parse_number(row.get("h")),
        "low": parse_number(row.get("l")),
        "previous_close": previous_close,
        "volume_lot": parse_int(row.get("v")),
        "last_tick_volume_lot": parse_int(row.get("tv")),
        "bid_prices": bid_prices,
        "ask_prices": ask_prices,
        "bid_sizes": [parse_int(item) for item in split_book(row.get("g"), numeric=False)],
        "ask_sizes": [parse_int(item) for item in split_book(row.get("f"), numeric=False)],
        "data_date": row.get("d"),
        "data_time": row.get("t"),
    }


def derive_quote_state(quote: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    price = quote.get("price")
    open_ = quote.get("open")
    high = quote.get("high")
    low = quote.get("low")
    volume = quote.get("volume_lot") or 0
    change_percent = quote.get("change_percent")
    heavy_volume_lot = volume_threshold(quote, rules)
    is_heavy_volume = volume >= heavy_volume_lot

    range_position = None
    if price is not None and high is not None and low is not None and high != low:
        range_position = (price - low) / (high - low)

    price_vs_open = "unknown"
    if price is not None and open_ is not None:
        price_vs_open = "above" if price > open_ else "below" if price < open_ else "equal"

    tags: list[str] = []
    state = "盤中觀察"
    if range_position is not None:
        if range_position >= rules.get("range_position_high", 0.65) and price_vs_open != "below":
            state = "高檔換手觀察" if is_heavy_volume else "偏多守高"
            tags.append(state)
        elif range_position <= rules.get("range_position_low", 0.35) and price_vs_open == "below":
            if is_heavy_volume:
                state = "量增轉弱" if (change_percent or 0) > -rules.get("large_move_percent", 2.0) else "量增下殺"
            else:
                state = "低檔轉弱" if (change_percent or 0) > -rules.get("large_move_percent", 2.0) else "低檔陰跌"
            tags.append(state)
        else:
            state = "區間震盪"
            tags.append(state)

    if change_percent is not None and change_percent <= -rules.get("large_move_percent", 2.0):
        tags.append("跌幅擴大")
    elif change_percent is not None and change_percent >= rules.get("large_move_percent", 2.0):
        tags.append("漲幅擴大")

    return {
        "range_position": round(range_position, 2) if range_position is not None else None,
        "price_vs_open": price_vs_open,
        "volume_signal": "heavy" if is_heavy_volume else "normal",
        "heavy_volume_lot": heavy_volume_lot,
        "intraday_state": state,
        "risk_tags": list(dict.fromkeys(tags)),
    }


def sector_summary(sector_name: str | None, quotes: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    if not sector_name:
        return {"name": None, "rank": None, "status": None, "leaders": [], "laggards": []}
    ranked = sorted(
        [q for q in quotes if q.get("change_percent") is not None],
        key=lambda q: q["change_percent"],
        reverse=True,
    )
    if not ranked:
        return {"name": sector_name, "rank": None, "status": "無有效即時報價", "leaders": [], "laggards": []}
    avg = sum(q["change_percent"] for q in ranked) / len(ranked)
    status = "族群強於大盤假設值" if avg >= rules.get("strong_sector_avg_percent", 1.0) else "族群偏弱" if avg <= rules.get("weak_sector_avg_percent", -1.0) else "族群震盪分歧"
    return {
        "name": sector_name,
        "rank": None,
        "status": status,
        "average_change_percent": round(avg, 2),
        "leaders": [q["symbol"] for q in ranked[:2]],
        "laggards": [q["symbol"] for q in ranked[-2:]],
    }


def spread_value(quote: dict[str, Any]) -> float | None:
    bids = quote.get("bid_prices") or []
    asks = quote.get("ask_prices") or []
    if not bids or not asks:
        return None
    return round(asks[0] - bids[0], 4)


def volume_threshold(quote: dict[str, Any], rules: dict[str, Any]) -> int:
    symbol = str(quote.get("symbol") or "")
    by_symbol = rules.get("heavy_volume_lot_by_symbol") or {}
    return int(by_symbol.get(symbol, rules.get("default_heavy_volume_lot", 50000)))


def classify_symbol(quote: dict[str, Any], derived: dict[str, Any]) -> str:
    change_percent = quote.get("change_percent")
    range_position = derived.get("range_position")
    price_vs_open = derived.get("price_vs_open")
    is_heavy_volume = derived.get("volume_signal") == "heavy"
    if range_position is None:
        return "盤中觀察"
    if price_vs_open == "above" and range_position >= 0.9 and (change_percent or 0) >= 5:
        return "強勢高檔換手" if is_heavy_volume else "強勢守高"
    if price_vs_open == "above" and range_position >= 0.75:
        return "高檔換手觀察" if is_heavy_volume else "偏多守高"
    if price_vs_open == "below" and range_position <= 0.35:
        if is_heavy_volume:
            return "量增轉弱" if (change_percent or 0) > -2 else "量增下殺"
        return "低檔轉弱" if (change_percent or 0) > -2 else "低檔陰跌"
    if price_vs_open == "above":
        return "偏多震盪"
    return "區間震盪"


def risk_note(quote: dict[str, Any], item: dict[str, Any]) -> str:
    open_price = quote.get("open")
    low = quote.get("low")
    state = item.get("state")
    if state in {"強勢高檔換手", "強勢守高"}:
        return "接近高點，留意爆量不漲"
    if state == "高檔換手觀察" and open_price is not None:
        return f"若跌回 {format_number(open_price)} 附近轉弱"
    if state in {"量增轉弱", "量增下殺", "低檔轉弱", "低檔陰跌"} and low is not None:
        return f"若跌破 {format_number(low)} 壓力升高"
    return "觀察是否守住開盤價"


def build_per_symbol(quotes: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for quote in quotes:
        derived = derive_quote_state(quote, rules)
        state = classify_symbol(quote, derived)
        item = {
            "symbol": quote.get("symbol"),
            "name": quote.get("name"),
            "change_percent": quote.get("change_percent"),
            "volume_lot": quote.get("volume_lot"),
            "range_position": derived.get("range_position"),
            "price_vs_open": derived.get("price_vs_open"),
            "volume_signal": derived.get("volume_signal"),
            "heavy_volume_lot": derived.get("heavy_volume_lot"),
            "spread": spread_value(quote),
            "state": state,
            "risk": "",
            "derived": derived,
        }
        item["risk"] = risk_note(quote, item)
        items.append(item)
    return items


def group_summary(per_symbol: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    total = len(per_symbol)
    if total == 0:
        return {
            "above_open_count": 0,
            "high_position_count": 0,
            "large_gain_count": 0,
            "high_turnover_count": 0,
            "consistency": "none",
            "state": "查無有效報價",
            "leader": None,
            "laggard": None,
        }

    above_open = [item for item in per_symbol if item.get("price_vs_open") == "above"]
    high_position = [item for item in per_symbol if (item.get("range_position") or 0) >= 0.75]
    large_gain = [item for item in per_symbol if (item.get("change_percent") or 0) >= rules.get("large_move_percent", 2.0)]
    high_turnover = [item for item in per_symbol if "高檔換手" in (item.get("state") or "")]
    heavy_volume = [item for item in per_symbol if item.get("volume_signal") == "heavy"]
    heavy_weak = [item for item in per_symbol if item.get("volume_signal") == "heavy" and "量增" in (item.get("state") or "")]
    ranked = sorted(
        [item for item in per_symbol if item.get("change_percent") is not None],
        key=lambda item: item["change_percent"],
        reverse=True,
    )

    above_ratio = len(above_open) / total
    high_ratio = len(high_position) / total
    if above_ratio >= 0.7 and high_ratio >= 0.7:
        state = "族群高檔換手"
        consistency = "strong"
    elif len(large_gain) / total >= 0.5 and high_ratio < 0.5:
        state = "漲多分歧"
        consistency = "mixed"
    elif above_ratio < 0.5 and high_ratio < 0.5:
        state = "量增轉弱" if len(heavy_weak) / total >= 0.5 else "族群低檔轉弱"
        consistency = "weak"
    elif ranked and len(high_position) == 1:
        state = "單檔硬撐"
        consistency = "mixed"
    else:
        state = "族群震盪分歧"
        consistency = "mixed"

    return {
        "above_open_count": len(above_open),
        "high_position_count": len(high_position),
        "large_gain_count": len(large_gain),
        "high_turnover_count": len(high_turnover),
        "heavy_volume_count": len(heavy_volume),
        "consistency": consistency,
        "state": state,
        "leader": ranked[0]["symbol"] if ranked else None,
        "laggard": ranked[-1]["symbol"] if ranked else None,
    }


def conclusion(primary: dict[str, Any] | None, derived: dict[str, Any], sector: dict[str, Any]) -> dict[str, Any]:
    if not primary:
        return {
            "state": "查無有效報價",
            "confidence": "low",
            "summary": "沒有取得有效即時報價，請確認股票代碼或稍後重試。",
            "watch_points": ["確認上市/上櫃代碼", "確認目前是否接近交易時段", "重新查詢"],
        }

    state = derived.get("intraday_state") or "盤中觀察"
    name = primary.get("name") or primary.get("symbol")
    price_vs_open = derived.get("price_vs_open")
    range_position = derived.get("range_position")
    sector_status = sector.get("status")
    summary = f"{primary.get('symbol')} {name} 目前偏「{state}」。"
    if primary.get("price_source") == "best_bid_ask_midpoint":
        summary += " 最新成交價未揭示，現價採最佳買賣價中位數估算。"
    if range_position is not None:
        summary += f" 日內位置約 {int(range_position * 100)}%，"
    if price_vs_open == "below":
        summary += "價格低於開盤，短線換手壓力較高。"
    elif price_vs_open == "above":
        summary += "價格高於開盤，短線承接仍在。"
    else:
        summary += "價格與開盤關係尚不明確。"
    if sector_status:
        summary += f" 族群狀態：{sector_status}。"

    watch_points = ["能否站回或守住開盤價", "是否跌破日內低點", "同族群領頭股是否同步轉弱"]
    return {
        "state": state,
        "confidence": "medium" if primary.get("price") is not None else "low",
        "summary": summary,
        "watch_points": watch_points,
    }


def group_conclusion(symbols: list[str], per_symbol: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    state = summary.get("state") or "多檔觀察"
    total = len(per_symbol)
    high_count = summary.get("high_position_count", 0)
    above_count = summary.get("above_open_count", 0)
    leader = summary.get("leader")
    names = "、".join(symbols)
    text = f"{names} 目前整體偏「{state}」。"
    if total:
        text += f"{above_count} / {total} 檔高於開盤，{high_count} / {total} 檔位於日內高檔。"
    if leader:
        text += f" 目前領頭為 {leader}。"
    if state == "族群高檔換手":
        text += " 這比較像族群同步承接，不是單檔硬撐。"
    elif state == "漲多分歧":
        text += " 漲幅仍在，但日內位置轉弱，要留意爆量不漲。"

    return {
        "state": state,
        "confidence": "medium" if total else "low",
        "summary": text,
        "watch_points": [
            "若 70% 以上個股仍守開盤價，族群多方結構維持",
            "若 2 檔以上跌回日內中位以下，判斷轉為漲多分歧",
            "若領頭股失去高檔位置，族群強度下降",
            "若量能放大但價格不再創高，從高檔換手轉為量增滯漲",
        ],
    }


def format_number(value: Any, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}{suffix}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    return f"{value}{suffix}"


def to_markdown(snapshot: dict[str, Any]) -> str:
    if len(snapshot.get("quotes", [])) > 1:
        return to_multi_markdown(snapshot)

    primary = snapshot["quotes"][0] if snapshot["quotes"] else {}
    derived = snapshot["derived"]
    sector = snapshot["sector"]
    conclusion_obj = snapshot["conclusion"]
    price_note = ""
    if primary.get("price_source") == "best_bid_ask_midpoint":
        price_note = " (買賣中位估)"
    elif primary.get("price_source") == "unavailable":
        price_note = " (未揭示)"
    lines = [
        "## 即時結論",
        conclusion_obj["summary"],
        "",
        "## 盤中快照",
        "| 項目 | 數值 |",
        "|---|---:|",
        f"| 代碼 | {primary.get('symbol', '-')} {primary.get('name', '')} |",
        f"| 現價 | {format_number(primary.get('price'))}{price_note} |",
        f"| 最新成交價 | {format_number(primary.get('last_trade_price'))} |",
        f"| 漲跌幅 | {format_number(primary.get('change_percent'), '%')} |",
        f"| 開盤 | {format_number(primary.get('open'))} |",
        f"| 最高 | {format_number(primary.get('high'))} |",
        f"| 最低 | {format_number(primary.get('low'))} |",
        f"| 昨收 | {format_number(primary.get('previous_close'))} |",
        f"| 累積量 | {format_number(primary.get('volume_lot'), ' 張')} |",
        f"| 日內位置 | {format_number(int(derived['range_position'] * 100) if derived.get('range_position') is not None else None, '%')} |",
        f"| 資料時間 | {primary.get('data_time', '-')} |",
        f"| 族群狀態 | {sector.get('status') or '-'} |",
        "",
        "## 判斷",
        "| 條件 | 狀態 |",
        "|---|---|",
        f"| 價格 vs 開盤 | {derived.get('price_vs_open', '-')} |",
        f"| 盤中狀態 | {derived.get('intraday_state', '-')} |",
        f"| 風險標籤 | {', '.join(derived.get('risk_tags') or []) or '-'} |",
        f"| 結論 | {conclusion_obj.get('state', '-')} |",
        "",
        "## 觀察點",
    ]
    for index, point in enumerate(conclusion_obj.get("watch_points", []), start=1):
        lines.append(f"{index}. {point}")
    return "\n".join(lines)


def pct_position(value: Any) -> str:
    if value is None:
        return "-"
    return f"{int(value * 100)}%"


def to_multi_markdown(snapshot: dict[str, Any]) -> str:
    quotes_by_symbol = {quote.get("symbol"): quote for quote in snapshot.get("quotes", [])}
    per_symbol = snapshot.get("per_symbol", [])
    summary = snapshot.get("group_summary", {})
    conclusion_obj = snapshot["conclusion"]
    market_turnover = snapshot.get("market_turnover", {})
    ranked = sorted(
        [item for item in per_symbol if item.get("change_percent") is not None],
        key=lambda item: item["change_percent"],
        reverse=True,
    )

    lines = [
        "## 即時結論",
        conclusion_obj["summary"],
        "",
        "## 強弱排序",
        "| 排名 | 代碼 | 名稱 | 漲跌幅 | 日內位置 | 累積量 | 狀態 |",
        "|---:|---|---|---:|---:|---:|---|",
    ]
    for index, item in enumerate(ranked, start=1):
        lines.append(
            f"| {index} | {item.get('symbol')} | {item.get('name') or ''} | "
            f"{format_number(item.get('change_percent'), '%')} | {pct_position(item.get('range_position'))} | "
            f"{format_number(item.get('volume_lot'), ' 張')} | {item.get('state')} |"
        )

    total = len(per_symbol)
    lines.extend(
        [
            "",
            "## 多檔判斷",
            "| 條件 | 結果 |",
            "|---|---|",
            f"| 高於開盤檔數 | {summary.get('above_open_count', 0)} / {total} |",
            f"| 位於日內高檔檔數 | {summary.get('high_position_count', 0)} / {total} |",
            f"| 漲幅超過 2% 檔數 | {summary.get('large_gain_count', 0)} / {total} |",
            f"| 高檔換手檔數 | {summary.get('high_turnover_count', 0)} / {total} |",
            f"| 大量檔數 | {summary.get('heavy_volume_count', 0)} / {total} |",
            f"| 族群一致性 | {summary.get('consistency', '-')} |",
            f"| 整體結論 | {summary.get('state', '-')} |",
            "",
            "## 大盤成交值",
            "| 項目 | 數值 |",
            "|---|---:|",
            f"| 目前成交值 | {format_number(market_turnover.get('current_turnover_billion'), ' 億元')} |",
            f"| 觀測時間 | {market_turnover.get('observed_time') or '-'} |",
            f"| 近期基準 | {format_number(market_turnover.get('recent_baseline_billion'), ' 億元')} |",
            f"| 線性收盤推估 | {format_number(market_turnover.get('projected_close_billion'), ' 億元')} |",
            f"| 推估 / 基準 | {format_number((market_turnover.get('projected_vs_baseline_ratio') or 0) * 100, '%') if market_turnover.get('projected_vs_baseline_ratio') is not None else '-'} |",
            f"| 相對量能 | {market_turnover.get('status', '-')} |",
            "",
            "## 個股細節",
            "| 代碼 | 價格 vs 開盤 | 日內位置 | 量能訊號 | 買賣價差 | 判斷 | 風險 |",
            "|---|---|---:|---|---:|---|---|",
        ]
    )
    for item in per_symbol:
        quote = quotes_by_symbol.get(item.get("symbol"), {})
        price_note = ""
        if quote.get("price_source") == "best_bid_ask_midpoint":
            price_note = "，現價為買賣中位估"
        lines.append(
            f"| {item.get('symbol')} | {item.get('price_vs_open')} | {pct_position(item.get('range_position'))} | "
            f"{item.get('volume_signal')} / {format_number(item.get('heavy_volume_lot'), ' 張')} | "
            f"{format_number(item.get('spread'))} | {item.get('state')} | {item.get('risk')}{price_note} |"
        )

    lines.extend(["", "## 觀察點"])
    for index, point in enumerate(conclusion_obj.get("watch_points", []), start=1):
        lines.append(f"{index}. {point}")
    return "\n".join(lines)


def save_log(snapshot: dict[str, Any]) -> pathlib.Path:
    today = now_taipei().strftime("%Y-%m-%d")
    symbol = snapshot["query"]["symbols"][0] if snapshot["query"]["symbols"] else "sector"
    stamp = now_taipei().strftime("%H%M%S")
    directory = LOG_DIR / today
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{symbol}_{stamp}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2)
    return path


def build_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    sectors = load_json(CONFIG_DIR / "sectors.json", {})
    rules = load_json(CONFIG_DIR / "rules.json", {})
    symbols: list[str] = []
    sector_name = args.sector

    if args.stock:
        symbols = [normalize_symbol(args.stock)]
    if args.stocks:
        symbols.extend(normalize_symbol(item) for item in args.stocks.split(",") if item.strip())
    if args.sector:
        sector_symbols = sectors.get(args.sector)
        if not sector_symbols:
            raise ValueError(f"Unknown sector {args.sector!r}. Available: {', '.join(sectors)}")
        symbols.extend(sector_symbols)

    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        raise ValueError("Provide --stock, --stocks, or --sector.")

    rows = mock_rows(symbols) if args.mock else fetch_twse_mis(symbols, timeout=args.timeout)
    quotes_by_symbol = {quote["symbol"]: quote for quote in (normalize_quote(row) for row in rows)}
    quotes = [quotes_by_symbol[symbol] for symbol in symbols if symbol in quotes_by_symbol]
    primary = quotes[0] if quotes else None
    derived = derive_quote_state(primary, rules) if primary else {}
    sector = sector_summary(sector_name, quotes, rules)
    per_symbol = build_per_symbol(quotes, rules)
    summary = group_summary(per_symbol, rules)
    market_turnover = build_market_turnover_context(
        getattr(args, "market_turnover_billion", None),
        getattr(args, "market_turnover_time", None),
        getattr(args, "market_baseline_billion", None),
        rules,
        timeout=args.timeout,
    )
    single_conclusion = conclusion(primary, derived, sector)
    final_conclusion = group_conclusion(symbols, per_symbol, summary) if len(quotes) > 1 else single_conclusion
    snapshot = {
        "query": {
            "market": "TW",
            "symbols": symbols,
            "sector": sector_name,
            "time": now_taipei().isoformat(timespec="seconds"),
            "storage": "json-log" if args.save_log else "none",
            "mock": bool(args.mock),
        },
        "quotes": quotes,
        "derived": derived,
        "per_symbol": per_symbol,
        "group_summary": summary,
        "market_turnover": market_turnover,
        "sector": sector,
        "conclusion": final_conclusion,
    }
    if args.save_log:
        snapshot["query"]["log_path"] = str(save_log(snapshot))
    return snapshot


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Realtime Taiwan stock snapshot without persistence.")
    parser.add_argument("--stock", help="Single Taiwan stock code, e.g. 3231.")
    parser.add_argument("--stocks", help="Comma-separated Taiwan stock codes, e.g. 2330,3231,2382.")
    parser.add_argument("--sector", help="Configured sector name, e.g. ODM.")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--save-log", action="store_true", help="Optionally write one JSON log under logs/.")
    parser.add_argument("--mock", action="store_true", help="Use deterministic sample data for validation.")
    parser.add_argument("--timeout", type=int, default=8, help="Network timeout in seconds.")
    parser.add_argument(
        "--market-turnover-billion",
        type=float,
        help="Current TW market turnover in 億元, e.g. 8750 for 8,750 億.",
    )
    parser.add_argument(
        "--market-turnover-time",
        help="Observation time for --market-turnover-billion in HH:MM, e.g. 12:00.",
    )
    parser.add_argument(
        "--market-baseline-billion",
        type=float,
        help="Optional manual recent full-day turnover baseline in 億元.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        snapshot = build_snapshot(args)
    except Exception as exc:
        error = {
            "query": {"market": "TW", "time": now_taipei().isoformat(timespec="seconds"), "storage": "none"},
            "quotes": [],
            "derived": {},
            "sector": {},
            "conclusion": {
                "state": "查詢失敗",
                "confidence": "low",
                "summary": str(exc),
                "watch_points": ["確認代碼", "確認網路連線", "稍後重試"],
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
