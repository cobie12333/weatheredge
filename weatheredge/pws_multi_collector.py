#!/usr/bin/env python3
"""Collect live Weather Underground PWS observations when an API key is configured.

All registry entries with enabled=1 are queried; verified is a research/quality flag, not a data-collection gate. The provider's documented
documented Weather Company PWS endpoints are used; no undocumented web endpoint is assumed.
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
WU_URL = "https://api.weather.com/v2/pws/observations/all/1day"


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
    obs_time = obs.get("epoch") or obs.get("obsTimeUtc") or obs.get("obsTimeLocal")
    if isinstance(obs_time, str):
        obs_time = obs_time.replace("+00:00", "Z")
    else:
        obs_time = _iso_from_epoch(obs_time)

    temp = _num(metric.get("tempAvg") if "tempAvg" in metric else metric.get("temp"))
    humidity = _num(obs.get("humidityAvg") if "humidityAvg" in obs else obs.get("humidity"))
    wind_dir = _num(obs.get("winddirAvg") if "winddirAvg" in obs else obs.get("winddir"))
    wind_speed = _num(metric.get("windspeedAvg") if "windspeedAvg" in metric else metric.get("windspeed"))
    pressure = _num(metric.get("pressureAvg") if "pressureAvg" in metric else metric.get("pressure"))

    return {
        "station_id": station["station_id"],
        "airport_icao": station["airport_icao"],
        "obs_time": obs_time,
        "latitude": station["latitude"],
        "longitude": station["longitude"],
        "distance_km": station["distance_km"],
        "temp_c": temp,
        "humidity": humidity,
        "dewpoint_c": _num(metric.get("dewpt")),
        "wind_dir_deg": wind_dir,
        "wind_speed_kt": wind_speed,
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
            logger.info("No enabled verified PWS stations; collector is idle")
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
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
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
