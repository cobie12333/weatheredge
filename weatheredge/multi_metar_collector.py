#!/usr/bin/env python3
"""Collect current METAR/SPECI observations for the WeatherEdge watchlist.

Uses the AviationWeather.gov JSON endpoint and stores observations in the
station-aware metar_multi table. The legacy FACT metar_obs table is untouched.
"""

import json
import urllib.error
import urllib.request

from airports import AIRPORTS
from config.settings import HTTP_TIMEOUT_SECONDS, USER_AGENT
from db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("multi_metar_collector")

METAR_URL = "https://aviationweather.gov/api/data/metar?ids={}&format=json&hours=3"


def run():
    ids = ",".join(a["icao"] for a in AIRPORTS)
    url = METAR_URL.format(ids)
    con = get_connection()
    try:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            msg = f"METAR request failed: {exc}"
            logger.error(msg)
            log_collection_attempt(con, "multi_metar", False, error_msg=msg)
            return 0

        written = 0
        seen = set()
        for obs in data or []:
            station = (obs.get("icaoId") or obs.get("stationId") or "").upper()
            raw = obs.get("rawOb") or ""
            obs_time = obs.get("obsTime")
            if not station or not raw or obs_time is None or station not in {a["icao"] for a in AIRPORTS}:
                continue
            if isinstance(obs_time, (int, float)):
                from datetime import datetime, timezone
                obs_time = datetime.fromtimestamp(obs_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                obs_time = str(obs_time)
            key = (station, obs_time)
            if key in seen:
                continue
            seen.add(key)
            cur = con.execute(
                """INSERT OR IGNORE INTO metar_multi
                   (station_id, fetched_at, obs_time, receipt_time, temp_c,
                    dewpoint_c, wind_dir_deg, wind_speed_kt, visibility_sm,
                    raw_metar, report_type, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    station, utc_now_iso(), obs_time, str(obs.get("receiptTime") or ""),
                    obs.get("temp"), obs.get("dewp"), obs.get("wdir"),
                    obs.get("wspd"), obs.get("visib"), raw,
                    obs.get("metarType", "METAR"), "aviationweather.gov",
                ),
            )
            if cur.rowcount:
                written += 1

        con.commit()
        log_collection_attempt(con, "multi_metar", True, rows_written=written)
        logger.info("stations=%s new_rows=%s", len(AIRPORTS), written)
        return written
    except Exception as exc:
        con.rollback()
        logger.exception("Collector failure")
        log_collection_attempt(con, "multi_metar", False, error_msg=str(exc))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    run()
