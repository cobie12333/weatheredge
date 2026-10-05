#!/usr/bin/env python3
"""FACT Tmax ESN feature extraction, training and live scoring."""

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .airports import AIRPORT_BY_ICAO
from .db import get_connection
from .reservoir import EchoStateTmax, ReservoirConfig


BUCKETS = list(range(15, 36))
FEATURES = (
    "temp", "dewpoint", "wind_speed", "wind_sin", "wind_cos",
    "pressure", "temp_delta", "dew_delta", "hour_sin", "hour_cos",
)
INPUT_SIZE = len(FEATURES)


def _num(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _feature(row, prev, tz):
    dt = datetime.fromisoformat(row["obs_time"].replace("Z", "+00:00")).astimezone(tz)
    hour = dt.hour + dt.minute / 60.0
    wind = math.radians(_num(row["wind_dir_deg"]))
    temp = _num(row["temp_c"])
    dew = _num(row["dewpoint_c"])
    return [
        temp / 40.0,
        dew / 30.0,
        _num(row["wind_speed_kt"]) / 30.0,
        math.sin(wind),
        math.cos(wind),
        _num(row["pressure_hpa"], 1013.0) / 1100.0,
        (temp - _num(prev["temp_c"], temp)) / 10.0 if prev else 0.0,
        (dew - _num(prev["dewpoint_c"], dew)) / 10.0 if prev else 0.0,
        math.sin(2 * math.pi * hour / 24.0),
        math.cos(2 * math.pi * hour / 24.0),
    ]


def _load_days(con, icao, cutoff_hour=12):
    airport = AIRPORT_BY_ICAO[icao]
    tz = ZoneInfo(airport["tz"])
    rows = con.execute(
        """SELECT obs_time,temp_c,dewpoint_c,wind_dir_deg,wind_speed_kt,pressure_hpa
           FROM metar_multi
           WHERE station_id=? AND temp_c IS NOT NULL
           ORDER BY obs_time""",
        (icao,),
    ).fetchall()
    outcomes = {
        r["market_date"]: r["actual_max_c"]
        for r in con.execute(
            "SELECT market_date,actual_max_c FROM outcome_multi WHERE station_id=?",
            (icao,),
        ).fetchall()
    }

    grouped = {}
    for row in rows:
        dt = datetime.fromisoformat(row["obs_time"].replace("Z", "+00:00")).astimezone(tz)
        if dt.hour >= cutoff_hour:
            continue
        grouped.setdefault(dt.date().isoformat(), []).append(row)

    sequences, targets, dates = [], [], []
    for date, dayrows in grouped.items():
        if date not in outcomes or len(dayrows) < 3:
            continue
        seq, prev = [], None
        for row in dayrows:
            seq.append(_feature(row, prev, tz))
            prev = row
        sequences.append(seq)
        targets.append(float(outcomes[date]))
        dates.append(date)
    return sequences, targets, dates


def train_and_score(icao="FACT", market_date=None, cutoff_hour=12):
    airport = AIRPORT_BY_ICAO[icao]
    tz = ZoneInfo(airport["tz"])
    if market_date is None:
        market_date = datetime.now(timezone.utc).astimezone(tz).date().isoformat()

    con = get_connection(readonly=True)
    try:
        sequences, targets, dates = _load_days(con, icao, cutoff_hour=cutoff_hour)
        if len(sequences) < 20:
            return {"status": "INSUFFICIENT_HISTORY", "training_days": len(sequences),
                    "required_days": 20, "icao": icao, "market_date": market_date}

        model = EchoStateTmax(INPUT_SIZE, BUCKETS, ReservoirConfig())
        # Last available completed days are reserved implicitly by chronological
        # ordering: live scoring is only trained on days strictly before today.
        if market_date in dates:
            keep = [i for i, d in enumerate(dates) if d < market_date]
            sequences = [sequences[i] for i in keep]
            targets = [targets[i] for i in keep]
            dates = [dates[i] for i in keep]
        if len(sequences) < 20:
            return {"status": "INSUFFICIENT_HISTORY", "training_days": len(sequences),
                    "required_days": 20, "icao": icao, "market_date": market_date}

        # Keep a chronological validation tail out of the training fit.
        split = max(15, int(len(sequences) * 0.8))
        if split >= len(sequences):
            split = len(sequences) - 1
        model.fit(sequences[:split], targets[:split])

        # Score today's observations with the same cutoff.
        today_rows = con.execute(
            """SELECT obs_time,temp_c,dewpoint_c,wind_dir_deg,wind_speed_kt,pressure_hpa
               FROM metar_multi WHERE station_id=? AND obs_time IS NOT NULL
               ORDER BY obs_time""",
            (icao,),
        ).fetchall()
        today = []
        prev = None
        for row in today_rows:
            dt = datetime.fromisoformat(row["obs_time"].replace("Z", "+00:00")).astimezone(tz)
            if dt.date().isoformat() != market_date or dt.hour >= cutoff_hour:
                continue
            today.append(_feature(row, prev, tz))
            prev = row
        if len(today) < 2:
            return {"status": "NO_CURRENT_SEQUENCE", "training_days": split,
                    "icao": icao, "market_date": market_date}

        probs = model.predict_proba(today)
        result = {
            "status": "OK", "icao": icao, "market_date": market_date,
            "cutoff_hour_local": cutoff_hour, "training_days": split,
            "validation_days": len(sequences) - split, "sequence_points": len(today),
            "model": "echo_state_tmax_v1",
            "probabilities": probs,
            "top_bucket": max(probs, key=probs.get),
        }
        return result
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
                   (station_id, market_date, scored_at, model, cutoff_hour_local,
                    bucket_label, probability, training_days, sequence_points)
                   VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(station_id, market_date, model, cutoff_hour_local, bucket_label)
                   DO UPDATE SET scored_at=excluded.scored_at, probability=excluded.probability,
                                 training_days=excluded.training_days, sequence_points=excluded.sequence_points""",
                (result["icao"], result["market_date"], result["model"],
                 result["cutoff_hour_local"], bucket, probability,
                 result["training_days"], result["sequence_points"]),
            )
        con.commit()
    finally:
        con.close()
