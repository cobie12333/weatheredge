#!/usr/bin/env python3
"""
WeatherEdge — Migration Runner
Version 1.0

SQLite's ALTER TABLE ADD COLUMN has no IF NOT EXISTS clause, so raw
migration SQL is NOT safely re-runnable the way CREATE TABLE IF NOT
EXISTS is. This runner checks column/table existence in Python before
attempting each change, making the migration genuinely idempotent —
correcting a false claim in migration_v2.sql's own header comment,
caught by testing rather than assumed correct.
"""

import sys
sys.path.insert(0, ".")
from db import get_connection


def column_exists(con, table: str, column: str) -> bool:
    cols = con.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c["name"] == column for c in cols)


def table_exists(con, table: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def run_migration():
    con = get_connection()
    try:
        # Step 1: metar_obs.source
        if not column_exists(con, "metar_obs", "source"):
            con.execute("ALTER TABLE metar_obs ADD COLUMN source TEXT DEFAULT 'live'")
            print("Added metar_obs.source")
        else:
            print("metar_obs.source already exists, skipped")

        # Step 2: market_price rebuild with source + UNIQUE constraint.
        # Only rebuild if 'source' is genuinely missing — check first,
        # since DROP/RENAME is destructive if run against an already-
        # migrated table (it would wipe the UNIQUE-constrained data by
        # re-running INSERT OR IGNORE from a table that no longer has the
        # old shape, or simply be wasted work).
        if not column_exists(con, "market_price", "source"):
            con.executescript("""
                CREATE TABLE market_price_new (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetched_at        TEXT NOT NULL,
                    market_date       TEXT NOT NULL,
                    bucket_label      TEXT NOT NULL,
                    yes_price_cents   REAL,
                    no_price_cents    REAL,
                    volume_usd        REAL,
                    raw_payload       TEXT NOT NULL,
                    source            TEXT DEFAULT 'live',
                    UNIQUE(fetched_at, market_date, bucket_label, source)
                );

                INSERT OR IGNORE INTO market_price_new
                    (id, fetched_at, market_date, bucket_label, yes_price_cents,
                     no_price_cents, volume_usd, raw_payload)
                    SELECT id, fetched_at, market_date, bucket_label, yes_price_cents,
                           no_price_cents, volume_usd, raw_payload
                    FROM market_price;

                DROP TABLE market_price;
                ALTER TABLE market_price_new RENAME TO market_price;
            """)
            print("Rebuilt market_price with source column and UNIQUE constraint")
        else:
            print("market_price.source already exists, skipped rebuild")

        # Step 3: forecast_history table
        if not table_exists(con, "forecast_history"):
            con.execute("""
                CREATE TABLE forecast_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetched_at  TEXT NOT NULL,
                    valid_time  TEXT NOT NULL,
                    lead_hours  INTEGER,
                    model       TEXT NOT NULL,
                    temp_c      REAL,
                    source      TEXT DEFAULT 'live',
                    raw_payload TEXT,
                    UNIQUE(valid_time, lead_hours, model, source)
                )
            """)
            print("Created forecast_history table")
        else:
            print("forecast_history already exists, skipped")

        con.commit()
        print("Migration complete.")
    finally:
        con.close()


if __name__ == "__main__":
    run_migration()
