# WeatherEdge — FACT Research & Trading Platform

WeatherEdge is a research and paper-trading platform for Cape Town International Airport (FACT) weather prediction markets.

Research pipeline: SAWS + FACT METAR/SPECI + nearby PWS + Windy spatial layer + Polymarket CLOB → probabilistic Tmax model → calibration → chronological walk-forward evaluation → paper-trading signals.

## Status
This repository is the source-code handoff. Secrets, `.env`, runtime logs, SQLite databases, generated analysis outputs, and caches are intentionally excluded from Git.

## Nearby PWS watchlist and live activation
The manually curated watchlist is in `weatheredge/nearby_pws_watchlist.py` and contains 65 station IDs grouped by the airport/city codes from the supplied research list. Discovery seeds candidates into the `pws_station` database even without an API key.

New watchlist entries start with `verified=0` and `enabled=0`. Coordinates, distance, online status, and feed availability are not assumed.

### Start the live collectors on the laptop
1. Pull the latest `main` branch.
2. Set the Weather Underground / Weather Company API key in the shell environment; do not put it in source code, a commit, or the database:
   `export WEATHER_UNDERGROUND_API_KEY='your-key'`
3. From the repository root, probe FACT's curated candidates (currently IMATRO5) and enable only if the authenticated API returns a recent observation with matching station ID, QC passed, temperature, and coordinates:
   `python -m weatheredge.pws_live_activation --airport FACT`
4. Start the continuous METAR, market, and enabled-PWS collectors:
   `python -m weatheredge.live_runner`
5. Open the local dashboard at `http://127.0.0.1:8420` if the dashboard server is started separately by your existing workflow.

Without `WEATHER_UNDERGROUND_API_KEY`, the live PWS API cannot be queried; the public METAR/market collectors can still run. The activation command defaults to FACT to avoid sending 65 station requests at once. After checking results, probe other supported WeatherEdge airport codes explicitly, for example `--airport SAEZ,LEMD,EGLC,KSEA`. Airport groups absent from the canonical market registry are skipped rather than assigned invented coordinates.

The station list is a research aid, not a source of settlement observations. Nearby PWS are comparison inputs only; use the market's specified settlement source for final outcomes.

## Primary data sources
- FACT METAR/SPECI and other airport METARs
- SAWS/AfriGIS — South African forecasts and observations
- Weather Company PWS API
- Windy Maps/Stations APIs
- Polymarket Gamma/CLOB
- NOAA/weather.gov WRH Time Series as authoritative settlement source when specified by the market

## Safety
Paper trading only. Never commit API keys, wallet private keys, or other credentials.
