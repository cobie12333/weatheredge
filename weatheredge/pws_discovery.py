"""Discover PWS stations and seed the curated nearby-station watchlist."""
from . import pws_api
from .airports import AIRPORTS
from .nearby_pws_watchlist import PWS_WATCHLIST
from .db import get_connection


def seed_watchlist(con):
    """Insert curated PWS candidates without inventing coordinates or enabling collection.

    Existing station rows are deliberately left untouched. In particular, a
    curated watchlist entry is not automatically enabled merely because the
    discovery API later returns it.
    """
    inserted = 0
    for station in PWS_WATCHLIST:
        cur = con.execute(
            """INSERT OR IGNORE INTO pws_station
               (station_id, airport_icao, name, source, source_url,
                latitude, longitude, distance_km, status, verified, enabled, notes)
               VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, 'candidate', 0, 0, ?)""",
            (
                station["station_id"],
                station["airport_icao"],
                station["city"] + " PWS watchlist candidate",
                station["source"],
                station["source_url"],
                "Imported from nearby PWS watchlist; coordinates, current status, "
                "and live feed not yet independently verified.",
            ),
        )
        inserted += max(cur.rowcount, 0)
    return inserted


def run():
    con = get_connection()
    try:
        # Always populate the local registry, even when no API key is available.
        seeded = seed_watchlist(con)
        con.commit()

        key = pws_api.api_key()
        if not key:
            return seeded

        added = seeded
        for airport in AIRPORTS:
            payload = pws_api.discover_near(airport["lat"], airport["lon"], key)
            loc = payload.get("location") or {}
            ids = loc.get("stationId") or []
            for i, station_id in enumerate(ids):
                if not station_id:
                    continue

                def at(name, default=None):
                    values = loc.get(name) or []
                    return values[i] if i < len(values) else default

                con.execute(
                    """INSERT INTO pws_station
                       (station_id,airport_icao,name,source,source_url,latitude,longitude,
                        distance_km,status,verified,enabled,notes)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(station_id) DO UPDATE SET
                         airport_icao=excluded.airport_icao,name=excluded.name,
                         latitude=excluded.latitude,longitude=excluded.longitude,
                         distance_km=excluded.distance_km,status=excluded.status""",
                    (
                        station_id, airport["icao"], at("stationName"),
                        "weather_company",
                        "https://www.wunderground.com/dashboard/pws/" + station_id,
                        at("latitude"), at("longitude"), at("distanceKm"),
                        "qc_ok" if at("qcStatus") == 1 else "candidate",
                        0, 1, "Auto-discovered; not a settlement sensor.",
                    ),
                )
                added += 1
        con.commit()
        return added
    finally:
        con.close()


if __name__ == "__main__":
    print(run())
