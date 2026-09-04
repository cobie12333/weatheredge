-- WeatherEdge Research Platform — Schema v2.0
-- Extended schema for full pipeline support
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
    receipt_time  TEXT,                   -- UTC ISO8601 — AWC's own receiptTime field
    temp_c        REAL,                   -- parsed dry-bulb temp, nullable if parse fails
    raw_metar     TEXT NOT NULL,          -- full raw METAR string, unparsed, source of truth
    report_type   TEXT DEFAULT 'METAR',   -- 'METAR' or 'SPECI'
    source        TEXT DEFAULT 'live',    -- 'live' or 'backfill'
    UNIQUE(obs_time)
);

-- Parsed METAR data with additional fields and derivatives
CREATE TABLE IF NOT EXISTS metar_parsed (
    obs_time        TEXT PRIMARY KEY,     -- UTC ISO8601
    dewpoint_c      REAL,
    wind_dir        INTEGER,
    wind_speed_kt   REAL,
    wind_gust_kt    REAL,
    visibility_m    REAL,
    pressure_hpa    REAL,
    sky_condition   TEXT,                 -- JSON array
    weather_phenomena TEXT,               -- JSON array
    dT_dt           REAL,                 -- temperature change rate (°C/hour)
    d2T_dt2         REAL,                 -- temperature acceleration (°C/hour²)
    FOREIGN KEY (obs_time) REFERENCES metar_obs(obs_time)
);

-- SAWS observations
CREATE TABLE IF NOT EXISTS saws_obs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at      TEXT NOT NULL,        -- UTC ISO8601
    obs_time        TEXT,                 -- UTC ISO8601
    temp_c          REAL,
    humidity        REAL,
    dewpoint_c      REAL,
    pressure_hpa    REAL,
    wind_dir        INTEGER,
    wind_speed      REAL,
    precipitation   REAL,
    cloud_cover     INTEGER,
    raw_payload     TEXT NOT NULL,
    UNIQUE(obs_time)
);

-- SAWS forecasts
CREATE TABLE IF NOT EXISTS saws_forecast (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at          TEXT NOT NULL,    -- UTC ISO8601
    issue_time          TEXT,             -- UTC ISO8601
    target_date         TEXT,             -- YYYY-MM-DD
    max_temp            REAL,
    min_temp            REAL,
    precipitation_prob  REAL,
    raw_payload         TEXT NOT NULL,
    UNIQUE(issue_time, target_date)
);

-- PWS observations
CREATE TABLE IF NOT EXISTS pws_obs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at      TEXT NOT NULL,        -- UTC ISO8601
    station_id      TEXT NOT NULL,
    latitude        REAL,
    longitude       REAL,
    distance_km     REAL,                 -- distance from FACT
    obs_time        TEXT,                 -- UTC ISO8601
    temp_c          REAL,
    humidity        REAL,
    dewpoint_c      REAL,
    wind_dir        INTEGER,
    wind_speed      REAL,
    pressure_hpa    REAL,
    source          TEXT,                 -- 'weather_company', 'windy', etc.
    is_valid        INTEGER DEFAULT 1,    -- quality control flag
    freshness_min   REAL,                 -- age of data at fetch time
    issues          TEXT,                 -- JSON array of QC issues
    raw_payload     TEXT NOT NULL,
    UNIQUE(station_id, obs_time)
);

-- Windy station data
CREATE TABLE IF NOT EXISTS windy_obs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at      TEXT NOT NULL,        -- UTC ISO8601
    station_id      TEXT NOT NULL,
    latitude        REAL,
    longitude       REAL,
    obs_time        TEXT,                 -- UTC ISO8601
    temp_c          REAL,
    wind_dir        INTEGER,
    wind_speed      REAL,
    pressure_hpa    REAL,
    raw_payload     TEXT NOT NULL,
    UNIQUE(station_id, obs_time)
);

-- Raw Polymarket price snapshots for the top 2-3 buckets by volume.
-- One row per (poll, bucket). Full order-book top-of-book, not just mid.
CREATE TABLE IF NOT EXISTS market_price (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at        TEXT NOT NULL,      -- UTC ISO8601 — when THIS poll ran
    market_date       TEXT NOT NULL,      -- YYYY-MM-DD — which day's market this is
    bucket_label      TEXT NOT NULL,      -- e.g. "16C", "17C", "19C or higher"
    yes_price_cents   REAL,               -- Buy Yes ask price in cents
    no_price_cents    REAL,               -- Buy No ask price in cents
    volume_usd        REAL,               -- reported bucket volume at poll time
    raw_payload       TEXT NOT NULL,      -- full raw JSON from source, unparsed
    source            TEXT DEFAULT 'live' -- 'live' or 'backfill'
);

-- Polymarket CLOB order book snapshots
CREATE TABLE IF NOT EXISTS market_orderbook (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at        TEXT NOT NULL,      -- UTC ISO8601
    market_id         TEXT NOT NULL,      -- Polymarket market ID
    market_date       TEXT NOT NULL,      -- YYYY-MM-DD
    bucket_label      TEXT NOT NULL,
    yes_bid           REAL,               -- executable YES bid
    yes_ask           REAL,               -- executable YES ask
    no_bid            REAL,               -- executable NO bid
    no_ask            REAL,               -- executable NO ask
    spread            REAL,               -- ask - bid
    liquidity_yes     REAL,               -- YES side depth
    liquidity_no      REAL,               -- NO side depth
    raw_payload       TEXT NOT NULL,
    UNIQUE(market_id, fetched_at, bucket_label)
);

-- Verified actual outcome, entered once per resolved market day.
-- source_url is mandatory — no outcome without a citation.
CREATE TABLE IF NOT EXISTS outcome (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at       TEXT NOT NULL,        -- UTC ISO8601 — when this row was written
    market_date     TEXT NOT NULL,        -- YYYY-MM-DD
    actual_max_c    REAL NOT NULL,
    source_url      TEXT NOT NULL,
    resolution_source TEXT,               -- e.g. 'wunderground', 'noaa'
    UNIQUE(market_date)
);

-- Collection health log. Every attempt, success or failure, is recorded.
CREATE TABLE IF NOT EXISTS collection_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    attempted_at  TEXT NOT NULL,          -- UTC ISO8601
    collector     TEXT NOT NULL,          -- 'metar' | 'market' | 'saws' | 'pws' | 'windy'
    success       INTEGER NOT NULL,       -- 1 or 0
    rows_written  INTEGER DEFAULT 0,
    error_msg     TEXT
);

-- Model predictions (walk-forward, no leakage)
CREATE TABLE IF NOT EXISTS model_prediction (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_time     TEXT NOT NULL,    -- UTC ISO8601 — when prediction was made
    market_date         TEXT NOT NULL,    -- YYYY-MM-DD
    bucket_label        TEXT NOT NULL,
    model_probability   REAL NOT NULL,    -- raw model P(Tmax in bucket)
    calibrated_probability REAL,          -- after isotonic calibration
    model_version       TEXT,             -- version identifier
    features_used       TEXT,             -- JSON of feature snapshot
    raw_payload         TEXT NOT NULL,
    UNIQUE(prediction_time, market_date, bucket_label)
);

-- Paper trades
CREATE TABLE IF NOT EXISTS paper_trade (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_time          TEXT NOT NULL,    -- UTC ISO8601
    market_date         TEXT NOT NULL,    -- YYYY-MM-DD
    bucket_label        TEXT NOT NULL,
    side                TEXT NOT NULL,    -- 'YES' or 'NO'
    shares              INTEGER NOT NULL,
    entry_price_cents   REAL NOT NULL,
    entry_reason        TEXT,             -- why this trade was taken
    exit_price_cents    REAL,             -- null if still open
    exit_time           TEXT,             -- null if still open
    pnl_cents           REAL,             -- realized PnL
    status              TEXT DEFAULT 'open', -- 'open', 'closed', 'settled'
    settlement_value    INTEGER,          -- 100 if won, 0 if lost
    fees_cents          REAL DEFAULT 0,
    notes               TEXT
);

-- Backtest results
CREATE TABLE IF NOT EXISTS backtest_result (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    backtest_time       TEXT NOT NULL,    -- UTC ISO8601
    start_date          TEXT NOT NULL,
    end_date            TEXT NOT NULL,
    starting_capital    REAL NOT NULL,
    ending_capital      REAL NOT NULL,
    total_pnl           REAL NOT NULL,
    roi                 REAL NOT NULL,
    num_trades          INTEGER NOT NULL,
    win_rate            REAL,
    profit_factor       REAL,
    max_drawdown        REAL,
    sharpe_ratio        REAL,
    brier_score         REAL,
    log_loss            REAL,
    config_snapshot     TEXT NOT NULL,    -- JSON of parameters used
    trade_log           TEXT              -- JSON array of trades
);

-- Data quality / source health tracking
CREATE TABLE IF NOT EXISTS source_health (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at         TEXT NOT NULL,    -- UTC ISO8601
    source_name         TEXT NOT NULL,    -- 'saws', 'metar', 'pws', 'polymarket', 'windy'
    status              TEXT NOT NULL,    -- 'HEALTHY', 'STALE', 'DOWN'
    last_success        TEXT,             -- UTC ISO8601
    last_observation    TEXT,             -- UTC ISO8601
    error_count_1h      INTEGER DEFAULT 0,
    error_count_24h     INTEGER DEFAULT 0,
    notes               TEXT,
    UNIQUE(source_name, recorded_at)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_metar_obs_time ON metar_obs(obs_time);
CREATE INDEX IF NOT EXISTS idx_market_date ON market_price(market_date);
CREATE INDEX IF NOT EXISTS idx_market_fetched ON market_price(fetched_at);
CREATE INDEX IF NOT EXISTS idx_outcome_date ON outcome(market_date);
CREATE INDEX IF NOT EXISTS idx_collection_attempted ON collection_log(attempted_at);
CREATE INDEX IF NOT EXISTS idx_pws_distance ON pws_obs(distance_km);
CREATE INDEX IF NOT EXISTS idx_saws_forecast_target ON saws_forecast(target_date);
CREATE INDEX IF NOT EXISTS idx_model_prediction_market ON model_prediction(market_date);
CREATE INDEX IF NOT EXISTS idx_paper_trade_market ON paper_trade(market_date);
CREATE INDEX IF NOT EXISTS idx_paper_trade_status ON paper_trade(status);
