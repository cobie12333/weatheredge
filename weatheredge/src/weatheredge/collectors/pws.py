"""Personal Weather Station (PWS) collector."""

import json
import math
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from weatheredge.config import (
    WEATHER_COMPANY_API_KEY, HTTP_TIMEOUT_SECONDS, USER_AGENT,
    FACT_LAT, FACT_LON
)
from weatheredge.db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("pws_collector")

# Maximum distance from FACT to consider a PWS (in km)
MAX_PWS_DISTANCE_KM = 50


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in kilometers."""
    R = 6371  # Earth's radius in km

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = math.sin(delta_lat / 2) ** 2 + \
        math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


class PwsCollector:
    """Collect data from nearby Personal Weather Stations."""

    def __init__(self):
        self.api_key = WEATHER_COMPANY_API_KEY
        self.fact_lat = FACT_LAT
        self.fact_lon = FACT_LON
        self.max_distance = MAX_PWS_DISTANCE_KM

    def fetch_weather_company_pws(self) -> List[Dict[str, Any]]:
        """Fetch PWS data from Weather Company API."""
        import urllib.request
        import urllib.error

        if not self.api_key:
            logger.info("Weather Company API key not configured, skipping PWS fetch")
            return []

        # Weather Company PWS API endpoint
        url = (
            f"https://api.weather.com/v2/pws/observation/current"
            f"?apiKey={self.api_key}"
            f"&format=json"
            f"&units=m"
        )

        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                observations = data.get("observations", [])

                # Filter by distance from FACT
                filtered = []
                for obs in observations:
                    lat = obs.get("latitude")
                    lon = obs.get("longitude")
                    if lat is not None and lon is not None:
                        dist = haversine_distance(self.fact_lat, self.fact_lon, lat, lon)
                        if dist <= self.max_distance:
                            obs["_distance_km"] = round(dist, 2)
                            filtered.append(obs)

                return filtered
        except (urllib.error.URLError, TimeoutError) as e:
            logger.error(f"Network error fetching PWS data: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in PWS data: {e}")
            return []

    def quality_check(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        """Perform quality control checks on PWS observation."""
        qc = {
            "is_valid": True,
            "issues": [],
            "freshness_min": None,
        }

        # Check temperature bounds (-20 to 50 C for Cape Town)
        temp = obs.get("metric", {}).get("temp", {}) if isinstance(obs.get("metric"), dict) else obs.get("temp")
        if isinstance(temp, dict):
            temp_val = temp.get("value")
        else:
            temp_val = temp

        if temp_val is not None:
            try:
                temp_float = float(temp_val)
                if temp_float < -20 or temp_float > 50:
                    qc["is_valid"] = False
                    qc["issues"].append(f"Temperature out of range: {temp_float}")
            except (ValueError, TypeError):
                qc["is_valid"] = False
                qc["issues"].append(f"Invalid temperature value: {temp_val}")

        # Check freshness
        obs_time_str = obs.get("obsTimeUtc") or obs.get("obsTime")
        if obs_time_str:
            try:
                obs_time = datetime.strptime(obs_time_str.replace("Z", "+00:00").replace("+00:00", ""), "%Y%m%d%H%M%S")
                obs_time = obs_time.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                age_minutes = (now - obs_time).total_seconds() / 60
                qc["freshness_min"] = round(age_minutes, 1)

                if age_minutes > 60:
                    qc["issues"].append(f"Stale data: {age_minutes:.0f} minutes old")
            except (ValueError, TypeError):
                qc["issues"].append("Could not parse observation time")

        return qc

    def store_observation(self, con, obs: Dict[str, Any], qc_result: Dict[str, Any]) -> bool:
        """Store a PWS observation in the database."""
        try:
            fetched_at = utc_now_iso()

            # Extract station info
            station_id = obs.get("stationId", "UNKNOWN")
            lat = obs.get("latitude")
            lon = obs.get("longitude")
            distance_km = obs.get("_distance_km")

            # Extract weather data
            metric = obs.get("metric", {}) if isinstance(obs.get("metric"), dict) else {}
            temp_c = metric.get("temp", {}).get("value") if isinstance(metric.get("temp"), dict) else metric.get("temp")
            humidity = metric.get("humidity", {}).get("value") if isinstance(metric.get("humidity"), dict) else metric.get("humidity")
            dewpoint_c = metric.get("dewPt", {}).get("value") if isinstance(metric.get("dewPt"), dict) else metric.get("dewPt")
            wind_dir = metric.get("winddir", {}).get("value") if isinstance(metric.get("winddir"), dict) else metric.get("winddir")
            wind_speed = metric.get("wspd", {}).get("value") if isinstance(metric.get("wspd"), dict) else metric.get("wspd")
            pressure_hpa = metric.get("pressure", {}).get("value") if isinstance(metric.get("pressure"), dict) else metric.get("pressure")

            obs_time_str = obs.get("obsTimeUtc") or obs.get("obsTime")
            obs_time = None
            if obs_time_str:
                try:
                    obs_time_dt = datetime.strptime(obs_time_str.replace("Z", ""), "%Y%m%d%H%M%S")
                    obs_time = obs_time_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except (ValueError, TypeError):
                    pass

            raw_payload = json.dumps(obs)
            source = "weather_company"
            is_valid = int(qc_result["is_valid"])
            freshness_min = qc_result.get("freshness_min")
            issues = json.dumps(qc_result.get("issues", []))

            con.execute(
                """
                INSERT OR REPLACE INTO pws_obs
                (fetched_at, station_id, latitude, longitude, distance_km,
                 obs_time, temp_c, humidity, dewpoint_c, wind_dir, wind_speed,
                 pressure_hpa, source, is_valid, freshness_min, issues, raw_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (fetched_at, station_id, lat, lon, distance_km, obs_time,
                 temp_c, humidity, dewpoint_c, wind_dir, wind_speed,
                 pressure_hpa, source, is_valid, freshness_min, issues, raw_payload),
            )
            return True
        except Exception as e:
            logger.error(f"Error storing PWS observation: {e}")
            return False

    def run(self) -> Dict[str, int]:
        """Run the PWS collection process."""
        con = get_connection()
        total_written = 0
        total_invalid = 0

        try:
            observations = self.fetch_weather_company_pws()

            for obs in observations:
                qc_result = self.quality_check(obs)
                if self.store_observation(con, obs, qc_result):
                    total_written += 1
                    if not qc_result["is_valid"]:
                        total_invalid += 1

            log_collection_attempt(con, "pws", success=True, rows_written=total_written)
            logger.info(f"PWS collection complete: {total_written} stations ({total_invalid} flagged)")

            return {"stations": total_written, "invalid": total_invalid}

        except Exception as e:
            msg = f"PWS collection error: {e}"
            logger.error(msg)
            log_collection_attempt(con, "pws", success=False, error_msg=msg)
            return {"stations": 0, "invalid": 0}

        finally:
            con.close()


if __name__ == "__main__":
    import sys
    collector = PwsCollector()
    result = collector.run()
    print(json.dumps(result, indent=2))
    sys.exit(0)
