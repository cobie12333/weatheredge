import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module

forecast = load_module("electricity_forecast", HERE / "forecast.py")
collect = load_module("electricity_collect", HERE / "collect.py")


class ForecastTests(unittest.TestCase):
    def test_seasonal_naive_perfect_for_repeating_series(self):
        values = [float(i % 4) for i in range(24)]
        result = forecast.evaluate(values, season=4, test_size=8)
        self.assertEqual(result["n_test"], 8)
        self.assertAlmostEqual(result["seasonal_naive"]["mae"], 0.0)
        self.assertAlmostEqual(result["seasonal_naive"]["rmse"], 0.0)

    def test_rejects_unsorted_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text(
                "timestamp,value\n2026-01-01T01:00:00,2\n2026-01-01T00:00:00,1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "strictly increasing"):
                forecast.load_series(path, "timestamp", "value")

    def test_requires_enough_history(self):
        with self.assertRaisesRegex(ValueError, "need more than"):
            forecast.evaluate([1.0, 2.0, 3.0], season=3, test_size=2)


class CollectorTests(unittest.TestCase):
    def test_rejects_external_hosts(self):
        self.assertIsNone(collect.candidate_url(
            "https://www.eskom.co.za/page", "https://example.com/data.csv", "CSV"
        ))

    def test_accepts_official_csv_link(self):
        result = collect.candidate_url(
            "https://www.eskom.co.za/page", "/files/demand.csv", "Download data"
        )
        self.assertEqual(result, "https://www.eskom.co.za/files/demand.csv")


if __name__ == "__main__":
    unittest.main()
