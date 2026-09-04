"""Command-line entry point for WeatherEdge."""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m weatheredge",
        description="WeatherEdge FACT weather research platform",
    )
    parser.add_argument("--version", action="store_true", help="show the installed version")
    args = parser.parse_args()

    if args.version:
        from . import __version__
        print(__version__)
        return 0

    print("WeatherEdge 2.0.0")
    print("Package is installed correctly.")
    print("Use the project collectors/scripts for data collection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
