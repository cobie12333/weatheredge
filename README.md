# WeatherEdge — FACT Research & Trading Platform

WeatherEdge is a research and paper-trading platform for Cape Town International Airport (FACT) weather prediction markets.

Research pipeline: SAWS + FACT METAR/SPECI + nearby PWS + Windy spatial layer + Polymarket CLOB → probabilistic Tmax models → calibration → chronological walk-forward evaluation → paper-trading signals.

## Status

This repository is the source-code handoff. Secrets, `.env`, runtime logs, SQLite databases, generated analysis outputs, and caches are intentionally excluded from Git.

## Experimental reservoir layer

WeatherEdge now includes a stdlib-only Echo State Network (ESN) for daily Tmax bucket probabilities.

The reservoir consumes the pre-noon airport time series plus the nearest available PWS observation at each airport observation time:

- temperature
- dewpoint
- wind speed/direction
- pressure
- temperature/dewpoint changes
- time-of-day phase
- nearest PWS temperature/dewpoint
- PWS minus airport temperature
- PWS temperature change

The ESN keeps its recurrent reservoir fixed and trains only a ridge-regularized readout. It outputs a probability distribution over integer Tmax buckets. The live runner scores the layer every 15 minutes and persists results in `reservoir_prediction`.

Run manually:

```bash
python -m weatheredge.reservoir_runner FACT
```

This is **research-only** until chronological walk-forward results demonstrate incremental skill versus persistence/NWP and calibration. It does not place orders.

## Primary data sources

- SAWS/AfriGIS — South African forecasts and observations
- FACT METAR/SPECI
- Weather Company PWS API
- Windy Maps/Stations APIs
- Polymarket Gamma/CLOB
- NOAA/weather.gov WRH Time Series as authoritative settlement source when specified by the market

## Safety

Paper trading only. Never commit API keys, wallet private keys, or other credentials.
