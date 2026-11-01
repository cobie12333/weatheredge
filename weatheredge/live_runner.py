#!/usr/bin/env python3
"""Run the WeatherEdge live collection loop."""

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .airports import AIRPORTS
from .config.settings import MARKET_POLL_MINUTES_DAYTIME, MARKET_POLL_MINUTES_NIGHT, METAR_POLL_MINUTES
from .db import get_connection, log_collection_attempt, setup_logger
from . import forecast_capture
from . import market_collector
from . import multi_metar_collector
from . import outcomes
from . import pws_discovery
from . import pws_multi_collector
from . import pws_rapid_collector

logger = setup_logger("live_runner")


def _minutes_for_market(airport):
    hour = datetime.now(ZoneInfo(airport["tz"])).hour
    return MARKET_POLL_MINUTES_DAYTIME if 6 <= hour < 20 else MARKET_POLL_MINUTES_NIGHT


def _safe(name, fn, *args, **kwargs):
    """Run one collector; log and survive any exception so the loop keeps going."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.exception("collector %s crashed", name)
        try:
            con = get_connection()
            try:
                log_collection_attempt(con, name, False, error_msg=f"crash: {type(exc).__name__}: {exc}"[:300])
            finally:
                con.close()
        except Exception:
            logger.exception("could not record failure of %s", name)
        return None


def run_forever():
    last_metar = 0.0
    last_market = {a["icao"]: 0.0 for a in AIRPORTS}
    last_pws = 0.0
    last_pws_rapid = 0.0
    last_pws_discovery = 0.0
    last_forecast = 0.0
    last_outcomes = 0.0

    while True:
        now = time.monotonic()

        if now - last_metar >= METAR_POLL_MINUTES * 60:
            logger.info("polling multi-airport METAR")
            _safe("multi_metar", multi_metar_collector.run)
            last_metar = now

        for airport in AIRPORTS:
            icao = airport["icao"]
            interval = _minutes_for_market(airport) * 60
            if now - last_market[icao] >= interval:
                logger.info("polling market %s", icao)
                _safe(f"market:{icao}", market_collector.run, icao=icao)
                last_market[icao] = now

        if now - last_pws_discovery >= 6 * 60 * 60:
            logger.info("discovering nearby PWS")
            _safe("pws_discovery", pws_discovery.run)
            last_pws_discovery = now

        if now - last_pws >= 5 * 60:
            logger.info("polling live PWS")
            _safe("pws_multi", pws_multi_collector.run)
            last_pws = now

        # Rapid history is a 24-hour snapshot, so refresh it less often than
        # current observations to avoid needless API calls.
        if now - last_pws_rapid >= 15 * 60:
            logger.info("polling PWS rapid 24h history")
            _safe("pws_rapid", pws_rapid_collector.run)
            last_pws_rapid = now

        # Forecast vintages every 6 hours: stored before outcomes are known.
        if now - last_forecast >= 6 * 60 * 60:
            logger.info("capturing forecast vintages")
            _safe("forecast_capture", forecast_capture.run)
            last_forecast = now

        # Provisional outcome labels and the FACT metar_obs mirror, hourly.
        if now - last_outcomes >= 60 * 60:
            logger.info("filling provisional outcomes")
            _safe("outcomes", outcomes.run)
            last_outcomes = now

        time.sleep(10)


if __name__ == "__main__":
    try:
        run_forever()
    except KeyboardInterrupt:
        logger.info("live runner stopped")
