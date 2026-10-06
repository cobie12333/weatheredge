#!/usr/bin/env python3
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WeatherEdge // Live Weather Cockpit</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
*{box-sizing:border-box}body{margin:0;background:#05080c;color:#dce5ee;font:13px ui-monospace,SFMono-Regular,Menlo,monospace}
header{position:sticky;top:0;z-index:20;background:#05080cf2;border-bottom:1px solid #1e2935;padding:14px 18px;backdrop-filter:blur(10px)}
h1{margin:0;font-size:19px;color:#fff;letter-spacing:.04em}.sub{color:#708090;font-size:10px;margin-top:4px}
.toolbar{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-top:11px}button,select{background:#0d141d;color:#dce5ee;border:1px solid #293746;border-radius:6px;padding:7px 9px}button.active{border-color:#58a6ff;color:#58a6ff}.live-dot{color:#3fb950}.search{margin-left:auto}
main{max-width:1600px;margin:auto;padding:14px}.sourcebar{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:12px}.source{background:#0b1118;border:1px solid #202c38;border-radius:6px;padding:7px 9px}.source b{color:#fff}.ok{color:#3fb950}.warn{color:#d29922}.bad{color:#f85149}
.hero{display:grid;grid-template-columns:1.35fr .8fr;gap:12px;margin-bottom:12px}.panel{background:#0a1017;border:1px solid #202c38;border-radius:8px;padding:13px}.panel h2{font-size:12px;margin:0 0 10px;color:#fff}
#map{height:470px;border-radius:6px;background:#0b1118}.leaflet-container{background:#080d12}.leaflet-control{font-family:inherit}.leaflet-popup-content-wrapper,.leaflet-popup-tip{background:#0b1118;color:#dce5ee}.leaflet-popup-content{font:12px ui-monospace,SFMono-Regular,Menlo,monospace}
.weather-map iframe{width:100%;height:470px;border:0;border-radius:6px;background:#080d12}.maptabs{display:flex;gap:6px;margin-bottom:8px}
.detail{display:grid;grid-template-columns:1.1fr .9fr;gap:12px;margin-bottom:12px}.chart{height:310px;width:100%;display:block;background:#070c12;border:1px solid #18232e;border-radius:6px}.chart text{fill:#718092;font-size:10px}.chart line{stroke:#1c2732}.chart .metar{stroke:#fff}.chart .pws{stroke:#58a6ff}.chart .forecast{stroke:#d29922;stroke-dasharray:6 5}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.metric{background:#070c12;border:1px solid #18232e;border-radius:6px;padding:9px}.metric small{display:block;color:#657586;font-size:9px}.metric strong{display:block;color:#fff;font-size:16px;margin-top:5px}.market{margin-top:10px;display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.bucket{background:#070c12;border:1px solid #18232e;border-radius:5px;padding:7px}.bucket b{color:#fff}.bucket small{display:block;color:#6f7d8d}.edge-pos{color:#3fb950}.edge-neg{color:#f85149}
.airports{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:10px}.airport-card{background:#0a1017;border:1px solid #202c38;border-radius:8px;padding:12px}.airport-card.live{border-left:3px solid #3fb950}.airport-card.stale{border-left:3px solid #d29922}.airport-card.dead{border-left:3px solid #f85149}.card-head{display:flex;justify-content:space-between}.card-head b{font-size:17px;color:#fff}.card-head span{color:#778696;margin-left:8px}.pill{font-style:normal;font-size:9px;padding:3px 6px;border-radius:9px;background:#303944}.pill.live{background:#1a7f37;color:#fff}.pill.stale{background:#9e6a03;color:#fff}.pill.dead{background:#303944}.bigtemp{font-size:35px;font-weight:700;color:#58a6ff;margin:14px 0 8px}.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.grid4 div{background:#070c12;border-radius:5px;padding:7px}.grid4 small{display:block;color:#657586;font-size:8px}.grid4 strong{display:block;margin-top:3px}.raw{margin-top:9px;color:#5d6b79;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.pwsline{margin-top:8px;color:#8492a0;font-size:10px;line-height:1.6}
.notice{color:#d29922;background:#171208;border:1px solid #4a3713;border-radius:6px;padding:9px;margin-top:8px}.footer{color:#566474;font-size:9px;padding:18px 2px}
@media(max-width:1000px){.hero,.detail{grid-template-columns:1fr}.weather-map iframe,#map{height:360px}.market{grid-template-columns:repeat(2,1fr)}}
</style></head><body>
<header><h1>WEATHEREDGE // LIVE WEATHER COCKPIT <span class="live-dot">●</span></h1>
<div class="sub">Live observations · PWS · satellite basemap · Windy forecast map · forecast · Polymarket · source freshness</div>
<div class="toolbar"><button class="active" onclick="setMode('all',this)">ALL</button><button onclick="setMode('live',this)">LIVE</button><button onclick="setMode('stale',this)">STALE</button>
<select id="airportSelect" onchange="selectAirport(this.value)"></select><input id="search" class="search" placeholder="filter airport" oninput="filterCards()">
<span id="clock">—</span></div></header>
<main>
<div class="sourcebar" id="sources"><span class="source">METAR <b>—</b></span><span class="source">PWS <b>—</b></span><span class="source">NWP <b>—</b></span><span class="source">MARKET <b>—</b></span><span class="source">UI <b class="ok">LIVE</b></span></div>
<div class="hero"><section class="panel"><h2>🛰 SATELLITE / STATION MAP</h2><div class="maptabs"><button id="streetBtn" onclick="mapMode('street',this)">STREET</button><button id="satBtn" class="active" onclick="mapMode('sat',this)">SATELLITE</button><button onclick="centerSelected()">CENTER</button></div><div id="map"></div></section>
<section class="panel weather-map"><h2>🌦 LIVE WEATHER MAP // WIND / CLOUD / TEMP</h2><iframe id="windy" loading="lazy" title="Windy weather map"></iframe><div class="sub" style="margin-top:6px">External live map. WeatherEdge does not treat the map as the settlement source.</div></section></div>
<div class="detail"><section class="panel"><h2>🌡 SELECTED AIRPORT // 24H SENSOR TRAJECTORY</h2><div id="selectedTitle" class="sub">—</div><svg id="chart" class="chart" viewBox="0 0 1000 310" preserveAspectRatio="none"></svg></section>
<section class="panel"><h2>TRADING / FORECAST STATE</h2><div class="metrics"><div class="metric"><small>AIRPORT</small><strong id="dTemp">—</strong></div><div class="metric"><small>24H MAX</small><strong id="dMax">—</strong></div><div class="metric"><small>FORECAST</small><strong id="dForecast">—</strong></div><div class="metric"><small>PWS SPREAD</small><strong id="dSpread">—</strong></div></div><div class="market" id="market"></div><div id="pwsNotice" class="notice">PWS registry is present, but live PWS observations require a configured Weather Company API key.</div></section></div>
<section class="airports" id="airportCards"><article class="airport-card" id="card-FACT" data-icao="FACT">
<div class="card-head"><div><b>FACT</b><span>Cape Town</span></div><i id="status-FACT" class="pill dead">NO DATA</i></div>
<div class="bigtemp" id="temp-FACT">—°C</div>
<div class="grid4"><div><small>DEW</small><strong id="dew-FACT">—</strong></div><div><small>WIND</small><strong id="wind-FACT">—</strong></div><div><small>DIR</small><strong id="dir-FACT">—</strong></div><div><small>AGE</small><strong id="age-FACT">—</strong></div></div>
<div class="raw" id="raw-FACT">waiting for live observation…</div>
<div class="pwsline" id="pws-FACT">PWS: no verified live observations</div>
</article><article class="airport-card" id="card-SAEZ" data-icao="SAEZ">
<div class="card-head"><div><b>SAEZ</b><span>Buenos Aires</span></div><i id="status-SAEZ" class="pill dead">NO DATA</i></div>
<div class="bigtemp" id="temp-SAEZ">—°C</div>
<div class="grid4"><div><small>DEW</small><strong id="dew-SAEZ">—</strong></div><div><small>WIND</small><strong id="wind-SAEZ">—</strong></div><div><small>DIR</small><strong id="dir-SAEZ">—</strong></div><div><small>AGE</small><strong id="age-SAEZ">—</strong></div></div>
<div class="raw" id="raw-SAEZ">waiting for live observation…</div>
<div class="pwsline" id="pws-SAEZ">PWS: no verified live observations</div>
</article><article class="airport-card" id="card-LEMD" data-icao="LEMD">
<div class="card-head"><div><b>LEMD</b><span>Madrid</span></div><i id="status-LEMD" class="pill dead">NO DATA</i></div>
<div class="bigtemp" id="temp-LEMD">—°C</div>
<div class="grid4"><div><small>DEW</small><strong id="dew-LEMD">—</strong></div><div><small>WIND</small><strong id="wind-LEMD">—</strong></div><div><small>DIR</small><strong id="dir-LEMD">—</strong></div><div><small>AGE</small><strong id="age-LEMD">—</strong></div></div>
<div class="raw" id="raw-LEMD">waiting for live observation…</div>
<div class="pwsline" id="pws-LEMD">PWS: no verified live observations</div>
</article><article class="airport-card" id="card-KATL" data-icao="KATL">
<div class="card-head"><div><b>KATL</b><span>Atlanta</span></div><i id="status-KATL" class="pill dead">NO DATA</i></div>
<div class="bigtemp" id="temp-KATL">—°C</div>
<div class="grid4"><div><small>DEW</small><strong id="dew-KATL">—</strong></div><div><small>WIND</small><strong id="wind-KATL">—</strong></div><div><small>DIR</small><strong id="dir-KATL">—</strong></div><div><small>AGE</small><strong id="age-KATL">—</strong></div></div>
<div class="raw" id="raw-KATL">waiting for live observation…</div>
<div class="pwsline" id="pws-KATL">PWS: no verified live observations</div>
</article><article class="airport-card" id="card-KSFO" data-icao="KSFO">
<div class="card-head"><div><b>KSFO</b><span>San Francisco</span></div><i id="status-KSFO" class="pill dead">NO DATA</i></div>
<div class="bigtemp" id="temp-KSFO">—°C</div>
<div class="grid4"><div><small>DEW</small><strong id="dew-KSFO">—</strong></div><div><small>WIND</small><strong id="wind-KSFO">—</strong></div><div><small>DIR</small><strong id="dir-KSFO">—</strong></div><div><small>AGE</small><strong id="age-KSFO">—</strong></div></div>
<div class="raw" id="raw-KSFO">waiting for live observation…</div>
<div class="pwsline" id="pws-KSFO">PWS: no verified live observations</div>
</article><article class="airport-card" id="card-KSEA" data-icao="KSEA">
<div class="card-head"><div><b>KSEA</b><span>Seattle</span></div><i id="status-KSEA" class="pill dead">NO DATA</i></div>
<div class="bigtemp" id="temp-KSEA">—°C</div>
<div class="grid4"><div><small>DEW</small><strong id="dew-KSEA">—</strong></div><div><small>WIND</small><strong id="wind-KSEA">—</strong></div><div><small>DIR</small><strong id="dir-KSEA">—</strong></div><div><small>AGE</small><strong id="age-KSEA">—</strong></div></div>
<div class="raw" id="raw-KSEA">waiting for live observation…</div>
<div class="pwsline" id="pws-KSEA">PWS: no verified live observations</div>
</article><article class="airport-card" id="card-EGLC" data-icao="EGLC">
<div class="card-head"><div><b>EGLC</b><span>London</span></div><i id="status-EGLC" class="pill dead">NO DATA</i></div>
<div class="bigtemp" id="temp-EGLC">—°C</div>
<div class="grid4"><div><small>DEW</small><strong id="dew-EGLC">—</strong></div><div><small>WIND</small><strong id="wind-EGLC">—</strong></div><div><small>DIR</small><strong id="dir-EGLC">—</strong></div><div><small>AGE</small><strong id="age-EGLC">—</strong></div></div>
<div class="raw" id="raw-EGLC">waiting for live observation…</div>
<div class="pwsline" id="pws-EGLC">PWS: no verified live observations</div>
</article><article class="airport-card" id="card-KBKF" data-icao="KBKF">
<div class="card-head"><div><b>KBKF</b><span>Buckley</span></div><i id="status-KBKF" class="pill dead">NO DATA</i></div>
<div class="bigtemp" id="temp-KBKF">—°C</div>
<div class="grid4"><div><small>DEW</small><strong id="dew-KBKF">—</strong></div><div><small>WIND</small><strong id="wind-KBKF">—</strong></div><div><small>DIR</small><strong id="dir-KBKF">—</strong></div><div><small>AGE</small><strong id="age-KBKF">—</strong></div></div>
<div class="raw" id="raw-KBKF">waiting for live observation…</div>
<div class="pwsline" id="pws-KBKF">PWS: no verified live observations</div>
</article><article class="airport-card" id="card-RJTT" data-icao="RJTT">
<div class="card-head"><div><b>RJTT</b><span>Tokyo</span></div><i id="status-RJTT" class="pill dead">NO DATA</i></div>
<div class="bigtemp" id="temp-RJTT">—°C</div>
<div class="grid4"><div><small>DEW</small><strong id="dew-RJTT">—</strong></div><div><small>WIND</small><strong id="wind-RJTT">—</strong></div><div><small>DIR</small><strong id="dir-RJTT">—</strong></div><div><small>AGE</small><strong id="age-RJTT">—</strong></div></div>
<div class="raw" id="raw-RJTT">waiting for live observation…</div>
<div class="pwsline" id="pws-RJTT">PWS: no verified live observations</div>
</article></section>
<div class="footer">WeatherEdge cockpit v2 · data timestamps are source observation/fetch times · stale status is based on source age, not prediction quality.</div>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const AIRPORTS=[{"icao":"FACT","city":"Cape Town","market_city":"cape-town","country":"ZA","tz":"Africa/Johannesburg","lat":-33.97403,"lon":18.60433},{"icao":"SAEZ","city":"Buenos Aires","market_city":"buenos-aires","country":"AR","tz":"America/Argentina/Buenos_Aires","lat":-34.82222,"lon":-58.53583},{"icao":"LEMD","city":"Madrid","market_city":"madrid","country":"ES","tz":"Europe/Madrid","lat":40.47222,"lon":-3.56083},{"icao":"KATL","city":"Atlanta","market_city":"atlanta","country":"US","tz":"America/New_York","lat":33.64073,"lon":-84.42774},{"icao":"KSFO","city":"San Francisco","market_city":"san-francisco","country":"US","tz":"America/Los_Angeles","lat":37.62131,"lon":-122.37896},{"icao":"KSEA","city":"Seattle","market_city":"seattle","country":"US","tz":"America/Los_Angeles","lat":47.45025,"lon":-122.30882},{"icao":"EGLC","city":"London","market_city":"london","country":"GB","tz":"Europe/London","lat":51.50528,"lon":0.05528},{"icao":"KBKF","city":"Buckley","market_city":"denver","country":"US","tz":"America/Denver","lat":39.70167,"lon":-104.75167},{"icao":"RJTT","city":"Tokyo","market_city":"tokyo","country":"JP","tz":"Asia/Tokyo","lat":35.54939,"lon":139.77984}];
let selected=AIRPORTS[0]?.icao||'FACT', mode='all', liveState={}, map, satLayer, streetLayer, markers={};
function esc(x){return String(x??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function fmt(v,s=''){return v==null?'—':(typeof v==='number'?v.toFixed(1):v)+s}
function ageText(a){return a==null?'—':a<1?Math.round(a*60)+'s':Math.round(a)+'m'}
function status(age){if(age==null)return ['NO DATA','dead'];if(age<=30)return ['LIVE','live'];if(age<=90)return ['STALE','stale'];return ['OFFLINE','dead']}
function initMap(){map=L.map('map',{zoomControl:true}).setView([AIRPORTS[0].lat,AIRPORTS[0].lon],5);streetLayer=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'});satLayer=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Tiles © Esri'});satLayer.addTo(map);AIRPORTS.forEach(a=>{const m=L.marker([a.lat,a.lon]).addTo(map).bindPopup('<b>'+a.icao+'</b> '+esc(a.city)+'<br><span id="pop-'+a.icao+'">loading…</span>');markers[a.icao]=m})}
function mapMode(modeName,btn){if(modeName==='sat'){streetLayer.remove();satLayer.addTo(map)}else{satLayer.remove();streetLayer.addTo(map)}document.querySelectorAll('.maptabs button').forEach(x=>x.classList.remove('active'));btn.classList.add('active')}
function centerSelected(){const a=AIRPORTS.find(x=>x.icao===selected);if(a){map.setView([a.lat,a.lon],10);markers[a.icao].openPopup()}}
function setMode(m,b){mode=m;document.querySelectorAll('.toolbar button').forEach(x=>x.classList.remove('active'));b.classList.add('active');filterCards()}
function filterCards(){const q=document.getElementById('search').value.toLowerCase();document.querySelectorAll('.airport-card').forEach(c=>{const a=liveState[c.dataset.icao]||{};const st=status(a.metar?.age_min)[1];const text=(c.dataset.icao+' '+(a.city||'')).toLowerCase();const okq=!q||text.includes(q);const okm=mode==='all'||st===mode; c.style.display=okq&&okm?'block':'none'})}
function selectAirport(icao){selected=icao;document.getElementById('airportSelect').value=icao;const a=AIRPORTS.find(x=>x.icao===icao);document.getElementById('selectedTitle').textContent=icao+' — '+a.city;updateWindy(a);centerSelected();loadDetail()}
function updateWindy(a){document.getElementById('windy').src='https://embed.windy.com/embed2.html?lat='+a.lat+'&lon='+a.lon+'&detailLat='+a.lat+'&detailLon='+a.lon+'&width=900&height=470&zoom=8&level=surface&overlay=temp&product=ecmwf&menu=&message=true&marker=true&calendar=now&type=map&location=coordinates&detail=true&metricWind=kt&metricTemp=C'}
function updateCard(a,d){liveState[a.icao]=d;const m=d.metar||{}, [label,cls]=status(m.age_min);const card=document.getElementById('card-'+a.icao);card.className='airport-card '+cls;document.getElementById('status-'+a.icao).textContent=label;document.getElementById('status-'+a.icao).className='pill '+cls;document.getElementById('temp-'+a.icao).textContent=fmt(m.temp_c,'°C');document.getElementById('dew-'+a.icao).textContent=fmt(m.dewpoint_c,'°C');document.getElementById('wind-'+a.icao).textContent=fmt(m.wind_speed_kt,'kt');document.getElementById('dir-'+a.icao).textContent=fmt(m.wind_dir_deg,'°');document.getElementById('age-'+a.icao).textContent=ageText(m.age_min);document.getElementById('raw-'+a.icao).textContent=m.raw_metar||'No observation';const p=d.pws||[];document.getElementById('pws-'+a.icao).innerHTML=p.length?'PWS: '+p.slice(0,3).map(x=>'<b>'+esc(x.station_id)+'</b> '+fmt(x.temp_c,'°C')+' '+ageText(x.age_min)+' · '+fmt(x.distance_km,'km')).join(' | '):'PWS: no live observations';const pop=document.getElementById('pop-'+a.icao);if(pop)pop.textContent=fmt(m.temp_c,'°C')+' · '+label+' · '+ageText(m.age_min);if(a.icao===selected)updateDetail(d)}
function updateSources(){const vals=Object.values(liveState);const ages=(key)=>vals.map(x=>x.sources?.[key]).filter(x=>x!=null);const min=(key)=>{const v=ages(key);return v.length?Math.min(...v):null};const sourceHtml=[['METAR','metar_age_min'],['PWS','pws_age_min'],['NWP','forecast_age_min'],['MARKET','market_age_min']].map(([n,k])=>{const a=min(k);const c=a==null?'warn':'ok';return '<span class="source">'+n+' <b class="'+c+'">'+(a==null?'NO DATA':ageText(a))+'</b></span>'}).join('');document.getElementById('sources').innerHTML=sourceHtml+'<span class="source">UI <b class="ok">LIVE</b></span>'}
async function poll(){try{const results=await Promise.all(AIRPORTS.map(a=>fetch('/api/airport/'+a.icao+'/live',{cache:'no-store'}).then(r=>r.json()).catch(()=>({error:'fetch'}))));results.forEach((d,i)=>{if(!d.error)updateCard(AIRPORTS[i],d)});updateSources();document.getElementById('clock').textContent=new Date().toLocaleTimeString()+' · refresh 5s';filterCards()}catch(e){}}
async function loadDetail(){try{const [ts,tr]=await Promise.all([fetch('/api/airport/'+selected+'/timeseries?hours=24',{cache:'no-store'}).then(r=>r.json()),fetch('/api/airport/'+selected+'/trading',{cache:'no-store'}).then(r=>r.json())]);drawChart(ts);drawTrading(tr)}catch(e){}}
function drawChart(d){const svg=document.getElementById('chart'),W=1000,H=310,L=45,R=15,T=15,B=30,rows=[...(d.metar||[]),...(d.series||[])].filter(x=>x.temp_c!=null);if(!rows.length){svg.innerHTML='<text x="45" y="60">NO 24H SENSOR HISTORY</text>';return}const min=Math.floor(Math.min(...rows.map(x=>x.temp_c))-1),max=Math.ceil(Math.max(...rows.map(x=>x.temp_c))+1),range=Math.max(1,max-min),start=new Date(Date.now()-24*3600000).getTime(),end=Date.now(),x=t=>L+(new Date(t).getTime()-start)/(end-start)*(W-L-R),y=v=>T+(max-v)/range*(H-T-B);let o='';for(let v=min;v<=max;v++){const yy=y(v);o+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+yy+'" y2="'+yy+'"/><text x="5" y="'+(yy+4)+'">'+v+'°</text>'}const met=(d.metar||[]).map(p=>x(p.obs_time)+','+y(p.temp_c)).join(' ');if(met)o+='<polyline class="metar" fill="none" stroke-width="2.5" points="'+met+'"/>';const ids=[...new Set((d.series||[]).map(p=>p.station_id))];ids.slice(0,6).forEach(id=>{const pts=d.series.filter(p=>p.station_id===id&&p.temp_c!=null).map(p=>x(p.obs_time)+','+y(p.temp_c)).join(' ');if(pts)o+='<polyline class="pws" fill="none" stroke-width="1.5" opacity=".65" points="'+pts+'"/>'});svg.innerHTML=o}
function updateDetail(d){const m=d.metar||{},p=(d.pws||[]).filter(x=>x.temp_c!=null);document.getElementById('dTemp').textContent=fmt(m.temp_c,'°C');document.getElementById('dForecast').textContent=d.forecast?fmt(d.forecast.temp_c,'°C'):'—';const mx=p.length?Math.max(...p.map(x=>x.temp_c)):null;document.getElementById('dMax').textContent=mx==null?'—':fmt(mx,'°C');const near=p.sort((a,b)=>(a.distance_km||999)-(b.distance_km||999))[0];document.getElementById('dSpread').textContent=near&&m.temp_c!=null?fmt(near.temp_c-m.temp_c,'°C'):'—';const notice=document.getElementById('pwsNotice');notice.textContent=p.length?'PWS LIVE: '+p.length+' enabled stations · nearest '+fmt(near.distance_km,'km')+' · spread '+fmt(near.temp_c-m.temp_c,'°C'):'PWS registry has no live observations. Configure WEATHER_UNDERGROUND_API_KEY for Weather Company PWS data.'}
function drawTrading(d){const box=document.getElementById('market');if(!d.market||!d.market.length){box.innerHTML='<div class="bucket">NO MARKET DATA</div>';return}box.innerHTML=d.market.slice(0,8).map(x=>'<div class="bucket"><b>'+esc(x.bucket)+'</b><small>mkt '+fmt(x.market_prob*100,'%')+' · fair '+fmt(x.fair_prob*100,'%')+'</small><strong class="'+(x.edge_cents>0?'edge-pos':x.edge_cents<0?'edge-neg':'')+'">'+(x.edge_cents>0?'+':'')+fmt(x.edge_cents,'¢')+'</strong></div>').join('')}
const sel=document.getElementById('airportSelect');AIRPORTS.forEach(a=>{const o=document.createElement('option');o.value=a.icao;o.textContent=a.icao+' — '+a.city;sel.appendChild(o)});initMap();selectAirport(selected);poll();setInterval(poll,5000);setInterval(loadDetail,15000);setInterval(()=>{if(selected)loadDetail()},15000);
</script></body></html>
