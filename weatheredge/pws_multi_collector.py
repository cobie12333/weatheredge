#!/usr/bin/env python3
"""Collect Weather Company PWS 24-hour observations into the canonical PWS table.

All registry entries with enabled=1 are queried. The verified flag is a
research-quality flag, not a collection gate. API credentials are never logged.
"""

import json
import os
import urllib.error
from datetime import datetime, timezone

from .db import get_connection, log_collection_attempt, setup_logger, utc_now_iso
from .pws_api import rapid_1day

logger = setup_logger("pws_multi_collector")


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_from_epoch(value):
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError):
        return None


def _observation_to_row(obs, station):
    metric = obs.get("metric") or obs.get("imperial") or {}
    obs_time = obs.get("obsTimeUtc") or obs.get("epoch") or obs.get("obsTimeLocal")
    if isinstance(obs_time, str):
        obs_time = obs_time.replace("+00:00", "Z")
    else:
        obs_time = _iso_from_epoch(obs_time)

    return {
        "station_id": station["station_id"],
        "airport_icao": station["airport_icao"],
        "obs_time": obs_time,
        "latitude": _num(obs.get("lat")) or station["latitude"],
        "longitude": _num(obs.get("lon")) or station["longitude"],
        "distance_km": station["distance_km"],
        "temp_c": _num(metric.get("tempAvg") if "tempAvg" in metric else metric.get("temp")),
        "humidity": _num(obs.get("humidityAvg") if "humidityAvg" in obs else obs.get("humidity")),
        "dewpoint_c": _num(metric.get("dewptAvg") if "dewptAvg" in metric else metric.get("dewpt")),
        "wind_dir_deg": _num(obs.get("winddirAvg") if "winddirAvg" in obs else obs.get("winddir")),
        "wind_speed_kt": _num(metric.get("windspeedAvg") if "windspeedAvg" in metric else metric.get("windspeed")),
        "pressure_hpa": _num(metric.get("pressureAvg") if "pressureAvg" in metric else metric.get("pressure")),
    }


def run():
    key = os.getenv("WEATHER_UNDERGROUND_API_KEY")
    con = get_connection()
    try:
        stations = con.execute(
            """SELECT station_id, airport_icao, latitude, longitude, distance_km
               FROM pws_station WHERE enabled=1 ORDER BY distance_km"""
        ).fetchall()

        if not stations:
            logger.info("No enabled PWS stations; collector is idle")
            log_collection_attempt(con, "pws_multi", True, rows_written=0)
            return 0

        if not key:
            msg = "WEATHER_UNDERGROUND_API_KEY is not configured"
            logger.warning(msg)
            log_collection_attempt(con, "pws_multi", False, error_msg=msg)
            return 0

        written = 0
        failures = []
        for sr in stations:
            station = dict(sr)
            try:
                payload = rapid_1day(station["station_id"], key)
                observations = payload.get("observations") or []
                if not observations:
                    failures.append(f'{station["station_id"]}: API returned no observations')
                    continue

                for obs in observations:
                    row = _observation_to_row(obs, station)
                    if not row["obs_time"]:
                        continue
                    cur = con.execute(
                        """INSERT OR IGNORE INTO pws_obs_multi
                           (station_id, airport_icao, fetched_at, obs_time,
                            latitude, longitude, distance_km, temp_c, humidity,
                            dewpoint_c, wind_dir_deg, wind_speed_kt,
                            pressure_hpa, source, is_valid, freshness_min,
                            issues, raw_payload)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                   1, NULL, NULL, ?)""",
                        (
                            row["station_id"], row["airport_icao"], utc_now_iso(),
                            row["obs_time"], row["latitude"], row["longitude"],
                            row["distance_km"], row["temp_c"], row["humidity"],
                            row["dewpoint_c"], row["wind_dir_deg"],
                            row["wind_speed_kt"], row["pressure_hpa"],
                            "weather_company", json.dumps(obs),
                        ),
                    )
                    written += int(cur.rowcount > 0)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
                # Avoid printing urllib exception URLs: they can contain the API key.
                detail = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                failures.append(f'{station["station_id"]}: {detail}')

        con.commit()
        msg = "; ".join(failures) if failures else None
        log_collection_attempt(con, "pws_multi", not failures, rows_written=written, error_msg=msg)
        logger.info("stations=%s written=%s failures=%s", len(stations), written, len(failures))
        if failures:
            logger.warning("PWS station issues: %s", msg)
        return written
    except Exception as exc:
        con.rollback()
        logger.exception("PWS collector failure (%s)", type(exc).__name__)
        log_collection_attempt(con, "pws_multi", False, error_msg=type(exc).__name__)
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    run()
