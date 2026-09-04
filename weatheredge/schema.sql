-- WeatherEdge Research Platform — Schema v2.0
-- Canonical schema. Migrations remain available for legacy databases.
-- Design law: raw observations and market snapshots are INSERT-only.

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS metar_obs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at    TEXT NOT NULL,
    obs_time      TEXT,
    receipt_time  TEXT,
    temp_c        REAL,
    raw_metar     TEXT NOT NULL,
    report_type   TEXT DEFAULT 'METAR',
    source        TEXT DEFAULT 'live',
    UNIQUE(obs_time)
);

CREATE TABLE IF NOT EXISTS market_price (
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

CREATE TABLE IF NOT EXISTS outcome (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at       TEXT NOT NULL,
    market_date     TEXT NOT NULL,
    actual_max_c    REAL NOT NULL,
    source_url      TEXT NOT NULL,
    UNIQUE(market_date)
);

CREATE TABLE IF NOT EXISTS collection_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    attempted_at  TEXT NOT NULL,
    collector     TEXT NOT NULL,
    success       INTEGER NOT NULL,
    rows_written  INTEGER DEFAULT 0,
    error_msg     TEXT
);

CREATE TABLE IF NOT EXISTS forecast_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at  TEXT NOT NULL,
    valid_time  TEXT NOT NULL,
    lead_hours  INTEGER,
    model       TEXT NOT NULL,
    temp_c      REAL,
    source      TEXT DEFAULT 'live',
    raw_payload TEXT,
    UNIQUE(valid_time, lead_hours, model, source)
);
