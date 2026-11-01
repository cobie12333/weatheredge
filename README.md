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

## RealityOS foundations (branch `reality-foundations`)

Goal: show, with evidence, whether weather information predicts real-world consequences (electricity demand first, then dam levels) better than a simple baseline, and whether a simulated hedge reduces financial exposure. Paper and research only. No exchange, token or payment code.

What was added (all standard library, no new dependencies):

| Module | Purpose |
|---|---|
| `weatheredge/outcomes.py` | Daily-high labels. `provisional:` rows come from our own METAR (whole degrees, may differ from a market's settlement source). `--manual` stores a settlement-source value and always replaces a provisional one. Also mirrors FACT `metar_multi` rows into `metar_obs` so `lag_analysis` keeps receiving live data. |
| `weatheredge/forecast_capture.py` | Stores Open-Meteo hourly forecasts with lead time in `forecast_history_multi` every 6 hours, so skill can be scored later. |
| `weatheredge/evaluation.py` | MAE, Brier, reliability, interval coverage, block-bootstrap CIs, `compare()` verdicts, small linear models, hedge effectiveness. |
| `weatheredge/demand_experiment.py` | Walk-forward test of weather vs calendar baselines on a daily demand CSV you assemble. |
| `live_runner.py`, `go_live.py`, `market_collector.py` | Each collector call is isolated, crashes are logged to `collection_log`, and `go_live` restarts a crashed child with back-off. |
| `tools/db_audit.py` | Read-only audit of a real database (row counts, collector success rates, METAR gaps, label coverage). |
| `docs/REALITYOS_AUDIT.md` | Evidence-labelled technical audit of this repository. |

Run the tests: `python -m unittest discover -s tests -t .`

Audit your data first: `python tools/db_audit.py weatheredge/weatheredge.db`

Weather vs demand test (needs a CSV you build from the Eskom Data Portal download and weather for the same place):

    python -m weatheredge.demand_experiment --csv daily.csv --y-col peak_gw \
        --date-col date --tmax-col tmax --tmin-col tmin --out report.md

A model is reported as better only when the whole 95% confidence interval of its loss difference is below zero.

Not yet verified live (the sandbox that wrote this could not reach external APIs): the Open-Meteo response parsing in `forecast_capture.py` is tested against a fixture shaped like the documented response. Check the first rows it writes. The Eskom file layout has not been seen; column names are therefore command-line options.
