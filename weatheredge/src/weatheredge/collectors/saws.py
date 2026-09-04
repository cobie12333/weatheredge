"""SAWS (South African Weather Service) API collector."""

import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from weatheredge.config import (
    SAWS_API_KEY, SAWS_API_SECRET, SAWS_BASE_URL,
    HTTP_TIMEOUT_SECONDS, USER_AGENT, FACT_LAT, FACT_LON
)
from weatheredge.db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("saws_collector")


class SawsCollector:
    """Collect observations and forecasts from SAWS/AfriGIS API."""

    def __init__(self):
        self.api_key = SAWS_API_KEY
        self.api_secret = SAWS_API_SECRET
        self.base_url = SAWS_BASE_URL
        self.fact_lat = FACT_LAT
        self.fact_lon = FACT_LON

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for SAWS API."""
        if not self.api_key or not self.api_secret:
            logger.warning("SAWS API credentials not configured")
            return {"User-Agent": USER_AGENT}
        return {
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {self.api_key}",
            "X-API-Secret": self.api_secret,
        }

    def fetch_observations(self, station_id: str = "FACT") -> List[Dict[str, Any]]:
        """Fetch current observations from SAWS."""
        import urllib.request
        import urllib.error

        if not self.api_key:
            logger.info("SAWS API key not configured, skipping observations fetch")
            return []

        url = f"{self.base_url}/observations/{station_id}"
        try:
            req = urllib.request.Request(url, headers=self._get_auth_headers())
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("observations", []) if isinstance(data, dict) else []
        except (urllib.error.URLError, TimeoutError) as e:
            logger.error(f"Network error fetching SAWS observations: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in SAWS observations: {e}")
            return []

    def fetch_forecast(self, station_id: str = "FACT") -> List[Dict[str, Any]]:
        """Fetch forecast data from SAWS."""
        import urllib.request
        import urllib.error

        if not self.api_key:
            logger.info("SAWS API key not configured, skipping forecast fetch")
            return []

        url = f"{self.base_url}/forecast/{station_id}"
        try:
            req = urllib.request.Request(url, headers=self._get_auth_headers())
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("forecasts", []) if isinstance(data, dict) else []
        except (urllib.error.URLError, TimeoutError) as e:
            logger.error(f"Network error fetching SAWS forecast: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in SAWS forecast: {e}")
            return []

    def store_observation(self, con, obs: Dict[str, Any]) -> bool:
        """Store a SAWS observation in the database."""
        try:
            fetched_at = utc_now_iso()
            obs_time = obs.get("observationTime")
            if isinstance(obs_time, (int, float)):
                obs_time = datetime.fromtimestamp(obs_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            temp_c = obs.get("temperature")
            humidity = obs.get("humidity")
            dewpoint_c = obs.get("dewpoint")
            pressure_hpa = obs.get("pressure")
            wind_dir = obs.get("windDirection")
            wind_speed = obs.get("windSpeed")
            precipitation = obs.get("precipitation")
            cloud_cover = obs.get("cloudCover")

            raw_payload = json.dumps(obs)

            con.execute(
                """
                INSERT OR IGNORE INTO saws_obs
                (fetched_at, obs_time, temp_c, humidity, dewpoint_c, pressure_hpa,
                 wind_dir, wind_speed, precipitation, cloud_cover, raw_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (fetched_at, obs_time, temp_c, humidity, dewpoint_c, pressure_hpa,
                 wind_dir, wind_speed, precipitation, cloud_cover, raw_payload),
            )
            return True
        except Exception as e:
            logger.error(f"Error storing SAWS observation: {e}")
            return False

    def store_forecast(self, con, forecast: Dict[str, Any]) -> bool:
        """Store a SAWS forecast in the database."""
        try:
            fetched_at = utc_now_iso()
            issue_time = forecast.get("issueTime")
            target_date = forecast.get("validDate")
            max_temp = forecast.get("maxTemperature")
            min_temp = forecast.get("minTemperature")
            precipitation_prob = forecast.get("precipitationProbability")
            raw_payload = json.dumps(forecast)

            con.execute(
                """
                INSERT OR IGNORE INTO saws_forecast
                (fetched_at, issue_time, target_date, max_temp, min_temp,
                 precipitation_prob, raw_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (fetched_at, issue_time, target_date, max_temp, min_temp,
                 precipitation_prob, raw_payload),
            )
            return True
        except Exception as e:
            logger.error(f"Error storing SAWS forecast: {e}")
            return False

    def run(self) -> Dict[str, int]:
        """Run the SAWS collection process."""
        con = get_connection()
        obs_written = 0
        forecast_written = 0

        try:
            # Fetch and store observations
            observations = self.fetch_observations()
            for obs in observations:
                if self.store_observation(con, obs):
                    obs_written += 1

            # Fetch and store forecasts
            forecasts = self.fetch_forecast()
            for fcst in forecasts:
                if self.store_forecast(con, fcst):
                    forecast_written += 1

            total = obs_written + forecast_written
            log_collection_attempt(con, "saws", success=True, rows_written=total)
            logger.info(f"SAWS collection complete: {obs_written} obs, {forecast_written} forecasts")

            return {"observations": obs_written, "forecasts": forecast_written}

        except Exception as e:
            msg = f"SAWS collection error: {e}"
            logger.error(msg)
            log_collection_attempt(con, "saws", success=False, error_msg=msg)
            return {"observations": 0, "forecasts": 0}

        finally:
            con.close()


if __name__ == "__main__":
    import sys
    collector = SawsCollector()
    result = collector.run()
    print(json.dumps(result, indent=2))
    sys.exit(0)
