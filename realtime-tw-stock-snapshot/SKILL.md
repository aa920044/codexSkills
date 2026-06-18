---
name: realtime-tw-stock-snapshot
description: Query Taiwan-listed intraday and closing stock snapshots, official TWSE institutional flows, historical volume structure, price-band volume, and USD/TWD noon reference series without a database or long-term storage. Use when the user asks for the realtime Taiwan stock skill, a fixed-format Taiwan stock report, current or closing conditions for Taiwan stock codes, ODM or configured sector checks, three-institution flows, trapped-volume structure, or daily noon USD/TWD context. Do not use for US stocks or long-term historical warehousing.
---

# Realtime TW Stock Snapshot

## Overview

Use this skill to fetch current Taiwan intraday quote snapshots for user-specified symbols and return a stable JSON or Markdown report. The skill is intentionally non-persistent: it does not create a database, does not build a warehouse, and only writes optional JSON logs when `--save-log` is passed.

## Quick Start

Run with the bundled or local Python executable:

```powershell
python realtime-tw-stock-snapshot/scripts/snapshot.py --stock 3231 --format markdown
python realtime-tw-stock-snapshot/scripts/snapshot.py --stocks 2330,3231,2382 --format json
python realtime-tw-stock-snapshot/scripts/snapshot.py --sector ODM --format markdown
python realtime-tw-stock-snapshot/scripts/snapshot.py --stocks 2330,3231,2382 --market-turnover-billion 8750 --market-turnover-time 12:00 --format markdown
python realtime-tw-stock-snapshot/scripts/fx_usdtwd_noon.py --days 10 --target-time 12:00 --format markdown
python realtime-tw-stock-snapshot/scripts/institutional_latest.py --stocks 2330,3231,2382 --format markdown
python realtime-tw-stock-snapshot/scripts/historical_structure.py --stock 3231 --event-start 2026-05-29 --event-end 2026-06-03 --recent-days 3
python realtime-tw-stock-snapshot/scripts/volume_profile.py --stock 3231 --start 2026-05-29 --end 2026-06-16 --current-price 158 --step 5
```

Use `--save-log` only when the user wants a local debug record:

```powershell
python realtime-tw-stock-snapshot/scripts/snapshot.py --stock 3231 --format json --save-log
```

## Data Policy

- Fetch only on demand.
- Do not store long-term history.
- Do not create or require a database.
- Write optional JSON logs only under `realtime-tw-stock-snapshot/logs/` when `--save-log` is explicitly supplied.
- Support Taiwan stocks only. Do not use this skill for US stocks.
- Fetch recent completed-day market turnover from the official TWSE `FMTQIK` endpoint.
- Accept current intraday market turnover with `--market-turnover-billion`, in 億元. Do not invent this value when it is unavailable.
- Pair a user-supplied turnover value with `--market-turnover-time HH:MM` when the observation time differs from the current query time.
- Fetch USD/TWD intraday reference values from Yahoo Finance chart data when the user asks for exchange-rate context. Treat the result as a market reference series, not an official central bank fixing.
- For FX context, prefer `--target-time 12:00` so each day is compared at the same Taipei-time observation point.

## Output Contract

The JSON output always contains:

```json
{
  "query": {},
  "quotes": [],
  "per_symbol": [],
  "group_summary": {},
  "market_turnover": {},
  "derived": {},
  "sector": {},
  "conclusion": {}
}
```

The Markdown output always uses these sections:

Single-symbol:

- `即時結論`
- `盤中快照`
- `判斷`
- `觀察點`

Multi-symbol or sector:

- `即時結論`
- `強弱排序`
- `多檔判斷`
- `個股細節`
- `觀察點`

## Scripts

- `scripts/snapshot.py`: main entry point. Query one stock, multiple stocks, or a configured sector and return JSON or Markdown.
- `scripts/quote_now.py`: quote-only convenience wrapper that returns fixed JSON for symbols.
- `scripts/fx_usdtwd_noon.py`: fetch USD/TWD hourly reference data and extract the daily value nearest to a target Taipei time, default 12:00. Use this for questions about TWD strength/weakness, external inflow, and whether Taiwan stock movement is more likely internal rotation.
- `scripts/institutional_latest.py`: fetch the latest available official TWSE market totals and per-stock foreign, investment-trust, and dealer net flows. Use after the close or when the user asks about three-institution activity.
- `scripts/historical_structure.py`: fetch up to three months of official daily volume, institutional, and margin data without persistence; compare a baseline period, a suspected ignition period, and the latest trading days.
- `scripts/volume_profile.py`: estimate price-band volume and possible overhead pressure from official daily OHLCV data. Use this for questions about boxed ranges, trapped volume, platform pressure, or whether a move was straight up/down without a thick consolidation area.

## FX Output Contract

`scripts/fx_usdtwd_noon.py` JSON output always contains:

```json
{
  "query": {},
  "source": {},
  "series": [],
  "skipped_dates": [],
  "summary": {},
  "conclusion": {}
}
```

Interpretation:

- `台幣偏升值`: USD/TWD is lower across the sampled noon series; this can support an external inflow thesis when paired with foreign net buying and expanding turnover.
- `台幣匯率橫向`: USD/TWD moved less than the configured flat threshold; prefer an internal-rotation explanation unless other evidence shows fresh inflow.
- `台幣偏貶值`: USD/TWD is higher across the sampled noon series; if Taiwan stocks rise anyway, check whether a few index weights are carrying the tape.

## Interpretation Rules

Use the script's `conclusion` as the primary result. When explaining to the user, keep the answer concise and preserve the fixed report structure.

Basic labels:

- `量縮守高`: healthier consolidation.
- `量增滯漲`: distribution or disagreement risk.
- `量增下殺`: breakdown risk.
- `高檔換手觀察`: elevated turnover that needs confirmation from price reclaiming the open or intraday midpoint.

Group labels:

- `族群高檔換手`: at least 70% of symbols are above open and at least 70% are in the upper intraday range.
- `漲多分歧`: large gains remain but fewer than half of symbols hold the upper intraday range.
- `量增轉弱`: fewer than half of symbols are above open and fewer than half hold the upper intraday range.
- `單檔硬撐`: only one symbol is holding a high intraday position.
- `族群震盪分歧`: mixed group behavior without a decisive label.

## Validation

Use `--mock` to validate formatting without market data:

```powershell
python realtime-tw-stock-snapshot/scripts/snapshot.py --stock 3231 --format markdown --mock
```
