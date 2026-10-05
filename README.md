# WeatherEdge — FACT Research & Trading Platform

WeatherEdge is a research and paper-trading platform for Cape Town International Airport (FACT) weather prediction markets.

Research pipeline: SAWS + FACT METAR/SPECI + nearby PWS + Windy spatial layer + Polymarket CLOB → probabilistic Tmax model → calibration → chronological walk-forward evaluation → paper-trading signals.

## Jev decision layer

WeatherEdge now has an optional TypeSafe Jev System One layer. Jev receives the latest WeatherEdge weather state and returns a typed probability distribution over candidate daily-maximum temperature buckets. The result is stored in the `jev_prediction` table for later calibration/backtesting.

Jev is **not** connected to order execution. Polymarket prices remain a separate input to the edge calculation after the weather distribution is produced.

Set the credentials locally:

    export TYPESAFE_API_KEY='your-key'
    export TYPESAFE_MODEL='jev-latest'

The integration uses Python's standard library and is disabled when `TYPESAFE_API_KEY` is absent.

API documentation: https://api.typesafe.ai/docs

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
