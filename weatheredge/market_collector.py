#!/usr/bin/env python3
"""Collect Polymarket daily-high temperature market snapshots per airport."""

import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .airports import AIRPORT_BY_ICAO, AIRPORTS
from .config.settings import GAMMA_API_BASE, HTTP_TIMEOUT_SECONDS, TRACKED_BUCKET_COUNT, USER_AGENT
from .db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("market_collector")


def build_slug_for_date(d: date, icao: str = "FACT") -> str:
    airport = AIRPORT_BY_ICAO[icao]
    return f"highest-temperature-in-{airport['market_city']}-on-{d.strftime('%B').lower()}-{d.day}-{d.year}"


def fetch_event(slug: str) -> dict:
    url = f"{GAMMA_API_BASE}/events?slug={slug}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if isinstance(data, list):
        return data[0] if data else None
    return data


def extract_buckets(event: dict, top_n: int) -> list:
    markets = event.get("markets", [])
    parsed = []
    for m in markets:
        try:
            volume = float(m.get("volume", 0) or 0)
        except (TypeError, ValueError):
            volume = 0.0

        yes_price = no_price = None
        outcome_prices = m.get("outcomePrices")
        if outcome_prices:
            try:
                prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                if len(prices) >= 2:
                    yes_price = float(prices[0]) * 100
                    no_price = float(prices[1]) * 100
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        parsed.append({
            "bucket_label": m.get("groupItemTitle") or m.get("question", "unknown"),
            "yes_price_cents": yes_price,
            "no_price_cents": no_price,
            "volume_usd": volume,
            "raw_payload": json.dumps(m),
        })

    if top_n > 0:
        parsed.sort(key=lambda b: min(b["yes_price_cents"] or 0, 100 - (b["yes_price_cents"] or 0)), reverse=True)
        return parsed[:top_n]
    return parsed


def run(target_date: date = None, icao: str = "FACT") -> int:
    if icao not in AIRPORT_BY_ICAO:
        raise ValueError(f"Unknown airport ICAO: {icao}")
    if target_date is None:
        airport = AIRPORT_BY_ICAO[icao]
        target_date = datetime.now(ZoneInfo(airport["tz"])).date()

    market_date_str = target_date.isoformat()
    slug = build_slug_for_date(target_date, icao)
    con = get_connection()

    try:
        try:
            event = fetch_event(slug)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            msg = f"Network error fetching event slug={slug}: {e}"
            logger.error(msg)
            log_collection_attempt(con, f"market:{icao}", False, error_msg=msg)
            return 0

        if not event:
            msg = f"No event found for slug={slug}"
            logger.warning(msg)
            log_collection_attempt(con, f"market:{icao}", False, error_msg=msg)
            return 0

        buckets = extract_buckets(event, TRACKED_BUCKET_COUNT)
        if not buckets:
            msg = f"Event found but no market buckets extracted for slug={slug}"
            logger.warning(msg)
            log_collection_attempt(con, f"market:{icao}", False, error_msg=msg)
            return 0

        fetched_at = utc_now_iso()
        rows_written = 0
        for b in buckets:
            cur = con.execute(
                """INSERT OR IGNORE INTO market_price_multi
                   (station_id, market_date, fetched_at, bucket_label,
                    yes_price_cents, no_price_cents, volume_usd, market_slug,
                    source, raw_payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'live', ?)""",
                (
                    icao, market_date_str, fetched_at, b["bucket_label"],
                    b["yes_price_cents"], b["no_price_cents"], b["volume_usd"],
                    slug, b["raw_payload"],
                ),
            )
            rows_written += int(cur.rowcount > 0)

        # Keep the legacy FACT table populated for existing FACT-only analysis.
        if icao == "FACT":
            for b in buckets:
                con.execute(
                    """INSERT OR IGNORE INTO market_price
                       (fetched_at, market_date, bucket_label, yes_price_cents,
                        no_price_cents, volume_usd, raw_payload, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'live')""",
                    (
                        fetched_at, market_date_str, b["bucket_label"],
                        b["yes_price_cents"], b["no_price_cents"], b["volume_usd"],
                        b["raw_payload"],
                    ),
                )

        con.commit()
        log_collection_attempt(con, f"market:{icao}", True, rows_written=rows_written)
        logger.info("%s: saved %s buckets for %s", icao, rows_written, market_date_str)
        return rows_written
    finally:
        con.close()


if __name__ == "__main__":
    from zoneinfo import ZoneInfo
    icao = sys.argv[1].upper() if len(sys.argv) > 1 else "FACT"
    written = run(icao=icao)
    sys.exit(0 if written >= 0 else 1)
