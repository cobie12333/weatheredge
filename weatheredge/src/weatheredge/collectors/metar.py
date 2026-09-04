"""METAR/SPECI collector for FACT station."""

import json
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

from weatheredge.config import METAR_STATION_ID, HTTP_TIMEOUT_SECONDS, USER_AGENT, FACT_LAT, FACT_LON
from weatheredge.db import get_connection, log_collection_attempt, setup_logger, utc_now_iso

logger = setup_logger("metar_collector")

# Aviation Weather API endpoints
METAR_URL = f"https://aviationweather.gov/api/data/metar?ids={METAR_STATION_ID}&format=json&hours=6"


class MetarCollector:
    """Collect METAR and SPECI observations for FACT station."""

    def __init__(self):
        self.station_id = METAR_STATION_ID
        self.fact_lat = FACT_LAT
        self.fact_lon = FACT_LON

    def fetch_metar_data(self) -> List[Dict[str, Any]]:
        """Fetch METAR data from Aviation Weather API."""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(METAR_URL, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, list) else [data]
        except (urllib.error.URLError, TimeoutError) as e:
            logger.error(f"Network error fetching METAR: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return []

    @staticmethod
    def extract_obs_time(obs_time_field) -> Optional[str]:
        """Extract and normalize observation time."""
        if obs_time_field is None:
            return None
        if isinstance(obs_time_field, (int, float)):
            return datetime.fromtimestamp(obs_time_field, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return str(obs_time_field)

    @staticmethod
    def normalize_receipt_time(receipt_time_field) -> Optional[str]:
        """Normalize receipt time."""
        if receipt_time_field is None:
            return None
        return str(receipt_time_field)

    @staticmethod
    def parse_metar(raw_metar: str) -> Dict[str, Any]:
        """Parse raw METAR string to extract additional fields."""
        result = {
            "temp_c": None,
            "dewpoint_c": None,
            "wind_dir": None,
            "wind_speed_kt": None,
            "wind_gust_kt": None,
            "visibility_m": None,
            "pressure_hpa": None,
            "sky_condition": None,
            "weather_phenomena": None,
        }

        # Temperature/Dewpoint group: TT/DD or MTT/MDD
        temp_match = re.search(r'\s(M?\d{2})/(M?\d{2})\s', raw_metar)
        if temp_match:
            temp_str = temp_match.group(1)
            dew_str = temp_match.group(2)
            result["temp_c"] = -float(temp_str[1:]) if temp_str.startswith("M") else float(temp_str)
            result["dewpoint_c"] = -float(dew_str[1:]) if dew_str.startswith("M") else float(dew_str)

        # Wind: DDDSSKT or DDDSSGSSKT or VRBSSKT
        wind_match = re.search(r'(VRB|\d{3})(\d{2,3})(?:G(\d{2,3}))?KT\s', raw_metar)
        if wind_match:
            dir_str = wind_match.group(1)
            result["wind_dir"] = None if dir_str == "VRB" else int(dir_str)
            result["wind_speed_kt"] = int(wind_match.group(2))
            if wind_match.group(3):
                result["wind_gust_kt"] = int(wind_match.group(3))

        # Visibility: NNNN or N.NNSM
        vis_match = re.search(r'(\d{4})\s|M?(\d+\.?\d*)SM\s', raw_metar)
        if vis_match:
            if vis_match.group(1):
                result["visibility_m"] = int(vis_match.group(1)) * 1000  # km to m
            elif vis_match.group(2):
                result["visibility_m"] = float(vis_match.group(2)) * 1609.34  # SM to m

        # Pressure: Qnnnn or Annnn
        press_match = re.search(r'(?:Q|A)(\d{4})\s', raw_metar)
        if press_match:
            press_val = int(press_match.group(1))
            # Q is hPa, A is inches Hg * 100
            if raw_metar.find(f"Q{press_val:04d}") > 0:
                result["pressure_hpa"] = press_val
            else:
                result["pressure_hpa"] = round(press_val * 0.0338639, 1)  # inHg to hPa

        # Sky conditions
        sky_matches = re.findall(r'((?:FEW|SCT|BKN|OVC)(\d{3})(?:/([A-Z]+))?)\s', raw_metar)
        if sky_matches:
            result["sky_condition"] = [m[0] for m in sky_matches]

        # Weather phenomena
        wx_matches = re.findall(r'((-[A-Z]{2,})|(\+[A-Z]{2,})|([A-Z]{2,}))\s', raw_metar)
        if wx_matches:
            result["weather_phenomena"] = [m[0] for m in wx_matches if m[0]]

        return result

    def calculate_derivatives(self, recent_obs: List[Dict]) -> Dict[str, Optional[float]]:
        """Calculate temperature and wind derivatives from recent observations."""
        result = {
            "dT_dt": None,  # °C per hour
            "d2T_dt2": None,  # °C per hour²
            "du_dt": None,  # wind u-component change
            "dv_dt": None,  # wind v-component change
        }

        if len(recent_obs) < 2:
            return result

        # Sort by observation time
        sorted_obs = sorted(recent_obs, key=lambda x: x.get("obs_time", ""))

        # Calculate dT/dt from last two observations
        if len(sorted_obs) >= 2:
            t1, t2 = sorted_obs[-2], sorted_obs[-1]
            temp1 = t1.get("temp_c")
            temp2 = t2.get("temp_c")

            if temp1 is not None and temp2 is not None:
                try:
                    time1 = datetime.strptime(t1["obs_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    time2 = datetime.strptime(t2["obs_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    dt_hours = (time2 - time1).total_seconds() / 3600
                    if dt_hours > 0:
                        result["dT_dt"] = round((temp2 - temp1) / dt_hours, 2)
                except (ValueError, KeyError):
                    pass

        # Calculate d²T/dt² from last three observations
        if len(sorted_obs) >= 3:
            t1, t2, t3 = sorted_obs[-3:]
            temp1, temp2, temp3 = t1.get("temp_c"), t2.get("temp_c"), t3.get("temp_c")

            if all(t is not None for t in [temp1, temp2, temp3]):
                try:
                    time1 = datetime.strptime(t1["obs_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    time2 = datetime.strptime(t2["obs_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    time3 = datetime.strptime(t3["obs_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

                    dt1 = (time2 - time1).total_seconds() / 3600
                    dt2 = (time3 - time2).total_seconds() / 3600

                    if dt1 > 0 and dt2 > 0:
                        rate1 = (temp2 - temp1) / dt1
                        rate2 = (temp3 - temp2) / dt2
                        avg_dt = (dt1 + dt2) / 2
                        result["d2T_dt2"] = round((rate2 - rate1) / avg_dt, 2)
                except (ValueError, KeyError):
                    pass

        return result

    def run(self) -> int:
        """Run the METAR collection process."""
        con = get_connection()
        total_written = 0

        try:
            data = self.fetch_metar_data()

            if not data:
                msg = "Empty response from METAR API"
                logger.warning(msg)
                log_collection_attempt(con, "metar", success=False, error_msg=msg)
                return 0

            # Get recent observations for derivative calculation
            recent_rows = con.execute(
                "SELECT obs_time, temp_c, raw_metar FROM metar_obs ORDER BY obs_time DESC LIMIT 10"
            ).fetchall()
            recent_obs = [dict(row) for row in recent_rows]
            derivatives = self.calculate_derivatives(recent_obs)

            for obs in data:
                raw_metar = obs.get("rawOb", "")
                obs_time = self.extract_obs_time(obs.get("obsTime"))
                receipt_time = self.normalize_receipt_time(obs.get("receiptTime"))
                temp_c = obs.get("temp")
                report_type = obs.get("metarType", "METAR")

                if not raw_metar or not obs_time:
                    continue

                # Parse additional fields from raw METAR
                parsed = self.parse_metar(raw_metar)

                try:
                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO metar_obs
                        (fetched_at, obs_time, receipt_time, temp_c, raw_metar, report_type, source)
                        VALUES (?, ?, ?, ?, ?, ?, 'live')
                        """,
                        (utc_now_iso(), obs_time, receipt_time, temp_c, raw_metar, report_type),
                    )

                    # Also store parsed data in a separate table if it exists
                    if cur.rowcount:
                        total_written += 1
                        logger.info(f"Saved {report_type} obs_time={obs_time} temp_c={temp_c}")

                        # Store extended parsed data
                        try:
                            con.execute(
                                """
                                INSERT OR REPLACE INTO metar_parsed
                                (obs_time, dewpoint_c, wind_dir, wind_speed_kt, wind_gust_kt,
                                 visibility_m, pressure_hpa, sky_condition, weather_phenomena,
                                 dT_dt, d2T_dt2)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (obs_time, parsed["dewpoint_c"], parsed["wind_dir"],
                                 parsed["wind_speed_kt"], parsed["wind_gust_kt"],
                                 parsed["visibility_m"], parsed["pressure_hpa"],
                                 json.dumps(parsed["sky_condition"]),
                                 json.dumps(parsed["weather_phenomena"]),
                                 derivatives["dT_dt"], derivatives["d2T_dt2"]),
                            )
                        except sqlite3.OperationalError:
                            # Table doesn't exist yet, skip
                            pass

                except Exception as e:
                    msg = f"DB write error on {obs_time}: {e}"
                    logger.error(msg)
                    log_collection_attempt(con, "metar", success=False, error_msg=msg)
                    return total_written

            if total_written == 0:
                logger.info("No new METAR reports since last poll")

            log_collection_attempt(con, "metar", success=True, rows_written=total_written)
            return total_written

        finally:
            con.close()


if __name__ == "__main__":
    import sys
    collector = MetarCollector()
    written = collector.run()
    sys.exit(0 if written >= 0 else 1)
