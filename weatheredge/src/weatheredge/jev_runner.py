"""Live Jev scoring for WeatherEdge; never places trades."""
from __future__ import annotations
import json, sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from .config.settings import DB_PATH
from .jev import JevError
from .jev_predictor import build_state, score_weather_state

def _connect():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; return conn

def _latest(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None

def _market_buckets(conn, station_id, market_date):
    rows = conn.execute("""SELECT DISTINCT bucket_label FROM market_price_multi
        WHERE station_id=? AND market_date=? ORDER BY CAST(bucket_label AS REAL)""",
        (station_id, market_date)).fetchall()
    labels = [str(r[0]) for r in rows if r[0] is not None]
    return labels or [str(t) for t in range(15, 36)]

def _latest_pws(conn, airport, limit=8):
    rows = conn.execute("""SELECT station_id, obs_time, distance_km, temp_c, humidity,
        dewpoint_c, wind_dir_deg, wind_speed_kt, pressure_hpa FROM pws_obs_multi
        WHERE airport_icao=? AND is_valid=1 ORDER BY obs_time DESC LIMIT ?""",
        (airport, limit)).fetchall()
    return [dict(r) for r in rows]

def run(airport="FACT"):
    conn = _connect()
    try:
        now = datetime.now(ZoneInfo("Africa/Johannesburg") if airport == "FACT" else ZoneInfo("UTC"))
        market_date = now.date().isoformat()
        metar = _latest(conn, """SELECT obs_time,temp_c,dewpoint_c,wind_dir_deg,
            wind_speed_kt,raw_metar FROM metar_multi WHERE station_id=?
            ORDER BY obs_time DESC LIMIT 1""", (airport,))
        saws = _latest(conn, """SELECT obs_time,temp_c,dewpoint_c,wind_dir,
            wind_speed,pressure_hpa FROM saws_obs ORDER BY obs_time DESC LIMIT 1""")
        current = metar or saws or {}
        state = build_state(
            airport=airport, market_date=market_date,
            current_temp_c=current.get("temp_c"),
            current_dewpoint_c=current.get("dewpoint_c"),
            wind_speed_kt=current.get("wind_speed_kt", current.get("wind_speed")),
            wind_dir_deg=current.get("wind_dir_deg", current.get("wind_dir")),
            pressure_hpa=current.get("pressure_hpa"), metar=current.get("raw_metar"),
            nearby_observations=_latest_pws(conn, airport))
        prediction = score_weather_state(state, _market_buckets(conn, airport, market_date))
        conn.execute("""INSERT INTO jev_prediction
            (airport_icao,market_date,fetched_at,model,choice,confidence,
             probabilities_json,state_json,usage_json)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (airport, market_date, prediction["evaluated_at"], prediction["model"],
             prediction["choice"], prediction["confidence"],
             json.dumps(prediction["probabilities"], separators=(",",":")),
             json.dumps(state, separators=(",",":")),
             json.dumps(prediction["usage"], separators=(",",":"))))
        conn.commit()
        return prediction
    finally:
        conn.close()

if __name__ == "__main__":
    try: print(json.dumps(run(), indent=2))
    except JevError as exc: print(f"Jev disabled/error: {exc}")
