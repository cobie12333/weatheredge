#!/usr/bin/env python3
"""Small dependency-free client for The Weather Company PWS APIs.

The API key is read from WEATHER_UNDERGROUND_API_KEY for compatibility with
the existing WeatherEdge deployment. Never include the key in logs/errors.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .config.settings import HTTP_TIMEOUT_SECONDS, USER_AGENT

BASE_V2 = "https://api.weather.com/v2"
BASE_V3 = "https://api.weather.com/v3"


def _get(base, path, params):
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{base}{path}?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            # Some station/endpoint combinations legitimately return HTTP 204.
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status == 204 or not body.strip():
                return {"observations": []}
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        # urllib's default exception string contains the full URL, including apiKey.
        raise RuntimeError(f"Weather Company API HTTP {exc.code} for {path}") from None


def api_key():
    return os.getenv("WEATHER_UNDERGROUND_API_KEY")


def current(station_id, key):
    return _get(BASE_V2, "/pws/observations/current", {
        "stationId": station_id,
        "format": "json",
        "units": "m",
        "numericPrecision": "decimal",
        "apiKey": key,
    })


def rapid_1day(station_id, key):
    return _get(BASE_V2, "/pws/observations/all/1day", {
        "stationId": station_id,
        "format": "json",
        "units": "m",
        "numericPrecision": "decimal",
        "apiKey": key,
    })


def discover_near(lat, lon, key):
    return _get(BASE_V3, "/location/near", {
        "geocode": f"{lat:.6f},{lon:.6f}",
        "product": "pws",
        "format": "json",
        "apiKey": key,
    })
