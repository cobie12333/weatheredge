#!/usr/bin/env python3
"""Run the WeatherEdge live collection loop."""

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from airports import AIRPORTS
from config.settings import MARKET_POLL_MINUTES_DAYTIME, MARKET_POLL_MINUTES_NIGHT, METAR_POLL_MINUTES
from db import setup_logger
import market_collector
import multi_metar_collector
import pws_discovery
import pws_multi_collector
import pws_rapid_collector

logger = setup_logger("live_runner")


def _minutes_for_market(airport):
    hour = datetime.now(ZoneInfo(airport["tz"])).hour
    return MARKET_POLL_MINUTES_DAYTIME if 6 <= hour < 20 else MARKET_POLL_MINUTES_NIGHT


def run_forever():
    last_metar = 0.0
    last_market = {a["icao"]: 0.0 for a in AIRPORTS}
    last_pws = 0.0
    last_pws_rapid = 0.0
    last_pws_discovery = 0.0

    while True:
        now = time.monotonic()

        if now - last_metar >= METAR_POLL_MINUTES * 60:
            logger.info("polling multi-airport METAR")
            multi_metar_collector.run()
            last_metar = now

        for airport in AIRPORTS:
            icao = airport["icao"]
            interval = _minutes_for_market(airport) * 60
            if now - last_market[icao] >= interval:
                logger.info("polling market %s", icao)
                market_collector.run(icao=icao)
                last_market[icao] = now

        if now - last_pws_discovery >= 6 * 60 * 60:
            logger.info("discovering nearby PWS")
            pws_discovery.run()
            last_pws_discovery = now

        if now - last_pws >= 5 * 60:
            logger.info("polling live PWS")
            pws_multi_collector.run()
            last_pws = now

        # Rapid history is a 24-hour snapshot, so refresh it less often than
        # current observations to avoid needless API calls.
        if now - last_pws_rapid >= 15 * 60:
            logger.info("polling PWS rapid 24h history")
            pws_rapid_collector.run()
            last_pws_rapid = now

        time.sleep(10)


if __name__ == "__main__":
    try:
        run_forever()
    except KeyboardInterrupt:
        logger.info("live runner stopped")
