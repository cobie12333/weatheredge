#!/usr/bin/env python3
"""Probe curated PWS candidates against the authenticated live observations API.

Only stations returning a fresh, valid observation with usable coordinates and
a positive quality-control flag are enabled. Defaults to FACT to avoid spending
API calls on an entire international watchlist during initial bring-up.
"""
import argparse
import math
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError

from . import pws_api
from .airports import AIRPORT_BY_ICAO
from .db import get_connection
from .nearby_pws_watchlist import PWS_WATCHLIST
from .pws_discovery import seed_watchlist

MAX_OBSERVATION_AGE_SECONDS = 60 * 60
MAX_FUTURE_SKEW_SECONDS = 5 * 60


def _timestamp(obs):
    epoch = obs.get("epoch")
    if epoch is not None:
        try:
            return datetime.fromtimestamp(float(epoch), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            return None
    value = obs.get("obsTimeUtc")
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _distance_km(lat1, lon1, lat2, lon2):
    radius_km = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius_km * math.asin(min(1.0, math.sqrt(value)))


def validate_observation(station_id, airport_icao, obs, now=None):
    """Return verified station metadata or a reason the probe must be rejected."""
    now = now or datetime.now(timezone.utc)
    returned_id = obs.get("stationID") or obs.get("stationId")
    if not returned_id or str(returned_id).upper() != station_id.upper():
        return None, "station_id_mismatch"

    if str(obs.get("qcStatus", "")) != "1":
        return None, "quality_control_not_passed"

    obs_time = _timestamp(obs)
    if obs_time is None:
        return None, "missing_or_invalid_observation_time"
    age = (now - obs_time).total_seconds()
    if age < -MAX_FUTURE_SKEW_SECONDS:
        return None, "observation_time_in_future"
    if age > MAX_OBSERVATION_AGE_SECONDS:
        return None, "observation_stale"

    measurements = obs.get("metric") or obs.get("metric_si") or {}
    temp = measurements.get("temp")
    if temp is None:
        temp = measurements.get("tempAvg")
    if temp is None:
        return None, "missing_temperature"

    lat, lon = obs.get("lat"), obs.get("lon")
    try:
        lat, lon, temp = float(lat), float(lon), float(temp)
    except (TypeError, ValueError):
        return None, "missing_or_invalid_coordinates_or_temperature"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, "invalid_coordinates"

    airport = AIRPORT_BY_ICAO.get(airport_icao)
    if not airport:
        return None, "airport_coordinates_not_configured"
    distance = _distance_km(airport["lat"], airport["lon"], lat, lon)
    return {
        "latitude": lat,
        "longitude": lon,
        "distance_km": round(distance, 3),
        "obs_time": obs_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "temp_c": temp,
        "qc_status": 1,
    }, None


def activate_airport(airport_icao, api_key, con, now=None):
    code = airport_icao.upper()
    if code not in AIRPORT_BY_ICAO:
        print(f"{code}: skipped; airport is not in WeatherEdge's canonical airport registry")
        return 0

    candidates = [s for s in PWS_WATCHLIST if s["airport_icao"] == code]
    if not candidates:
        print(f"{code}: no curated PWS candidates")
        return 0

    activated = 0
    for candidate in candidates:
        station_id = candidate["station_id"]
        try:
            payload = pws_api.current(station_id, api_key)
            observations = payload.get("observations") or []
            if not observations:
                reason = "offline_or_no_recent_observation"
                con.execute(
                    """UPDATE pws_station SET status=?, verified=0, enabled=0, notes=?
                       WHERE station_id=?""",
                    (reason, "Live probe returned no current observation; kept disabled.", station_id),
                )
                print(f"{station_id}: NOT LIVE ({reason})")
                continue

            verified, reason = validate_observation(station_id, code, observations[0], now=now)
            if reason:
                con.execute(
                    """UPDATE pws_station SET status=?, verified=0, enabled=0, notes=?
                       WHERE station_id=?""",
                    (reason, f"Live probe rejected observation: {reason}; kept disabled.", station_id),
                )
                print(f"{station_id}: NOT LIVE ({reason})")
                continue

            con.execute(
                """UPDATE pws_station
                   SET latitude=?, longitude=?, distance_km=?, status='live_verified',
                       verified=1, enabled=1, notes=?
                   WHERE station_id=?""",
                (
                    verified["latitude"], verified["longitude"], verified["distance_km"],
                    f"Live API probe passed QC; observation {verified['obs_time']} "
                    f"at {verified['temp_c']:.1f} C. Research input, not settlement sensor.",
                    station_id,
                ),
            )
            activated += 1
            print(
                f"{station_id}: LIVE {verified['temp_c']:.1f} C, "
                f"{verified['distance_km']:.2f} km from {code}, "
                f"observed {verified['obs_time']}"
            )
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            reason = f"probe_error:{type(exc).__name__}"
            con.execute(
                """UPDATE pws_station SET status=?, verified=0, enabled=0, notes=?
                   WHERE station_id=?""",
                (reason, "Live API probe failed; kept disabled. Check API key/network.", station_id),
            )
            print(f"{station_id}: NOT LIVE ({reason})")
    con.commit()
    return activated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--airport", default="FACT",
        help="comma-separated canonical airport ICAO code(s); defaults to FACT",
    )
    args = parser.parse_args()
    key = pws_api.api_key()
    con = get_connection()
    try:
        seeded = seed_watchlist(con)
        con.commit()
        if not key:
            print(
                f"Seeded {seeded} new watchlist station(s). No live PWS probe performed: "
                "WEATHER_UNDERGROUND_API_KEY is not set. No station was enabled."
            )
            return 2
        total = 0
        for code in dict.fromkeys(x.strip().upper() for x in args.airport.split(",") if x.strip()):
            total += activate_airport(code, key, con)
        print(f"Live PWS activation complete: {total} station(s) passed live validation.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
