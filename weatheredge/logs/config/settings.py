import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "weatheredge.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")
LOG_DIR = os.path.join(BASE_DIR, "logs")

METAR_STATION_ID = "FACT"
METAR_URL = f"https://aviationweather.gov/api/data/metar?ids={METAR_STATION_ID}&format=json"

GAMMA_API_BASE = "https://gamma-api.polymarket.com"

TRACKED_BUCKET_COUNT = 3

METAR_POLL_MINUTES = 30
MARKET_POLL_MINUTES_DAYTIME = 15
MARKET_POLL_MINUTES_NIGHT = 60

SAST_OFFSET_HOURS = 2
DAYTIME_START_SAST = 6
DAYTIME_END_SAST = 20

HTTP_TIMEOUT_SECONDS = 20
USER_AGENT = "weatheredge-research/1.0 (personal research project)"
