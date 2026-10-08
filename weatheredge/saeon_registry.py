"""High-frequency SAEON research stations.

These are independent environmental sensors, not settlement stations.
They are tracked separately from Weather Underground PWS feeds.
"""

SAEON_STATIONS = [
    {
        "station_id": "STJOSEPHS",
        "airport_icao": "FACT",
        "name": "GCT St Josephs MRC weather station",
        "source": "saeon_lognet",
        "source_url": "https://lognet.saeon.ac.za/StJosephs/index.html",
        "latitude": -33.96307,
        "longitude": 18.57389,
        "elevation_m": 31.0,
        "distance_km": 3.06,
        "sampling_minutes": 5,
        "status": "candidate",
        "verified": 1,
        "enabled": 0,
        "notes": "Screenshot-verified station page states updates every 5 minutes (signal quality dependent). Raw historical endpoint still needs verification before enabling collection.",
    },
]

SAEON_BY_AIRPORT = {}
for station in SAEON_STATIONS:
    SAEON_BY_AIRPORT.setdefault(station["airport_icao"], []).append(station)
