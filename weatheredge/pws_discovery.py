"""Discover nearby Weather Company PWS stations into the WeatherEdge registry."""
from . import pws_api
from .airports import AIRPORTS
from .db import get_connection

def run():
    key = pws_api.api_key()
    if not key:
        return 0
    con = get_connection()
    added = 0
    try:
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
                con.execute("""INSERT INTO pws_station
                    (station_id,airport_icao,name,source,source_url,latitude,longitude,
                     distance_km,status,verified,enabled,notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(station_id) DO UPDATE SET
                      airport_icao=excluded.airport_icao,name=excluded.name,
                      latitude=excluded.latitude,longitude=excluded.longitude,
                      distance_km=excluded.distance_km,status=excluded.status""",
                    (station_id, airport["icao"], at("stationName"), "weather_company",
                     "https://www.wunderground.com/dashboard/pws/" + station_id,
                     at("latitude"), at("longitude"), at("distanceKm"),
                     "qc_ok" if at("qcStatus") == 1 else "candidate",
                     0, 1, "Auto-discovered; not a settlement sensor."))
                added += 1
        con.commit()
        return added
    finally:
        con.close()

if __name__ == "__main__":
    print(run())
