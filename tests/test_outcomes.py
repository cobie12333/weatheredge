import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from tests._helpers import TempDB
from weatheredge import outcomes
from weatheredge.airports import AIRPORT_BY_ICAO

FACT = AIRPORT_BY_ICAO["FACT"]
TZ = ZoneInfo(FACT["tz"])
DAY = datetime(2026, 10, 30).date()


def add_metar(con, icao, local_dt, temp):
    utc = local_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute(
        "INSERT OR IGNORE INTO metar_multi (station_id, fetched_at, obs_time, temp_c, raw_metar) VALUES (?,?,?,?,?)",
        (icao, utc, utc, temp, "X"),
    )


def fill_day(con, hours, peak=24.0):
    for h in hours:
        add_metar(con, "FACT", datetime(2026, 10, 30, h, 0, tzinfo=TZ), peak if h == 15 else 15.0)
    con.commit()


NOW = datetime(2026, 10, 31, 10, 0, tzinfo=TZ).astimezone(timezone.utc)


class OutcomesTest(unittest.TestCase):
    def test_provisional_from_full_day(self):
        with TempDB() as db:
            con = db.get_connection()
            fill_day(con, range(24))
            res = outcomes.fill_provisional(con, days=1, now=NOW, airports=[FACT])
            self.assertEqual(res["written"], 1)
            row = con.execute("SELECT * FROM outcome_multi").fetchone()
            self.assertEqual(row["actual_max_c"], 24.0)
            self.assertTrue(outcomes.is_provisional(row["source_url"]))
            legacy = con.execute("SELECT actual_max_c FROM outcome WHERE market_date='2026-10-30'").fetchone()
            self.assertEqual(legacy["actual_max_c"], 24.0)

    def test_low_coverage_day_is_not_labelled(self):
        with TempDB() as db:
            con = db.get_connection()
            fill_day(con, range(6, 16))  # only 10 distinct hours
            res = outcomes.fill_provisional(con, days=1, now=NOW, airports=[FACT])
            self.assertEqual(res["written"], 0)
            self.assertEqual(res["skipped_low_coverage"], 1)
            self.assertIsNone(con.execute("SELECT 1 FROM outcome_multi").fetchone())

    def test_incomplete_current_day_never_labelled(self):
        with TempDB() as db:
            con = db.get_connection()
            now = datetime(2026, 10, 30, 23, 30, tzinfo=TZ).astimezone(timezone.utc)
            fill_day(con, range(24))
            res = outcomes.fill_provisional(con, days=1, now=now, airports=[FACT])
            self.assertEqual(res["written"], 0)

    def test_manual_replaces_provisional_and_is_not_overwritten(self):
        with TempDB() as db:
            con = db.get_connection()
            fill_day(con, range(24))
            outcomes.fill_provisional(con, days=1, now=NOW, airports=[FACT])
            outcomes.record_manual(con, "FACT", "2026-10-30", 25.0, "https://example.org/settlement")
            row = con.execute("SELECT * FROM outcome_multi").fetchone()
            self.assertEqual(row["actual_max_c"], 25.0)
            self.assertFalse(outcomes.is_provisional(row["source_url"]))
            outcomes.fill_provisional(con, days=1, now=NOW, airports=[FACT])
            self.assertEqual(con.execute("SELECT actual_max_c FROM outcome_multi").fetchone()[0], 25.0)

    def test_manual_requires_real_source(self):
        with TempDB() as db:
            con = db.get_connection()
            with self.assertRaises(ValueError):
                outcomes.record_manual(con, "FACT", "2026-10-30", 25.0, "")
            with self.assertRaises(ValueError):
                outcomes.record_manual(con, "FACT", "2026-10-30", 25.0, "provisional:x")

    def test_mirror_fact_metar_is_idempotent_and_keeps_existing(self):
        with TempDB() as db:
            con = db.get_connection()
            t = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            con.execute("INSERT INTO metar_multi (station_id,fetched_at,obs_time,receipt_time,temp_c,raw_metar) "
                        "VALUES ('FACT','2026-01-01T00:00:00Z',?, 'r', 20.0,'RAW')", (t,))
            con.execute("INSERT INTO metar_multi (station_id,fetched_at,obs_time,temp_c,raw_metar) "
                        "VALUES ('KATL','2026-01-01T00:00:00Z',?, 5.0,'RAW')", (t,))
            con.commit()
            self.assertEqual(outcomes.mirror_fact_metar(con), 1)
            self.assertEqual(outcomes.mirror_fact_metar(con), 0)
            rows = con.execute("SELECT * FROM metar_obs").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source"], "live")
            self.assertEqual(rows[0]["fetched_at"], "2026-01-01T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
