import json
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timezone

from config.settings import GAMMA_API_BASE, HTTP_TIMEOUT_SECONDS, USER_AGENT
from db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("market_collector")


def build_slug_for_date(d: date) -> str:
    month_name = d.strftime("%B").lower()
    return f"highest-temperature-in-cape-town-on-{month_name}-{d.day}-{d.year}"


def fetch_event(slug: str) -> dict:
    url = f"{GAMMA_API_BASE}/events?slug={slug}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if isinstance(data, list):
        return data[0] if data else None
    return data


def source_timestamp(payload: dict):
    """Return an upstream timestamp if the API exposes one; never invent it."""
    for key in ("updatedAt", "updated_at", "lastUpdated", "last_updated"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def extract_buckets(event: dict) -> list:
    """Extract every market outcome returned by Gamma; never truncate the universe."""
    markets = event.get("markets", [])
    if not markets:
        return []

    event_updated_at = source_timestamp(event)
    parsed = []

    for m in markets:
        try:
            volume = float(m.get("volume", 0) or 0)
        except (TypeError, ValueError):
            volume = 0.0

        outcome_prices = m.get("outcomePrices")
        yes_price = no_price = None
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
            "source_updated_at": source_timestamp(m) or event_updated_at,
            "raw_payload": json.dumps(m, separators=(",", ":")),
        })

    return parsed


def run(target_date: date = None) -> int:
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()

    market_date_str = target_date.isoformat()
    slug = build_slug_for_date(target_date)
    con = get_connection()

    try:
        try:
            event = fetch_event(slug)
        except (urllib.error.URLError, TimeoutError) as e:
            msg = f"Network error fetching event slug={slug}: {e}"
            logger.error(msg)
            log_collection_attempt(con, "market", success=False, error_msg=msg)
            return 0
        except json.JSONDecodeError as e:
            msg = f"JSON parse error for slug={slug}: {e}"
            logger.error(msg)
            log_collection_attempt(con, "market", success=False, error_msg=msg)
            return 0

        if not event:
            msg = f"No event found for slug={slug}"
            logger.warning(msg)
            log_collection_attempt(con, "market", success=False, error_msg=msg)
            return 0

        buckets = extract_buckets(event)

        if not buckets:
            msg = f"Event found but no market buckets extracted for slug={slug}"
            logger.warning(msg)
            log_collection_attempt(con, "market", success=False, error_msg=msg)
            return 0

        # This is the time WeatherEdge received the response.
        # Keep it separate from any upstream timestamp exposed by Gamma.
        fetched_at = utc_now_iso()
        rows_written = 0

        try:
            for b in buckets:
                con.execute(
                    """
                    INSERT INTO market_price
                    (fetched_at, source_updated_at, market_date, bucket_label,
                     yes_price_cents, no_price_cents, volume_usd, raw_payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fetched_at,
                        b["source_updated_at"],
                        market_date_str,
                        b["bucket_label"],
                        b["yes_price_cents"],
                        b["no_price_cents"],
                        b["volume_usd"],
                        b["raw_payload"],
                    ),
                )
                rows_written += 1

            con.commit()
            logger.info(
                f"Saved {rows_written} complete market outcomes for {market_date_str}"
            )
            log_collection_attempt(con, "market", success=True, rows_written=rows_written)
            return rows_written

        except Exception as e:
            msg = f"DB write error: {e}"
            logger.error(msg)
            log_collection_attempt(con, "market", success=False, error_msg=msg)
            return 0
    finally:
        con.close()


if __name__ == "__main__":
    written = run()
    sys.exit(0 if written >= 0 else 1)
