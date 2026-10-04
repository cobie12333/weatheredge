#!/usr/bin/env python3
"""JSON endpoints for WeatherEdge sensor time series and comparison."""

import json
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

from db import get_connection
from airports import AIRPORTS


def _age_minutes(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return round(max(0, (datetime.now(timezone.utc) - dt).total_seconds() / 60), 1)
    except ValueError:
        return None


def _airport(icao):
    return next((a for a in AIRPORTS if a["icao"] == icao), None)


def _trend(rows):
    vals = [(r["obs_time"], r["temp_c"]) for r in rows if r["temp_c"] is not None]
    if len(vals) < 2:
        return None
    first_t = datetime.fromisoformat(vals[0][0].replace("Z", "+00:00"))
    last_t = datetime.fromisoformat(vals[-1][0].replace("Z", "+00:00"))
    hours = (last_t - first_t).total_seconds() / 3600
    if hours <= 0:
        return None
    return round((vals[-1][1] - vals[0][1]) / hours, 3)


def timeseries(icao, hours=24):
    airport = _airport(icao)
    if not airport:
        return {"error": "unknown airport"}
    hours = max(1, min(int(hours), 168))
    con = get_connection(readonly=True)
    try:
        rows = con.execute(
            """SELECT station_id, obs_time, temp_c, source, distance_km, is_valid
               FROM pws_obs_multi
               WHERE airport_icao = ?
                 AND obs_time >= datetime('now', ?)
                 AND temp_c IS NOT NULL
               ORDER BY obs_time ASC""",
            (icao, f"-{hours} hours"),
        ).fetchall()
        metar = con.execute(
            """SELECT obs_time, temp_c FROM metar_multi
               WHERE station_id=? AND obs_time >= datetime('now', ?)
               AND temp_c IS NOT NULL ORDER BY obs_time ASC""",
            (icao, f"-{hours} hours"),
        ).fetchall()
        return {
            "icao": icao,
            "city": airport["city"],
            "hours": hours,
            "series": [
                {
                    "station_id": r["station_id"],
                    "obs_time": r["obs_time"],
                    "temp_c": r["temp_c"],
                    "source": r["source"],
                    "distance_km": r["distance_km"],
                    "is_valid": bool(r["is_valid"]),
                }
                for r in rows
            ],
            "metar": [{"obs_time": r["obs_time"], "temp_c": r["temp_c"]} for r in metar],
        }
    finally:
        con.close()


def comparison(icao):
    airport = _airport(icao)
    if not airport:
        return {"error": "unknown airport"}
    con = get_connection(readonly=True)
    try:
        metar = con.execute(
            """SELECT obs_time,temp_c FROM metar_multi
               WHERE station_id=? ORDER BY obs_time DESC LIMIT 1""", (icao,)
        ).fetchone()
        stations = con.execute(
            """SELECT s.station_id,s.name,s.distance_km,s.status,s.verified,s.enabled,
                      o.temp_c,o.obs_time,o.source,o.is_valid
               FROM pws_station s
               LEFT JOIN pws_obs_multi o ON o.id=(
                 SELECT x.id FROM pws_obs_multi x
                 WHERE x.station_id=s.station_id
                 ORDER BY x.obs_time DESC LIMIT 1)
               WHERE s.airport_icao=? AND s.verified=1
               ORDER BY s.distance_km""", (icao,)
        ).fetchall()
        settlement = metar["temp_c"] if metar else None
        pws = []
        for s in stations:
            spread = None if settlement is None or s["temp_c"] is None else round(s["temp_c"] - settlement, 2)
            pws.append({
                "station_id": s["station_id"],
                "name": s["name"],
                "distance_km": s["distance_km"],
                "status": s["status"],
                "verified": bool(s["verified"]),
                "enabled": bool(s["enabled"]),
                "temp_c": s["temp_c"],
                "obs_time": s["obs_time"],
                "source": s["source"],
                "is_valid": bool(s["is_valid"]) if s["is_valid"] is not None else None,
                "age_min": _age_minutes(s["obs_time"]),
                "spread_vs_settlement_c": spread,
            })
        return {
            "icao": icao,
            "city": airport["city"],
            "settlement_sensor": {
                "source": "METAR",
                "station_id": icao,
                "temp_c": settlement,
                "obs_time": metar["obs_time"] if metar else None,
                "age_min": _age_minutes(metar["obs_time"]) if metar else None,
            },
            "pws": pws,
        }
    finally:
        con.close()


def handle(path):
    parsed = urlparse(path)
    parts = parsed.path.strip("/").split("/")
    if len(parts) == 4 and parts[:3] == ["api", "airport", parts[2]] and parts[3] == "timeseries":
        q = parse_qs(parsed.query)
        hours = q.get("hours", ["24"])[0]
        try:
            return 200, timeseries(parts[2], int(hours))
        except ValueError:
            return 400, {"error": "hours must be an integer"}
    if len(parts) == 4 and parts[:3] == ["api", "airport", parts[2]] and parts[3] == "sensor-comparison":
        return 200, comparison(parts[2])
    return None
