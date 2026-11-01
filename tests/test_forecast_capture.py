import unittest
from datetime import datetime, timedelta, timezone

from tests._helpers import TempDB
from weatheredge import forecast_capture as fc

FIXTURE = {  # shaped like the documented Open-Meteo hourly response, NOT a real capture
    "hourly": {
        "time": ["2026-10-31T00:00", "2026-10-31T01:00", "2026-10-31T02:00", "2026-10-31T03:00"],
        "temperature_2m": [14.0, None, 15.5, 16.0],
    }
}


class ForecastCaptureTest(unittest.TestCase):
    def test_parse_skips_nulls(self):
        pts = fc.parse_hourly(FIXTURE, "gfs_seamless")
        self.assertEqual(len(pts), 3)
        self.assertEqual(pts[0], ("2026-10-31T00:00:00Z", 14.0))

    def test_parse_multi_model_suffix(self):
        data = {"hourly": {"time": ["2026-10-31T00:00"], "temperature_2m_gfs_seamless": [9.0]}}
        self.assertEqual(fc.parse_hourly(data, "gfs_seamless"), [("2026-10-31T00:00:00Z", 9.0)])

    def test_parse_empty(self):
        self.assertEqual(fc.parse_hourly({}, "m"), [])
        self.assertEqual(fc.parse_hourly({"hourly": {"time": []}}, "m"), [])

    def test_store_computes_lead_and_drops_past(self):
        with TempDB() as db:
            con = db.get_connection()
            pts = fc.parse_hourly(FIXTURE, "gfs_seamless")
            n = fc.store(con, "FACT", "gfs_seamless", pts, "2026-10-31T01:00:00Z")
            self.assertEqual(n, 2)  # 00:00 is in the past relative to fetch; 01:00 was null
            leads = [r[0] for r in con.execute("SELECT lead_hours FROM forecast_history_multi ORDER BY valid_time")]
            self.assertEqual(leads, [1, 2])
            self.assertEqual(fc.store(con, "FACT", "gfs_seamless", pts, "2026-10-31T01:00:00Z"), 0)  # idempotent

    def test_one_failing_airport_does_not_stop_the_rest(self):
        calls = []

        def fake_fetch(url, timeout=30):
            calls.append(url)
            if "latitude=-33.97403" in url:  # FACT fails
                raise ConnectionResetError("boom")
            now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            times = [(now + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in (1, 2, 3)]
            return {"hourly": {"time": times, "temperature_2m": [10.0, 11.0, 12.0]}}

        orig = fc.fetch_json
        fc.fetch_json = fake_fetch
        try:
            with TempDB() as db:
                total = fc.run()
                con = db.get_connection()
                fails = con.execute("SELECT collector FROM collection_log WHERE success=0").fetchall()
                self.assertEqual([r[0] for r in fails], ["forecast:FACT:gfs_seamless"])
                self.assertGreater(total, 0)
                self.assertEqual(len(calls), 9)
        finally:
            fc.fetch_json = orig


if __name__ == "__main__":
    unittest.main()
