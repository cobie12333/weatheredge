#!/usr/bin/env python3
"""WeatherEdge multi-airport Mission Control."""

import html
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")
from airports import AIRPORTS
from db import get_connection
import sensor_api

PORT = 8420
LIVE_MAX_MINUTES = 30
STALE_MAX_MINUTES = 90


def _fmt(v, suffix=""):
    return "—" if v is None else f"{v:g}{suffix}" if isinstance(v, (int, float)) else f"{v}{suffix}"


def _age_minutes(obs_time):
    if not obs_time:
        return None
    try:
        dt = datetime.fromisoformat(obs_time.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60)
    except ValueError:
        return None


def _status(age):
    if age is None:
        return "NO DATA", "dead"
    if age <= LIVE_MAX_MINUTES:
        return "LIVE", "live"
    if age <= STALE_MAX_MINUTES:
        return "STALE", "stale"
    return "OFFLINE", "dead"


def get_airport_rows():
    con = get_connection(readonly=True)
    try:
        rows = []
        for airport in AIRPORTS:
            station = airport["icao"]
            latest = con.execute(
                """SELECT * FROM metar_multi
                   WHERE station_id = ?
                   ORDER BY obs_time DESC LIMIT 1""",
                (station,),
            ).fetchone()

            prev = con.execute(
                """SELECT temp_c, obs_time FROM metar_multi
                   WHERE station_id = ? AND temp_c IS NOT NULL
                   ORDER BY obs_time DESC LIMIT 2""",
                (station,),
            ).fetchall()

            pws = con.execute(
                """SELECT s.station_id, s.name, s.distance_km, s.status, s.enabled, s.source_url,
                          o.temp_c, o.obs_time
                   FROM pws_station s
                   LEFT JOIN pws_obs_multi o ON o.id = (
                       SELECT x.id FROM pws_obs_multi x
                       WHERE x.station_id = s.station_id
                       ORDER BY x.obs_time DESC LIMIT 1
                   )
                   WHERE airport_icao = ? AND verified = 1
                   ORDER BY distance_km ASC""",
                (station,),
            ).fetchall()

            temp_change = None
            if len(prev) == 2:
                temp_change = round(prev[0]["temp_c"] - prev[1]["temp_c"], 1)

            age = _age_minutes(latest["obs_time"]) if latest else None
            status, cls = _status(age)

            rows.append({
                **airport,
                "temp_c": latest["temp_c"] if latest else None,
                "dewpoint_c": latest["dewpoint_c"] if latest else None,
                "wind_dir_deg": latest["wind_dir_deg"] if latest else None,
                "wind_speed_kt": latest["wind_speed_kt"] if latest else None,
                "obs_time": latest["obs_time"] if latest else None,
                "report_type": latest["report_type"] if latest else None,
                "raw_metar": latest["raw_metar"] if latest else None,
                "temp_change": temp_change,
                "age_min": round(age, 1) if age is not None else None,
                "status": status,
                "pws": [dict(x) for x in pws],
            })
        return rows
    finally:
        con.close()


def render(rows):
    now_utc = datetime.now(timezone.utc)
    cards = []

    for r in rows:
        local_time = "—"
        if r["obs_time"]:
            try:
                dt = datetime.fromisoformat(r["obs_time"].replace("Z", "+00:00"))
                local_time = dt.astimezone(ZoneInfo(r["tz"])).strftime("%Y-%m-%d %H:%M:%S %Z")
            except (ValueError, KeyError):
                local_time = r["obs_time"]

        pws_html = "".join(
            f'<a href="{html.escape(p["source_url"], quote=True)}" target="_blank" rel="noreferrer">'
            f'{html.escape(p["station_id"])} {html.escape(p["name"] or "")} '
            f'({p["distance_km"]:.1f}km, {html.escape(p["status"])}; '
            f'{_fmt(p["temp_c"], "°C")})</a>'
            for p in r["pws"]
        ) or '<span class="muted">No verified nearby PWS in registry</span>'

        delta = "—" if r["temp_change"] is None else f"{r['temp_change']:+.1f}°C"
        age = "—" if r["age_min"] is None else f"{r['age_min']:.0f}m"

        cards.append(f"""
        <article class="card {r['cls'] if 'cls' in r else ('live' if r['status']=='LIVE' else 'dead')}"
                 data-icao="{html.escape(r['icao'])}" data-country="{html.escape(r['country'])}">
          <div class="top">
            <div><span class="icao">{html.escape(r['icao'])}</span>
                 <span class="city">{html.escape(r['city'])}</span></div>
            <span class="status">{html.escape(r['status'])}</span>
          </div>
          <div class="temp">{_fmt(r['temp_c'], '°C')}</div>
          <div class="metrics">
            <span>Δ obs {delta}</span>
            <span>Wind {_fmt(r['wind_speed_kt'], 'kt')}</span>
            <span>Dir {_fmt(r['wind_dir_deg'], '°')}</span>
            <span>Age {age}</span>
          </div>
          <div class="meta">Local obs: {html.escape(local_time)}</div>
          <div class="raw">{html.escape(r['raw_metar'] or 'No observation')}</div>
          <div class="pws"><b>PWS</b>{pws_html}</div>
        </article>""")

    js_rows = [
        {"icao": r["icao"], "city": r["city"], "country": r["country"], "status": r["status"]}
        for r in rows
    ]
    payload = json.dumps(js_rows, separators=(",", ":")).replace("<", "\\u003c")
    live_count = sum(r["status"] == "LIVE" for r in rows)
    stale_count = sum(r["status"] == "STALE" for r in rows)

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WeatherEdge — Airport Mission Control</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#070b10;color:#d7dee7;font:14px ui-monospace,SFMono-Regular,Menlo,monospace}}
header{{padding:18px 20px;border-bottom:1px solid #202832;position:sticky;top:0;background:#070b10ee;backdrop-filter:blur(8px);z-index:2}}
h1{{margin:0;color:#fff;font-size:20px}} .sub{{color:#7d8a99;font-size:11px;margin-top:5px}}
.toolbar{{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}}
button{{background:#111923;color:#d7dee7;border:1px solid #293442;border-radius:6px;padding:7px 10px;cursor:pointer}}
button.active{{border-color:#4aa3ff;color:#4aa3ff}}
main{{padding:18px;max-width:1500px;margin:auto}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px}}
.card{{background:#0d141d;border:1px solid #202b36;border-radius:8px;padding:15px;min-height:225px}}
.card.live{{border-left:3px solid #3fb950}} .card.stale{{border-left:3px solid #d29922}}
.card.dead{{border-left:3px solid #6e7681}}
.top{{display:flex;justify-content:space-between;align-items:center}}
.icao{{font-size:18px;font-weight:700;color:#fff}} .city{{color:#8b949e;margin-left:8px}}
.status{{font-size:10px;padding:3px 6px;border-radius:10px;background:#1a7f37;color:#fff}}
.stale .status{{background:#9e6a03}} .dead .status{{background:#30363d}}
.temp{{font-size:38px;font-weight:700;color:#58a6ff;margin:18px 0 10px}}
.metrics{{display:flex;gap:14px;color:#c9d1d9;font-size:12px;flex-wrap:wrap}}
.meta{{color:#7d8a99;font-size:10px;margin-top:14px}}
.raw{{margin-top:8px;color:#596574;font-size:10px;line-height:1.35;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.pws{{margin-top:10px;color:#7d8a99;font-size:10px;line-height:1.6}}
.pws b{{color:#c9d1d9;margin-right:8px}} .pws a{{display:block;color:#58a6ff;text-decoration:none}}
.muted{{color:#596574}}
.summary{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:15px;color:#8b949e;font-size:12px}}
.summary b{{color:#d7dee7}} .search{{margin-left:auto;background:#0d141d;border:1px solid #293442;color:#d7dee7;padding:7px;border-radius:6px}}
</style></head>
<body>
<header><h1>WEATHEREDGE // AIRPORT MISSION CONTROL</h1>
<div class="sub">Canonical multi-airport observation layer · generated {now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")}</div>
<div class="toolbar">
<button class="active" onclick="filterCards('all',this)">ALL</button>
<button onclick="filterCards('live',this)">LIVE</button><button onclick="filterCards('stale',this)">STALE</button>
<button onclick="filterCards('us',this)">US</button><button onclick="filterCards('intl',this)">INTL</button>
<input class="search" id="q" placeholder="search ICAO/city" oninput="searchCards()">
</div></header>
<main><div class="summary"><span>Airports: <b>{len(rows)}</b></span>
<span>Live: <b id="liveCount">{live_count}</b></span><span>Stale: <b>{stale_count}</b></span>
<span>Refresh: <b id="refresh">{now_utc.strftime("%H:%M:%S UTC")}</b></span></div>
<section class="grid" id="grid">{''.join(cards)}</section></main>
<script>
const airports={payload};
let mode='all';
function apply(){{const q=document.getElementById('q').value.toLowerCase();let live=0;
document.querySelectorAll('.card').forEach((c,i)=>{{const a=airports[i];
const okq=!q||(a.icao+' '+a.city).toLowerCase().includes(q);
const okm=mode==='all'||(mode==='live'&&a.status==='LIVE')||(mode==='stale'&&a.status==='STALE')||(mode==='us'&&a.country==='US')||(mode==='intl'&&a.country!=='US');
if(a.status==='LIVE')live++;c.style.display=okq&&okm?'block':'none'}});document.getElementById('liveCount').textContent=live}}
function filterCards(m,b){{mode=m;document.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');apply()}}
function searchCards(){{apply()}}
setTimeout(()=>location.reload(),60000);apply();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        api = sensor_api.handle(self.path)
        if api:
            status, payload = api
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        try:
            body = render(get_airport_rows()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            body = f"Dashboard error: {html.escape(str(exc))}".encode()
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    print(f"WeatherEdge Airport Mission Control: http://localhost:{PORT}")
    HTTPServer(("localhost", PORT), Handler).serve_forever()
