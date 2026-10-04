#!/usr/bin/env python3
"""Ingest The Weather Company PWS rapid 24-hour history."""

import json
import os
import urllib.error
from datetime import datetime, timezone

from .config.settings import HTTP_TIMEOUT_SECONDS
from .db import get_connection, log_collection_attempt, setup_logger, utc_now_iso
from .pws_api import rapid_1day

logger = setup_logger("pws_rapid_collector")


def _num(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _obs_time(obs):
    value = obs.get("obsTimeUtc") or obs.get("epoch")
    if isinstance(value, str):
        return value.replace("+00:00", "Z")
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError):
        return None


def run():
    key = os.getenv("WEATHER_UNDERGROUND_API_KEY")
    con = get_connection()
    try:
        stations = con.execute(
            """SELECT station_id, airport_icao, latitude, longitude, distance_km
               FROM pws_station WHERE enabled=1 ORDER BY distance_km"""
        ).fetchall()
        if not stations:
            log_collection_attempt(con, "pws_rapid", True, rows_written=0)
            return 0
        if not key:
            msg = "WEATHER_UNDERGROUND_API_KEY is not configured"
            log_collection_attempt(con, "pws_rapid", False, error_msg=msg)
            return 0

        written = 0
        failures = []
        for sr in stations:
            station = dict(sr)
            try:
                payload = rapid_1day(station["station_id"], key)
                for obs in payload.get("observations") or []:
                    metric = obs.get("metric") or {}
                    t = _obs_time(obs)
                    if not t:
                        continue
                    # Rapid records are reporting-interval aggregates; tempAvg
                    # is the time-series value, while high/low remain available
                    # in raw_payload for later max-temperature analytics.
                    cur = con.execute(
                        """INSERT OR IGNORE INTO pws_obs_multi
                           (station_id, airport_icao, fetched_at, obs_time,
                            latitude, longitude, distance_km, temp_c, humidity,
                            dewpoint_c, wind_dir_deg, wind_speed_kt,
                            pressure_hpa, source, is_valid, freshness_min,
                            issues, raw_payload)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                                   ?,NULL,NULL,?)""",
                        (
                            station["station_id"], station["airport_icao"],
                            utc_now_iso(), t, station["latitude"],
                            station["longitude"], station["distance_km"],
                            _num(metric.get("tempAvg")),
                            _num(obs.get("humidityAvg")),
                            _num(metric.get("dewptAvg")),
                            _num(obs.get("winddirAvg")),
                            _num(metric.get("windspeedAvg")),
                            _num(metric.get("pressureAvg")),
                            "weather_company_pws_rapid",
                            1 if obs.get("qcStatus", 1) == 1 else 0,
                            json.dumps(obs),
                        ),
                    )
                    written += int(cur.rowcount > 0)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                failures.append(f'{station["station_id"]}: {exc}')
        con.commit()
        msg = "; ".join(failures) if failures else None
        log_collection_attempt(con, "pws_rapid", not failures,
                               rows_written=written, error_msg=msg)
        logger.info("stations=%s written=%s failures=%s",
                    len(stations), written, len(failures))
        return written
    except Exception as exc:
        con.rollback()
        logger.exception("PWS rapid collector failure")
        log_collection_attempt(con, "pws_rapid", False, error_msg=str(exc))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    run()
