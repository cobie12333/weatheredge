"""Jev weather decision layer."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .jev import JevError, enabled, evaluate

def _question(bucket_labels: list[str]) -> dict[str, Any]:
    return {
        "type": "choice",
        "instructions": (
            "Estimate which temperature bucket is most likely to be the official "
            "daily maximum at the target airport. Use observations, timing, wind, "
            "dew point, pressure, nearby sensors and forecast context. Do not use "
            "market prices to decide the weather outcome."
        ),
        "criteria": {label: f"The official daily maximum settles in the {label} C bucket."
                     for label in bucket_labels},
    }

def score_weather_state(state: dict[str, Any], bucket_labels: list[str]) -> dict[str, Any]:
    if not enabled():
        raise JevError("Jev is disabled: set TYPESAFE_API_KEY")
    result = evaluate(state, {"daily_max_bucket": _question(bucket_labels)})
    answer = result.get("answers", {}).get("daily_max_bucket", {})
    probabilities = answer.get("probabilities", {})
    if not probabilities:
        raise JevError(f"Jev returned no probabilities: {result}")
    return {
        "model": result.get("model", "jev-latest"),
        "choice": answer.get("choice"),
        "confidence": answer.get("confidence"),
        "probabilities": probabilities,
        "usage": result.get("usage", {}),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

def build_state(*, airport: str, market_date: str, current_temp_c: float | None,
                current_dewpoint_c: float | None, wind_speed_kt: float | None,
                wind_dir_deg: float | None, pressure_hpa: float | None,
                metar: str | None, nearby_observations=None, forecast=None) -> dict[str, Any]:
    return {
        "airport": airport, "market_date": market_date,
        "current": {"temperature_c": current_temp_c, "dewpoint_c": current_dewpoint_c,
                    "wind_speed_kt": wind_speed_kt, "wind_direction_deg": wind_dir_deg,
                    "pressure_hpa": pressure_hpa, "metar": metar},
        "nearby_observations": nearby_observations or [],
        "forecast": forecast or [],
    }
