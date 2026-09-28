"""SAWS WIS collector entry point for the WeatherEdge pipeline.

The previous placeholder API collector targeted an unverified endpoint and an
obsolete saws_obs table. This implementation uses the verified SAWS WIS 2.0
message service instead.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict

from weatheredge.db import get_connection, log_collection_attempt, setup_logger
from weatheredge.collectors.saws_wis import (
    FACT_SURFACE_WIGOS,
    decode_bufr_base64,
    decode_with_eccodes,
    fetch_messages,
    normalize_observation,
)

logger = setup_logger("saws_wis_collector")


class SawsCollector:
    """Collect verified SAWS WIS surface messages for FACT."""

    def fetch_observations(self):
        return fetch_messages(FACT_SURFACE_WIGOS)

    def run(self) -> Dict[str, int]:
        con = get_connection()
        seen = 0
        decoded = 0
        written = 0
        try:
            messages = self.fetch_observations()
            seen = len(messages)

            for message in messages:
                content = message.get("content", {})
                encoded = content.get("value") if isinstance(content, dict) else None
                if not encoded:
                    continue

                try:
                    decoded_payload = decode_with_eccodes(
                        decode_bufr_base64(encoded)
                    )
                except RuntimeError as exc:
                    logger.warning("SAWS message retained but not decoded: %s", exc)
                    continue

                decoded += 1
                obs = normalize_observation(message, decoded_payload)

                if not obs.get("observed_at"):
                    continue

                con.execute(
                    """
                    INSERT OR IGNORE INTO weather_observation
                    (source_id, station_id, observed_at, fetched_at, temp_c,
                     dewpoint_c, humidity_pct, wind_dir_deg, wind_speed_ms,
                     pressure_hpa, raw_payload, quality_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        obs["source_id"],
                        obs["station_id"],
                        obs["observed_at"],
                        obs["fetched_at"],
                        obs["temp_c"],
                        obs["dewpoint_c"],
                        obs["humidity_pct"],
                        obs["wind_dir_deg"],
                        obs["wind_speed_ms"],
                        obs["pressure_hpa"],
                        obs["raw_payload"],
                        obs["quality_status"],
                    ),
                )
                written += 1

            con.commit()
            log_collection_attempt(
                con,
                "saws_wis_fact",
                success=True,
                rows_written=written,
            )
            return {
                "messages_seen": seen,
                "messages_decoded": decoded,
                "observations_written": written,
            }
        except Exception as exc:
            con.rollback()
            log_collection_attempt(
                con,
                "saws_wis_fact",
                success=False,
                error_msg=str(exc),
            )
            logger.exception("SAWS WIS collection failed")
            return {
                "messages_seen": seen,
                "messages_decoded": decoded,
                "observations_written": written,
            }
        finally:
            con.close()


if __name__ == "__main__":
    print(json.dumps(SawsCollector().run(), indent=2))
