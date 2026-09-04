#!/usr/bin/env python3
"""
WeatherEdge — Historical Backfill: Polymarket Historical Prices
Version 1.0

Source: Polymarket's own official prices-history endpoint (free,
first-party, no auth). Reuses market_collector.py's build_slug_for_date
and fetch_event to resolve a date into an event, then extracts each
market's clobTokenIds — required because the prices-history endpoint
takes a token/asset id, not a slug.

Endpoint: https://clob.polymarket.com/prices-history
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timezone

sys.path.insert(0, ".")
from db import get_connection, log_collection_attempt, setup_logger, utc_now_iso
from market_collector import build_slug_for_date, fetch_event

logger = setup_logger("backfill_polymarket")

CLOB_HISTORY_URL = "https://clob.polymarket.com/prices-history"


def extract_token_ids(event: dict) -> list:
    """
    Each market within an event has a clobTokenIds field — a
    JSON-encoded array of two token ids: [YES_token, NO_token].
    Returns a list of (bucket_label, yes_token_id) pairs.
    """
    markets = event.get("markets", [])
    result = []
    for m in markets:
        raw_ids = m.get("clobTokenIds")
        if not raw_ids:
            continue
        try:
            ids = json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
            if not ids:
                continue
            bucket_label = m.get("groupItemTitle") or m.get("question", "unknown")
            result.append((bucket_label, ids[0]))  # index 0 = YES token, per Polymarket convention
        except (json.JSONDecodeError, IndexError, TypeError):
            continue
    return result


def fetch_price_history(token_id: str, start_ts: int, end_ts: int) -> list:
    """
    Fetch historical price points for one CLOB token.

    fidelity=5 requests 5-minute resolution. Confirmed via live testing
    (2026-07-11) that fidelity=60 produces genuinely hourly-only data
    points (verified against real timestamps: 00:00:03Z, 01:00:04Z,
    02:00:xx...), which floors any lag measurement at a 60-minute
    resolution and produces misleading exact-60.0-min artifacts.
    5-minute fidelity roughly matches live collection's 15-min polling
    granularity without over-requesting.
    """
    url = (
        f"{CLOB_HISTORY_URL}?market={token_id}"
        f"&startTs={start_ts}&endTs={end_ts}&fidelity=5"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "weatheredge-research/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8")).get("history", [])


def backfill_day(target_date: date) -> dict:
    """
    Backfill one market-day: resolve slug -> event -> token ids ->
    price history per bucket, tagged source='backfill_polymarket'.
    """
    con = get_connection()
    slug = build_slug_for_date(target_date)
    market_date_str = target_date.isoformat()

    try:
        try:
            event = fetch_event(slug)
        except (urllib.error.URLError, TimeoutError) as e:
            msg = f"Network error fetching event slug={slug}: {e}"
            logger.error(msg)
            log_collection_attempt(con, "market_backfill", success=False, error_msg=msg)
            return {"status": "error", "error": msg}

        if not event:
            msg = f"No event found for slug={slug}"
            logger.warning(msg)
            log_collection_attempt(con, "market_backfill", success=False, error_msg=msg)
            return {"status": "error", "error": msg}

        token_pairs = extract_token_ids(event)
        if not token_pairs:
            msg = f"No clobTokenIds found in event for slug={slug}"
            logger.warning(msg)
            log_collection_attempt(con, "market_backfill", success=False, error_msg=msg)
            return {"status": "error", "error": msg}

        start_dt = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
        end_dt = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=timezone.utc)
        start_ts, end_ts = int(start_dt.timestamp()), int(end_dt.timestamp())

        total_written, total_dup = 0, 0
        for bucket_label, token_id in token_pairs:
            try:
                history = fetch_price_history(token_id, start_ts, end_ts)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                logger.error(f"Error fetching history for {bucket_label}: {e}")
                continue

            for point in history:
                ts = point.get("t")
                price = point.get("p")
                if ts is None or price is None:
                    continue
                fetched_at = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                yes_cents = float(price) * 100

                try:
                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO market_price
                        (fetched_at, market_date, bucket_label, yes_price_cents,
                         no_price_cents, volume_usd, raw_payload, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'backfill_polymarket')
                        """,
                        (fetched_at, market_date_str, bucket_label, yes_cents,
                         100 - yes_cents, None, json.dumps(point)),
                    )
                    if cur.rowcount:
                        total_written += 1
                    else:
                        total_dup += 1
                except Exception as e:
                    logger.error(f"DB write error: {e}")

        con.commit()
        log_collection_attempt(con, "market_backfill", success=True, rows_written=total_written)

        logger.info(f"Backfill complete for {market_date_str}: {total_written} price points written")
        return {"status": "ok", "written": total_written, "buckets_covered": len(token_pairs)}
    finally:
        con.close()


def backfill_range(start: date, end: date) -> dict:
    """Backfill each day in [start, end] as a separate market event."""
    results = []
    current = start
    while current <= end:
        result = backfill_day(current)
        results.append({"date": current.isoformat(), **result})
        current = date.fromordinal(current.toordinal() + 1)
    return {"status": "ok", "days": results}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 backfill/polymarket_prices.py YYYY-MM-DD YYYY-MM-DD")
        sys.exit(1)
    start = date.fromisoformat(sys.argv[1])
    end = date.fromisoformat(sys.argv[2])
    result = backfill_range(start, end)
    print(json.dumps(result, indent=2))
