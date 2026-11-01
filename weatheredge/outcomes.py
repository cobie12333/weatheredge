#!/usr/bin/env python3
"""Settlement-label capture and the FACT metar_obs mirror.

Why this exists: nothing in the repo wrote `outcome` / `outcome_multi`, so no
forecast could be scored. This module fills them in two honest tiers:

1. PROVISIONAL rows, derived from our own METAR collection. The daily high is
   the maximum reported METAR temperature on a completed local day. METAR
   temperatures are whole degrees and are not guaranteed to match a market's
   settlement source, so these rows are labelled `source_url = 'provisional:...'`
   and are never presented as settlement truth.
2. MANUAL rows, entered from the market's actual settlement source. A manual
   row always replaces a provisional one.

Usage:
    python -m weatheredge.outcomes                      # fill provisional, last 3 days
    python -m weatheredge.outcomes --days 10
    python -m weatheredge.outcomes --manual FACT 2026-10-30 24.0 --url <settlement url>
    python -m weatheredge.outcomes --mirror-fact        # copy FACT metar_multi -> metar_obs
"""

import argparse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .airports import AIRPORT_BY_ICAO, AIRPORTS
from .db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("outcomes")

PROVISIONAL_PREFIX = "provisional:"
PROVISIONAL_SOURCE = PROVISIONAL_PREFIX + "metar_multi/aviationweather.gov"
MIN_DISTINCT_LOCAL_HOURS = 18  # a day counts as covered only if METARs span this many local hours

_TIME_FORMATS = ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def parse_utc(text):
    if not text:
        return None
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def is_provisional(source_url):
    return bool(source_url) and str(source_url).startswith(PROVISIONAL_PREFIX)


def daily_max_from_metar(con, icao, local_date, tz_name, min_hours=MIN_DISTINCT_LOCAL_HOURS):
    """Return (max_temp_c, n_reports, distinct_hours) for one completed local day, or None.

    None means "not enough coverage to label this day", never a guess.
    """
    tz = ZoneInfo(tz_name)
    start_local = datetime(local_date.year, local_date.month, local_date.day, tzinfo=tz)
    lo = (start_local - timedelta(hours=2)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = (start_local + timedelta(hours=26)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = con.execute(
        "SELECT obs_time, temp_c FROM metar_multi WHERE station_id=? AND obs_time>=? AND obs_time<=?",
        (icao, lo, hi),
    ).fetchall()
    temps, hours = [], set()
    for r in rows:
        t = parse_utc(r["obs_time"])
        if t is None or r["temp_c"] is None:
            continue
        local = t.astimezone(tz)
        if local.date() != local_date:
            continue
        temps.append(float(r["temp_c"]))
        hours.add(local.hour)
    if not temps or len(hours) < min_hours:
        return None
    return max(temps), len(temps), len(hours)


def _write_outcome(con, icao, market_date, actual_max_c, source_url, overwrite):
    verb = "INSERT OR REPLACE" if overwrite else "INSERT OR IGNORE"
    cur = con.execute(
        f"""{verb} INTO outcome_multi (station_id, logged_at, market_date, actual_max_c, source_url)
            VALUES (?, ?, ?, ?, ?)""",
        (icao, utc_now_iso(), market_date, actual_max_c, source_url),
    )
    n = int(cur.rowcount > 0)
    if icao == "FACT":
        con.execute(
            f"""{verb} INTO outcome (logged_at, market_date, actual_max_c, source_url)
                VALUES (?, ?, ?, ?)""",
            (utc_now_iso(), market_date, actual_max_c, source_url),
        )
    return n


def record_manual(con, icao, market_date, actual_max_c, source_url):
    """Store a settlement-source value. Replaces any existing row for that day."""
    if icao not in AIRPORT_BY_ICAO:
        raise ValueError(f"Unknown airport ICAO: {icao}")
    if not source_url or is_provisional(source_url):
        raise ValueError("A manual outcome needs the settlement source URL")
    datetime.strptime(market_date, "%Y-%m-%d")
    n = _write_outcome(con, icao, market_date, float(actual_max_c), source_url, overwrite=True)
    con.commit()
    return n


def fill_provisional(con, days=3, now=None, airports=None):
    """Create provisional outcomes for completed local days that have none."""
    now = now or datetime.now(timezone.utc)
    written = skipped = 0
    for a in airports or AIRPORTS:
        tz = ZoneInfo(a["tz"])
        today_local = now.astimezone(tz).date()
        for back in range(1, days + 1):
            d = today_local - timedelta(days=back)
            existing = con.execute(
                "SELECT 1 FROM outcome_multi WHERE station_id=? AND market_date=?",
                (a["icao"], d.isoformat()),
            ).fetchone()
            if existing:
                continue
            res = daily_max_from_metar(con, a["icao"], d, a["tz"])
            if res is None:
                skipped += 1
                continue
            written += _write_outcome(con, a["icao"], d.isoformat(), res[0], PROVISIONAL_SOURCE, overwrite=False)
    con.commit()
    return {"written": written, "skipped_low_coverage": skipped}


def mirror_fact_metar(con, hours=48):
    """Copy recent FACT rows from metar_multi into legacy metar_obs (source='live').

    `lag_analysis` reads metar_obs, but the live runner writes only metar_multi.
    INSERT OR IGNORE on UNIQUE(obs_time) means an already-present legacy row wins,
    so this never alters rows the old collector wrote. fetched_at and receipt_time
    are copied unchanged so latency measures stay meaningful.
    """
    cut = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = con.execute(
        """SELECT fetched_at, obs_time, receipt_time, temp_c, raw_metar, report_type
           FROM metar_multi WHERE station_id='FACT' AND obs_time>=?""",
        (cut,),
    ).fetchall()
    n = 0
    for r in rows:
        cur = con.execute(
            """INSERT OR IGNORE INTO metar_obs
               (fetched_at, obs_time, receipt_time, temp_c, raw_metar, report_type, source)
               VALUES (?, ?, ?, ?, ?, ?, 'live')""",
            (r["fetched_at"], r["obs_time"], r["receipt_time"], r["temp_c"], r["raw_metar"], r["report_type"]),
        )
        n += int(cur.rowcount > 0)
    con.commit()
    return n


def run(days=3):
    con = get_connection()
    try:
        res = fill_provisional(con, days=days)
        mirrored = mirror_fact_metar(con)
        log_collection_attempt(con, "outcomes", True, rows_written=res["written"] + mirrored)
        logger.info("outcomes: %s mirrored_fact_metar=%s", res, mirrored)
        return res
    except Exception as exc:
        con.rollback()
        logger.exception("outcomes failed")
        log_collection_attempt(con, "outcomes", False, error_msg=str(exc))
        return {"written": 0, "skipped_low_coverage": 0, "error": str(exc)}
    finally:
        con.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--manual", nargs=3, metavar=("ICAO", "YYYY-MM-DD", "MAX_C"))
    p.add_argument("--url", help="settlement source URL (required with --manual)")
    p.add_argument("--mirror-fact", action="store_true")
    a = p.parse_args(argv)
    if a.manual:
        con = get_connection()
        try:
            record_manual(con, a.manual[0].upper(), a.manual[1], float(a.manual[2]), a.url)
        finally:
            con.close()
        print("manual outcome stored")
        return 0
    if a.mirror_fact:
        con = get_connection()
        try:
            print("mirrored", mirror_fact_metar(con))
        finally:
            con.close()
        return 0
    print(run(days=a.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
