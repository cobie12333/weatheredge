# WeatherEdge — FACT Research & Trading Platform

WeatherEdge is a research and paper-trading platform for Cape Town International Airport (FACT) weather prediction markets.

Research pipeline: SAWS + FACT METAR/SPECI + nearby PWS + Windy spatial layer + Polymarket CLOB → probabilistic Tmax model → calibration → chronological walk-forward evaluation → paper-trading signals.

## Status
This repository is the source-code handoff. Secrets, `.env`, runtime logs, SQLite databases, generated analysis outputs, and caches are intentionally excluded from Git.

## Primary data sources
- SAWS/AfriGIS — South African forecasts and observations
- FACT METAR/SPECI
- Weather Company PWS API
- Windy Maps/Stations APIs
- Polymarket Gamma/CLOB
- NOAA/weather.gov WRH Time Series as authoritative settlement source when specified by the market

## Safety
Paper trading only. Never commit API keys, wallet private keys, or other credentials.
