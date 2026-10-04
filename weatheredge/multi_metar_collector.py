#!/usr/bin/env python3
"""Collect current METAR/SPECI observations for all configured airports."""

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .airports import AIRPORTS
from .config.settings import HTTP_TIMEOUT_SECONDS, USER_AGENT
from .db import get_connection, init_schema, log_collection_attempt, setup_logger, utc_now_iso
from .pws_registry import PWS_STATIONS

logger = setup_logger("multi_metar_collector")

METAR_URL = "https://aviationweather.gov/api/data/metar?ids={}&format=json&hours=6"
STATION_IDS = {a["icao"] for a in AIRPORTS}


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.upper() in {"", "VRB", "M", "NA", "N/A"}:
        return None
    if text.endswith("+"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _obs_time(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value) if value is not None else None


def seed_pws_registry(con):
    for pws in PWS_STATIONS:
        con.execute(
            """INSERT INTO pws_station
               (station_id, airport_icao, name, source, source_url, latitude,
                longitude, distance_km, status, verified, enabled, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(station_id) DO UPDATE SET
                 airport_icao=excluded.airport_icao,
                 name=excluded.name,
                 source=excluded.source,
                 source_url=excluded.source_url,
                 latitude=excluded.latitude,
                 longitude=excluded.longitude,
                 distance_km=excluded.distance_km,
                 status=excluded.status,
                 verified=excluded.verified,
                 notes=excluded.notes""",
            (
                pws["station_id"], pws["airport_icao"], pws["name"], pws["source"],
                pws["source_url"], pws["lat"], pws["lon"], pws["distance_km"],
                pws["status"], pws["verified"], pws["enabled"], pws["notes"],
            ),
        )


def run():
    init_schema()
    ids = ",".join(a["icao"] for a in AIRPORTS)
    url = METAR_URL.format(ids)
    con = get_connection()
    try:
        seed_pws_registry(con)
        con.commit()

        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            msg = f"METAR request failed: {exc}"
            logger.error(msg)
            log_collection_attempt(con, "multi_metar", False, error_msg=msg)
            return 0

        if not isinstance(data, list) or not data:
            msg = "METAR API returned no observations"
            logger.error(msg)
            log_collection_attempt(con, "multi_metar", False, error_msg=msg)
            return 0

        received = set()
        written = 0
        seen = set()

        for obs in data:
            station = (obs.get("icaoId") or obs.get("stationId") or "").upper()
            raw = obs.get("rawOb") or ""
            obs_time = _obs_time(obs.get("obsTime"))
            if station not in STATION_IDS or not raw or not obs_time:
                continue
            received.add(station)

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
                    station, utc_now_iso(), obs_time,
                    str(obs.get("receiptTime") or "") or None,
                    _num(obs.get("temp")), _num(obs.get("dewp")),
                    _num(obs.get("wdir")), _num(obs.get("wspd")),
                    _num(obs.get("visib")), raw,
                    obs.get("metarType", "METAR"), "aviationweather.gov",
                ),
            )
            if cur.rowcount:
                written += 1

        missing = sorted(STATION_IDS - received)
        success = not missing
        msg = None if success else f"Missing stations: {', '.join(missing)}"
        con.commit()
        log_collection_attempt(con, "multi_metar", success, rows_written=written, error_msg=msg)

        logger.info(
            "requested=%s received=%s missing=%s new_rows=%s",
            len(STATION_IDS), len(received), ",".join(missing) or "-", written,
        )
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
