"""Small, dependency-free Cape Town climate-risk research pipeline.

Data is stored separately from WeatherEdge's live database. Reanalysis is a
gridded estimate, not an airport observation or archived forecast.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_DEFAULT = ROOT / "climaterisk.db"
LAT, LON = -33.97403, 18.60433
TZ = "Africa/Johannesburg"
OPEN_METEO = "https://archive-api.open-meteo.com/v1/archive"
USER_AGENT = "ClimateRisk-SA-research/0.1 (public-data research)"

SCHEMA = """
CREATE TABLE IF NOT EXISTS weather_hourly (
  local_time TEXT PRIMARY KEY, temp_c REAL, rain_mm REAL, wind_kmh REAL,
  cloud_pct REAL, shortwave_mj REAL, source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weather_daily (
  local_date TEXT PRIMARY KEY, tmax_c REAL, tmin_c REAL, tmean_c REAL,
  rain_mm REAL, wind_max_kmh REAL, et0_mm REAL, cdd18 REAL, hdd18 REAL,
  cat_c REAL, source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS power_hourly (
  timestamp TEXT PRIMARY KEY, demand_mw REAL, source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS water_readings (
  reading_date TEXT NOT NULL, dam TEXT NOT NULL, percentage_full REAL,
  stored_mcm REAL, source TEXT NOT NULL, PRIMARY KEY(reading_date, dam)
);
CREATE TABLE IF NOT EXISTS market_audit (
  market_date TEXT, bucket_label TEXT, snapshot_at TEXT, yes_price_cents REAL,
  forecast_probability REAL, raw_edge REAL, status TEXT
);
CREATE TABLE IF NOT EXISTS source_log (
  id INTEGER PRIMARY KEY, fetched_at TEXT NOT NULL, dataset TEXT NOT NULL,
  source_url TEXT NOT NULL, rows_written INTEGER NOT NULL, notes TEXT
);
"""
WATER_URL = "https://capetowndata.com/en/data/dam-levels/"
POWER_URL = "https://www.eskom.co.za/dataportal/demand-side/system-hourly-demand-and-available-capacity/"
WEATHER_DOC = "https://open-meteo.com/en/docs/historical-weather-api"
POLY_DOC = "https://institute.polymarket.com/data"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_weather(con: sqlite3.Connection, start: str, end: str) -> int:
    """Fetch FACT-grid ERA5 hourly/daily historical weather; end is inclusive."""
    params = {
        "latitude": LAT, "longitude": LON, "start_date": start, "end_date": end,
        "timezone": TZ, "temperature_unit": "celsius", "wind_speed_unit": "kmh",
        "precipitation_unit": "mm", "models": "era5",
        "hourly": "temperature_2m,precipitation,wind_speed_10m,cloud_cover,shortwave_radiation",
        "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum,wind_speed_10m_max,et0_fao_evapotranspiration",
    }
    url = OPEN_METEO + "?" + urllib.parse.urlencode(params)
    payload = fetch_json(url)
    hourly, daily = payload.get("hourly", {}), payload.get("daily", {})
    times = hourly.get("time", [])
    rows = []
    for i, stamp in enumerate(times):
        def at(key):
            values = hourly.get(key, [])
            return values[i] if i < len(values) else None
        rows.append((stamp, at("temperature_2m"), at("precipitation"),
                     at("wind_speed_10m"), at("cloud_cover"),
                     at("shortwave_radiation"), "Open-Meteo ERA5"))
    con.executemany(
        "INSERT OR REPLACE INTO weather_hourly VALUES (?,?,?,?,?,?,?)", rows
    )
    drows = []
    for i, day in enumerate(daily.get("time", [])):
        def dat(key):
            values = daily.get(key, [])
            return values[i] if i < len(values) else None
        tmean = dat("temperature_2m_mean")
        if tmean is None:
            hi, lo = dat("temperature_2m_max"), dat("temperature_2m_min")
            tmean = (hi + lo) / 2 if hi is not None and lo is not None else None
        cdd = max(tmean - 18.0, 0.0) if tmean is not None else None
        hdd = max(18.0 - tmean, 0.0) if tmean is not None else None
        drows.append((day, dat("temperature_2m_max"), dat("temperature_2m_min"),
                      tmean, dat("precipitation_sum"), dat("wind_speed_10m_max"),
                      dat("et0_fao_evapotranspiration"), cdd, hdd, tmean,
                      "Open-Meteo ERA5"))
    con.executemany(
        "INSERT OR REPLACE INTO weather_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)", drows
    )
    con.execute(
        "INSERT INTO source_log(fetched_at,dataset,source_url,rows_written,notes) VALUES(?,?,?,?,?)",
        (datetime.now().astimezone().isoformat(), "weather", url, len(rows),
         "ERA5 gridded reanalysis; not observed FACT METAR or a historical forecast"),
    )
    con.commit()
    return len(rows)


def import_power(con: sqlite3.Connection, filename: str) -> int:
    """Import Eskom CSV with a timestamp column and demand_mw (or demand) column."""
    count = 0
    with open(filename, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = {x.lower().strip(): x for x in (reader.fieldnames or [])}
        tcol = next((fields[k] for k in ("timestamp", "datetime", "date_time", "date") if k in fields), None)
        dcol = next((fields[k] for k in ("demand_mw", "demand", "rsa contracted demand", "actual demand") if k in fields), None)
        if not tcol or not dcol:
            raise ValueError("Power CSV needs timestamp/datetime and demand_mw/demand columns")
        for row in reader:
            stamp = row[tcol].strip()
            raw = row[dcol].strip().replace(",", "")
            try:
                value = float(raw)
            except ValueError:
                continue
            con.execute("INSERT OR REPLACE INTO power_hourly VALUES(?,?,?)",
                        (stamp, value, "Eskom CSV import"))
            count += 1
    con.execute(
        "INSERT INTO source_log(fetched_at,dataset,source_url,rows_written,notes) VALUES(?,?,?,?,?)",
        (datetime.now().astimezone().isoformat(), "power", POWER_URL, count,
         "Imported source CSV; national RSA demand, not City of Cape Town load"),
    )
    con.commit()
    return count


def import_water(con: sqlite3.Connection, filename: str) -> int:
    """Import CapeTownData workbook exported as CSV (one row per dam/date)."""
    count = 0
    with open(filename, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = {x.lower().strip(): x for x in (reader.fieldnames or [])}
        dcol = fields.get("date")
        damcol = fields.get("dam")
        pcol = fields.get("percentage_full")
        vcol = fields.get("stored_mcm") or fields.get("storage_mcm")
        if not dcol or not damcol or not (pcol or vcol):
            raise ValueError("Water CSV needs date, dam, and percentage_full or stored_mcm")
        for row in reader:
            dam = row[damcol].strip()
            if not dam or dam.lower() in ("nan", "none"):
                continue
            def number(col):
                if not col: return None
                try: return float(row[col].replace(",", "").strip())
                except (ValueError, AttributeError): return None
            con.execute("INSERT OR REPLACE INTO water_readings VALUES(?,?,?,?,?)",
                        (row[dcol].strip()[:10], dam, number(pcol), number(vcol),
                         "CapeTownData / City of Cape Town"))
            count += 1
    con.execute(
        "INSERT INTO source_log(fetched_at,dataset,source_url,rows_written,notes) VALUES(?,?,?,?,?)",
        (datetime.now().astimezone().isoformat(), "water", WATER_URL, count,
         "CSV export of published dam readings; weekly/daily cadence depends on source series"),
    )
    con.commit()
    return count


def regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    if len(xs) < 2:
        return (statistics.mean(ys) if ys else 0.0, 0.0)
    xm, ym = statistics.mean(xs), statistics.mean(ys)
    denom = sum((x - xm) ** 2 for x in xs)
    slope = sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / denom if denom else 0.0
    return ym - slope * xm, slope


def scores(actual: list[float], predicted: list[float]) -> dict:
    if not actual:
        return {"n": 0, "mae": None, "rmse": None}
    errors = [a - p for a, p in zip(actual, predicted)]
    return {"n": len(errors), "mae": round(statistics.mean(abs(e) for e in errors), 3),
            "rmse": round(math.sqrt(statistics.mean(e * e for e in errors)), 3)}


def temperature_backtest(con: sqlite3.Connection) -> dict:
    """Walk-forward Tmax: 7-day trailing mean vs yesterday persistence."""
    rows = con.execute(
        "SELECT local_date,tmax_c FROM weather_daily WHERE tmax_c IS NOT NULL ORDER BY local_date"
    ).fetchall()
    actual, model, persistence = [], [], []
    history = []
    for row in rows:
        value = float(row["tmax_c"])
        if len(history) >= 7:
            actual.append(value)
            model.append(statistics.mean(history[-7:]))
            persistence.append(history[-1])
        history.append(value)
    return {"model": "7-day trailing mean", "baseline": "previous-day persistence",
            "model_scores": scores(actual, model), "baseline_scores": scores(actual, persistence),
            "warning": "ERA5 reanalysis Tmax is the target; this is not a forecast-vs-observed FACT METAR backtest."}


def power_backtest(con: sqlite3.Connection) -> dict:
    rows = con.execute("""
      SELECT p.timestamp,p.demand_mw,w.temp_c
      FROM power_hourly p JOIN weather_hourly w ON substr(p.timestamp,1,13)=substr(w.local_time,1,13)
      WHERE p.demand_mw IS NOT NULL AND w.temp_c IS NOT NULL
      ORDER BY p.timestamp
    """).fetchall()
    if len(rows) < 48:
        return {"n": len(rows), "status": "Need at least 48 matched hourly rows; import Eskom CSV first."}
    split = max(24, int(len(rows) * 0.7))
    train, test = rows[:split], rows[split:]
    intercept, slope = regression([float(r["temp_c"]) for r in train],
                                  [float(r["demand_mw"]) for r in train])
    by_hour = defaultdict(list)
    for r in train:
        try: hour = datetime.fromisoformat(r["timestamp"].replace("Z","+00:00")).hour
        except ValueError: hour = int(r["timestamp"][11:13])
        by_hour[hour].append(float(r["demand_mw"]))
    actual, weather_pred, hour_pred = [], [], []
    for r in test:
        try: hour = datetime.fromisoformat(r["timestamp"].replace("Z","+00:00")).hour
        except ValueError: hour = int(r["timestamp"][11:13])
        actual.append(float(r["demand_mw"]))
        weather_pred.append(intercept + slope * float(r["temp_c"]))
        hour_pred.append(statistics.mean(by_hour[hour]) if by_hour[hour] else statistics.mean(x["demand_mw"] for x in train))
    return {"n_train": len(train), "n_test": len(test),
            "weather_model": scores(actual, weather_pred),
            "hour_of_day_baseline": scores(actual, hour_pred),
            "warning": "Eskom RSA system demand is a national proxy, not Cape Town municipal load. This is association/forecast testing, not causal attribution."}


def water_summary(con: sqlite3.Connection) -> dict:
    rows = con.execute("""
      SELECT reading_date,percentage_full,stored_mcm FROM water_readings
      WHERE lower(dam) IN ('total','system total','combined','six major dams')
         OR lower(dam) LIKE '%total%'
      ORDER BY reading_date
    """).fetchall()
    if not rows:
        return {"status": "No combined-system water rows imported yet."}
    latest = rows[-1]
    previous = rows[-2] if len(rows) > 1 else None
    return {"latest_date": latest["reading_date"], "percentage_full": latest["percentage_full"],
            "stored_mcm": latest["stored_mcm"],
            "change_percentage_points": round(latest["percentage_full"] - previous["percentage_full"], 3)
                if previous and latest["percentage_full"] is not None and previous["percentage_full"] is not None else None,
            "note": "Storage change is net inflow minus withdrawals and evaporation; it is not rainfall or river inflow alone."}


def market_check(con: sqlite3.Connection, weatheredge_db: str) -> dict:
    """Compare tomorrow's empirical Tmax bucket probabilities with pre-day market prices."""
    path = Path(weatheredge_db).expanduser()
    if not path.exists():
        return {"status": f"WeatherEdge database not found: {path}"}
    wx = con.execute("SELECT local_date,tmax_c FROM weather_daily WHERE tmax_c IS NOT NULL ORDER BY local_date").fetchall()
    if len(wx) < 35:
        return {"status": "Need at least 35 historical daily temperatures before estimating error probabilities."}
    target = (date.today() + timedelta(days=1)).isoformat()
    history = [float(r["tmax_c"]) for r in wx if r["local_date"] < target]
    if len(history) < 35:
        return {"status": "Insufficient history for tomorrow's forecast."}
    forecast = statistics.mean(history[-7:])
    # Expanding walk-forward residuals; each historical prediction uses only earlier observations.
    residuals = []
    vals = [float(r["tmax_c"]) for r in wx if r["local_date"] < target]
    for i in range(8, len(vals)):
        residuals.append(vals[i] - statistics.mean(vals[max(0, i-7):i]))
    if len(residuals) < 20:
        return {"status": "Insufficient forecast residual history."}
    market = sqlite3.connect(path)
    market.row_factory = sqlite3.Row
    try:
        rows = market.execute("""
          SELECT bucket_label,yes_price_cents,MAX(fetched_at) AS snapshot_at
          FROM market_price_multi WHERE station_id='FACT' AND market_date=?
          GROUP BY bucket_label
        """, (target,)).fetchall()
    except sqlite3.Error as exc:
        return {"status": f"WeatherEdge market table unavailable: {exc}"}
    finally:
        market.close()
    if not rows:
        return {"target_date": target, "tmax_forecast_c": round(forecast,2),
                "status": "No FACT market snapshot for tomorrow in local WeatherEdge DB."}
    output = []
    for row in rows:
        label = row["bucket_label"]
        import re
        match = re.search(r"(-?\d+(?:\.\d+)?)", label or "")
        if not match: continue
        bucket = float(match.group(1))
        # Exact integer/half-degree bucket is approximated as +/-0.5C; range labels aren't inferred.
        probability = sum(1 for e in residuals if bucket-0.5 <= forecast+e < bucket+0.5) / len(residuals)
        price = row["yes_price_cents"]
        edge = probability - float(price)/100 if price is not None else None
        output.append({"bucket": label, "model_probability": round(probability,4),
                       "market_yes_price": price, "raw_edge": round(edge,4) if edge is not None else None,
                       "snapshot_at": row["snapshot_at"]})
    return {"target_date": target, "forecast_tmax_c": round(forecast,2),
            "residual_sample_n": len(residuals), "buckets": output,
            "warning": "Research-only edge: ERA5-derived naive forecast, historical residual distribution and stored snapshot prices. Not an executable backtest; excludes spread, depth, fees, market rules and settlement verification."}


def report(con: sqlite3.Connection, weatheredge_db: str) -> None:
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("weather_hourly","weather_daily","power_hourly","water_readings")}
    print(json.dumps({"database": str(DB_DEFAULT), "row_counts": counts,
                      "temperature_backtest": temperature_backtest(con),
                      "electricity_backtest": power_backtest(con),
                      "water": water_summary(con),
                      "market_research": market_check(con, weatheredge_db)}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Cape Town ClimateRisk research MVP")
    parser.add_argument("--db", default=str(DB_DEFAULT), help="ClimateRisk SQLite database")
    parser.add_argument("--weatheredge-db", default="../weatheredge/weatheredge.db",
                        help="Existing WeatherEdge SQLite database for FACT market snapshots")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("fetch-weather")
    build.add_argument("--start", default="2025-01-01")
    build.add_argument("--end", default=(date.today()-timedelta(days=5)).isoformat())
    p = sub.add_parser("import-power"); p.add_argument("csv_file")
    w = sub.add_parser("import-water"); w.add_argument("csv_file")
    sub.add_parser("backtest")
    sub.add_parser("report")
    args = parser.parse_args()
    con = connect(Path(args.db).expanduser())
    try:
        if args.command == "fetch-weather":
            print(f"Stored {fetch_weather(con,args.start,args.end)} hourly ERA5 rows.")
        elif args.command == "import-power":
            print(f"Imported {import_power(con,args.csv_file)} hourly power rows.")
        elif args.command == "import-water":
            print(f"Imported {import_water(con,args.csv_file)} water rows.")
        elif args.command == "backtest":
            print(json.dumps({"temperature": temperature_backtest(con),
                              "electricity": power_backtest(con),
                              "water": water_summary(con)}, indent=2))
        elif args.command == "report":
            report(con, args.weatheredge_db)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()
