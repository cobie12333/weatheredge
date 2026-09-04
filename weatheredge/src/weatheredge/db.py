"""Database utilities for WeatherEdge."""

import sqlite3
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from weatheredge.config import DB_PATH, SCHEMA_PATH, LOG_DIR


def utc_now_iso() -> str:
    """Return current UTC time as ISO8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    # Ensure schema is up to date
    if os.path.exists(SCHEMA_PATH):
        with open(SCHEMA_PATH, "r") as f:
            con.executescript(f.read())
    return con


def log_collection_attempt(con, collector: str, success: bool, rows_written: int = 0, error_msg: str = None):
    """Log a collection attempt to the collection_log table."""
    con.execute(
        """
        INSERT INTO collection_log
        (attempted_at, collector, success, rows_written, error_msg)
        VALUES (?, ?, ?, ?, ?)
        """,
        (utc_now_iso(), collector, int(success), rows_written, error_msg),
    )
    con.commit()


def setup_logger(name: str) -> logging.Logger:
    """Set up a logger with file and stream handlers."""
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s UTC [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    fmt.converter = lambda *args: datetime.now(timezone.utc).timetuple()

    log_path = Path(LOG_DIR) / f"{name}.log"
    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    return logger
