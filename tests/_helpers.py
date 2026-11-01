"""Shared test helpers: a fresh temporary WeatherEdge database per test."""
import os
import tempfile

import weatheredge.db as db


class TempDB:
    def __enter__(self):
        self._dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(self._dir.name, "test.db")
        db.SCHEMA_PATH = os.path.abspath("weatheredge/schema.sql")
        db._SCHEMA_READY = False
        db.init_schema()
        return db

    def __exit__(self, *exc):
        self._dir.cleanup()
