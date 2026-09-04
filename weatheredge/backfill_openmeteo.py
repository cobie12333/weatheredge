#!/usr/bin/env python3
"""
WeatherEdge — Historical Backfill: Open-Meteo Previous Runs
Version 1.0

Source: Open-Meteo Previous Runs API. Same provider already used by
the live system, no new dependency. Archives forecast values at fixed
lead-time offsets, built specifically for evaluating forecast skill —
exactly the "which provider was closest to reality" question.

Endpoint pattern (per Open-Meteo docs): each lead-time offset is
requested as a suffixed hourly variable, e.g. temperature_2m_previous_day1
for the run made ~24h before valid_time. This module requests a small,
explicit set of lead times (1, 2, 3 days) rather than guessing at every
possible offset — narrower, defensible scope per Deliverable 3's actual
question, extendable later if evidence calls for finer granularity.
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timezone

sys.path.insert(0, ".")
from db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("backfill_openmeteo")

FACT_LAT = -33.9648
FACT_LON = 18.6017

MODEL = "gfs_seamless"
LEAD_DAYS = [1, 2, 3]  # matches Deliverable 3's stated question scope


def build_url(start: date, end: date) -> str:
    lead_vars = "".join(f",temperature_2m_previous_day{d}" for d in LEAD_DAYS)
    return (
        "https://previous-runs-api.open-meteo.com/v1/forecast"
        f"?latitude={FACT_LAT}&longitude={FACT_LON}"
        f"&hourly=temperature_2m{lead_vars}"
        f"&models={MODEL}"
        f"&start_date={start.isoformat()}&end_date={end.isoformat()}"
        "&timezone=UTC"
    )


def fetch_json(start: date, end: date) -> dict:
    url = build_url(start, end)
    req = urllib.request.Request(url, headers={"User-Agent": "weatheredge-research/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_response(data: dict) -> list:
    """
    Open-Meteo hourly response shape:
      {"hourly": {"time": [...], "temperature_2m": [...],
                  "temperature_2m_previous_day1": [...], ...}}
    Each lead-time column becomes its own row per timestamp, so a
    single valid_time produces up to len(LEAD_DAYS) rows — one per
    lead time — matching forecast_history's (valid_time, lead_hours,
    model) uniqueness.
    """
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return []

    rows = []
    for lead_days in LEAD_DAYS:
        key = f"temperature_2m_previous_day{lead_days}"
        values = hourly.get(key, [])
        if not values:
            continue
        for t, v in zip(times, values):
            if v is None:
                continue
            try:
                valid_dt = datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
                valid_time = valid_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                continue
            rows.append({
                "valid_time": valid_time,
                "lead_hours": lead_days * 24,
                "temp_c": float(v),
            })
    return rows


def backfill(start: date, end: date) -> dict:
    con = get_connection()
    logger.info(f"Backfilling Open-Meteo Previous Runs, {start} to {end}, leads={LEAD_DAYS}")

    try:
        try:
            data = fetch_json(start, end)
        except (urllib.error.URLError, TimeoutError) as e:
            msg = f"Network error fetching Open-Meteo data: {e}"
            logger.error(msg)
            log_collection_attempt(con, "forecast_backfill", success=False, error_msg=msg)
            return {"status": "error", "error": msg}
        except json.JSONDecodeError as e:
            msg = f"JSON parse error: {e}"
            logger.error(msg)
            log_collection_attempt(con, "forecast_backfill", success=False, error_msg=msg)
            return {"status": "error", "error": msg}

        rows = parse_response(data)
        logger.info(f"Parsed {len(rows)} forecast-lead rows from Open-Meteo response")

        written, duplicates = 0, 0
        for r in rows:
            try:
                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO forecast_history
                    (fetched_at, valid_time, lead_hours, model, temp_c, source, raw_payload)
                    VALUES (?, ?, ?, ?, ?, 'backfill_openmeteo', ?)
                    """,
                    (utc_now_iso(), r["valid_time"], r["lead_hours"], MODEL, r["temp_c"], json.dumps(r)),
                )
                if cur.rowcount:
                    written += 1
                else:
                    duplicates += 1
            except Exception as e:
                logger.error(f"DB write error on valid_time={r['valid_time']}: {e}")

        con.commit()
        log_collection_attempt(con, "forecast_backfill", success=True, rows_written=written)

        logger.info(f"Backfill complete: {written} new rows, {duplicates} duplicates skipped")
        return {"status": "ok", "written": written, "duplicates": duplicates, "total_parsed": len(rows)}
    finally:
        con.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 backfill/openmeteo_forecast.py YYYY-MM-DD YYYY-MM-DD")
        sys.exit(1)
    start = date.fromisoformat(sys.argv[1])
    end = date.fromisoformat(sys.argv[2])
    result = backfill(start, end)
    print(result)
