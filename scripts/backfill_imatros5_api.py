#!/usr/bin/env python3
"""Backfill IMATRO5 PWS history from The Weather Company PWS Historical API.

Requires:
  export WEATHER_COMPANY_API_KEY='...'

The API supports hourly, all-native-interval, and daily PWS history.
For research, use /v2/pws/history/all so we do not silently destroy
the station's native reporting cadence.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, ".")
from weatheredge.db import get_connection, utc_now_iso

BASE = "https://api.weather.com/v2/pws/history"
STATION_ID = "IMATRO5"


def fetch_day(target: date, api_key: str) -> list:
    params = urllib.parse.urlencode({
        "apiKey": api_key,
        "stationId": STATION_ID,
        "date": target.isoformat(),
        "format": "json",
        "numericPrecision": "decimal",
        "units": "m",
    })
    req = urllib.request.Request(
        f"{BASE}/all?{params}",
        headers={"User-Agent": "weatheredge-research/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("observations", [])


def first_number(value):
    if isinstance(value, dict):
        return value.get("value")
    return value


def normalize_time(obs):
    raw = obs.get("obsTimeUtc") or obs.get("obsTimeLocal") or obs.get("obsTime")
    if not raw:
        return None
    if isinstance(raw, str):
        if raw.endswith("Z"):
            return raw
        # Weather Company commonly returns YYYYMMDDHHMMSS for obsTimeUtc.
        if len(raw) == 14 and raw.isdigit():
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}T{raw[8:10]}:{raw[10:12]}:{raw[12:14]}Z"
    return raw


def store(con, obs):
    metric = obs.get("metric") or {}
    observed_at = normalize_time(obs)
    if not observed_at:
        return False

    row = (
        STATION_ID,
        STATION_ID,
        observed_at,
        utc_now_iso(),
        first_number(metric.get("temp")),
        first_number(metric.get("dewPt")),
        first_number(metric.get("humidity")),
        first_number(metric.get("winddir")),
        first_number(metric.get("wspd")),
        first_number(metric.get("gust")),
        first_number(metric.get("pressure")),
        json.dumps(obs, separators=(",", ":")),
        "imported_twc_pws_history",
    )
    con.execute(
        """
        INSERT OR IGNORE INTO weather_observation
        (source_id, station_id, observed_at, fetched_at, temp_c, dewpoint_c,
         humidity_pct, wind_dir_deg, wind_speed_ms, gust_ms, pressure_hpa,
         raw_payload, quality_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        row,
    )
    return True


def backfill(start: date, end: date):
    api_key = os.environ.get("WEATHER_COMPANY_API_KEY")
    if not api_key:
        raise SystemExit(
            "WEATHER_COMPANY_API_KEY is not set. "
            "Get a Weather Company API key, then export it before running."
        )

    con = get_connection()
    total = 0
    days = 0
    try:
        d = start
        while d <= end:
            observations = fetch_day(d, api_key)
            written = 0
            for obs in observations:
                if store(con, obs):
                    written += 1
            con.commit()
            print(f"{d}: {len(observations)} observations")
            total += written
            days += 1
            d += timedelta(days=1)
    finally:
        con.close()

    print(json.dumps({"days": days, "rows_seen": total}, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 scripts/backfill_imatros5_api.py YYYY-MM-DD YYYY-MM-DD")
        raise SystemExit(2)
    backfill(date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2]))
