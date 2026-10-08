#!/usr/bin/env python3
"""WeatherEdge multi-airport Mission Control."""

import html
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")
from .airports import AIRPORTS
from .db import get_connection
from . import sensor_api

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
                   WHERE s.airport_icao = ? AND s.enabled = 1
                   ORDER BY s.distance_km ASC""",
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
.detail{{margin-bottom:18px;background:#0d141d;border:1px solid #293442;border-radius:8px;padding:15px}}.detailhead{{display:flex;gap:12px;align-items:center;flex-wrap:wrap}}.detailhead h2{{margin:0;color:#fff;font-size:16px}}.select{{background:#111923;color:#d7dee7;border:1px solid #293442;border-radius:6px;padding:7px}}.chartwrap{{margin-top:12px;border:1px solid #202b36;border-radius:6px;background:#080d13;overflow:hidden}}#chart{{display:block;width:100%;height:340px}}.axis{{fill:#596574;font-size:10px}}.legend{{display:flex;gap:14px;flex-wrap:wrap;margin-top:9px;font-size:11px}}.legend span{{color:#c9d1d9}}.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;background:#58a6ff;margin-right:5px}}.metardot{{background:#fff}}.compare{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:8px;margin-top:12px}}.stat{{background:#080d13;border:1px solid #202b36;border-radius:6px;padding:10px}}.stat .k{{font-size:9px;color:#596574}}.stat .v{{font-size:16px;color:#d7dee7;margin-top:5px}}</style></head>
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
<section class="detail"><div class="detailhead"><h2>REPLAY LAB // WEATHER + WIND + MARKET</h2>
<select class="select" id="airportSelect" onchange="loadReplay()"></select><input class="select" id="replayDate" type="date">
<button onclick="loadReplay()">LOAD DAY</button><button onclick="toggleReplay()" id="playBtn">▶ PLAY</button>
<select class="select" id="speed" onchange="setSpeed()"><option value="1">1×</option><option value="5">5×</option><option value="20" selected>20×</option><option value="60">60×</option></select>
<a class="windy" id="windyLink" target="_blank" rel="noreferrer">WINDY LIVE ↗</a><span class="muted" id="labStatus">—</span></div>
<div class="replaygrid"><div class="mapwrap"><div class="maptitle">HISTORICAL SENSOR MAP</div><svg id="map" viewBox="0 0 700 430"></svg></div>
<div class="windywrap"><div class="maptitle">WINDY LIVE MAP</div><iframe id="windyFrame" title="Windy live weather map" loading="lazy"></iframe></div></div>
<div class="timeline"><input id="timeSlider" type="range" min="0" max="1439" value="0" oninput="seekReplay(this.value)"><div class="timeLabels"><span id="replayClock">—</span><span id="replayEvent">—</span></div></div>
<div class="chartwrap"><svg id="chart" viewBox="0 0 1000 340" preserveAspectRatio="none"></svg></div><div class="legend" id="legend"></div><div class="compare" id="compare"></div></section><section class="grid" id="grid">{''.join(cards)}</section></main>
<script>
const airports={{payload}};
let mode='all';
function apply(){{const q=document.getElementById('q').value.toLowerCase();let live=0;
document.querySelectorAll('.card').forEach((c,i)=>{{const a=airports[i];
const okq=!q||(a.icao+' '+a.city).toLowerCase().includes(q);
const okm=mode==='all'||(mode==='live'&&a.status==='LIVE')||(mode==='stale'&&a.status==='STALE')||(mode==='us'&&a.country==='US')||(mode==='intl'&&a.country!=='US');
if(a.status==='LIVE')live++;c.style.display=okq&&okm?'block':'none'}});document.getElementById('liveCount').textContent=live}}
function filterCards(m,b){{mode=m;document.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');apply()}}

const labAirports={{payload}};
let replayData=null,replayTimer=null,replayMinutes=0,replaySpeed=20;
function fillAirportSelect(){{const s=document.getElementById('airportSelect');if(s.options.length)return;labAirports.forEach(a=>{{const o=document.createElement('option');o.value=a.icao;o.textContent=a.icao+' — '+a.city;s.appendChild(o)}})}}
function fmt(v,s=''){{return v==null?'—':Number(v).toFixed(1)+s}}
function isoAtMinute(min){{return new Date(replayData.replay_start_utc).getTime()+Number(min)*60000}}
function latestAt(rows,t,key='obs_time'){{let best=null;for(const r of rows||[]){{const d=new Date(r[key]);if(!isNaN(d)&&d.getTime()<=t&&(!best||d.getTime()>new Date(best[key]).getTime()))best=r}}return best}}
function setWindy(){{const a=labAirports.find(x=>x.icao===document.getElementById('airportSelect').value);if(!a)return;document.getElementById('windyLink').href='https://www.windy.com/'+a.lat+','+a.lon+',9';document.getElementById('windyFrame').src='https://embed.windy.com/embed2.html?lat='+a.lat+'&lon='+a.lon+'&detailLat='+a.lat+'&detailLon='+a.lon+'&width=650&height=400&zoom=9&level=surface&overlay=temp&product=ecmwf&menu=&message=true&marker=true&calendar=now&type=map&location=coordinates&detail=true&metricWind=kt&metricTemp=C'}}
async function loadReplay(){{fillAirportSelect();setWindy();const icao=document.getElementById('airportSelect').value;let date=document.getElementById('replayDate').value;if(!date){{date=new Date().toISOString().slice(0,10);document.getElementById('replayDate').value=date}}document.getElementById('labStatus').textContent='loading '+icao+' '+date+'…';try{{const r=await fetch('/api/airport/'+icao+'/replay?date='+encodeURIComponent(date),{{cache:'no-store'}});replayData=await r.json();if(replayData.error)throw new Error(replayData.error);replayMinutes=0;document.getElementById('timeSlider').value=0;document.getElementById('labStatus').textContent='loaded '+replayData.metar.length+' METAR · '+replayData.pws.length+' PWS · '+replayData.markets.length+' market rows';renderReplay()}}catch(e){{document.getElementById('labStatus').textContent='ERROR: '+e.message}}
function setSpeed(){{replaySpeed=Number(document.getElementById('speed').value)}}
function toggleReplay(){{if(replayTimer){{clearInterval(replayTimer);replayTimer=null;document.getElementById('playBtn').textContent='▶ PLAY';return}}document.getElementById('playBtn').textContent='⏸ PAUSE';replayTimer=setInterval(()=>{{replayMinutes+=replaySpeed;if(replayMinutes>=1439){{replayMinutes=1439;toggleReplay()}}document.getElementById('timeSlider').value=replayMinutes;renderReplay()}},250)}}
function seekReplay(v){{replayMinutes=Number(v);renderReplay()}}
function currentSnapshot(){{const t=isoAtMinute(replayMinutes),metar=latestAt(replayData.metar,t),by={{}};for(const p of replayData.pws){{(by[p.station_id]??=[]).push(p)}}const stations=(replayData.stations||[]).map(s=>({{...s,obs:latestAt(by[s.station_id],t)}}));const buckets={{}};for(const m of replayData.markets||[]){{if(new Date(m.fetched_at).getTime()<=t){{const old=buckets[m.bucket_label];if(!old||new Date(m.fetched_at)>new Date(old.fetched_at))buckets[m.bucket_label]=m}}return{{t,metar,stations,markets:Object.values(buckets).sort((a,b)=>(a.yes_price_cents??0)-(b.yes_price_cents??0))}}
function renderReplay(){{if(!replayData)return;const s=currentSnapshot(),dt=new Date(s.t);document.getElementById('replayClock').textContent=dt.toLocaleString('en-GB',{{timeZone:replayData.timezone,hour:'2-digit',minute:'2-digit',second:'2-digit'}})+' '+replayData.timezone;document.getElementById('replayEvent').textContent=s.metar?('METAR '+fmt(s.metar.temp_c,'°C')+' · wind '+(s.metar.wind_dir_deg==null?'—':Math.round(s.metar.wind_dir_deg)+'°')+' / '+fmt(s.metar.wind_speed_kt,'kt')):'NO AIRPORT OBSERVATION';drawReplayMap(s);drawReplayChart();drawReplayCompare(s)}}
function drawReplayMap(s){{const svg=document.getElementById('map'),W=700,H=400,pad=55,pts=[{{lat:replayData.airport.lat,lon:replayData.airport.lon,temp:s.metar?.temp_c,wind:s.metar,airport:true,label:replayData.icao}},...s.stations.map(x=>({{lat:x.latitude,lon:x.longitude,temp:x.obs?.temp_c,wind:x.obs,airport:false,label:x.station_id}}))].filter(x=>x.lat!=null&&x.lon!=null);if(!pts.length){{svg.innerHTML='<text x="20" y="40" class="axis">NO STATION GEOMETRY</text>';return}}let minLat=Math.min(...pts.map(p=>p.lat)),maxLat=Math.max(...pts.map(p=>p.lat)),minLon=Math.min(...pts.map(p=>p.lon)),maxLon=Math.max(...pts.map(p=>p.lon));const lp=Math.max((maxLat-minLat)*.25,.01),op=Math.max((maxLon-minLon)*.25,.01);minLat-=lp;maxLat+=lp;minLon-=op;maxLon+=op;const x=p=>pad+(p.lon-minLon)/(maxLon-minLon)*(W-2*pad),y=p=>H-pad-(p.lat-minLat)/(maxLat-minLat)*(H-2*pad);let out='<rect x="0" y="0" width="'+W+'" height="'+H+'" fill="#080d13"/>';for(let i=0;i<=5;i++){{const xx=pad+i*(W-2*pad)/5,yy=pad+i*(H-2*pad)/5;out+='<line x1="'+xx+'" x2="'+xx+'" y1="'+pad+'" y2="'+(H-pad)+'" stroke="#17202a"/><line x1="'+pad+'" x2="'+(W-pad)+'" y1="'+yy+'" y2="'+yy+'" stroke="#17202a"/>'}}for(const p of pts){{const cx=x(p),cy=y(p),r=p.airport?9:7;out+='<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="'+(p.airport?'#fff':'#58a6ff')+'" stroke="#0b1016" stroke-width="2"/>';out+='<text x="'+(cx+11)+'" y="'+(cy+4)+'" fill="#d7dee7" font-size="11">'+p.label+' '+(p.temp==null?'—':Number(p.temp).toFixed(1)+'°C')+'</text>';if(p.wind?.wind_dir_deg!=null){{const rad=(Number(p.wind.wind_dir_deg)-90)*Math.PI/180,len=18,ex=cx+Math.cos(rad)*len,ey=cy+Math.sin(rad)*len;out+='<line x1="'+cx+'" y1="'+cy+'" x2="'+ex+'" y2="'+ey+'" stroke="#ffcc66" stroke-width="2"/><polygon points="'+ex+','+ey+' '+(ex-5*Math.cos(rad-.5))+','+(ey-5*Math.sin(rad-.5))+' '+(ex-5*Math.cos(rad+.5))+','+(ey-5*Math.sin(rad+.5))+'" fill="#ffcc66"/>'}}svg.innerHTML=out}}
function drawReplayChart(){{const svg=document.getElementById('chart'),d=replayData,W=1000,H=340,L=48,R=15,T=18,B=30,all=[...d.metar,...d.pws].filter(x=>x.temp_c!=null);if(!all.length){{svg.innerHTML='<text x="50" y="80" class="axis">NO HISTORICAL SENSOR DATA</text>';return}}const min=Math.floor(Math.min(...all.map(x=>x.temp_c))-1),max=Math.ceil(Math.max(...all.map(x=>x.temp_c))+1),range=Math.max(1,max-min),start=new Date(d.replay_start_utc).getTime(),x=t=>L+(new Date(t).getTime()-start)/86400000*(W-L-R),y=v=>T+(max-v)/range*(H-T-B);let out='';for(let v=min;v<=max;v++){{const yy=y(v);out+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+yy+'" y2="'+yy+'" stroke="#202b36"/><text x="5" y="'+(yy+4)+'" class="axis">'+v+'°C</text>'}}const met=d.metar.map(p=>x(p.obs_time)+','+y(p.temp_c)).join(' ');if(met)out+='<polyline fill="none" stroke="#fff" stroke-width="2.5" points="'+met+'"/>';[...new Set(d.pws.map(p=>p.station_id))].forEach((id,i)=>{{const pts=d.pws.filter(p=>p.station_id===id&&p.temp_c!=null).map(p=>x(p.obs_time)+','+y(p.temp_c)).join(' ');if(pts)out+='<polyline fill="none" stroke="hsl('+(190+i*55)+',80%,60%)" stroke-width="1.5" points="'+pts+'"/>'}});const nowX=x(new Date(isoAtMinute(replayMinutes)));out+='<line x1="'+nowX+'" x2="'+nowX+'" y1="'+T+'" y2="'+(H-B)+'" stroke="#ffcc66" stroke-width="2"/>';svg.innerHTML=out;document.getElementById('legend').innerHTML='<span><i class="dot metardot"></i>Airport/METAR</span>'+[...new Set(d.pws.map(p=>p.station_id))].map((id,i)=>'<span><i class="dot" style="background:hsl('+(190+i*55)+',80%,60%)"></i>'+id+'</span>').join('')}}
function drawReplayCompare(s){{const near=s.stations.filter(x=>x.obs?.temp_c!=null).sort((a,b)=>(a.distance_km??999)-(b.distance_km??999))[0],marketText=s.markets.slice(0,8).map(m=>m.bucket_label+' '+fmt(m.yes_price_cents,'¢')).join(' · '),o=replayData.outcome,vals=[['AIRPORT TEMP',fmt(s.metar?.temp_c,'°C')],['NEAREST PWS',fmt(near?.obs?.temp_c,'°C')],['PWS Δ',near&&s.metar?fmt(near.obs.temp_c-s.metar.temp_c,'°C'):'—'],['AIRPORT WIND',s.metar?.wind_dir_deg!=null?Math.round(s.metar.wind_dir_deg)+'° / '+fmt(s.metar.wind_speed_kt,'kt'):'—'],['MARKET LADDER',marketText||'—'],['MARKET BUCKETS',String(s.markets.length)],['SETTLED MAX',o?fmt(o.actual_max_c,'°C'):'—'],['PWS STATIONS',String(s.stations.filter(x=>x.obs).length)]];document.getElementById('compare').innerHTML=vals.map(v=>'<div class="stat"><div class="k">'+v[0]+'</div><div class="v">'+v[1]+'</div></div>').join('')}}
fillAirportSelect();document.getElementById('replayDate').value=new Date().toISOString().slice(0,10);loadReplay();
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
