# WeatherEdge — FACT Research & Trading Platform

WeatherEdge is a research and paper-trading platform for Cape Town International Airport (FACT) weather prediction markets.

Research pipeline: SAWS + FACT METAR/SPECI + nearby PWS + Windy spatial layer + Polymarket CLOB → probabilistic Tmax model → calibration → chronological walk-forward evaluation → paper-trading signals.

## Status
This repository is the source-code handoff. Secrets, `.env`, runtime logs, SQLite databases, generated analysis outputs, and caches are intentionally excluded from Git.

## Nearby PWS watchlist
The manually curated watchlist is in `weatheredge/nearby_pws_watchlist.py` and contains 65 station IDs grouped by the airport/city codes from the supplied research list. The discovery job seeds these candidates into the `pws_station` database table even when no Weather Company API key is configured.

Watchlist entries start with `verified=0` and `enabled=0`; no coordinates, distance, online status, or feed availability are assumed. Confirm each station and its observation feed before enabling live collection. The list is a research aid, not a source of settlement observations.

## Primary data sources
- SAWS/AfriGIS — South African forecasts and observations
- FACT METAR/SPECI
- Weather Company PWS API
- Windy Maps/Stations APIs
- Polymarket Gamma/CLOB
- NOAA/weather.gov WRH Time Series as authoritative settlement source when specified by the market

## Safety
Paper trading only. Never commit API keys, wallet private keys, or other credentials.
