import os
import sqlite3
import tempfile
import unittest

from climaterisk.cli import (
    connect, regression, scores, temperature_backtest, import_water, power_backtest
)


class ClimateRiskTests(unittest.TestCase):
    def test_regression(self):
        a, b = regression([1, 2, 3], [3, 5, 7])
        self.assertAlmostEqual(a, 1)
        self.assertAlmostEqual(b, 2)

    def test_scores(self):
        result = scores([10, 12], [9, 14])
        self.assertEqual(result["n"], 2)
        self.assertEqual(result["mae"], 1.5)

    def test_temperature_walk_forward(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = connect(os.path.join(tmp, "test.db"))
            for i in range(12):
                con.execute("INSERT INTO weather_daily(local_date,tmax_c,source) VALUES(?,?,?)",
                            (f"2026-01-{i+1:02d}", 20 + i, "fixture"))
            con.commit()
            result = temperature_backtest(con)
            self.assertEqual(result["model_scores"]["n"], 5)
            self.assertEqual(result["baseline_scores"]["n"], 5)
            con.close()

    def test_water_csv_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(os.path.join(tmp, "test.db"))
            path = os.path.join(tmp, "water.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write("date,dam,percentage_full,stored_mcm\n")
                f.write("2026-10-19,Total,74.0,664.0\n")
                f.write("2026-10-26,Total,73.7,661.0\n")
            self.assertEqual(import_water(db, path), 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM water_readings").fetchone()[0], 2)
            db.close()

    def test_power_backtest_needs_minimum_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(os.path.join(tmp, "test.db"))
            result = power_backtest(db)
            self.assertIn("Need at least 48", result["status"])
            db.close()


if __name__ == "__main__":
    unittest.main()
