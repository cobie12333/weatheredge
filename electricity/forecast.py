#!/usr/bin/env python3
"""Walk-forward baselines for a normalized hourly electricity time series."""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path


def load_series(path: Path, timestamp_col: str, value_col: str) -> list[tuple[datetime, float]]:
    rows: list[tuple[datetime, float]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or timestamp_col not in reader.fieldnames or value_col not in reader.fieldnames:
            raise ValueError(
                f"CSV needs columns {timestamp_col!r} and {value_col!r}; "
                f"found {reader.fieldnames!r}"
            )
        for line_no, row in enumerate(reader, start=2):
            try:
                stamp = datetime.fromisoformat(row[timestamp_col].strip().replace("Z", "+00:00"))
                value = float(row[value_col])
                if not math.isfinite(value):
                    raise ValueError("value is not finite")
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"invalid timestamp/value on CSV line {line_no}: {exc}") from exc
            rows.append((stamp, value))
    if len(rows) < 3:
        raise ValueError("need at least 3 valid rows")
    if any(rows[i][0] <= rows[i - 1][0] for i in range(1, len(rows))):
        raise ValueError("timestamps must be strictly increasing; sort and deduplicate first")
    return rows


def mae(actual: list[float], predicted: list[float]) -> float:
    return sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)


def rmse(actual: list[float], predicted: list[float]) -> float:
    return math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual))


def evaluate(values: list[float], season: int = 24, test_size: int = 168) -> dict[str, object]:
    if season < 1:
        raise ValueError("season must be >= 1")
    if test_size < 1:
        raise ValueError("test_size must be >= 1")
    if len(values) <= season:
        raise ValueError(f"need more than {season} observations")
    start = max(season, len(values) - test_size)
    actual: list[float] = []
    seasonal: list[float] = []
    trailing: list[float] = []
    for i in range(start, len(values)):
        actual.append(values[i])
        seasonal.append(values[i - season])
        trailing.append(sum(values[i - season:i]) / season)
    return {
        "n_total": len(values),
        "n_test": len(actual),
        "season": season,
        "test_start_index": start,
        "seasonal_naive": {"mae": mae(actual, seasonal), "rmse": rmse(actual, seasonal)},
        "trailing_mean": {"mae": mae(actual, trailing), "rmse": rmse(actual, trailing)},
        "interpretation": (
            "One-step walk-forward baseline only. Historical observations are used after they occur. "
            "This does not test electricity-price profitability."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--timestamp", default="timestamp")
    parser.add_argument("--value", default="value")
    parser.add_argument("--season", type=int, default=24, help="season length; 24 for hourly daily seasonality")
    parser.add_argument("--test-size", type=int, default=168, help="last N observations used for evaluation")
    args = parser.parse_args()
    try:
        rows = load_series(args.csv, args.timestamp, args.value)
        result = evaluate([value for _, value in rows], args.season, args.test_size)
        result["first_timestamp"] = rows[0][0].isoformat()
        result["last_timestamp"] = rows[-1][0].isoformat()
        print(json.dumps(result, indent=2))
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
