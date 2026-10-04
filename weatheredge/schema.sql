-- WeatherEdge Research Platform — Schema v4.0
-- Legacy FACT tables are retained. Multi-airport tables are canonical for new data.
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

CREATE TABLE IF NOT EXISTS metar_parsed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    obs_time TEXT NOT NULL,
    dewpoint_c REAL,
    wind_dir INTEGER,
    wind_speed_kt REAL,
    wind_gust_kt REAL,
    visibility_m REAL,
    pressure_hpa REAL,
    sky_condition TEXT,
    weather_phenomena TEXT,
    dT_dt REAL,
    d2T_dt2 REAL,
    UNIQUE(obs_time)
);

CREATE TABLE IF NOT EXISTS pws_obs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,
    station_id TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    distance_km REAL,
    obs_time TEXT,
    temp_c REAL,
    humidity REAL,
    dewpoint_c REAL,
    wind_dir REAL,
    wind_speed REAL,
    pressure_hpa REAL,
    source TEXT DEFAULT 'weather_company',
    is_valid INTEGER NOT NULL DEFAULT 1,
    freshness_min REAL,
    issues TEXT,
    raw_payload TEXT NOT NULL,
    UNIQUE(station_id, obs_time)
);

CREATE TABLE IF NOT EXISTS saws_obs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,
    obs_time TEXT,
    temp_c REAL,
    humidity REAL,
    dewpoint_c REAL,
    pressure_hpa REAL,
    wind_dir REAL,
    wind_speed REAL,
    precipitation REAL,
    cloud_cover REAL,
    raw_payload TEXT NOT NULL,
    UNIQUE(obs_time)
);

CREATE TABLE IF NOT EXISTS saws_forecast (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,
    issue_time TEXT,
    target_date TEXT NOT NULL,
    max_temp REAL,
    min_temp REAL,
    precipitation_prob REAL,
    raw_payload TEXT NOT NULL,
    UNIQUE(issue_time, target_date)
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
CREATE INDEX IF NOT EXISTS idx_metar_multi_station_time ON metar_multi(station_id, obs_time DESC);

CREATE TABLE IF NOT EXISTS pws_station (
    station_id TEXT PRIMARY KEY,
    airport_icao TEXT NOT NULL,
    name TEXT,
    source TEXT NOT NULL,
    source_url TEXT,
    latitude REAL,
    longitude REAL,
    elevation_m REAL,
    distance_km REAL,
    status TEXT DEFAULT 'unknown',
    verified INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_pws_station_airport ON pws_station(airport_icao);

CREATE TABLE IF NOT EXISTS pws_obs_multi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    airport_icao TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    obs_time TEXT,
    latitude REAL,
    longitude REAL,
    distance_km REAL,
    temp_c REAL,
    humidity REAL,
    dewpoint_c REAL,
    wind_dir_deg REAL,
    wind_speed_kt REAL,
    pressure_hpa REAL,
    source TEXT NOT NULL,
    is_valid INTEGER NOT NULL DEFAULT 1,
    freshness_min REAL,
    issues TEXT,
    raw_payload TEXT NOT NULL,
    UNIQUE(station_id, obs_time, source)
);
CREATE INDEX IF NOT EXISTS idx_pws_obs_airport_time ON pws_obs_multi(airport_icao, obs_time DESC);

CREATE TABLE IF NOT EXISTS market_price_multi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    market_date TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    bucket_label TEXT NOT NULL,
    yes_price_cents REAL,
    no_price_cents REAL,
    volume_usd REAL,
    market_slug TEXT,
    source TEXT DEFAULT 'live',
    raw_payload TEXT NOT NULL,
    UNIQUE(station_id, fetched_at, market_date, bucket_label, source)
);
CREATE INDEX IF NOT EXISTS idx_market_multi_station_date ON market_price_multi(station_id, market_date, fetched_at DESC);

CREATE TABLE IF NOT EXISTS outcome_multi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    logged_at TEXT NOT NULL,
    market_date TEXT NOT NULL,
    actual_max_c REAL NOT NULL,
    source_url TEXT NOT NULL,
    UNIQUE(station_id, market_date)
);

CREATE TABLE IF NOT EXISTS forecast_history_multi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    valid_time TEXT NOT NULL,
    lead_hours INTEGER,
    model TEXT NOT NULL,
    temp_c REAL,
    source TEXT DEFAULT 'live',
    raw_payload TEXT,
    UNIQUE(station_id, valid_time, lead_hours, model, source)
);

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
