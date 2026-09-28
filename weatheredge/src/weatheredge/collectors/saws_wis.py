"""SAWS WIS 2.0 collector for FACT-area observations.

The SAWS WIS catalogue exposes FACT-related WIGOS identifiers in more than
one product.  0-20000-0-68816 appears in the TEMP (upper-air) stream, while
0-20000-0-68999 appears in the hourly SYNOP surface-observation stream.

This collector deliberately keeps the BUFR payload raw and only decodes it
when the optional eccodes Python package is installed. It never treats an
unverified decoded field as settlement truth.
"""

import base64
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


WIS_BASE_URL = "https://wis.weathersa.co.za/oapi"
SYNOP_COLLECTION = f"{WIS_BASE_URL}/collections/messages/items"
FACT_SURFACE_WIGOS = "0-20000-0-68999"
FACT_UPPER_AIR_WIGOS = "0-20000-0-68816"
SYNOP_METADATA_ID = "urn:wmo:md:za-weathersa:xoeh2t"
USER_AGENT = "weatheredge/0.1 (research)"


def _request_json(url: str, timeout: int = 20) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_messages(
    wigos_station_identifier: str = FACT_SURFACE_WIGOS,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Fetch recent WIS message notifications for a WIGOS station.

    WIS deployments differ in which OGC property filters they expose. The
    station property is sent as a filter first; callers should retain the raw
    response and verify returned station IDs before ingestion.
    """
    params = urllib.parse.urlencode(
        {
            "f": "json",
            "limit": str(limit),
            "wigos_station_identifier": wigos_station_identifier,
            "sortby": "-datetime",
        }
    )
    data = _request_json(f"{SYNOP_COLLECTION}?{params}")
    features = data.get("features", data.get("items", []))
    if not isinstance(features, list):
        return []

    # Never trust a server-side filter blindly.
    out = []
    for item in features:
        props = item.get("properties", item)
        if props.get("wigos_station_identifier") == wigos_station_identifier:
            out.append(props)
    return out


def decode_bufr_base64(value: str) -> bytes:
    return base64.b64decode(value)


def decode_with_eccodes(bufr_bytes: bytes) -> Dict[str, Any]:
    """Decode one BUFR message using ECMWF ecCodes.

    Returns the scalar keys exposed by ecCodes. Raises RuntimeError with an
    actionable message when ecCodes is not installed.
    """
    try:
        import eccodes
    except ImportError as exc:
        raise RuntimeError(
            "SAWS BUFR decoding requires the optional 'eccodes' Python package."
        ) from exc

    handle = eccodes.codes_bufr_new_from_message(bufr_bytes)
    if handle is None:
        raise RuntimeError("ecCodes could not create a BUFR handle")

    try:
        eccodes.codes_set(handle, "unpack", 1)
        result: Dict[str, Any] = {}
        for key in (
            "WMO_station_identifier",
            "stationOrSiteName",
            "latitude",
            "longitude",
            "heightOfStationGroundAboveMeanSeaLevel",
            "year",
            "month",
            "day",
            "hour",
            "minute",
            "airTemperatureAt2M",
            "dewpointTemperatureAt2M",
            "relativeHumidity",
            "windDirectionAt10M",
            "windSpeedAt10M",
            "nonCoordinatePressure",
            "airPressureAtStationLevel",
        ):
            try:
                result[key] = eccodes.codes_get(handle, key)
            except Exception:
                pass
        return result
    finally:
        eccodes.codes_release(handle)


def normalize_observation(
    message: Dict[str, Any],
    decoded: Dict[str, Any],
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Map a decoded SAWS surface report into weather_observation fields."""
    props = message.get("properties", message)
    observed_at = props.get("datetime")

    if not observed_at:
        parts = [
            decoded.get("year"),
            decoded.get("month"),
            decoded.get("day"),
            decoded.get("hour"),
            decoded.get("minute", 0),
        ]
        if all(v is not None for v in parts[:4]):
            observed_at = datetime(
                int(parts[0]), int(parts[1]), int(parts[2]),
                int(parts[3]), int(parts[4]),
                tzinfo=timezone.utc,
            ).isoformat().replace("+00:00", "Z")

    return {
        "source_id": "saws:wis:synop:FACT",
        "station_id": FACT_SURFACE_WIGOS,
        "observed_at": observed_at,
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
        "temp_c": decoded.get("airTemperatureAt2M"),
        "dewpoint_c": decoded.get("dewpointTemperatureAt2M"),
        "humidity_pct": decoded.get("relativeHumidity"),
        "wind_dir_deg": decoded.get("windDirectionAt10M"),
        "wind_speed_ms": decoded.get("windSpeedAt10M"),
        "pressure_hpa": decoded.get("airPressureAtStationLevel"),
        "raw_payload": json.dumps(
            {"message": message, "decoded": decoded}, sort_keys=True
        ),
        "quality_status": "decoded_saws_wis_unverified",
    }


if __name__ == "__main__":
    messages = fetch_messages()
    print(json.dumps(messages, indent=2))
