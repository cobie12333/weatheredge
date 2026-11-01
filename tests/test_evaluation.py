import random
import unittest
from datetime import date, timedelta

from weatheredge import demand_experiment as de
from weatheredge import evaluation as ev


def synth_rows(seed, n=620, weather_effect=True):
    """Synthetic daily demand. A test of the harness, not evidence about South Africa."""
    rnd = random.Random(seed)
    rows, d = [], date(2022, 1, 3)  # a Monday
    for i in range(n):
        season = 12 * __import__("math").sin(2 * 3.14159 * i / 365)
        tmax = 22 + season + rnd.gauss(0, 3)
        tmin = tmax - 9 + rnd.gauss(0, 1.5)
        wd = d.weekday()
        y = 28.0 - (1.8 if wd == 5 else 3.0 if wd == 6 else 0.0) + rnd.gauss(0, 0.4)
        if weather_effect:
            tm = (tmax + tmin) / 2
            y += 0.25 * max(0, 15 - tm) + 0.30 * max(0, tm - 24)
        rows.append({"date": d, "y": y, "tmax": tmax, "tmin": tmin})
        d += timedelta(days=1)
    return rows


class ScoringTest(unittest.TestCase):
    def test_basic_scores(self):
        self.assertAlmostEqual(ev.mae([1, 2, 3], [1, 3, 5]), 1.0)
        self.assertAlmostEqual(ev.rmse([0, 0], [3, 4]), (12.5) ** 0.5)
        self.assertAlmostEqual(ev.brier([0.5, 0.5], [1, 0]), 0.25)
        self.assertAlmostEqual(ev.brier([1.0, 0.0], [1, 0]), 0.0)
        self.assertAlmostEqual(ev.pinball(10, 8, 0.9), 1.8)
        self.assertAlmostEqual(ev.pinball(8, 10, 0.9), 0.2)

    def test_reliability_and_coverage(self):
        rows = ev.reliability([0.1, 0.1, 0.9, 0.9], [0, 0, 1, 1], bins=10)
        self.assertEqual(rows[1]["n"], 2)
        self.assertEqual(rows[1]["freq"], 0.0)
        self.assertEqual(rows[9]["freq"], 1.0)
        self.assertEqual(ev.interval_coverage([0, 0, None], [1, 1, None], [0.5, 2, 9]), 0.5)

    def test_ridge_recovers_known_coefficients(self):
        rnd = random.Random(1)
        X = [[1.0, rnd.random(), rnd.random()] for _ in range(200)]
        y = [2 + 3 * a - 1 * b for _, a, b in X]
        c = ev.fit_ridge(X, y)
        self.assertAlmostEqual(c[0], 2, places=3)
        self.assertAlmostEqual(c[1], 3, places=3)
        self.assertAlmostEqual(c[2], -1, places=3)

    def test_bootstrap_ci_contains_true_mean_and_is_ordered(self):
        rnd = random.Random(3)
        v = [rnd.gauss(1.0, 1.0) for _ in range(300)]
        m, lo, hi = ev.block_bootstrap_ci(v, n_boot=500)
        self.assertLess(lo, m)
        self.assertLess(m, hi)
        self.assertLess(lo, 1.0)
        self.assertGreater(hi, 0.7)

    def test_compare_small_sample_refuses_verdict(self):
        self.assertEqual(ev.compare([1] * 10, [2] * 10)["verdict"], "insufficient_data")

    def test_compare_clear_win_and_loss_and_tie(self):
        rnd = random.Random(5)
        base = [rnd.random() for _ in range(200)]
        better = [b - 0.3 + rnd.gauss(0, 0.05) for b in base]
        self.assertEqual(ev.compare(better, base, n_boot=500)["verdict"], "model_better")
        self.assertEqual(ev.compare(base, better, n_boot=500)["verdict"], "baseline_better")
        noise = [b + rnd.gauss(0, 0.2) for b in base]
        self.assertEqual(ev.compare(noise, base, n_boot=500)["verdict"], "no_difference_detected")


class HedgeTest(unittest.TestCase):
    def test_correlated_hedge_reduces_risk_out_of_sample(self):
        rnd = random.Random(7)
        hedge = [rnd.gauss(0, 10) for _ in range(240)]
        exposure = [-0.8 * h + rnd.gauss(0, 3) for h in hedge]
        res = ev.out_of_sample_hedge(exposure, hedge, split=120)
        self.assertGreater(res["effectiveness"], 0.8)
        self.assertGreater(res["worst_hedged"], res["worst_unhedged"])

    def test_unrelated_hedge_does_not_help(self):
        rnd = random.Random(8)
        hedge = [rnd.gauss(0, 10) for _ in range(240)]
        exposure = [rnd.gauss(0, 10) for _ in range(240)]
        res = ev.out_of_sample_hedge(exposure, hedge, split=120)
        self.assertLess(res["effectiveness"], 0.15)

    def test_fixed_bad_ratio_adds_risk(self):
        rnd = random.Random(9)
        hedge = [rnd.gauss(0, 10) for _ in range(100)]
        exposure = [rnd.gauss(0, 10) for _ in range(100)]
        self.assertLess(ev.hedge_effectiveness(exposure, hedge, ratio=3.0)["effectiveness"], 0)


class DemandExperimentTest(unittest.TestCase):
    def run_exp(self, seed, weather_effect):
        rows = synth_rows(seed, weather_effect=weather_effect)
        recs = de.walk_forward(rows, set(), min_train=365)
        return de.evaluate(recs, n_boot=400, seed=seed)

    def test_real_weather_effect_is_detected(self):
        res = self.run_exp(11, True)
        self.assertEqual(res["vs_calendar"]["verdict"], "model_better")
        self.assertEqual(res["vs_naive_weekday_last_week"]["verdict"], "model_better")
        self.assertLess(res["mae"]["wx"], res["mae"]["cal"])

    def test_no_false_wins_when_weather_is_irrelevant(self):
        wins = sum(self.run_exp(s, False)["vs_calendar"]["verdict"] == "model_better" for s in range(20))
        self.assertLessEqual(wins, 2, f"{wins}/20 false wins at a nominal 5% level")

    def test_no_lookahead(self):
        # Perturb the outcome of day k, which falls on a refit boundary. Predictions for
        # every day up to and including k must be unchanged: day k's own value may never
        # influence the forecast made for day k.
        min_train, k = 365, 365 + 7 * 10
        rows = synth_rows(21, n=520)
        base = de.walk_forward(rows, set(), min_train=min_train)
        rows[k]["y"] += 1000
        changed = de.walk_forward(rows, set(), min_train=min_train)
        i = k - min_train
        for key in ("wx", "cal", "naive1", "naive4"):
            self.assertEqual([r[key] for r in base[:i + 1]], [r[key] for r in changed[:i + 1]], key)
        self.assertNotEqual([r["wx"] for r in base[i + 1:]], [r["wx"] for r in changed[i + 1:]])

    def test_interval_coverage_reasonable(self):
        res = self.run_exp(13, True)
        self.assertIsNotNone(res["interval_80_coverage"])
        self.assertGreater(res["interval_80_coverage"], 0.65)
        self.assertLess(res["interval_80_coverage"], 0.92)

    def test_csv_loader_skips_bad_rows(self):
        import os, tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.csv")
            with open(p, "w") as f:
                f.write("date,peak,tmax,tmin\n2024-01-02,28,30,18\nbad,1,2,3\n2024-01-01,27,29,17\n2024-01-01,99,1,1\n2024-01-03,,31,19\n")
            rows = de.load_rows(p, "date", "peak", "tmax", "tmin")
            self.assertEqual([r["date"].day for r in rows], [1, 2])
            self.assertEqual(rows[0]["y"], 27.0)  # first occurrence of a duplicate date wins


if __name__ == "__main__":
    unittest.main()
