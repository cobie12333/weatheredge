# SAWEM / South African electricity research prototype

A lightweight, standard-library-only research module alongside WeatherEdge. It is for **data collection, quality checks, and forecasting experiments**, not live trading.

## What it does

- Discovers candidate download links on configured official Eskom data-portal pages.
- Downloads only links hosted on `eskom.co.za`, with a delay, size limit, and content checks.
- Saves raw files plus a JSON Lines manifest recording source URL, retrieval time, SHA-256, byte count, and content type.
- Inspects downloaded CSV files without assuming every source has the same schema.
- Provides a small walk-forward baseline evaluator for a **user-prepared, normalized time series**. It compares a 24-hour seasonal-naive forecast with a trailing-mean baseline; it does not claim to predict electricity prices.

## Data-source status

The initial source pages are official Eskom data-portal pages for demand, available capacity, and renewable generation. Download links may change or be temporarily broken. The collector discovers links from the page instead of hard-coding unverified CSV endpoints.

- System demand / available capacity: https://www.eskom.co.za/dataportal/demand-side/system-hourly-demand-and-available-capacity/
- Actual and forecast demand: https://www.eskom.co.za/dataportal/demand-side/system-hourly-actual-and-forecasted-demand/
- Hourly renewable generation: https://www.eskom.co.za/dataportal/renewables-performance/hourly-renewable-generation/
- Total hourly renewable generation: https://www.eskom.co.za/dataportal/renewables-performance/total-hourly-renewable-generation/
- SAWEM documents / API status: https://www.ntcsa.co.za/sawem-documents/

**Important:** A public data portal is not proof that a tradable SAWEM price feed is public. Do not infer prices, imbalance settlements, or participant access from generation/demand data. The NTCSA API endpoint must be obtained from an official published source or NTCSA directly. Respect each site's terms and request permission where automated extraction is restricted.

## Requirements

Python 3.10+; no third-party packages. Designed for low-memory machines.

## Use

Run from the repository root:

```bash
python electricity/collect.py --help
python electricity/collect.py discover
python electricity/collect.py download
python electricity/collect.py inspect
```

Use `--out data/electricity_raw` to select a raw-data directory. `discover` only reads the configured source pages and prints candidate links. `download` downloads candidates after discovery and records outcomes in `manifest.jsonl`. It does not log in, bypass access controls, or scrape the SAPP QA dashboard.

The collector deliberately records failures instead of treating a broken link as an empty dataset. Review downloaded files and their terms before using them.

## Forecast experiment

Prepare a CSV with columns `timestamp,value`, one regular observation per hour, timestamps parseable by Python's ISO parser, and numeric values. Example:

```csv
timestamp,value
2026-01-01T00:00:00,24000
2026-01-01T01:00:00,23800
```

Then run:

```bash
python electricity/forecast.py path/to/normalized_hourly.csv --value value --timestamp timestamp --season 24 --test-size 168
```

The script evaluates forecasts in chronological order. It reports MAE and RMSE against a seasonal-naive forecast and a trailing-mean baseline. This is a baseline sanity check, not evidence of a profitable strategy. Keep timezone and daylight-saving treatment consistent when normalizing South African data.

## Next milestones

1. Verify working official download links and archive a small sample.
2. Map source columns and units explicitly; never guess MW/MWh or timestamp semantics.
3. Build a normalized hourly dataset with source provenance and quality checks.
4. Test out-of-sample demand/renewables forecasts.
5. Obtain verified historical wholesale/balancing prices and applicable rules before testing any price-edge hypothesis.
