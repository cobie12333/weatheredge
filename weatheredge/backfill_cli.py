#!/usr/bin/env python3
"""
WeatherEdge — Backfill CLI
Version 1.0

Single entrypoint for all historical backfill sources. Run migrate.py
once before first use.

Usage:
    python3 backfill_cli.py metar 2026-06-01 2026-07-01
    python3 backfill_cli.py forecast 2026-06-01 2026-07-01
    python3 backfill_cli.py market 2026-06-01 2026-07-01
    python3 backfill_cli.py all 2026-06-01 2026-07-01
"""

import argparse
import json
import sys
from datetime import date

sys.path.insert(0, ".")
from backfill_iem_metar import backfill as backfill_metar
from backfill_openmeteo import backfill as backfill_forecast
from backfill_polymarket import backfill_range as backfill_market


def main():
    parser = argparse.ArgumentParser(description="WeatherEdge historical backfill")
    parser.add_argument("source", choices=["metar", "forecast", "market", "all"])
    parser.add_argument("start", help="YYYY-MM-DD")
    parser.add_argument("end", help="YYYY-MM-DD")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    if start > end:
        print("Error: start date must be before end date")
        sys.exit(1)

    results = {}

    if args.source in ("metar", "all"):
        print(f"\n--- Backfilling METAR/SPECI ({start} to {end}) ---")
        results["metar"] = backfill_metar(start, end)
        print(json.dumps(results["metar"], indent=2))

    if args.source in ("forecast", "all"):
        print(f"\n--- Backfilling forecasts ({start} to {end}) ---")
        results["forecast"] = backfill_forecast(start, end)
        print(json.dumps(results["forecast"], indent=2))

    if args.source in ("market", "all"):
        print(f"\n--- Backfilling market prices ({start} to {end}) ---")
        results["market"] = backfill_market(start, end)
        print(json.dumps(results["market"], indent=2))

    print("\n=== Backfill run complete ===")


if __name__ == "__main__":
    main()
