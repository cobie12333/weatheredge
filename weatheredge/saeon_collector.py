#!/usr/bin/env python3
"""Collect high-frequency SAEON observations.

The public St Josephs page is a presentation layer. Until its raw CSV/JSON
endpoint is independently verified, collection remains disabled by default.
Set SAEON_STJOSEPHS_DATA_URL to a verified CSV or JSON endpoint before enabling
the station in the database.
"""

import csv
import io
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .config.settings import HTTP_TIMEOUT_SECONDS, USER_AGENT
from .db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("saeon_collector")

# Station metadata verified from the public SAEON St Josephs MRC page.
# Raw observation endpoint is intentionally NOT assumed; keep collection disabled
# until the endpoint is independently verified.
STJOSEPHS = {
    "station_id": "STJOSEPHS",
    "airport_icao": "FACT",
    "name": "GCT St Josephs MRC weather station",
    "source": "saeon_lognet",
    "source_url": "https://lognet.saeon.ac.za/StJosephs/index.html",
    "latitude": -33.96307,
    "longitude": 18.57389,
    "elevation_m": 31.0,
    "distance_km": 3.0603,
    "sampling_minutes": 5,
}


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick(row, *keys):
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _iso(value):
    if value is None:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                dt = datetime.strptime(str(value).strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(payload, content_type):
    if "json" in content_type.lower() or payload.lstrip().startswith(("{", "[")):
        data = json.loads(payload)
        if isinstance(data, dict):
            data = data.get("observations") or data.get("data") or []
        return data if isinstance(data, list) else []
    return list(csv.DictReader(io.StringIO(payload)))


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        return resp.read().decode("utf-8"), resp.headers.get("Content-Type", "")


def run():
    data_url = os.getenv("SAEON_STJOSEPHS_DATA_URL")
    con = get_connection()
    try:
        # Keep the station in the canonical registry even before its raw feed
        # is verified. This makes it visible to research tooling without
        # allowing an unverified endpoint to enter the live collector.
        con.execute(
            """INSERT INTO saeon_station
               (station_id, airport_icao, name, source, source_url,
                latitude, longitude, elevation_m, distance_km,
                sampling_minutes, status, verified, enabled, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
               ON CONFLICT(station_id) DO UPDATE SET
                 name=excluded.name, source_url=excluded.source_url,
                 latitude=excluded.latitude, longitude=excluded.longitude,
                 elevation_m=excluded.elevation_m, distance_km=excluded.distance_km,
                 sampling_minutes=excluded.sampling_minutes,
                 status=excluded.status, verified=excluded.verified,
                 notes=excluded.notes""",
            (
                STJOSEPHS["station_id"], STJOSEPHS["airport_icao"],
                STJOSEPHS["name"], STJOSEPHS["source"], STJOSEPHS["source_url"],
                STJOSEPHS["latitude"], STJOSEPHS["longitude"],
                STJOSEPHS["elevation_m"], STJOSEPHS["distance_km"],
                STJOSEPHS["sampling_minutes"], "candidate", 1,
                "Public station page verified; raw CSV/JSON endpoint still pending independent verification.",
            ),
        )
        con.commit()

        enabled = con.execute(
            "SELECT enabled FROM saeon_station WHERE station_id='STJOSEPHS'"
        ).fetchone()
        if not enabled or not enabled["enabled"]:
            logger.info("STJOSEPHS disabled pending raw endpoint verification")
            log_collection_attempt(con, "saeon", True, rows_written=0)
            return 0
        if not data_url:
            msg = "SAEON_STJOSEPHS_DATA_URL is not configured"
            logger.warning(msg)
            log_collection_attempt(con, "saeon", False, error_msg=msg)
            return 0

        payload, content_type = fetch(data_url)
        written = 0
        for item in _rows(payload, content_type):
            obs_time = _iso(_pick(item, "timestamp", "obs_time", "time", "date_time", "datetime"))
            temp = _num(_pick(item, "temperature", "temp", "temp_c"))
            if not obs_time or temp is None:
                continue
            values = (
                "STJOSEPHS", "FACT", utc_now_iso(), obs_time, temp,
                _num(_pick(item, "humidity", "rh")),
                _num(_pick(item, "dewpoint", "dew_point", "dewpoint_c")),
                _num(_pick(item, "wind_direction", "wind_dir", "wind_dir_deg")),
                _num(_pick(item, "wind_speed", "windspeed", "wind_speed_ms")),
                _num(_pick(item, "pressure", "pressure_hpa")),
                _num(_pick(item, "solar_radiation", "solar", "solar_radiation_wm2")),
                "saeon_lognet", 1, json.dumps(item, separators=(",", ":")),
            )
            cur = con.execute(
                """INSERT OR IGNORE INTO saeon_obs
                   (station_id,airport_icao,fetched_at,obs_time,temp_c,humidity,
                    dewpoint_c,wind_dir_deg,wind_speed,pressure_hpa,
                    solar_radiation_wm2,source,is_valid,raw_payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                values,
            )
            written += int(cur.rowcount > 0)
        con.commit()
        log_collection_attempt(con, "saeon", True, rows_written=written)
        logger.info("STJOSEPHS rows_written=%s", written)
        return written
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        con.rollback()
        logger.exception("SAEON collection failed")
        log_collection_attempt(con, "saeon", False, error_msg=str(exc))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    run()
