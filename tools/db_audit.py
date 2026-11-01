#!/usr/bin/env python3
"""Read-only data audit for a WeatherEdge SQLite database.

Usage:  python3 db_audit.py /path/to/weatheredge.db [--out audit_report.md]

Opens the database in read-only mode, never writes, never reads raw_payload
columns, and prints a markdown report: row counts and time ranges per table,
collector reliability from collection_log, METAR coverage gaps per station,
market snapshot coverage, and settlement-label coverage. Standard library only.
Share the report, not the database.
"""
import argparse
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

TIME_COL = {
    "metar_obs": "obs_time", "metar_multi": "obs_time", "metar_parsed": "obs_time",
    "pws_obs": "obs_time", "pws_obs_multi": "obs_time",
    "saws_obs": "obs_time", "saws_forecast": "target_date",
    "market_price": "fetched_at", "market_price_multi": "fetched_at",
    "outcome": "market_date", "outcome_multi": "market_date",
    "forecast_history": "valid_time", "forecast_history_multi": "valid_time",
    "collection_log": "attempted_at",
}


def parse(ts):
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def tables(con):
    return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}


def cols(con, t):
    return {r[1] for r in con.execute(f"pragma table_info({t})")}


def section_counts(con, have, out):
    out.append("## 1. Tables: rows and time range\n")
    out.append("| table | rows | earliest | latest |")
    out.append("|---|---:|---|---|")
    for t, c in TIME_COL.items():
        if t not in have:
            out.append(f"| {t} | (table missing) | | |")
            continue
        n = con.execute(f"select count(*) from {t}").fetchone()[0]
        lo = hi = ""
        if n and c in cols(con, t):
            lo, hi = con.execute(f"select min({c}), max({c}) from {t}").fetchone()
        out.append(f"| {t} | {n} | {lo or ''} | {hi or ''} |")
    out.append("")


def section_collectors(con, have, out, now):
    out.append("## 2. Collector reliability (from collection_log)\n")
    if "collection_log" not in have:
        out.append("collection_log missing.\n")
        return
    rows = con.execute(
        "select attempted_at, collector, success, rows_written, error_msg from collection_log"
    ).fetchall()
    if not rows:
        out.append("collection_log is empty.\n")
        return
    out.append("| collector | attempts 7d | success 7d | attempts 30d | success 30d | last success | last failure |")
    out.append("|---|---:|---:|---:|---:|---|---|")
    by = {}
    for ts, name, ok, _w, err in rows:
        by.setdefault(name, []).append((parse(ts), ok, err))
    errs = {}
    for name, items in sorted(by.items()):
        def window(days):
            cut = now - timedelta(days=days)
            sub = [i for i in items if i[0] and i[0] >= cut]
            return len(sub), (sum(1 for i in sub if i[1]) / len(sub) if sub else None)
        n7, s7 = window(7)
        n30, s30 = window(30)
        ok_ts = [i[0] for i in items if i[1] and i[0]]
        bad = [i for i in items if not i[1] and i[0]]
        last_ok = max(ok_ts).strftime("%Y-%m-%d %H:%M") if ok_ts else "never"
        last_bad = max(b[0] for b in bad).strftime("%Y-%m-%d %H:%M") if bad else "never"
        f = lambda x: "n/a" if x is None else f"{x:.0%}"
        out.append(f"| {name} | {n7} | {f(s7)} | {n30} | {f(s30)} | {last_ok} | {last_bad} |")
        errs[name] = Counter((b[2] or "")[:90] for b in bad)
    out.append("\nMost frequent failure messages:\n")
    for name, c in errs.items():
        for msg, k in c.most_common(2):
            out.append(f"- `{name}` x{k}: {msg}")
    out.append("")


def section_metar_gaps(con, have, out, now):
    out.append("## 3. METAR coverage and gaps, last 14 days (metar_multi)\n")
    if "metar_multi" not in have:
        out.append("metar_multi missing.\n")
        return
    cut = (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stations = [r[0] for r in con.execute("select distinct station_id from metar_multi")]
    if not stations:
        out.append("No rows.\n")
        return
    out.append("| station | reports | first | last | largest gap (h) | gaps over 3h |")
    out.append("|---|---:|---|---|---:|---:|")
    for s in sorted(stations):
        ts = [parse(r[0]) for r in con.execute(
            "select obs_time from metar_multi where station_id=? and obs_time>=? order by obs_time", (s, cut))]
        ts = [t for t in ts if t]
        if len(ts) < 2:
            out.append(f"| {s} | {len(ts)} | | | | |")
            continue
        gaps = [(b - a).total_seconds() / 3600 for a, b in zip(ts, ts[1:])]
        out.append(f"| {s} | {len(ts)} | {ts[0]:%Y-%m-%d %H:%M} | {ts[-1]:%Y-%m-%d %H:%M} | {max(gaps):.1f} | {sum(1 for g in gaps if g > 3)} |")
    out.append("")


def section_markets(con, have, out):
    out.append("## 4. Market snapshot coverage (market_price_multi)\n")
    if "market_price_multi" not in have:
        out.append("market_price_multi missing.\n")
        return
    rows = con.execute(
        """select station_id, count(distinct market_date), count(distinct fetched_at),
                  min(market_date), max(market_date) from market_price_multi group by station_id"""
    ).fetchall()
    if not rows:
        out.append("No rows.\n")
        return
    out.append("| station | market days | snapshots | first day | last day |")
    out.append("|---|---:|---:|---|---|")
    for r in rows:
        out.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |")
    out.append("")


def section_labels(con, have, out):
    out.append("## 5. Settlement labels vs market days (can accuracy be scored?)\n")
    if "market_price_multi" not in have:
        out.append("n/a\n")
        return
    days = {(r[0], r[1]) for r in con.execute("select distinct station_id, market_date from market_price_multi")}
    lab = set()
    if "outcome_multi" in have:
        lab |= {(r[0], r[1]) for r in con.execute("select station_id, market_date from outcome_multi")}
    if "outcome" in have:
        lab |= {("FACT", r[0]) for r in con.execute("select market_date from outcome")}
    if not days:
        out.append("No market days.\n")
        return
    out.append(f"- market days with snapshots: {len(days)}")
    out.append(f"- of those with a recorded outcome: {len(days & lab)}")
    missing = sorted(days - lab)
    out.append(f"- without outcome: {len(missing)}" + (f" (first few: {', '.join(f'{a} {b}' for a, b in missing[:5])})" if missing else ""))
    out.append("")


def section_forecasts(con, have, out):
    out.append("## 6. Forecast archive (forecast_history / forecast_history_multi)\n")
    for t in ("forecast_history", "forecast_history_multi"):
        if t not in have:
            out.append(f"- {t}: missing")
            continue
        n = con.execute(f"select count(*) from {t}").fetchone()[0]
        if not n:
            out.append(f"- {t}: 0 rows")
            continue
        models = con.execute(f"select model, lead_hours, count(*), min(valid_time), max(valid_time) from {t} group by model, lead_hours").fetchall()
        out.append(f"- {t}: {n} rows")
        for m in models:
            out.append(f"  - model={m[0]} lead={m[1]}h rows={m[2]} {m[3]} .. {m[4]}")
    out.append("")


def section_live_days(con, have, out, now):
    out.append("## 7. Live METAR days per date, last 30 days (metar_obs, source='live')\n")
    if "metar_obs" not in have:
        out.append("metar_obs missing.\n")
        return
    cut = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    rows = con.execute(
        "select substr(obs_time,1,10) d, count(*) from metar_obs where source='live' and obs_time>=? group by d order by d",
        (cut,)).fetchall()
    if not rows:
        out.append("No live rows in the last 30 days. If you have moved to go_live, the legacy FACT collector may no longer be feeding this table.\n")
        return
    out.append("| date | live reports |")
    out.append("|---|---:|")
    for d, n in rows:
        out.append(f"| {d} | {n} |")
    out.append("")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--out")
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=30)
    have = tables(con)
    now = datetime.now(timezone.utc)
    out = [f"# WeatherEdge database audit\n\nGenerated {now:%Y-%m-%d %H:%M} UTC. Read-only. No raw payloads read.\n"]
    for fn in (section_counts, section_collectors, section_metar_gaps, section_markets,
               section_labels, section_forecasts, section_live_days):
        try:
            if fn in (section_collectors, section_metar_gaps, section_live_days):
                fn(con, have, out, now)
            else:
                fn(con, have, out)
        except sqlite3.Error as e:
            out.append(f"(section {fn.__name__} failed: {e})\n")
    text = "\n".join(out)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)
    con.close()


if __name__ == "__main__":
    sys.exit(main())
