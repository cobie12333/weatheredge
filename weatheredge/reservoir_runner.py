#!/usr/bin/env python3
"""Run the experimental ESN Tmax layer for configured airports."""

import json
import sys

from .airports import AIRPORTS
from .reservoir_tmax import persist, train_and_score


def main():
    icao = sys.argv[1] if len(sys.argv) > 1 else None
    airports = [a for a in AIRPORTS if not icao or a["icao"] == icao]
    if not airports:
        raise SystemExit(f"unknown airport: {icao}")
    for airport in airports:
        result = train_and_score(airport["icao"])
        persist(result)
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
