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


class Child:
    """A supervised child process that is restarted if it exits.

    Restarts back off (5 s, 15 s, 60 s, then 60 s) and stop after `max_restarts`
    within `window` seconds, so a child that fails instantly cannot spin forever.
    """

    BACKOFF = (5, 15, 60)

    def __init__(self, label, module, spawn=None, max_restarts=10, window=3600):
        self.label = label
        self.module = module
        self.spawn = spawn or (lambda m: subprocess.Popen([sys.executable, "-m", m]))
        self.max_restarts = max_restarts
        self.window = window
        self.restarts = []  # monotonic timestamps
        self.proc = self.spawn(module)
        self.next_start = None
        self.gave_up = False

    def poll(self, now):
        """Call regularly. Returns a status string for logging, or None."""
        if self.gave_up:
            return None
        if self.next_start is not None:
            if now >= self.next_start:
                self.next_start = None
                self.proc = self.spawn(self.module)
                self.restarts.append(now)
                return f"{self.label} restarted"
            return None
        code = self.proc.poll()
        if code is None:
            return None
        self.restarts = [t for t in self.restarts if now - t < self.window]
        if len(self.restarts) >= self.max_restarts:
            self.gave_up = True
            return f"{self.label} exited with code {code}; giving up after {self.max_restarts} restarts in {self.window}s"
        delay = self.BACKOFF[min(len(self.restarts), len(self.BACKOFF) - 1)]
        self.next_start = now + delay
        return f"{self.label} exited with code {code}; restarting in {delay}s"

    def stop_target(self):
        return self.proc


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

    children = []
    try:
        children.append(Child("live collectors", "weatheredge.live_runner"))
        children.append(Child("dashboard", "weatheredge.dashboard"))
        print("Live collectors and dashboard started (auto-restart on exit).")
        print("Dashboard: http://127.0.0.1:8420")
        print("Paper/research collection only; no orders are placed. Press Ctrl+C to stop.")

        while not all(c.gave_up for c in children):
            for c in children:
                msg = c.poll(time.monotonic())
                if msg:
                    print(f"WeatherEdge: {msg}")
            time.sleep(1)
        print("All children gave up restarting; check the logs/ folder.")
        return 1
    except KeyboardInterrupt:
        print("\nStopping WeatherEdge...")
        return 0
    finally:
        _stop_processes([c.stop_target() for c in children])


if __name__ == "__main__":
    raise SystemExit(main())
