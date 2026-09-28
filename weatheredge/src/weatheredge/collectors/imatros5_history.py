"""IMATRO5 historical observation adapter.

IMATRO5 is treated as an independent PWS source, never as FACT settlement
truth. The adapter accepts normalized CSV/JSON records so historical data can
be imported without assuming that a WU webpage exposes a particular sampling
interval.

Expected normalized fields:
  observed_at,temp_c,dewpoint_c,humidity_pct,wind_dir_deg,wind_speed_ms,
  gust_ms,pressure_hpa
"""

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SOURCE_ID = "wu:IMATRO5"
STATION_ID = "IMATRO5"


def _utc(value: str) -> str:
    value = value.strip()
    if value.endswith("Z"):
        return value
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _f(row, *names):
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return float(value)
    return None


def load_csv(path: str, con: sqlite3.Connection, fetched_at: str = None) -> int:
    """Import already-obtained IMATRO5 observations without inventing timestamps."""
    count = 0
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            observed_at = _utc(row["observed_at"])
            con.execute(
                """
                INSERT OR IGNORE INTO weather_observation
                (source_id, station_id, observed_at, fetched_at, temp_c,
                 dewpoint_c, humidity_pct, wind_dir_deg, wind_speed_ms,
                 gust_ms, pressure_hpa, raw_payload, quality_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    SOURCE_ID, STATION_ID, observed_at, fetched_at,
                    _f(row, "temp_c", "temp"),
                    _f(row, "dewpoint_c", "dewpoint"),
                    _f(row, "humidity_pct", "humidity"),
                    _f(row, "wind_dir_deg", "wind_dir"),
                    _f(row, "wind_speed_ms", "wind_speed"),
                    _f(row, "gust_ms", "gust"),
                    _f(row, "pressure_hpa", "pressure"),
                    json.dumps(row, sort_keys=True),
                    "imported_unverified",
                ),
            )
            count += 1
    con.commit()
    return count
