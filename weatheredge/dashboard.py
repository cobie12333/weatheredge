#!/usr/bin/env python3
"""
WeatherEdge — Mission Control v0
Read-only instrument panel. Consumes existing SQLite tables only.
"""

import json
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, ".")
from db import get_connection
from analysis.lag_analysis import (
    compute_lag_for_day,
    compute_confidence_for_day,
    list_available_market_dates,
    is_post_fix,
    compute_collector_latency_minutes,
)

PORT = 8420


def get_dashboard_data():
    con = get_connection()
    try:
        data = {}

        for collector in ("metar", "market"):
            row = con.execute(
                "SELECT COUNT(*) as att, SUM(success) as succ FROM collection_log WHERE collector = ?",
                (collector,),
            ).fetchone()
            att, succ = row["att"] or 0, row["succ"] or 0
            data[f"{collector}_health"] = {
                "attempts": att, "successes": succ,
                "rate": round(succ / att * 100, 1) if att else None,
            }

        latest_metar = con.execute(
            "SELECT obs_time, temp_c, report_type, fetched_at, raw_metar FROM metar_obs ORDER BY obs_time DESC LIMIT 1"
        ).fetchone()
        data["latest_metar"] = dict(latest_metar) if latest_metar else None

        latest_fetch = con.execute(
            "SELECT fetched_at FROM market_price ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        if latest_fetch:
            latest_buckets = con.execute(
                "SELECT bucket_label, yes_price_cents, volume_usd FROM market_price WHERE fetched_at = ? ORDER BY yes_price_cents DESC",
                (latest_fetch["fetched_at"],),
            ).fetchall()
            data["latest_market"] = {"fetched_at": latest_fetch["fetched_at"], "buckets": [dict(b) for b in latest_buckets]}
        else:
            data["latest_market"] = None

        dates = list_available_market_dates(con)
        pre_fix = [d for d in dates if not is_post_fix(d)]
        post_fix_dates = [d for d in dates if is_post_fix(d)]
        data["dataset_status"] = {
            "total_days": len(dates), "pre_fix_days": len(pre_fix),
            "post_fix_days": len(post_fix_dates), "threshold": 15,
            "sufficient": len(post_fix_dates) >= 15,
        }

        if dates:
            most_recent = dates[-1]
            lag_result = compute_lag_for_day(con, most_recent)
            confidence = compute_confidence_for_day(con, most_recent)
            data["latest_day"] = {"date": most_recent, "lag": lag_result, "confidence": confidence}

            temp_rows = con.execute(
                "SELECT obs_time, temp_c FROM metar_obs WHERE obs_time LIKE ? AND temp_c IS NOT NULL ORDER BY obs_time ASC",
                (f"{most_recent}%",),
            ).fetchall()
            data["temp_series"] = [{"t": r["obs_time"], "v": r["temp_c"]} for r in temp_rows]

            top_bucket_row = con.execute(
                "SELECT bucket_label FROM market_price WHERE market_date = ? ORDER BY volume_usd DESC LIMIT 1",
                (most_recent,),
            ).fetchone()
            if top_bucket_row:
                price_rows = con.execute(
                    "SELECT fetched_at, yes_price_cents FROM market_price WHERE market_date = ? AND bucket_label = ? ORDER BY fetched_at ASC",
                    (most_recent, top_bucket_row["bucket_label"]),
                ).fetchall()
                data["market_series"] = {"bucket": top_bucket_row["bucket_label"], "points": [{"t": r["fetched_at"], "v": r["yes_price_cents"]} for r in price_rows]}
            else:
                data["market_series"] = None
        else:
            data["latest_day"] = None
            data["temp_series"] = []
            data["market_series"] = None

        latency_series = []
        for d in dates:
            lat = compute_collector_latency_minutes(con, d)
            if lat["median_latency_min"] is not None:
                latency_series.append({"date": d, "latency_min": lat["median_latency_min"]})
        data["latency_series"] = latency_series

        return data
    finally:
        con.close()


def render_html(data):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    metar_h = data["metar_health"]
    market_h = data["market_health"]

    def health_badge(rate):
        if rate is None:
            return '<span class="badge gray">N/A</span>'
        color = "green" if rate >= 95 else ("yellow" if rate >= 80 else "red")
        return f'<span class="badge {color}">{rate}%</span>'

    m = data["latest_metar"]
    if m:
        metar_html = f"""
        <div class="row"><span class="label">Report type</span><span class="val">{m['report_type']}</span></div>
        <div class="row"><span class="label">Observed at</span><span class="val">{m['obs_time']}</span></div>
        <div class="row"><span class="label">Temperature</span><span class="val big">{m['temp_c']}°C</span></div>
        <div class="row"><span class="label">Collected at</span><span class="val">{m['fetched_at']}</span></div>
        <div class="raw">{m['raw_metar']}</div>
        """
    else:
        metar_html = '<div class="empty">No METAR data yet</div>'

    mk = data["latest_market"]
    if mk:
        rows = "".join(
            f'<div class="row"><span class="label">{b["bucket_label"]}</span><span class="val">{b["yes_price_cents"]}c <small>(${b["volume_usd"]:,.0f} vol)</small></span></div>'
            for b in mk["buckets"]
        )
        market_html = f'<div class="row"><span class="label">As of</span><span class="val">{mk["fetched_at"]}</span></div>{rows}'
    else:
        market_html = '<div class="empty">No market data yet</div>'

    ds = data["dataset_status"]
    status_color = "green" if ds["sufficient"] else "yellow"
    status_text = "SUFFICIENT DATA" if ds["sufficient"] else "INSUFFICIENT DATA"
    dataset_html = f"""
    <div class="row"><span class="label">Total days</span><span class="val">{ds['total_days']}</span></div>
    <div class="row"><span class="label">Pre-fix days</span><span class="val">{ds['pre_fix_days']} <small>(unusable)</small></span></div>
    <div class="row"><span class="label">Post-fix days</span><span class="val">{ds['post_fix_days']} / {ds['threshold']}</span></div>
    <div class="row"><span class="badge {status_color}">{status_text}</span></div>
    """

    ld = data["latest_day"]
    if ld and ld["lag"]["status"] == "ok":
        lag = ld["lag"]
        conf = ld["confidence"]
        conf_color = {"HIGH": "green", "MEDIUM": "yellow", "LOW": "red"}.get(conf["confidence"], "gray")
        reasons_html = "".join(f"<li>{r}</li>" for r in conf["reasons"]) or "<li>None</li>"
        lag_html = f"""
        <div class="row"><span class="label">Date</span><span class="val">{ld['date']}</span></div>
        <div class="row"><span class="label">Actual max</span><span class="val">{lag['actual_max_c']}°C</span></div>
        <div class="row"><span class="label">Expected bucket</span><span class="val">{lag['expected_bucket']}</span></div>
        <div class="row"><span class="label">Raw lag</span><span class="val big">{lag['lag_minutes']} min</span></div>
        <div class="row"><span class="label">Market state at max</span><span class="val">{lag['market_state_at_max']}</span></div>
        """
        confidence_html = f"""
        <div class="row"><span class="label">Collector latency</span><span class="val">{conf['collector_latency_min']} min</span></div>
        <div class="row"><span class="label">METAR health</span><span class="val">{conf['metar_health_pct']}%</span></div>
        <div class="row"><span class="label">Market health</span><span class="val">{conf['market_health_pct']}%</span></div>
        <div class="row"><span class="label">Pre/Post fix</span><span class="val">{'POST-FIX' if conf['post_fix'] else 'PRE-FIX'}</span></div>
        <div class="row"><span class="badge {conf_color}">{conf['confidence']} CONFIDENCE</span></div>
        <ul class="reasons">{reasons_html}</ul>
        """
    else:
        lag_html = '<div class="empty">No resolved day yet</div>'
        confidence_html = '<div class="empty">No confidence data yet</div>'

    temp_series = json.dumps(data["temp_series"])
    market_series = json.dumps(data["market_series"])
    latency_series = json.dumps(data["latency_series"])

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>WeatherEdge Mission Control</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d1117; color: #c9d1d9; font-family: 'Courier New', monospace; padding: 20px; }}
  h1 {{ font-size: 18px; color: #58a6ff; margin-bottom: 4px; }}
  .subtitle {{ color: #8b949e; font-size: 12px; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-bottom: 20px; }}
  .panel {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; }}
  .panel h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: #8b949e; margin-bottom: 12px; border-bottom: 1px solid #30363d; padding-bottom: 8px; }}
  .row {{ display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }}
  .label {{ color: #8b949e; }}
  .val {{ color: #c9d1d9; text-align: right; }}
  .val.big {{ font-size: 20px; color: #58a6ff; }}
  .raw {{ margin-top: 8px; font-size: 11px; color: #6e7681; word-break: break-all; background: #0d1117; padding: 8px; border-radius: 4px; }}
  .empty {{ color: #6e7681; font-style: italic; font-size: 13px; }}
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 10px; font-size: 12px; font-weight: bold; }}
  .badge.green {{ background: #1a7f37; color: #fff; }}
  .badge.yellow {{ background: #9e6a03; color: #fff; }}
  .badge.red {{ background: #cf222e; color: #fff; }}
  .badge.gray {{ background: #30363d; color: #c9d1d9; }}
  .reasons {{ margin-top: 8px; padding-left: 18px; font-size: 12px; color: #f0883e; }}
  .chart-container {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; margin-bottom: 16px; height: 260px; }}
  .chart-container h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: #8b949e; margin-bottom: 12px; }}
</style>
</head>
<body>
<h1>WeatherEdge — Mission Control v0</h1>
<div class="subtitle">Read-only instrument panel · Generated {now} · Refresh to update</div>
<div class="grid">
  <div class="panel"><h2>Collector Health</h2>
    <div class="row"><span class="label">METAR</span><span class="val">{health_badge(metar_h['rate'])} <small>{metar_h['successes']}/{metar_h['attempts']}</small></span></div>
    <div class="row"><span class="label">Market</span><span class="val">{health_badge(market_h['rate'])} <small>{market_h['successes']}/{market_h['attempts']}</small></span></div>
  </div>
  <div class="panel"><h2>Latest METAR / SPECI</h2>{metar_html}</div>
  <div class="panel"><h2>Latest Market Prices</h2>{market_html}</div>
  <div class="panel"><h2>Dataset Status</h2>{dataset_html}</div>
  <div class="panel"><h2>Current Lag Measurement</h2>{lag_html}</div>
  <div class="panel"><h2>Research Confidence</h2>{confidence_html}</div>
</div>
<div class="chart-container"><h2>Temperature vs Time (latest day)</h2><canvas id="tempChart"></canvas></div>
<div class="chart-container"><h2>Market Probability vs Time (leading bucket, latest day)</h2><canvas id="marketChart"></canvas></div>
<div class="chart-container"><h2>Collector Latency Over Time (per day)</h2><canvas id="latencyChart"></canvas></div>
<script>
const tempData = {temp_series};
const marketData = {market_series};
const latencyData = {latency_series};
const darkGridOpts = {{ scales: {{ x: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#30363d' }} }}, y: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#30363d' }} }} }}, plugins: {{ legend: {{ labels: {{ color: '#c9d1d9' }} }} }} }};
new Chart(document.getElementById('tempChart'), {{ type: 'line', data: {{ labels: tempData.map(d => d.t.slice(11,16)), datasets: [{{ label: 'Temp (°C)', data: tempData.map(d => d.v), borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.1)', tension: 0.2 }}] }}, options: darkGridOpts }});
new Chart(document.getElementById('marketChart'), {{ type: 'line', data: {{ labels: marketData ? marketData.points.map(d => d.t.slice(11,16)) : [], datasets: [{{ label: marketData ? marketData.bucket + ' (cents)' : 'No data', data: marketData ? marketData.points.map(d => d.v) : [], borderColor: '#3fb950', backgroundColor: 'rgba(63,185,80,0.1)', tension: 0.2 }}] }}, options: darkGridOpts }});
new Chart(document.getElementById('latencyChart'), {{ type: 'bar', data: {{ labels: latencyData.map(d => d.date), datasets: [{{ label: 'Collector latency (min)', data: latencyData.map(d => d.latency_min), backgroundColor: '#f0883e' }}] }}, options: darkGridOpts }});
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        try:
            data = get_dashboard_data()
            html = render_html(data)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Dashboard error: {e}".encode("utf-8"))

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    print(f"WeatherEdge Mission Control running at http://localhost:{PORT}")
    print("Read-only. Refresh browser to update. Ctrl+C to stop.")
    server = HTTPServer(("localhost", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
