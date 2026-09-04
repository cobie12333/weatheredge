-- WeatherEdge Research Platform — Schema v2.0
-- Canonical schema. Migrations remain available for legacy databases.
-- Raw observations and market snapshots are append-only facts.

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

CREATE TABLE IF NOT EXISTS metar_parsed (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    obs_time          TEXT NOT NULL,
    dewpoint_c        REAL,
    wind_dir          INTEGER,
    wind_speed_kt     REAL,
    wind_gust_kt      REAL,
    visibility_m      REAL,
    pressure_hpa      REAL,
    sky_condition     TEXT,
    weather_phenomena TEXT,
    dT_dt             REAL,
    d2T_dt2           REAL,
    UNIQUE(obs_time)
);

CREATE TABLE IF NOT EXISTS pws_obs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at    TEXT NOT NULL,
    station_id    TEXT NOT NULL,
    latitude      REAL,
    longitude     REAL,
    distance_km   REAL,
    obs_time      TEXT,
    temp_c        REAL,
    humidity      REAL,
    dewpoint_c    REAL,
    wind_dir      REAL,
    wind_speed    REAL,
    pressure_hpa  REAL,
    source        TEXT DEFAULT 'weather_company',
    is_valid      INTEGER NOT NULL DEFAULT 1,
    freshness_min REAL,
    issues        TEXT,
    raw_payload   TEXT NOT NULL,
    UNIQUE(station_id, obs_time)
);

CREATE TABLE IF NOT EXISTS saws_obs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at    TEXT NOT NULL,
    obs_time      TEXT,
    temp_c        REAL,
    humidity      REAL,
    dewpoint_c    REAL,
    pressure_hpa  REAL,
    wind_dir      REAL,
    wind_speed    REAL,
    precipitation REAL,
    cloud_cover   REAL,
    raw_payload   TEXT NOT NULL,
    UNIQUE(obs_time)
);

CREATE TABLE IF NOT EXISTS saws_forecast (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at            TEXT NOT NULL,
    issue_time            TEXT,
    target_date           TEXT NOT NULL,
    max_temp              REAL,
    min_temp              REAL,
    precipitation_prob    REAL,
    raw_payload           TEXT NOT NULL,
    UNIQUE(issue_time, target_date)
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
