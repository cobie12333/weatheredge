#!/usr/bin/env python3
"""WeatherEdge multi-airport Mission Control.

Read-only dashboard. The station list is configuration-driven and the live
airport cards are populated from the station-aware METAR table.
"""

import html
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, ".")
from airports import AIRPORTS
from db import get_connection

PORT = 8420


def _fmt(v, suffix=""):
    return "—" if v is None else f"{v}{suffix}"


def get_airport_rows():
    con = get_connection()
    try:
        rows = []
        for airport in AIRPORTS:
            station = airport["icao"]
            r = con.execute(
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

            temp_change = None
            if len(prev) == 2 and prev[0]["temp_c"] is not None and prev[1]["temp_c"] is not None:
                temp_change = round(prev[0]["temp_c"] - prev[1]["temp_c"], 1)

            rows.append({
                **airport,
                "temp_c": r["temp_c"] if r else None,
                "dewpoint_c": r["dewpoint_c"] if r else None,
                "wind_dir_deg": r["wind_dir_deg"] if r else None,
                "wind_speed_kt": r["wind_speed_kt"] if r else None,
                "obs_time": r["obs_time"] if r else None,
                "report_type": r["report_type"] if r else None,
                "raw_metar": r["raw_metar"] if r else None,
                "temp_change": temp_change,
            })
        return rows
    finally:
        con.close()


def render(rows):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    cards = []
    for r in rows:
        fresh = "LIVE" if r["obs_time"] else "NO DATA"
        cls = "live" if r["obs_time"] else "dead"
        cards.append(f"""
        <article class="card {cls}">
          <div class="top">
            <div><span class="icao">{html.escape(r['icao'])}</span>
                 <span class="city">{html.escape(r['city'])}</span></div>
            <span class="status">{fresh}</span>
          </div>
          <div class="temp">{_fmt(r['temp_c'], '°C')}</div>
          <div class="metrics">
            <span>Δ obs {('+' if r['temp_change'] is not None and r['temp_change'] >= 0 else '') + str(r['temp_change']) + '°C' if r['temp_change'] is not None else '—'}</span>
            <span>Wind {_fmt(r['wind_speed_kt'], 'kt')}</span>
            <span>Dir {_fmt(r['wind_dir_deg'], '°')}</span>
          </div>
          <div class="meta">Obs: {html.escape(r['obs_time'] or '—')}</div>
          <div class="raw">{html.escape(r['raw_metar'] or 'No observation')}</div>
        </article>""")

    payload = json.dumps(rows)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WeatherEdge — Airport Mission Control</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#070b10;color:#d7dee7;font:14px ui-monospace,SFMono-Regular,Menlo,monospace}}
header{{padding:18px 20px;border-bottom:1px solid #202832;position:sticky;top:0;background:#070b10ee;backdrop-filter:blur(8px);z-index:2}}
h1{{margin:0;color:#fff;font-size:20px}} .sub{{color:#7d8a99;font-size:11px;margin-top:5px}}
.toolbar{{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}} button{{background:#111923;color:#d7dee7;border:1px solid #293442;border-radius:6px;padding:7px 10px;cursor:pointer}}
button.active{{border-color:#4aa3ff;color:#4aa3ff}} main{{padding:18px;max-width:1500px;margin:auto}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}}
.card{{background:#0d141d;border:1px solid #202b36;border-radius:8px;padding:15px;min-height:185px}}
.card.live{{border-left:3px solid #3fb950}} .card.dead{{border-left:3px solid #6e7681}}
.top{{display:flex;justify-content:space-between;align-items:center}} .icao{{font-size:18px;font-weight:700;color:#fff}} .city{{color:#8b949e;margin-left:8px}}
.status{{font-size:10px;padding:3px 6px;border-radius:10px;background:#1a7f37;color:#fff}} .dead .status{{background:#30363d}}
.temp{{font-size:38px;font-weight:700;color:#58a6ff;margin:18px 0 10px}}
.metrics{{display:flex;gap:14px;color:#c9d1d9;font-size:12px;flex-wrap:wrap}} .meta{{color:#7d8a99;font-size:10px;margin-top:14px}}
.raw{{margin-top:8px;color:#596574;font-size:10px;line-height:1.35;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.summary{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:15px;color:#8b949e;font-size:12px}}
.summary b{{color:#d7dee7}} .search{{margin-left:auto;background:#0d141d;border:1px solid #293442;color:#d7dee7;padding:7px;border-radius:6px}}
</style></head>
<body>
<header><h1>WEATHEREDGE // AIRPORT MISSION CONTROL</h1>
<div class="sub">FACT-style monitoring across the configured Polymarket weather watchlist · generated {now}</div>
<div class="toolbar"><button class="active" onclick="filterCards('all',this)">ALL</button>
<button onclick="filterCards('live',this)">LIVE</button><button onclick="filterCards('us',this)">US</button>
<button onclick="filterCards('intl',this)">INTL</button>
<input class="search" id="q" placeholder="search ICAO/city" oninput="searchCards()"></div></header>
<main><div class="summary"><span>Airports: <b>{len(rows)}</b></span>
<span>Live: <b id="liveCount">0</b></span><span>Last refresh: <b id="refresh">now</b></span></div>
<section class="grid" id="grid">{''.join(cards)}</section></main>
<script>
const airports={payload};
let mode='all';
function apply(){{const q=document.getElementById('q').value.toLowerCase();let live=0;
document.querySelectorAll('.card').forEach((c,i)=>{const a=airports[i];const okq=!q||(a.icao+' '+a.city).toLowerCase().includes(q);
const okm=mode==='all'||(mode==='live'&&a.obs_time)||(mode==='us'&&a.country==='US')||(mode==='intl'&&a.country!=='US');
if(a.obs_time)live++;c.style.display=okq&&okm?'block':'none'});document.getElementById('liveCount').textContent=live}}
function filterCards(m,b){{mode=m;document.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');apply()}}
function searchCards(){{apply()}}
setTimeout(()=>location.reload(),60000);apply();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_response(404); self.end_headers(); return
        try:
            body = render(get_airport_rows()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            body = f"Dashboard error: {html.escape(str(exc))}".encode()
            self.send_response(500); self.send_header("Content-Type","text/plain"); self.end_headers(); self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    print(f"WeatherEdge Airport Mission Control: http://localhost:{PORT}")
    HTTPServer(("localhost", PORT), Handler).serve_forever()
