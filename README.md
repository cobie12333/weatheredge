# WeatherEdge — FACT Research & Trading Platform

WeatherEdge is a research and paper-trading platform for Cape Town International Airport (FACT) weather prediction markets.

Research pipeline: SAWS + FACT METAR/SPECI + nearby PWS + Windy spatial layer + Polymarket CLOB → probabilistic Tmax model → calibration → chronological walk-forward evaluation → paper-trading signals.

## Electricity-market research prototype

The `electricity/` directory is a separate, lightweight South African electricity research module. It discovers candidate public data downloads from official Eskom portal pages, records provenance for retrieved files, and includes walk-forward forecast baselines for normalized time series. It is not a live trading bot and does not assume a public SAWEM price API exists.

Start here: [electricity/README.md](electricity/README.md). The collector uses Python's standard library only. Review source-site terms and confirm timestamps, units, and source links before relying on any downloaded data.

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
