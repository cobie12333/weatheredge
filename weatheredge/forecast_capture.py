#!/usr/bin/env python3
"""Capture live forecast vintages so forecast skill can be scored later.

A forecast is only evidence if it was stored BEFORE the outcome was known.
This module stores an hourly 2 m temperature forecast per airport in
`forecast_history_multi` with the lead time (hours between fetch and valid
time). The same request shape (hourly=temperature_2m, timezone=UTC, models=...)
is already used by `backfill_openmeteo.py`.

Open-Meteo is free for non-commercial use with no key. Paid client work needs
their commercial terms.

NOT YET VERIFIED LIVE: the sandbox this was written in could not reach
api.open-meteo.com. The parser is tested against a fixture shaped like the
documented response, not against a real response. Check the first rows on
your machine (see README section "RealityOS foundations").

Usage:
    python -m weatheredge.forecast_capture
    python -m weatheredge.forecast_capture --models gfs_seamless,ecmwf_ifs025 --days 3
"""

import argparse
import json
import urllib.request
from datetime import datetime, timezone

from .airports import AIRPORTS
from .config.settings import USER_AGENT
from .db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("forecast_capture")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_MODELS = ("gfs_seamless",)
DEFAULT_DAYS = 3


def build_url(lat, lon, model, days):
    return (
        f"{OPEN_METEO_URL}?latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m&models={model}&forecast_days={days}&timezone=UTC"
    )


def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_hourly(data, model):
    """Return [(valid_time_iso_z, temp_c)] from an Open-Meteo hourly response."""
    hourly = (data or {}).get("hourly") or {}
    times = hourly.get("time") or []
    values = hourly.get("temperature_2m")
    if values is None:
        values = hourly.get(f"temperature_2m_{model}")  # multi-model responses suffix the name
    if not times or not values:
        return []
    out = []
    for t, v in zip(times, values):
        if v is None:
            continue
        try:
            dt = datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        out.append((dt.strftime("%Y-%m-%dT%H:%M:%SZ"), float(v)))
    return out


def store(con, icao, model, points, fetched_at):
    """Insert points with lead_hours >= 0. Returns rows written."""
    fetched = datetime.strptime(fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    written = 0
    for valid_time, temp in points:
        valid = datetime.strptime(valid_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        lead = int((valid - fetched).total_seconds() // 3600)
        if lead < 0:
            continue  # already-observed hours are not forecasts
        cur = con.execute(
            """INSERT OR IGNORE INTO forecast_history_multi
               (station_id, fetched_at, valid_time, lead_hours, model, temp_c, source, raw_payload)
               VALUES (?, ?, ?, ?, ?, ?, 'live_openmeteo', NULL)""",
            (icao, fetched_at, valid_time, lead, model, temp),
        )
        written += int(cur.rowcount > 0)
    return written


def run(models=DEFAULT_MODELS, days=DEFAULT_DAYS, airports=None):
    con = get_connection()
    total = 0
    try:
        for a in airports or AIRPORTS:
            for model in models:
                name = f"forecast:{a['icao']}:{model}"
                try:
                    data = fetch_json(build_url(a["lat"], a["lon"], model, days))
                    points = parse_hourly(data, model)
                    if not points:
                        raise ValueError("no hourly temperature_2m in response")
                    n = store(con, a["icao"], model, points, utc_now_iso())
                    con.commit()
                    total += n
                    log_collection_attempt(con, name, True, rows_written=n)
                except Exception as exc:  # one airport/model failing must not stop the rest
                    con.rollback()
                    logger.error("%s failed: %s", name, exc)
                    log_collection_attempt(con, name, False, error_msg=str(exc)[:300])
        return total
    finally:
        con.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", default=",".join(DEFAULT_MODELS))
    p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    a = p.parse_args(argv)
    print("rows written:", run(tuple(m.strip() for m in a.models.split(",") if m.strip()), a.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
