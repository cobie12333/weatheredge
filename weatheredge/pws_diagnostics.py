#!/usr/bin/env python3
"""Diagnose Weather Company PWS freshness without printing the API key.

Run from the repository root:
    python -m weatheredge.pws_diagnostics
"""
from datetime import datetime, timezone

from .pws_api import api_key, current, rapid_1day

STATIONS = ("IMATRO5", "IBELLV58")


def _timestamp(obs):
    value = obs.get("obsTimeUtc") or obs.get("obsTimeLocal") or obs.get("epoch")
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _temperature(obs):
    metric = obs.get("metric") or {}
    return metric.get("temp") if metric.get("temp") is not None else metric.get("tempAvg")


def _report(station, endpoint, payload, now):
    observations = payload.get("observations") or []
    valid = [(ts, obs) for obs in observations if (ts := _timestamp(obs)) is not None]
    latest_ts, latest_obs = max(valid, key=lambda item: item[0]) if valid else (None, None)
    age_min = round((now - latest_ts).total_seconds() / 60, 1) if latest_ts else None
    print(f"  {endpoint}: rows={len(observations)}")
    print(f"    latest_utc={latest_ts.isoformat() if latest_ts else 'NONE'}")
    print(f"    age_minutes={age_min if age_min is not None else 'N/A'}")
    print(f"    temp_c={_temperature(latest_obs) if latest_obs else 'N/A'}")
    print(f"    fresh_under_15m={bool(age_min is not None and 0 <= age_min < 15)}")


def main():
    key = api_key()
    if not key or key.strip().lower() in {"your_key", "paste_the_key_here"}:
        print("API key missing or placeholder: set WEATHER_UNDERGROUND_API_KEY in this shell.")
        return 2

    now = datetime.now(timezone.utc)
    for station in STATIONS:
        print(f"\n{station}")
        for endpoint, call in (("current", current), ("rapid_1day", rapid_1day)):
            try:
                payload = call(station, key)
                _report(station, endpoint, payload, datetime.now(timezone.utc))
            except Exception as exc:
                # API client errors are sanitized; don't print request URLs or credentials.
                print(f"  {endpoint}: ERROR {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
