-- WeatherEdge Research Platform — Schema v3.0
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS metar_obs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,
    obs_time TEXT,
    receipt_time TEXT,
    temp_c REAL,
    raw_metar TEXT NOT NULL,
    report_type TEXT DEFAULT 'METAR',
    source TEXT DEFAULT 'live',
    UNIQUE(obs_time)
);

CREATE TABLE IF NOT EXISTS metar_multi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    obs_time TEXT NOT NULL,
    receipt_time TEXT,
    temp_c REAL,
    dewpoint_c REAL,
    wind_dir_deg REAL,
    wind_speed_kt REAL,
    visibility_sm REAL,
    raw_metar TEXT NOT NULL,
    report_type TEXT DEFAULT 'METAR',
    source TEXT DEFAULT 'aviationweather.gov',
    UNIQUE(station_id, obs_time, source)
);

CREATE INDEX IF NOT EXISTS idx_metar_multi_station_time
    ON metar_multi(station_id, obs_time DESC);

CREATE TABLE IF NOT EXISTS market_price (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,
    market_date TEXT NOT NULL,
    bucket_label TEXT NOT NULL,
    yes_price_cents REAL,
    no_price_cents REAL,
    volume_usd REAL,
    raw_payload TEXT NOT NULL,
    source TEXT DEFAULT 'live',
    UNIQUE(fetched_at, market_date, bucket_label, source)
);

CREATE TABLE IF NOT EXISTS outcome (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL,
    market_date TEXT NOT NULL,
    actual_max_c REAL NOT NULL,
    source_url TEXT NOT NULL,
    UNIQUE(market_date)
);

CREATE TABLE IF NOT EXISTS collection_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempted_at TEXT NOT NULL,
    collector TEXT NOT NULL,
    success INTEGER NOT NULL,
    rows_written INTEGER DEFAULT 0,
    error_msg TEXT
);

CREATE TABLE IF NOT EXISTS forecast_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,
    valid_time TEXT NOT NULL,
    lead_hours INTEGER,
    model TEXT NOT NULL,
    temp_c REAL,
    source TEXT DEFAULT 'live',
    raw_payload TEXT,
    UNIQUE(valid_time, lead_hours, model, source)
);
