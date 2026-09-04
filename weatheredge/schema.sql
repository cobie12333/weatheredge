-- WeatherEdge Research Platform — Schema v1.0
-- FROZEN. Do not add tables without a critical-bug justification.
--
-- Design law: INSERT only. No UPDATE. No REPLACE. No derived columns.
-- Every row is a raw, timestamped fact. All analysis happens outside this schema.

PRAGMA journal_mode = WAL;

-- Raw METAR observations for Cape Town International (FACT).
-- One row per successful poll. Duplicates on obs_time are ignored, not overwritten.
CREATE TABLE IF NOT EXISTS metar_obs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at    TEXT NOT NULL,          -- UTC ISO8601 — when THIS poll ran and wrote the row
    obs_time      TEXT,                   -- UTC ISO8601 — actual METAR observation time (from station)
    receipt_time  TEXT,                   -- UTC ISO8601 — AWC's own receiptTime field: when AWC
                                           -- ingested the report internally. This is the one
                                           -- schema addition justified by Phase 1's mission:
                                           -- characterizing Observation -> Receipt -> Collector-detection.
    temp_c        REAL,                   -- parsed dry-bulb temp, nullable if parse fails
    raw_metar     TEXT NOT NULL,          -- full raw METAR string, unparsed, source of truth
    report_type   TEXT DEFAULT 'METAR',   -- 'METAR' or 'SPECI'
    UNIQUE(obs_time)
);

-- Raw Polymarket price snapshots for the top 2-3 buckets by volume.
-- One row per (poll, bucket). Full order-book top-of-book, not just mid.
CREATE TABLE IF NOT EXISTS market_price (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at        TEXT NOT NULL,    -- UTC ISO8601 — when THIS poll ran
    market_date       TEXT NOT NULL,    -- YYYY-MM-DD — which day's market this is
    bucket_label      TEXT NOT NULL,    -- e.g. "16C", "17C", "19C or higher"
    yes_price_cents   REAL,             -- Buy Yes ask price in cents
    no_price_cents    REAL,             -- Buy No ask price in cents
    volume_usd        REAL,             -- reported bucket volume at poll time
    raw_payload       TEXT NOT NULL     -- full raw JSON from source, unparsed
);

-- Verified actual outcome, entered once per resolved market day.
-- source_url is mandatory — no outcome without a citation.
CREATE TABLE IF NOT EXISTS outcome (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at       TEXT NOT NULL,      -- UTC ISO8601 — when this row was written
    market_date     TEXT NOT NULL,      -- YYYY-MM-DD
    actual_max_c    REAL NOT NULL,
    source_url      TEXT NOT NULL,
    UNIQUE(market_date)
);

-- Collection health log. Every attempt, success or failure, is recorded.
-- This is what prevents silent survivorship bias in the dataset.
CREATE TABLE IF NOT EXISTS collection_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    attempted_at  TEXT NOT NULL,        -- UTC ISO8601
    collector     TEXT NOT NULL,        -- 'metar' | 'market'
    success       INTEGER NOT NULL,     -- 1 or 0
    rows_written  INTEGER DEFAULT 0,
    error_msg     TEXT
);
