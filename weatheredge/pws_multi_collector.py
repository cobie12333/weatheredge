#!/usr/bin/env python3
"""Collect live Weather Underground PWS observations when an API key is configured.

Only stations with enabled=1 are queried. Curated watchlist candidates remain
disabled unless a live probe explicitly verifies them. The documented Weather
Company PWS endpoint is used.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .config.settings import HTTP_TIMEOUT_SECONDS, USER_AGENT
from .db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("pws_multi_collector")
WU_URL = "https://api.weather.com/v2/pws/observations/current"


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
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _first(mapping, *keys):
    for key in keys:
        if mapping.get(key) is not None:
            return mapping[key]
    return None


def _observation_to_row(obs, station):
    metric = obs.get("metric") or obs.get("metric_si") or obs.get("imperial") or {}
    obs_time = _first(obs, "epoch", "obsTimeUtc", "obsTimeLocal")
    if isinstance(obs_time, str):
        obs_time = obs_time.replace("+00:00", "Z")
    else:
        obs_time = _iso_from_epoch(obs_time)

    temp = _num(_first(metric, "temp", "tempAvg"))
    humidity = _num(_first(obs, "humidityAvg", "humidity"))
    wind_dir = _num(_first(obs, "winddirAvg", "winddir"))
    # units=m is requested below, so wind speed arrives in km/h. The database
    # column is knots; convert rather than silently recording the wrong unit.
    wind_speed_kmh = _num(_first(metric, "windSpeed", "windspeed", "windSpeedAvg", "windspeedAvg"))
    wind_speed_kt = wind_speed_kmh / 1.852 if wind_speed_kmh is not None else None
    pressure = _num(_first(metric, "pressureAvg", "pressure"))

    return {
        "station_id": station["station_id"],
        "airport_icao": station["airport_icao"],
        "obs_time": obs_time,
        "latitude": station["latitude"],
        "longitude": station["longitude"],
        "distance_km": station["distance_km"],
        "temp_c": temp,
        "humidity": humidity,
        "dewpoint_c": _num(_first(metric, "dewpt", "dewPoint")),
        "wind_dir_deg": wind_dir,
        "wind_speed_kt": wind_speed_kt,
        "pressure_hpa": pressure,
    }


def fetch_station(station_id, api_key):
    params = urllib.parse.urlencode({
        "stationId": station_id,
        "format": "json",
        "units": "m",
        "numericPrecision": "decimal",
        "apiKey": api_key,
    })
    req = urllib.request.Request(
        f"{WU_URL}?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run():
    api_key = os.getenv("WEATHER_UNDERGROUND_API_KEY")
    con = get_connection()
    try:
        stations = con.execute(
            """SELECT station_id, airport_icao, latitude, longitude, distance_km
               FROM pws_station
               WHERE enabled = 1
               ORDER BY distance_km"""
        ).fetchall()

        if not stations:
            logger.info("No enabled PWS stations; collector is idle")
            log_collection_attempt(con, "pws_multi", True, rows_written=0)
            return 0

        if not api_key:
            msg = "WEATHER_UNDERGROUND_API_KEY is not configured"
            logger.warning(msg)
            log_collection_attempt(con, "pws_multi", False, error_msg=msg)
            return 0

        written = 0
        failures = []
        for station_row in stations:
            station = dict(station_row)
            try:
                payload = fetch_station(station["station_id"], api_key)
                observations = payload.get("observations") or []
                if not observations:
                    failures.append(f'{station["station_id"]}: no observations')
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
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                failures.append(f'{station["station_id"]}: {exc}')

        con.commit()
        success = not failures
        msg = "; ".join(failures) if failures else None
        log_collection_attempt(con, "pws_multi", success, rows_written=written, error_msg=msg)
        logger.info("stations=%s written=%s failures=%s", len(stations), written, len(failures))
        return written
    except Exception as exc:
        con.rollback()
        logger.exception("PWS collector failure")
        log_collection_attempt(con, "pws_multi", False, error_msg=str(exc))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    run()
