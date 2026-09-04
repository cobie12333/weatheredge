#!/usr/bin/env python3
"""
WeatherEdge — Historical Backfill: IEM METAR/SPECI
Version 1.0

Source: Iowa Environmental Mesonet ASOS archive.
Confirmed via live lookup: FACT is indexed under network ZA__ASOS,
data availability listed from 1949 (realistic automated coverage
will be much shorter — the archive itself states actual start date
per-station; this script does not assume full range works).

Endpoint: https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py
Format: onlycomma CSV, no auth required.

Design decision — temperature parsing:
IEM's own maintainer has published a documented warning about
Fahrenheit/Celsius round-trip rounding errors for temperature-wagering
use cases. FACT is a non-US, Celsius-native station. Rather than
requesting IEM's 'tmpf' field (Fahrenheit) and converting back to C
— which reintroduces exactly the rounding risk IEM warned about — this
module parses temp_c directly from the raw METAR string's temperature
group, the same whole-degree-C value the station actually transmitted.
This matches how metar_collector.py's live path already trusts the
station's own raw string as source of truth over any derived field.

Report type (METAR vs SPECI) is likewise parsed from the raw string's
first token, since IEM's CSV does not expose a dedicated column for it.
"""

import csv
import io
import re
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timezone

sys.path.insert(0, ".")
from db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("backfill_iem")

IEM_BASE = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
STATION = "FACT"
NETWORK = "ZA__ASOS"

# Matches the temperature/dewpoint group in a raw METAR, e.g. "18/13" or "M02/M05"
TEMP_GROUP_RE = re.compile(r"\s(M?\d{2})/(M?\d{2})\s")


def build_url(start: date, end: date) -> str:
    """
    Build the IEM request URL for a date range.
    data=metar is sufficient — we parse temp_c and report_type from the
    raw string ourselves, per the design decision above.
    """
    return (
        f"{IEM_BASE}?station={STATION}&network={NETWORK}"
        f"&data=metar"
        f"&year1={start.year}&month1={start.month}&day1={start.day}"
        f"&year2={end.year}&month2={end.month}&day2={end.day}"
        f"&tz=Etc%2FUTC&format=onlycomma&latlon=no&elev=no"
        f"&missing=M&trace=T&direct=no&report_type=3&report_type=4"
    )


def parse_temp_c(raw_metar: str) -> float:
    """
    Extract temperature in Celsius directly from the raw METAR string's
    temperature group (e.g. '18/13' -> 18.0). Returns None if no match.
    'M' prefix indicates negative (e.g. 'M02' -> -2).
    """
    match = TEMP_GROUP_RE.search(raw_metar)
    if not match:
        return None
    temp_str = match.group(1)
    if temp_str.startswith("M"):
        return -float(temp_str[1:])
    return float(temp_str)


def parse_report_type(raw_metar: str) -> str:
    """First token of a raw METAR/SPECI string identifies its type."""
    stripped = raw_metar.strip()
    if stripped.upper().startswith("SPECI"):
        return "SPECI"
    return "METAR"


def fetch_csv(start: date, end: date) -> str:
    url = build_url(start, end)
    req = urllib.request.Request(url, headers={"User-Agent": "weatheredge-research/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_csv(raw_csv: str) -> list:
    """
    Parse IEM's onlycomma CSV output. Expected columns include
    'station', 'valid' (observation time), and 'metar' (raw string).
    Skips the '#' comment header lines IEM prepends to output.
    """
    lines = [ln for ln in raw_csv.splitlines() if not ln.startswith("#")]
    if not lines:
        return []

    reader = csv.DictReader(lines)
    rows = []
    for row in reader:
        raw_metar = row.get("metar", "").strip()
        valid = row.get("valid", "").strip()
        if not raw_metar or not valid:
            continue

        try:
            # IEM 'valid' format: 'YYYY-MM-DD HH:MM'
            obs_dt = datetime.strptime(valid, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            obs_time = obs_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            logger.warning(f"Unparseable valid timestamp, skipping: {valid}")
            continue

        temp_c = parse_temp_c(raw_metar)
        report_type = parse_report_type(raw_metar)

        rows.append({
            "obs_time": obs_time,
            "temp_c": temp_c,
            "raw_metar": raw_metar,
            "report_type": report_type,
        })
    return rows


def backfill(start: date, end: date) -> dict:
    """
    Fetch and insert historical METAR/SPECI for FACT over [start, end].
    Tagged source='backfill_iem'. Uses the same INSERT OR IGNORE +
    UNIQUE(obs_time) deduplication as the live collector — a backfilled
    row and a live row for the same obs_time cannot both exist; live
    data (inserted first, in practice) wins by virtue of already being
    present, since IGNORE means the second INSERT is a no-op.
    """
    con = get_connection()
    logger.info(f"Backfilling IEM METAR/SPECI for {STATION}, {start} to {end}")

    try:
        try:
            raw_csv = fetch_csv(start, end)
        except (urllib.error.URLError, TimeoutError) as e:
            msg = f"Network error fetching IEM data: {e}"
            logger.error(msg)
            log_collection_attempt(con, "metar_backfill", success=False, error_msg=msg)
            return {"status": "error", "error": msg}

        rows = parse_csv(raw_csv)
        logger.info(f"Parsed {len(rows)} rows from IEM response")

        written = 0
        duplicates = 0
        for r in rows:
            try:
                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO metar_obs
                    (fetched_at, obs_time, temp_c, raw_metar, report_type, source)
                    VALUES (?, ?, ?, ?, ?, 'backfill_iem')
                    """,
                    (utc_now_iso(), r["obs_time"], r["temp_c"], r["raw_metar"], r["report_type"]),
                )
                if cur.rowcount:
                    written += 1
                else:
                    duplicates += 1
            except Exception as e:
                logger.error(f"DB write error on obs_time={r['obs_time']}: {e}")

        con.commit()
        log_collection_attempt(con, "metar_backfill", success=True, rows_written=written)

        logger.info(f"Backfill complete: {written} new rows, {duplicates} duplicates skipped")
        return {"status": "ok", "written": written, "duplicates": duplicates, "total_parsed": len(rows)}
    finally:
        con.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 backfill/iem_metar.py YYYY-MM-DD YYYY-MM-DD")
        sys.exit(1)
    start = date.fromisoformat(sys.argv[1])
    end = date.fromisoformat(sys.argv[2])
    result = backfill(start, end)
    print(result)
