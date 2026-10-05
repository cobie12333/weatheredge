#!/usr/bin/env python3
"""FACT Tmax ESN feature extraction, training and live scoring."""

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .airports import AIRPORT_BY_ICAO
from .db import get_connection
from .reservoir import EchoStateTmax, ReservoirConfig

BUCKETS = list(range(15, 36))
FEATURES = (
    "temp", "dewpoint", "wind_speed", "wind_sin", "wind_cos",
    "pressure", "temp_delta", "dew_delta", "hour_sin", "hour_cos",
    "pws_temp", "pws_dewpoint", "pws_minus_airport", "pws_temp_delta",
)
INPUT_SIZE = len(FEATURES)


def _num(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _feature(row, prev, pws, prev_pws, tz):
    dt = datetime.fromisoformat(row["obs_time"].replace("Z", "+00:00")).astimezone(tz)
    hour = dt.hour + dt.minute / 60.0
    wind = math.radians(_num(row["wind_dir_deg"]))
    temp = _num(row["temp_c"])
    dew = _num(row["dewpoint_c"])
    ptemp = _num(pws["temp_c"], temp) if pws else temp
    pdew = _num(pws["dewpoint_c"], dew) if pws else dew
    prev_ptemp = _num(prev_pws["temp_c"], ptemp) if prev_pws else ptemp
    return [
        temp / 40.0, dew / 30.0, _num(row["wind_speed_kt"]) / 30.0,
        math.sin(wind), math.cos(wind), _num(row["pressure_hpa"], 1013.0) / 1100.0,
        (temp - _num(prev["temp_c"], temp)) / 10.0 if prev else 0.0,
        (dew - _num(prev["dewpoint_c"], dew)) / 10.0 if prev else 0.0,
        math.sin(2 * math.pi * hour / 24.0), math.cos(2 * math.pi * hour / 24.0),
        ptemp / 40.0, pdew / 30.0, (ptemp - temp) / 10.0,
        (ptemp - prev_ptemp) / 10.0 if prev_pws else 0.0,
    ]


def _pws_index(con, icao):
    rows = con.execute(
        """SELECT station_id,obs_time,temp_c,dewpoint_c,distance_km
           FROM pws_obs_multi WHERE airport_icao=? AND temp_c IS NOT NULL
           ORDER BY obs_time""", (icao,)
    ).fetchall()
    return [r for r in rows if r["obs_time"]]


def _nearest_pws(pws_rows, obs_time, max_minutes=45):
    target = datetime.fromisoformat(obs_time.replace("Z", "+00:00"))
    best, best_key = None, None
    for row in pws_rows:
        dt = datetime.fromisoformat(row["obs_time"].replace("Z", "+00:00"))
        age = abs((target - dt).total_seconds()) / 60.0
        if age > max_minutes:
            continue
        key = (age, _num(row["distance_km"], 9999.0))
        if best_key is None or key < best_key:
            best, best_key = row, key
    return best


def _build_sequence(rows, pws_rows, tz):
    seq, prev, prev_pws = [], None, None
    for row in rows:
        pws = _nearest_pws(pws_rows, row["obs_time"])
        seq.append(_feature(row, prev, pws, prev_pws, tz))
        prev, prev_pws = row, pws
    return seq


def _load_days(con, icao, cutoff_hour=12):
    tz = ZoneInfo(AIRPORT_BY_ICAO[icao]["tz"])
    rows = con.execute(
        """SELECT obs_time,temp_c,dewpoint_c,wind_dir_deg,wind_speed_kt,pressure_hpa
           FROM metar_multi WHERE station_id=? AND temp_c IS NOT NULL ORDER BY obs_time""",
        (icao,),
    ).fetchall()
    pws_rows = _pws_index(con, icao)
    outcomes = {r["market_date"]: r["actual_max_c"] for r in con.execute(
        "SELECT market_date,actual_max_c FROM outcome_multi WHERE station_id=?", (icao,)
    ).fetchall()}
    grouped = {}
    for row in rows:
        dt = datetime.fromisoformat(row["obs_time"].replace("Z", "+00:00")).astimezone(tz)
        if dt.hour < cutoff_hour:
            grouped.setdefault(dt.date().isoformat(), []).append(row)
    sequences, targets, dates = [], [], []
    for date, dayrows in grouped.items():
        if date in outcomes and len(dayrows) >= 3:
            sequences.append(_build_sequence(dayrows, pws_rows, tz))
            targets.append(float(outcomes[date]))
            dates.append(date)
    return sequences, targets, dates


def train_and_score(icao="FACT", market_date=None, cutoff_hour=12):
    tz = ZoneInfo(AIRPORT_BY_ICAO[icao]["tz"])
    if market_date is None:
        market_date = datetime.now(timezone.utc).astimezone(tz).date().isoformat()
    con = get_connection(readonly=True)
    try:
        sequences, targets, dates = _load_days(con, icao, cutoff_hour)
        keep = [i for i, d in enumerate(dates) if d < market_date]
        sequences = [sequences[i] for i in keep]
        targets = [targets[i] for i in keep]
        if len(sequences) < 20:
            return {"status": "INSUFFICIENT_HISTORY", "training_days": len(sequences),
                    "required_days": 20, "icao": icao, "market_date": market_date}
        model = EchoStateTmax(INPUT_SIZE, BUCKETS, ReservoirConfig())
        split = max(15, int(len(sequences) * 0.8))
        split = min(split, len(sequences) - 1)
        model.fit(sequences[:split], targets[:split])
        rows = con.execute(
            """SELECT obs_time,temp_c,dewpoint_c,wind_dir_deg,wind_speed_kt,pressure_hpa
               FROM metar_multi WHERE station_id=? ORDER BY obs_time""", (icao,)
        ).fetchall()
        today = [r for r in rows if
                 datetime.fromisoformat(r["obs_time"].replace("Z", "+00:00")).astimezone(tz).date().isoformat() == market_date
                 and datetime.fromisoformat(r["obs_time"].replace("Z", "+00:00")).astimezone(tz).hour < cutoff_hour
                 and r["temp_c"] is not None]
        if len(today) < 2:
            return {"status": "NO_CURRENT_SEQUENCE", "training_days": split,
                    "icao": icao, "market_date": market_date}
        seq = _build_sequence(today, _pws_index(con, icao), tz)
        probs = model.predict_proba(seq)
        return {"status": "OK", "icao": icao, "market_date": market_date,
                "cutoff_hour_local": cutoff_hour, "training_days": split,
                "validation_days": len(sequences) - split, "sequence_points": len(seq),
                "pws_features": True, "model": "echo_state_tmax_v1",
                "probabilities": probs, "top_bucket": max(probs, key=probs.get)}
    finally:
        con.close()


def persist(result):
    if result.get("status") != "OK":
        return
    con = get_connection()
    try:
        for bucket, probability in result["probabilities"].items():
            con.execute(
                """INSERT INTO reservoir_prediction
                   (station_id,market_date,scored_at,model,cutoff_hour_local,bucket_label,probability,training_days,sequence_points)
                   VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(station_id,market_date,model,cutoff_hour_local,bucket_label)
                   DO UPDATE SET scored_at=excluded.scored_at,probability=excluded.probability,
                                 training_days=excluded.training_days,sequence_points=excluded.sequence_points""",
                (result["icao"], result["market_date"], result["model"], result["cutoff_hour_local"],
                 bucket, probability, result["training_days"], result["sequence_points"]),
            )
        con.commit()
    finally:
        con.close()
