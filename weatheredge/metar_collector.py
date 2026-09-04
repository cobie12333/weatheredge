#!/usr/bin/env python3
import os
import json
import sys
import urllib.request
import urllib.error

from config.settings import METAR_STATION_ID, HTTP_TIMEOUT_SECONDS, USER_AGENT
from db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("metar_collector")

METAR_URL = (
    f"https://aviationweather.gov/api/data/metar"
    f"?ids={METAR_STATION_ID}&format=json&hours=3"
)


def extract_obs_time(obs_time_field):
    if obs_time_field is None:
        return None
    if isinstance(obs_time_field, (int, float)):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(obs_time_field, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(obs_time_field)


def normalize_receipt_time(receipt_time_field):
    if receipt_time_field is None:
        return None
    return str(receipt_time_field)


def run():
    con = get_connection()
    try:
        try:
            req = urllib.request.Request(METAR_URL, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as e:
            msg = f"Network error fetching METAR: {e}"
            logger.error(msg)
            log_collection_attempt(con, "metar", success=False, error_msg=msg)
            return 0
        except json.JSONDecodeError as e:
            msg = f"JSON parse error: {e}"
            logger.error(msg)
            log_collection_attempt(con, "metar", success=False, error_msg=msg)
            return 0

        if not data:
            msg = "Empty response from API"
            logger.warning(msg)
            log_collection_attempt(con, "metar", success=False, error_msg=msg)
            return 0

        total_written = 0
        for obs in data:
            raw_metar = obs.get("rawOb", "")
            obs_time = extract_obs_time(obs.get("obsTime"))
            receipt_time = normalize_receipt_time(obs.get("receiptTime"))
            temp_c = obs.get("temp")
            report_type = obs.get("metarType", "METAR")

            if not raw_metar or not obs_time:
                continue

            try:
                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO metar_obs
                    (fetched_at, obs_time, receipt_time, temp_c, raw_metar, report_type)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (utc_now_iso(), obs_time, receipt_time, temp_c, raw_metar, report_type),
                )
                con.commit()
                if cur.rowcount:
                    total_written += 1
                    logger.info(f"Saved {report_type} obs_time={obs_time} receipt_time={receipt_time} temp_c={temp_c}")
            except Exception as e:
                msg = f"DB write error on {obs_time}: {e}"
                logger.error(msg)
                log_collection_attempt(con, "metar", success=False, error_msg=msg)
                return total_written

        if total_written == 0:
            logger.info("No new reports since last poll")

        log_collection_attempt(con, "metar", success=True, rows_written=total_written)
        return total_written
    finally:
        con.close()


if __name__ == "__main__":
    written = run()
    sys.exit(0 if written >= 0 else 1)
