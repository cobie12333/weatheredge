import http.client
import unittest

from tests._helpers import TempDB
from weatheredge import go_live, live_runner, market_collector


class FakeProc:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class ResilienceTest(unittest.TestCase):
    def test_safe_swallows_and_records_crash(self):
        with TempDB() as db:
            def boom():
                raise RuntimeError("collector blew up")
            self.assertIsNone(live_runner._safe("demo", boom))
            con = db.get_connection()
            row = con.execute("SELECT collector, success, error_msg FROM collection_log").fetchone()
            self.assertEqual(row["collector"], "demo")
            self.assertEqual(row["success"], 0)
            self.assertIn("RuntimeError", row["error_msg"])

    def test_safe_returns_value_on_success(self):
        self.assertEqual(live_runner._safe("ok", lambda x: x + 1, 1), 2)

    def test_market_collector_survives_connection_reset(self):
        with TempDB() as db:
            def reset(slug):
                raise ConnectionResetError("mid-read reset")
            orig = market_collector.fetch_event
            market_collector.fetch_event = reset
            try:
                self.assertEqual(market_collector.run(icao="FACT"), 0)
            finally:
                market_collector.fetch_event = orig
            con = db.get_connection()
            self.assertEqual(con.execute("SELECT success FROM collection_log").fetchone()[0], 0)

    def test_market_collector_survives_incomplete_read(self):
        with TempDB():
            def short(slug):
                raise http.client.IncompleteRead(b"x")
            orig = market_collector.fetch_event
            market_collector.fetch_event = short
            try:
                self.assertEqual(market_collector.run(icao="FACT"), 0)
            finally:
                market_collector.fetch_event = orig

    def test_child_restarts_with_backoff_and_gives_up(self):
        spawned = []

        def spawn(module):
            p = FakeProc(code=None)
            spawned.append(p)
            return p

        child = go_live.Child("runner", "m", spawn=spawn, max_restarts=2, window=1000)
        self.assertEqual(len(spawned), 1)
        self.assertIsNone(child.poll(0))            # healthy
        spawned[-1].code = 1                        # crash
        self.assertIn("restarting in 5s", child.poll(10))
        self.assertIsNone(child.poll(12))           # still waiting
        self.assertIn("restarted", child.poll(15))
        self.assertEqual(len(spawned), 2)
        spawned[-1].code = 1
        self.assertIn("restarting in 15s", child.poll(20))
        self.assertIn("restarted", child.poll(35))
        spawned[-1].code = 1
        self.assertIn("giving up", child.poll(40))
        self.assertTrue(child.gave_up)
        self.assertIsNone(child.poll(100))

    def test_child_restart_window_expires(self):
        spawned = []
        spawn = lambda m: (spawned.append(FakeProc()), spawned[-1])[1]
        child = go_live.Child("r", "m", spawn=spawn, max_restarts=1, window=100)
        spawned[-1].code = 1
        child.poll(0)
        child.poll(5)                               # restart #1 at t=5
        spawned[-1].code = 1
        self.assertIn("restarting", child.poll(500))  # old restart aged out, not giving up
        self.assertFalse(child.gave_up)


if __name__ == "__main__":
    unittest.main()
