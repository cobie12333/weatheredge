import sqlite3
import logging
import os
import urllib.request
from datetime import datetime, timezone, timedelta

from config.settings import DB_PATH, SCHEMA_PATH, LOG_DIR

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_connection() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    with open(SCHEMA_PATH, "r") as f:
        con.executescript(f.read())
    return con


def log_collection_attempt(con, collector, success, rows_written=0, error_msg=None):
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

    file_handler = logging.FileHandler(os.path.join(LOG_DIR, f"{name}.log"))
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    return logger
