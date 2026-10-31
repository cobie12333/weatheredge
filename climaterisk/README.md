# ClimateRisk Cape Town MVP

A small, reproducible research layer alongside WeatherEdge. It connects:
- FACT-area historical weather and synthetic HDD/CDD/CAT indices;
- Eskom national hourly demand (optional CSV import);
- City of Cape Town dam storage readings (optional CSV import);
- WeatherEdge FACT market snapshots (read-only SQLite integration).

It is deliberately dependency-free (Python standard library only) and keeps its own SQLite database. It does **not** place orders.

## Quick start (antiX / Python 3.10+)

Run from the repository root:

```bash
python3 -m climaterisk.cli fetch-weather --start 2025-01-01 --end 2026-10-25
python3 -m climaterisk.cli backtest
python3 -m climaterisk.cli report
```

The default local database is `climaterisk/climaterisk.db`. The default WeatherEdge database for market comparison is `weatheredge/weatheredge.db`; override it with `--weatheredge-db /path/to/weatheredge.db`.

Open-Meteo historical API data is ERA5 gridded reanalysis at the FACT coordinates, not observed airport METAR and not an archived forecast. Its daily max/min/mean temperature, precipitation, wind and ET0 variables are used to calculate:
- `CDD18 = max(Tmean - 18, 0)`
- `HDD18 = max(18 - Tmean, 0)`
- `CAT = Tmean` (daily average temperature contribution)

The temperature backtest is a chronological walk-forward comparison of a trailing 7-day mean against previous-day persistence. It tests a simple baseline on ERA5 daily maximum temperature; it is **not** proof of forecast skill against FACT settlement observations. Use the existing WeatherEdge METAR data for the settlement-grade airport backtest.

## Electricity data

Download the CSV from the [Eskom hourly demand and available capacity portal](https://www.eskom.co.za/dataportal/demand-side/system-hourly-demand-and-available-capacity/), when the download is available, then import it:

```bash
python3 -m climaterisk.cli import-power /path/to/eskom-hourly.csv
python3 -m climaterisk.cli backtest
```

CSV needs a timestamp/datetime column and a demand column such as `demand_mw`, `demand`, `RSA Contracted Demand` or `Actual Demand`. Timestamps must be in the same local-hour convention as Open-Meteo's `Africa/Johannesburg` output. The power backtest uses the first 70% chronologically for training and the last 30% for testing. It compares a one-variable temperature regression with an hour-of-day mean baseline.

**Interpretation:** Eskom demand is national RSA demand, not City of Cape Town load. A temperature association does not establish causation. The Eskom portal currently documents the hourly series and download, but its linked CSV has previously returned 404; if unavailable, the power test reports that it needs imported rows rather than fabricating them.

## Water data

The [Cape Town dam-level archive](https://capetowndata.com/en/data/dam-levels/) republishes City of Cape Town storage readings and provides an Excel archive. Export its relevant sheet as CSV, then import:

```bash
python3 -m climaterisk.cli import-water /path/to/cape-town-dam-levels.csv
python3 -m climaterisk.cli report
```

Required columns: `date`, `dam`, and either `percentage_full` or `stored_mcm`. Include the combined/system-total row if available. Do not sum dam percentages. The report calculates change between successive combined-system readings.

Storage change is a **net balance** (inflow minus withdrawals and evaporation); it is not a direct measure of rainfall, runoff, inflow or consumption. The first MVP does not claim a water forecast because reliable catchment rainfall/inflow series have not yet been ingested.

## Polymarket comparison

The report reads FACT rows from WeatherEdge's existing `market_price_multi` table, if present. It compares a naive 7-day Tmax estimate and empirical walk-forward residual probabilities with stored YES prices for the next date.

This is a research-only disagreement indicator, **not an executable trading backtest**. It does not yet account for bid/ask spread, depth, fees, complete contract universes, settlement rule validation, or a verified pre-entry order-book snapshot. A market probability is only comparable when the snapshot timestamp precedes the forecast target and all outcome buckets are represented. Inspect source rows before interpreting any apparent edge.

## Sources and provenance

- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) — ERA5 reanalysis, hourly/daily variables and model caveats.
- [Eskom System Hourly Demand & Available Capacity](https://www.eskom.co.za/dataportal/demand-side/system-hourly-demand-and-available-capacity/) — national hourly demand/capacity.
- [City of Cape Town dam levels](https://www.capetown.gov.za/family-and-home/residential-utility-services/residential-water-and-sanitation-services/this-weeks-dam-levels/) — official weekly storage reports.
- [CapeTownData dam-level archive](https://capetowndata.com/en/data/dam-levels/) — downloadable archive compiled from City readings; retain attribution.
- [Polymarket research data documentation](https://institute.polymarket.com/data) — CLOB price history and token identifiers.
- FACT market snapshots and station observations — local WeatherEdge SQLite database.

Each weather fetch and CSV import is logged in `source_log`. Re-run imports safely; primary keys replace duplicate date/hour records.

## MVP boundaries / next validation gates

1. Confirm weather reanalysis daily maxima against routine FACT METAR and the actual market settlement rule (do not mix SPECI if excluded).
2. Obtain a stable Eskom historical CSV and test national demand against temperature; later source City municipal load if available.
3. Obtain dam-specific catchment rainfall and inflow (not FACT rainfall), then test lagged rainfall against storage changes chronologically.
4. Only run a market backtest after reconstructing complete bucket universes, timestamped pre-entry prices, settlement outcomes, fees and executable liquidity.
