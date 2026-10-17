# WeatherEdge — FACT Research & Trading Platform

WeatherEdge is a research and paper-trading platform for Cape Town International Airport (FACT) weather prediction markets.

Research pipeline: SAWS + FACT METAR/SPECI + nearby PWS + Windy spatial layer + Polymarket CLOB → probabilistic Tmax model → calibration → chronological walk-forward evaluation → paper-trading signals.

## Status
This repository is the source-code handoff. Secrets, `.env`, runtime logs, SQLite databases, generated analysis outputs, and caches are intentionally excluded from Git.

## Nearby PWS watchlist and live activation
The manually curated watchlist is in `weatheredge/nearby_pws_watchlist.py` and contains 65 station IDs grouped by the airport/city codes from the supplied research list. The discovery job seeds candidates into the `pws_station` database even without an API key.

New candidates start with `verified=0` and `enabled=0`. Coordinates, distance, online status, and feed availability are not assumed. Both current PWS and rapid-history collectors query only stations marked `live_verified`, `verified=1`, and `enabled=1`.

## Start WeatherEdge live on antiX Linux
From the repository root (the folder containing this README), pull the latest `main` branch:

```bash
git pull origin main
```

To enable PWS probing, enter your Weather Underground / Weather Company API key without echoing it to the terminal, then export it for this session:

```bash
read -rsp 'Weather Company API key: ' WEATHER_UNDERGROUND_API_KEY; echo
export WEATHER_UNDERGROUND_API_KEY
```

Then start the live collectors and dashboard together:

```bash
python -m weatheredge.go_live
```

The launcher initializes the database, seeds the watchlist, probes FACT candidates (IMATRO5 plus the existing IMATRO4 and IBELLV58 candidates when an API key is configured), and enables only stations whose current API response has the matching ID, recent timestamp, passing quality-control flag, temperature, and coordinates. It then starts the continuous METAR, market, and eligible PWS collectors plus the local dashboard at `http://127.0.0.1:8420`.

Without an API key, METAR and market collection still start, but curated PWS candidates remain disabled and no PWS API observations are collected. Weather Company API access and quotas depend on the account/key; don't assume it is unlimited. Press Ctrl+C in the launcher terminal to stop both child processes. This is research/paper collection only; no market orders are placed.

After FACT, probe other supported WeatherEdge airport codes explicitly with `python -m weatheredge.pws_live_activation --airport SAEZ,LEMD,EGLC,KSEA`. This only checks those airports' listed/previously researched candidates; airports absent from the canonical market registry are skipped rather than assigned invented coordinates.

Nearby PWS stations are comparison inputs, not settlement sensors. Use the market's specified settlement source for final outcomes.

## Primary data sources
- FACT METAR/SPECI and other airport METARs
- SAWS/AfriGIS — South African forecasts and observations
- Weather Company PWS API
- Windy Maps/Stations APIs
- Polymarket Gamma/CLOB
- NOAA/weather.gov WRH Time Series as authoritative settlement source when specified by the market

## Safety
Paper trading only. Never commit API keys, wallet private keys, or other credentials.
