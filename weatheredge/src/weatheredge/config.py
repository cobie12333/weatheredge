"""Configuration settings for WeatherEdge."""

import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).parent.parent.parent
if not os.path.exists(os.path.join(BASE_DIR, "weatheredge.db")):
    # Fall back to old location if db exists there
    old_base = BASE_DIR.parent
    if os.path.exists(os.path.join(old_base, "weatheredge.db")):
        BASE_DIR = old_base

DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "weatheredge.db"))
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# Station configuration
METAR_STATION_ID = os.environ.get("METAR_STATION_ID", "FACT")
FACT_LAT = -33.9648
FACT_LON = 18.6017

# SAWS/AfriGIS API
SAWS_API_KEY = os.environ.get("SAWS_API_KEY", "")
SAWS_API_SECRET = os.environ.get("SAWS_API_SECRET", "")
SAWS_BASE_URL = os.environ.get("SAWS_BASE_URL", "https://api.aws.saaws.gov.za")

# Weather Company PWS API
WEATHER_COMPANY_API_KEY = os.environ.get("WEATHER_COMPANY_API_KEY", "")

# Windy API
WINDY_API_KEY = os.environ.get("WINDY_API_KEY", "")

# Polymarket
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
POLYMARKET_WALLET_PRIVATE_KEY = os.environ.get("POLYMARKET_WALLET_PRIVATE_KEY", "")

# Market tracking
TRACKED_BUCKET_COUNT = int(os.environ.get("TRACKED_BUCKET_COUNT", "5"))

# Polling intervals (minutes)
METAR_POLL_MINUTES = int(os.environ.get("METAR_POLL_MINUTES", "30"))
MARKET_POLL_MINUTES_DAYTIME = int(os.environ.get("MARKET_POLL_MINUTES_DAYTIME", "15"))
MARKET_POLL_MINUTES_NIGHT = int(os.environ.get("MARKET_POLL_MINUTES_NIGHT", "60"))

# Timezone handling
SAST_OFFSET_HOURS = 2
DAYTIME_START_SAST = 6
DAYTIME_END_SAST = 20

# HTTP settings
HTTP_TIMEOUT_SECONDS = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "20"))
USER_AGENT = "weatheredge-research/2.0 (personal research project)"

# Trading parameters
STARTING_CAPITAL = float(os.environ.get("STARTING_CAPITAL", "10000"))
MAX_POSITION_SIZE = int(os.environ.get("MAX_POSITION_SIZE", "500"))
MIN_EDGE_THRESHOLD = float(os.environ.get("MIN_EDGE_THRESHOLD", "0.05"))
MAX_SPREAD_THRESHOLD = float(os.environ.get("MAX_SPREAD_THRESHOLD", "0.10"))
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", "100"))

# Model parameters
CALIBRATION_MIN_SAMPLES = int(os.environ.get("CALIBRATION_MIN_SAMPLES", "30"))
FORECAST_ERROR_WINDOW_DAYS = int(os.environ.get("FORECAST_ERROR_WINDOW_DAYS", "60"))
