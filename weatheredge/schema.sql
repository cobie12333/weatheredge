-- WeatherEdge Research Platform — Schema v2.2
-- Raw observations and market snapshots are INSERT-only.
-- fetched_at is the local receive time. source_updated_at is optional
-- and must only be populated when the upstream payload provides it.

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS metar_obs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at        TEXT NOT NULL,
    obs_time          TEXT,
    receipt_time      TEXT,
    temp_c            REAL,
    raw_metar         TEXT NOT NULL,
    report_type       TEXT DEFAULT 'METAR',
    source            TEXT DEFAULT 'live',
    UNIQUE(obs_time)
);

CREATE TABLE IF NOT EXISTS market_price (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at          TEXT NOT NULL,
    source_updated_at   TEXT,
    market_date         TEXT NOT NULL,
    bucket_label        TEXT NOT NULL,
    yes_price_cents     REAL,
    no_price_cents      REAL,
    volume_usd          REAL,
    raw_payload         TEXT NOT NULL,
    source              TEXT DEFAULT 'live',
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

-- Source provenance. Coordinates and access notes are explicit so a sensor
-- cannot silently become "airport data" merely because it is nearby.
CREATE TABLE IF NOT EXISTS source_registry (
    source_id           TEXT PRIMARY KEY,
    provider             TEXT NOT NULL,
    station_id           TEXT,
    name                 TEXT NOT NULL,
    latitude             REAL,
    longitude            REAL,
    distance_km          REAL,
    observation_endpoint TEXT,
    historical_endpoint  TEXT,
    granularity_claim    TEXT,
    access_status        TEXT NOT NULL,
    commercial_use_status TEXT NOT NULL,
    verification_notes   TEXT,
    verified_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weather_observation (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id         TEXT NOT NULL,
    station_id        TEXT,
    observed_at       TEXT NOT NULL,
    fetched_at        TEXT,
    temp_c            REAL,
    dewpoint_c        REAL,
    humidity_pct      REAL,
    wind_dir_deg      REAL,
    wind_speed_ms     REAL,
    gust_ms            REAL,
    pressure_hpa      REAL,
    raw_payload       TEXT,
    quality_status    TEXT DEFAULT 'unverified',
    UNIQUE(source_id, station_id, observed_at)
);

-- Rules are stored per market because the settlement source changed over time.
CREATE TABLE IF NOT EXISTS market_rule (
    market_date             TEXT PRIMARY KEY,
    rule_version             TEXT NOT NULL,
    resolution_provider      TEXT NOT NULL,
    resolution_station       TEXT NOT NULL,
    primary_source_url       TEXT NOT NULL,
    fallback_source_url      TEXT,
    fallback_deadline_et     TEXT,
    resolution_precision_c   INTEGER NOT NULL DEFAULT 1,
    revision_cutoff_rule     TEXT NOT NULL,
    rule_text_hash           TEXT,
    verified_at              TEXT NOT NULL,
    verification_source_url  TEXT NOT NULL
);

-- Settlement evidence is separate from provisional meteorological truth.
CREATE TABLE IF NOT EXISTS settlement_observation (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    market_date           TEXT NOT NULL,
    source_url             TEXT NOT NULL,
    provider               TEXT NOT NULL,
    station                TEXT NOT NULL,
    observed_max_c         REAL,
    winning_bucket         TEXT,
    first_next_day_point_at TEXT,
    settlement_deadline_et TEXT,
    revision_cutoff_at     TEXT,
    captured_at            TEXT NOT NULL,
    status                  TEXT NOT NULL,
    raw_payload             TEXT,
    UNIQUE(market_date, source_url, captured_at)
);
