"""Live Jev scoring for WeatherEdge; never places trades."""
from __future__ import annotations
import json,sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from config.settings import DB_PATH
from jev import JevError
from jev_predictor import build_state,score_weather_state

def _connect():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c
def _latest(c,sql,params=()):
    r=c.execute(sql,params).fetchone(); return dict(r) if r else None
def _market_buckets(c,station,date):
    rows=c.execute("SELECT DISTINCT bucket_label FROM market_price_multi WHERE station_id=? AND market_date=? ORDER BY CAST(bucket_label AS REAL)",(station,date)).fetchall()
    labels=[str(r[0]) for r in rows if r[0] is not None]
    return labels or [str(t) for t in range(15,36)]
def _latest_pws(c,airport,limit=8):
    rows=c.execute("SELECT station_id,obs_time,distance_km,temp_c,humidity,dewpoint_c,wind_dir_deg,wind_speed_kt,pressure_hpa FROM pws_obs_multi WHERE airport_icao=? AND is_valid=1 ORDER BY obs_time DESC LIMIT ?",(airport,limit)).fetchall()
    return [dict(r) for r in rows]
def run(airport="FACT"):
    c=_connect()
    try:
        now=datetime.now(ZoneInfo("Africa/Johannesburg") if airport=="FACT" else ZoneInfo("UTC"))
        date=now.date().isoformat()
        metar=_latest(c,"SELECT obs_time,temp_c,dewpoint_c,wind_dir_deg,wind_speed_kt,raw_metar FROM metar_multi WHERE station_id=? ORDER BY obs_time DESC LIMIT 1",(airport,))
        saws=_latest(c,"SELECT obs_time,temp_c,dewpoint_c,wind_dir,wind_speed,pressure_hpa FROM saws_obs ORDER BY obs_time DESC LIMIT 1")
        cur=metar or saws or {}
        state=build_state(airport=airport,market_date=date,current_temp_c=cur.get("temp_c"),current_dewpoint_c=cur.get("dewpoint_c"),wind_speed_kt=cur.get("wind_speed_kt",cur.get("wind_speed")),wind_dir_deg=cur.get("wind_dir_deg",cur.get("wind_dir")),pressure_hpa=cur.get("pressure_hpa"),metar=cur.get("raw_metar"),nearby_observations=_latest_pws(c,airport))
        out=score_weather_state(state,_market_buckets(c,airport,date))
        c.execute("INSERT INTO jev_prediction (airport_icao,market_date,fetched_at,model,choice,confidence,probabilities_json,state_json,usage_json) VALUES (?,?,?,?,?,?,?,?,?)",(airport,date,out["evaluated_at"],out["model"],out["choice"],out["confidence"],json.dumps(out["probabilities"],separators=(",",":")),json.dumps(state,separators=(",",":")),json.dumps(out["usage"],separators=(",",":"))))
        c.commit(); return out
    finally: c.close()
