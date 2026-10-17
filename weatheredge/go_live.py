#!/usr/bin/env python3
"""Start WeatherEdge's live collectors and local dashboard together.

Run from the repository root with: python -m weatheredge.go_live
The process stays in the foreground until Ctrl+C. No trades are placed.
"""
import os
import subprocess
import sys
import time

from .db import get_connection
from .pws_discovery import seed_watchlist


def _stop_processes(processes):
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    # Initialize the database and seed candidates before starting either child.
    con = get_connection()
    try:
        seeded = seed_watchlist(con)
        con.commit()
    finally:
        con.close()
    print(f"WeatherEdge database ready; added {seeded} new PWS watchlist candidate(s).")

    if os.getenv("WEATHER_UNDERGROUND_API_KEY"):
        print("Checking FACT PWS candidates against the live Weather Company API...")
        subprocess.run(
            [sys.executable, "-m", "weatheredge.pws_live_activation", "--airport", "FACT"],
            check=False,
        )
    else:
        print(
            "WEATHER_UNDERGROUND_API_KEY is not set: PWS API collection stays disabled. "
            "Public METAR and market collectors will still start."
        )

    processes = []
    try:
        runner = subprocess.Popen([sys.executable, "-m", "weatheredge.live_runner"])
        processes.append(runner)
        dashboard = subprocess.Popen([sys.executable, "-m", "weatheredge.dashboard"])
        processes.append(dashboard)
        print("Live collectors and dashboard started.")
        print("Dashboard: http://127.0.0.1:8420")
        print("Paper/research collection only; no orders are placed. Press Ctrl+C to stop.")

        while all(process.poll() is None for process in processes):
            time.sleep(1)

        for name, process in zip(("live collectors", "dashboard"), processes):
            if process.poll() is not None:
                print(f"WeatherEdge {name} exited with code {process.returncode}.")
        return 1
    except KeyboardInterrupt:
        print("\nStopping WeatherEdge...")
        return 0
    finally:
        _stop_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())
