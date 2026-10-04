import logging
import os
import sqlite3
from datetime import datetime, timezone

from config.settings import DB_PATH, SCHEMA_PATH, LOG_DIR


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_SCHEMA_READY = False


def init_schema() -> None:
    global _SCHEMA_READY
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            con.executescript(f.read())
        con.commit()
        _SCHEMA_READY = True
    finally:
        con.close()


def get_connection(readonly: bool = False) -> sqlite3.Connection:
    global _SCHEMA_READY
    if not readonly and not _SCHEMA_READY:
        init_schema()
    if readonly:
        if not os.path.exists(DB_PATH):
            raise FileNotFoundError(DB_PATH)
        con = sqlite3.connect(
            f"file:{DB_PATH}?mode=ro",
            uri=True,
            timeout=30,
        )
    else:
        con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
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
