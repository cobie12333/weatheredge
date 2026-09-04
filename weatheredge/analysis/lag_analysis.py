#!/usr/bin/env python3
"""
WeatherEdge Research Platform — Lag Analysis
Version 1.0 — FROZEN

READ-ONLY. This module never writes to the database. Every value here
is computed fresh from raw tables each time it's run. If an assumption
changes (e.g. the berg-wind threshold, the lag-detection method), this
script is what changes — not the schema, not stored columns.

Usage:
    python3 -m analysis.lag_analysis                  # full report
    python3 -m analysis.lag_analysis --date 2026-07-03 # single day detail
"""

import argparse
import sqlite3
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")
from db import get_connection

# The exact moment the collector-latency bug was fixed (hours=1 -> hours=3
# query window). Any day's data collected before this is PRE-FIX and must
# not be used to support or reject the lag hypothesis — the collector
# itself introduced up to ~150 minutes of artificial delay before this.
# Set once, on the day it was actually fixed. Do not backdate or adjust
# this to make more days count as "clean" — that would be exactly the
# kind of goalpost-moving the research discipline here is meant to prevent.
COLLECTOR_FIX_TIME = "2026-07-08T20:45:00Z"


def compute_information_edge_for_day(con: sqlite3.Connection, market_date: str) -> dict:
    """
    Phase 1 core measurement: characterize the one information edge
    under study — Observation -> Receipt -> Collector Detection —
    as two segments per report, for one day.

    Segment A: Observation -> Receipt
        obs_time to receipt_time. This is AWC's own internal ingestion
        speed — how fast the station's report enters AWC's system.

    Segment B: Receipt -> Collector Detection
        receipt_time to fetched_at. This UPPER-BOUNDS how long the
        report sat before becoming visible via the public API query —
        conflated with our own poll interval. We cannot distinguish
        "API took 90 min to serve it" from "our poll happened to land
        90 min later" using this data alone. Stating this limitation
        here, explicitly, rather than letting it be discovered again.

    Returns per-report segments and daily medians for both.
    """
    rows = con.execute(
        """
        SELECT obs_time, receipt_time, fetched_at, report_type FROM metar_obs
        WHERE obs_time LIKE ? AND obs_time IS NOT NULL
        ORDER BY obs_time ASC
        """,
        (f"{market_date}%",),
    ).fetchall()

    if not rows:
        return {"status": "no_data", "n": 0}

    fmt_obs = "%Y-%m-%dT%H:%M:%SZ"
    fmt_receipt_variants = ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"]

    def parse_receipt(s):
        for fmt in fmt_receipt_variants:
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
        return None

    segment_a = []  # obs -> receipt
    segment_b = []  # receipt -> fetched (upper bound)
    missing_receipt = 0

    for r in rows:
        if not r["receipt_time"]:
            missing_receipt += 1
            continue
        try:
            t_obs = datetime.strptime(r["obs_time"], fmt_obs).replace(tzinfo=timezone.utc)
            t_receipt = parse_receipt(r["receipt_time"])
            t_fetch = datetime.strptime(r["fetched_at"], fmt_obs).replace(tzinfo=timezone.utc)
            if t_receipt is None:
                missing_receipt += 1
                continue
            segment_a.append((t_receipt - t_obs).total_seconds() / 60)
            segment_b.append((t_fetch - t_receipt).total_seconds() / 60)
        except (ValueError, TypeError):
            continue

    result = {
        "status": "ok",
        "n_reports": len(rows),
        "n_missing_receipt_time": missing_receipt,
        "segment_a_obs_to_receipt": {
            "median_min": round(statistics.median(segment_a), 1) if segment_a else None,
            "n": len(segment_a),
        },
        "segment_b_receipt_to_collector": {
            "median_min": round(statistics.median(segment_b), 1) if segment_b else None,
            "max_min": round(max(segment_b), 1) if segment_b else None,
            "n": len(segment_b),
            "note": "Upper bound only — conflates true API-availability delay with poll interval.",
        },
    }
    return result



def compute_collector_latency_minutes(con: sqlite3.Connection, market_date: str) -> dict:
    """
    Median gap between obs_time (when the station observed it) and
    fetched_at (when our collector actually wrote the row), for one day.
    This is the instrument-calibration number established via the
    receiptTime cross-check on 2026-07-08 — real relay delay was 5-8
    minutes; anything far above that reflects collector delay, not the
    weather station or the market.

    CRITICAL: source='live' only. Bug found and fixed 2026-07-11 —
    backfilled rows set fetched_at to whenever the backfill script
    happened to run (e.g. days after obs_time), which is not a
    latency measurement at all. Including them produced nonsense
    multi-day "latency" values (~9870 min observed) and incorrectly
    forced every backfilled day to LOW confidence for a meaningless
    reason, masking whether the actual market-side lag was real.
    """
    rows = con.execute(
        """
        SELECT obs_time, fetched_at FROM metar_obs
        WHERE obs_time LIKE ? AND obs_time IS NOT NULL AND fetched_at IS NOT NULL
        AND source = 'live'
        """,
        (f"{market_date}%",),
    ).fetchall()

    if not rows:
        return {"median_latency_min": None, "n": 0}

    fmt = "%Y-%m-%dT%H:%M:%SZ"
    gaps = []
    for r in rows:
        try:
            t_obs = datetime.strptime(r["obs_time"], fmt).replace(tzinfo=timezone.utc)
            t_fetch = datetime.strptime(r["fetched_at"], fmt).replace(tzinfo=timezone.utc)
            gaps.append((t_fetch - t_obs).total_seconds() / 60)
        except (ValueError, TypeError):
            continue

    if not gaps:
        return {"median_latency_min": None, "n": 0}

    return {"median_latency_min": round(statistics.median(gaps), 1), "n": len(gaps)}


def compute_collection_health_for_day(con: sqlite3.Connection, market_date: str) -> dict:
    """Success rate of collection_log entries for this specific date."""
    result = {}
    for collector in ("metar", "market"):
        rows = con.execute(
            """
            SELECT success FROM collection_log
            WHERE collector = ? AND attempted_at LIKE ?
            """,
            (collector, f"{market_date}%"),
        ).fetchall()
        attempts = len(rows)
        successes = sum(r["success"] for r in rows)
        result[collector] = {
            "attempts": attempts,
            "successes": successes,
            "rate": round(successes / attempts * 100, 0) if attempts else None,
        }
    return result


def count_speci_captured(con: sqlite3.Connection, market_date: str) -> int:
    """
    How many SPECI (unscheduled) reports were captured this day.
    Note: this can only report what WAS captured, not what might have
    been missed — there is no ground-truth count of "true" SPECIs
    issued that we can check against. Absence of a SPECI here means
    either none were issued, or one was missed; the two are
    indistinguishable from this data alone.
    """
    row = con.execute(
        """
        SELECT COUNT(*) as n FROM metar_obs
        WHERE obs_time LIKE ? AND report_type = 'SPECI'
        """,
        (f"{market_date}%",),
    ).fetchone()
    return row["n"] if row else 0


def is_post_fix(market_date: str) -> bool:
    """
    Whether this date's data was collected entirely after the collector fix.
    NOTE: the fix happened mid-day on 2026-07-08, so that specific date is
    NOT cleanly post-fix — it contains both pre- and post-fix readings.
    Only dates strictly after the fix date count as clean.
    """
    fix_date = COLLECTOR_FIX_TIME[:10]
    return market_date > fix_date


def is_backfilled_day(con: sqlite3.Connection, market_date: str) -> bool:
    """
    True if this day has zero live-collected METAR rows — meaning the
    'before the collector-latency fix' reasoning doesn't apply at all,
    since that fix concerned live polling behavior, not historical
    archive data. Distinguishing this from is_post_fix (date-only)
    was needed after finding that fully-backfilled days were being
    mislabeled with a reason that doesn't describe their actual data.
    """
    row = con.execute(
        "SELECT COUNT(*) as n FROM metar_obs WHERE obs_time LIKE ? AND source = 'live'",
        (f"{market_date}%",),
    ).fetchone()
    return (row["n"] or 0) == 0


def compute_confidence_for_day(con: sqlite3.Connection, market_date: str) -> dict:
    """
    Combine collector health, latency, and pre/post-fix status into a
    single confidence rating for whether this day's lag measurement is
    scientifically usable. This is a simple, explicit, arguable rule —
    not a model — stated plainly so it can be revised if wrong.
    """
    health = compute_collection_health_for_day(con, market_date)
    latency = compute_collector_latency_minutes(con, market_date)
    speci_count = count_speci_captured(con, market_date)
    post_fix = is_post_fix(market_date)
    backfilled = is_backfilled_day(con, market_date)

    metar_rate = health["metar"]["rate"]
    market_rate = health["market"]["rate"]
    lat = latency["median_latency_min"]

    reasons = []
    if backfilled:
        reasons.append(
            "Fully backfilled day — no live METAR polling occurred, so the "
            "collector-latency-fix timeline does not apply. Confidence here "
            "reflects backfill data completeness, not live instrument health."
        )
    elif not post_fix:
        reasons.append(
            "Collected before the collector-latency fix (2026-07-08) — "
            "measured lag may reflect instrument delay, not market behavior."
        )
    if lat is not None and lat > 30:
        reasons.append(f"Collector latency ({lat} min) exceeds the 30 min tolerance.")
    if metar_rate is not None and metar_rate < 90:
        reasons.append(f"METAR collection health only {metar_rate:.0f}%.")
    if market_rate is not None and market_rate < 90:
        reasons.append(f"Market collection health only {market_rate:.0f}%.")

    if backfilled:
        # Backfilled days are judged on data completeness alone, not
        # live-collector timing, which never applied to them.
        confidence = "MEDIUM"
    elif not post_fix or (lat is not None and lat > 30) or \
       (metar_rate is not None and metar_rate < 90) or \
       (market_rate is not None and market_rate < 90):
        confidence = "LOW"
    elif lat is not None and lat <= 15 and \
         (metar_rate is None or metar_rate >= 95) and \
         (market_rate is None or market_rate >= 95):
        confidence = "HIGH"
    else:
        confidence = "MEDIUM"

    return {
        "confidence": confidence,
        "post_fix": post_fix,
        "backfilled": backfilled,
        "collector_latency_min": lat,
        "metar_health_pct": metar_rate,
        "market_health_pct": market_rate,
        "speci_captured": speci_count,
        "reasons": reasons,
    }


def print_confidence_block(conf: dict) -> None:
    print("\n  --- Research Confidence ---")
    print(f"  Collector Latency     {conf['collector_latency_min']} min"
          if conf['collector_latency_min'] is not None else "  Collector Latency     n/a")
    print(f"  METAR Health          {conf['metar_health_pct']}%"
          if conf['metar_health_pct'] is not None else "  METAR Health          n/a")
    print(f"  Market Health         {conf['market_health_pct']}%"
          if conf['market_health_pct'] is not None else "  Market Health         n/a")
    print(f"  SPECI Captured        {conf['speci_captured']}")
    print(f"  Pre/Post Fix          {'POST-FIX' if conf['post_fix'] else 'PRE-FIX'}")
    print(f"\n  Confidence: {conf['confidence']}")
    if conf["reasons"]:
        print("  Reason:")
        for r in conf["reasons"]:
            print(f"    - {r}")


def print_dataset_status(con: sqlite3.Connection) -> None:
    """
    Overall dataset maturity — separate from any single day's confidence.
    Tracks how many clean, post-fix days exist toward the 15-20 day
    threshold the hypothesis needs before any statistical claim is made.
    """
    dates = list_available_market_dates(con)
    pre_fix = [d for d in dates if not is_post_fix(d)]
    post_fix_dates = [d for d in dates if is_post_fix(d)]

    print("\n=== Research Dataset ===")
    print(f"  Days collected:  {len(dates)}")
    print(f"  Pre-fix days:    {len(pre_fix)}  (not usable for hypothesis testing)")
    print(f"  Post-fix days:   {len(post_fix_dates)}")

    if len(post_fix_dates) < 15:
        print(f"\n  Research status: INSUFFICIENT DATA")
        print(f"  Reason: Need at least 15-20 clean post-fix days before drawing")
        print(f"          any statistical conclusion. Currently have {len(post_fix_dates)}.")
    else:
        print(f"\n  Research status: SUFFICIENT DATA — statistical testing may begin")


def classify_uncertainty_at_time(con: sqlite3.Connection, market_date: str, at_time: str) -> dict:
    """
    Check whether the market was a genuine "horse race" (multiple buckets
    still plausible) at a given timestamp, or already had a clear leader.

    This distinguishes two things that look identical in a raw lag number:
      - REAL LAG: one bucket was already clearly correct, but the market
        still priced a different bucket highly (slow to update on known info)
      - HONEST UNCERTAINTY: multiple buckets were genuinely close (e.g. two
        buckets both near 40-50%) because the true outcome hadn't been
        decided yet — not a market failure, just accurate uncertainty

    Uses the market_price snapshot closest to (but not before) at_time.
    No new table needed — reads the same top-3-bucket data already
    collected by market_collector.py.

    Returns the snapshot's bucket prices and a simple classification.
    """
    rows = con.execute(
        """
        SELECT fetched_at, bucket_label, yes_price_cents
        FROM market_price
        WHERE market_date = ? AND fetched_at >= ?
        ORDER BY fetched_at ASC
        LIMIT 10
        """,
        (market_date, at_time),
    ).fetchall()

    if not rows:
        return {"status": "no_data", "snapshot_time": None, "buckets": []}

    first_ts = rows[0]["fetched_at"]
    snapshot = [dict(r) for r in rows if r["fetched_at"] == first_ts]
    prices = sorted(
        [b["yes_price_cents"] or 0 for b in snapshot], reverse=True
    )

    # Simple, explicit rule — not a model, just a threshold, stated plainly
    # so it can be argued with: if the top two buckets are both above 25c,
    # more than one outcome was genuinely live. If the leader is above 80c
    # and everything else is below 20c, the outcome was already decided.
    if len(prices) >= 2 and prices[0] >= 25 and prices[1] >= 25:
        classification = "GENUINE_HORSE_RACE"
    elif prices and prices[0] >= 80:
        classification = "ALREADY_DECIDED"
    else:
        classification = "UNCLEAR"

    return {
        "status": "ok",
        "snapshot_time": first_ts,
        "buckets": snapshot,
        "classification": classification,
    }


def get_daily_max_from_metar(con: sqlite3.Connection, market_date: str) -> dict:
    """
    Derive the day's actual max temperature and its observation time
    directly from raw METAR rows — never from a stored/entered value.

    Window: obs_time falls on market_date, interpreted loosely as any
    METAR row whose obs_time string starts with market_date (UTC date).
    NOTE: Cape Town local date (SAST, UTC+2) and UTC date can differ
    near midnight — this is a known simplification for v1.0 and should
    be revisited only if it materially affects results.
    """
    rows = con.execute(
        """
        SELECT obs_time, temp_c FROM metar_obs
        WHERE obs_time LIKE ?
        AND temp_c IS NOT NULL
        ORDER BY obs_time ASC
        """,
        (f"{market_date}%",),
    ).fetchall()

    if not rows:
        return {"max_temp_c": None, "max_obs_time": None, "n_obs": 0}

    max_row = max(rows, key=lambda r: r["temp_c"])
    return {
        "max_temp_c": max_row["temp_c"],
        "max_obs_time": max_row["obs_time"],
        "n_obs": len(rows),
    }


def get_market_price_history(con: sqlite3.Connection, market_date: str, bucket_label: str) -> list:
    """Raw price history for one bucket on one market day, time-ordered."""
    rows = con.execute(
        """
        SELECT fetched_at, yes_price_cents, no_price_cents, volume_usd
        FROM market_price
        WHERE market_date = ? AND bucket_label = ?
        ORDER BY fetched_at ASC
        """,
        (market_date, bucket_label),
    ).fetchall()
    return [dict(r) for r in rows]


def find_leading_bucket_at_time(con: sqlite3.Connection, market_date: str, at_or_after: str) -> dict:
    """
    Find whichever bucket had the highest yes_price_cents at the first
    poll timestamp >= at_or_after. Used to check what the market
    believed immediately after the true max was locked in.
    """
    rows = con.execute(
        """
        SELECT fetched_at, bucket_label, yes_price_cents
        FROM market_price
        WHERE market_date = ? AND fetched_at >= ?
        ORDER BY fetched_at ASC
        LIMIT ?
        """,
        (market_date, at_or_after, 20),  # top N rows across buckets at that poll
    ).fetchall()

    if not rows:
        return None

    first_ts = rows[0]["fetched_at"]
    same_poll = [r for r in rows if r["fetched_at"] == first_ts]
    leader = max(same_poll, key=lambda r: r["yes_price_cents"] or 0)
    return dict(leader)


def compute_lag_for_day(con: sqlite3.Connection, market_date: str) -> dict:
    """
    Core analysis: for one market day, determine when the true max was
    locked in (last METAR reading of the day, if it's the max) and
    when the market's leading bucket matched that outcome with high
    confidence (>=80 cents). Returns a dict describing the finding —
    nothing here is written back to the database.
    """
    daily_max = get_daily_max_from_metar(con, market_date)
    if daily_max["max_temp_c"] is None:
        return {"market_date": market_date, "status": "no_metar_data"}

    max_temp = daily_max["max_temp_c"]
    max_obs_time = daily_max["max_obs_time"]
    expected_bucket_temp = round(max_temp)  # whole-degree resolution, per confirmed rules

    # Find when the market's price for the correct bucket first crossed 80 cents
    # AT OR AFTER the max was observed. This is the plain-English question:
    # "how long after we knew the answer did the market agree with high confidence?"
    rows = con.execute(
        """
        SELECT fetched_at, bucket_label, yes_price_cents
        FROM market_price
        WHERE market_date = ? AND fetched_at >= ?
        ORDER BY fetched_at ASC
        """,
        (market_date, max_obs_time),
    ).fetchall()

    confirmation_time = None
    for r in rows:
        label = (r["bucket_label"] or "").upper()
        if str(expected_bucket_temp) in label and (r["yes_price_cents"] or 0) >= 80:
            confirmation_time = r["fetched_at"]
            break

    lag_minutes = None
    if confirmation_time:
        t_max = datetime.strptime(max_obs_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        t_conf = datetime.strptime(confirmation_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        lag_minutes = (t_conf - t_max).total_seconds() / 60

    # Check what the market looked like AT the moment the true max was
    # observed — this separates real lag (already had a clear leader,
    # but it wasn't THIS bucket) from honest uncertainty (still a genuine
    # multi-bucket race because the outcome hadn't been decided yet).
    uncertainty = classify_uncertainty_at_time(con, market_date, max_obs_time)

    return {
        "market_date": market_date,
        "status": "ok",
        "actual_max_c": max_temp,
        "market_state_at_max": uncertainty.get("classification", "unknown"),
        "max_obs_time": max_obs_time,
        "n_metar_obs": daily_max["n_obs"],
        "expected_bucket": f"{expected_bucket_temp}C",
        "confirmation_time": confirmation_time,
        "lag_minutes": round(lag_minutes, 1) if lag_minutes is not None else None,
    }


import re


def parse_wind(raw_metar: str) -> dict:
    """
    Extract wind direction/speed from a raw METAR string.
    e.g. '18009KT' -> dir=180, speed_kt=9. Variable wind 'VRB' -> dir=None.
    Returns raw numbers only — no interpretation.
    """
    match = re.search(r"\b(\d{3}|VRB)(\d{2,3})(?:G\d{2,3})?KT\b", raw_metar)
    if not match:
        return {"wind_dir": None, "wind_speed_kt": None}
    direction = None if match.group(1) == "VRB" else int(match.group(1))
    return {"wind_dir": direction, "wind_speed_kt": int(match.group(2))}


def parse_dewpoint_c(raw_metar: str) -> float:
    """Second value in the temp/dewpoint group, e.g. '18/13' -> 13.0."""
    match = re.search(r"\s(M?\d{2})/(M?\d{2})\s", raw_metar)
    if not match:
        return None
    dp = match.group(2)
    return -float(dp[1:]) if dp.startswith("M") else float(dp)


def parse_pressure_hpa(raw_metar: str) -> float:
    """QNH group, e.g. 'Q1022' -> 1022.0."""
    match = re.search(r"\bQ(\d{4})\b", raw_metar)
    return float(match.group(1)) if match else None


def parse_sky(raw_metar: str) -> str:
    """First cloud layer or CAVOK/SKC, e.g. 'FEW035' -> 'FEW035'."""
    if "CAVOK" in raw_metar:
        return "CAVOK"
    match = re.search(r"\b(SKC|FEW\d{3}|SCT\d{3}|BKN\d{3}|OVC\d{3})\b", raw_metar)
    return match.group(1) if match else None


def get_raw_conditions_for_day(con: sqlite3.Connection, market_date: str) -> list:
    """
    Extract wind/dewpoint/pressure/sky from every raw_metar string for
    one day, at analysis time only — nothing stored, nothing
    interpreted. Purely descriptive extraction for a human to review
    across many days. Does not draw conclusions about causation.
    """
    rows = con.execute(
        "SELECT obs_time, temp_c, raw_metar, report_type FROM metar_obs "
        "WHERE obs_time LIKE ? ORDER BY obs_time ASC",
        (f"{market_date}%",),
    ).fetchall()

    result = []
    for r in rows:
        wind = parse_wind(r["raw_metar"])
        result.append({
            "obs_time": r["obs_time"],
            "report_type": r["report_type"],
            "temp_c": r["temp_c"],
            "dewpoint_c": parse_dewpoint_c(r["raw_metar"]),
            "wind_dir": wind["wind_dir"],
            "wind_speed_kt": wind["wind_speed_kt"],
            "pressure_hpa": parse_pressure_hpa(r["raw_metar"]),
            "sky": parse_sky(r["raw_metar"]),
        })
    return result


def get_latest_market_snapshot(con: sqlite3.Connection, market_date: str) -> dict:
    """
    Most recent poll's full bucket spread for a given day — real prices
    only, no derived probability, no narrative.
    """
    latest = con.execute(
        "SELECT fetched_at FROM market_price WHERE market_date = ? ORDER BY fetched_at DESC LIMIT 1",
        (market_date,),
    ).fetchone()
    if not latest:
        return {"fetched_at": None, "buckets": []}

    buckets = con.execute(
        "SELECT bucket_label, yes_price_cents, volume_usd FROM market_price "
        "WHERE market_date = ? AND fetched_at = ? ORDER BY yes_price_cents DESC",
        (market_date, latest["fetched_at"]),
    ).fetchall()
    return {
        "fetched_at": latest["fetched_at"],
        "buckets": [dict(b) for b in buckets],
    }


def print_situation_report(con: sqlite3.Connection, market_date: str) -> None:
    """
    Combined readout: latest real METAR conditions + latest real market
    prices, side by side. No probability estimate, no auto-generated
    explanation for why anything changed — that judgment stays with
    the person, using real numbers, not an invented model.
    """
    conditions = get_raw_conditions_for_day(con, market_date)
    market = get_latest_market_snapshot(con, market_date)

    print(f"\n=== Situation Report: {market_date} ===")

    if conditions:
        latest_obs = conditions[-1]
        temps_so_far = [c["temp_c"] for c in conditions if c["temp_c"] is not None]
        peak_so_far = max(temps_so_far) if temps_so_far else None

        print(f"\n  Latest observation ({latest_obs['obs_time'][11:16]} UTC, {latest_obs['report_type']}):")
        print(f"    Temp:        {latest_obs['temp_c']}°C")
        print(f"    Dewpoint:    {latest_obs['dewpoint_c']}°C")
        wind_str = (
            f"{latest_obs['wind_dir']}@{latest_obs['wind_speed_kt']}kt"
            if latest_obs["wind_dir"] is not None
            else (f"VRB@{latest_obs['wind_speed_kt']}kt" if latest_obs["wind_speed_kt"] is not None else "—")
        )
        print(f"    Wind:        {wind_str}")
        print(f"    Pressure:    {latest_obs['pressure_hpa']} hPa")
        print(f"    Sky:         {latest_obs['sky'] or '—'}")
        print(f"    Peak so far: {peak_so_far}°C")
    else:
        print("\n  No METAR data yet for this day.")

    if market["buckets"]:
        print(f"\n  Market as of {market['fetched_at'][11:16]} UTC:")
        for b in market["buckets"]:
            print(f"    {b['bucket_label']:>12}: {b['yes_price_cents']:>6.2f}c  (${b['volume_usd']:,.0f} vol)")
    else:
        print("\n  No market data yet for this day.")

    print(
        "\n  This is a raw readout, not a prediction. No probability or\n"
        "  explanation is generated automatically — that judgment is yours,\n"
        "  based on these real numbers."
    )


def print_raw_conditions(con: sqlite3.Connection, market_date: str) -> None:
    """Plain table, no narrative. The person draws their own conclusions."""
    rows = get_raw_conditions_for_day(con, market_date)
    if not rows:
        print(f"  No METAR data for {market_date}")
        return

    print(f"\n=== Raw Conditions: {market_date} (descriptive only, no interpretation) ===")
    print(f"  {'Time':<9} {'Type':<6} {'Temp':>5} {'Dewpt':>6} {'Wind':>10} {'Pressure':>9} {'Sky':>8}")
    for r in rows:
        wind_str = f"{r['wind_dir']}@{r['wind_speed_kt']}kt" if r["wind_dir"] is not None else (
            f"VRB@{r['wind_speed_kt']}kt" if r["wind_speed_kt"] is not None else "—"
        )
        print(
            f"  {r['obs_time'][11:16]:<9} {r['report_type']:<6} "
            f"{r['temp_c'] if r['temp_c'] is not None else '—':>5} "
            f"{r['dewpoint_c'] if r['dewpoint_c'] is not None else '—':>6} "
            f"{wind_str:>10} "
            f"{r['pressure_hpa'] if r['pressure_hpa'] is not None else '—':>9} "
            f"{r['sky'] or '—':>8}"
        )


def list_available_market_dates(con: sqlite3.Connection) -> list:
    """All distinct market_date values collected so far."""
    rows = con.execute(
        "SELECT DISTINCT market_date FROM market_price ORDER BY market_date ASC"
    ).fetchall()
    return [r["market_date"] for r in rows]


def collection_health_summary(con: sqlite3.Connection) -> dict:
    """
    Summarize collection_log to surface gaps — this is the survivorship
    bias check. A day with poor METAR/market coverage should be flagged,
    not silently included in the lag statistics.
    """
    metar_stats = con.execute(
        """
        SELECT
            COUNT(*) as attempts,
            SUM(success) as successes
        FROM collection_log WHERE collector = 'metar'
        """
    ).fetchone()

    market_stats = con.execute(
        """
        SELECT
            COUNT(*) as attempts,
            SUM(success) as successes
        FROM collection_log WHERE collector = 'market'
        """
    ).fetchone()

    return {
        "metar": {
            "attempts": metar_stats["attempts"] or 0,
            "successes": metar_stats["successes"] or 0,
        },
        "market": {
            "attempts": market_stats["attempts"] or 0,
            "successes": market_stats["successes"] or 0,
        },
    }


def run_full_report(con: sqlite3.Connection) -> None:
    """Print the day-by-day lag analysis and summary statistics."""
    health = collection_health_summary(con)
    print("\n=== Collection Health ===")
    for collector, stats in health.items():
        att, succ = stats["attempts"], stats["successes"]
        rate = (succ / att * 100) if att else 0
        print(f"  {collector}: {succ}/{att} successful polls ({rate:.0f}%)")

    dates = list_available_market_dates(con)
    print(f"\n=== Market days with data: {len(dates)} ===\n")

    results = []
    for d in dates:
        r = compute_lag_for_day(con, d)
        results.append(r)
        if r["status"] == "ok":
            gap_str = f"{r['lag_minutes']} min" if r["lag_minutes"] is not None else "no confirmation found"
            print(f"  {d}: actual_max={r['actual_max_c']}C  bucket={r['expected_bucket']}  confirmation_gap={gap_str}")
        else:
            print(f"  {d}: {r['status']}")

    gaps = [r["lag_minutes"] for r in results if r.get("lag_minutes") is not None]

    print(f"\n=== Summary (n={len(gaps)} days with a measured confirmation gap) ===")
    print("  NOTE: 'confirmation gap' is a raw time difference only — it does NOT")
    print("  mean the market was slow or wrong. It can reflect genuine weather")
    print("  uncertainty, collector-side latency, or actual market behavior.")
    print("  Check each day's Research Confidence and market_state_at_max before")
    print("  drawing any conclusion from this number.")
    if gaps:
        print(f"  Median confirmation gap: {statistics.median(gaps):.1f} min")
        print(f"  Mean confirmation gap:   {statistics.mean(gaps):.1f} min")
        if len(gaps) > 1:
            print(f"  Std dev:                 {statistics.stdev(gaps):.1f} min")
        print(f"  Min/Max:                 {min(gaps):.1f} / {max(gaps):.1f} min")
    else:
        print("  Not enough confirmed observations yet.")

    print(
        "\nReminder: this is a raw descriptive summary, not a significance test.\n"
        "Statistical testing (t-test, sign test) should be run explicitly once\n"
        "n >= 15-20 per the frozen kill/success criteria — not inferred from this printout."
    )


def print_observations_and_interpretation(r: dict) -> None:
    """Hard separation between objective facts and possible explanations."""
    print("\n  --- Observations (facts only) ---")
    print(f"  Actual max temperature: {r['actual_max_c']}C, observed at {r['max_obs_time']}")
    print(f"  Expected resolution bucket: {r['expected_bucket']}")
    if r["confirmation_time"]:
        print(f"  Market crossed 80c confidence on this bucket at {r['confirmation_time']}")
        print(f"  Confirmation gap (time-only, not a verdict): {r['lag_minutes']} minutes")
    else:
        print(f"  Market had not crossed 80c confidence on this bucket in available data")
    print(f"  Market state at moment of true max: {r['market_state_at_max']}")

    print("\n  --- Interpretation (hypotheses, not fact) ---")
    state = r.get("market_state_at_max")
    if state == "GENUINE_HORSE_RACE":
        print("  - Possible: genuine weather uncertainty (multiple outcomes still")
        print("    plausible when the true max occurred) — not necessarily a market failure.")
    elif state == "ALREADY_DECIDED":
        print("  - Possible: the correct outcome was already the clear leader, but the")
        print("    market took additional time to fully confirm it. This may reflect")
        print("    residual uncertainty, thin liquidity, or collector latency — not")
        print("    necessarily a market failure to notice known information.")
    else:
        print("  - Insufficient data to classify market state at time of true max.")
    print("  NOTE: the confirmation gap above is a raw time difference, not a")
    print("  verdict on market speed — check the Research Confidence block below")


def main():
    parser = argparse.ArgumentParser(description="WeatherEdge lag analysis (read-only)")
    parser.add_argument("--date", help="Show detail for a single market_date (YYYY-MM-DD)")
    parser.add_argument("--situation", help="Quick live readout for a date (YYYY-MM-DD) — no probability, just current conditions + prices")
    args = parser.parse_args()

    con = get_connection()

    if args.situation:
        print_situation_report(con, args.situation)
    elif args.date:
        r = compute_lag_for_day(con, args.date)
        print(f"\n=== Detail: {args.date} ===")
        for k, v in r.items():
            print(f"  {k}: {v}")
        if r["status"] == "ok":
            print_observations_and_interpretation(r)
            conf = compute_confidence_for_day(con, args.date)
            print_confidence_block(conf)
            print_raw_conditions(con, args.date)
    else:
        run_full_report(con)
        print_dataset_status(con)

    con.close()


if __name__ == "__main__":
    main()
