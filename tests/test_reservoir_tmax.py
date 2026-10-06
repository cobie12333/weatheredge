import unittest

from weatheredge.reservoir_tmax import BUCKETS, walk_forward_evaluate


class ReservoirTmaxEvaluationTest(unittest.TestCase):
    def test_walk_forward_is_chronological_and_scores_metrics(self):
        sequences = []
        targets = []
        dates = []
        for i in range(12):
            temp = 0.45 + (i % 4) * 0.05
            sequences.append([[temp, 0.3, 0.1, 0.0, 1.0, 0.92, 0.0, 0.0,
                               0.5, 0.8, temp, 0.25, 0.0, 0.0]])
            targets.append(20 + (i % 3))
            dates.append(f"2026-01-{i + 1:02d}")

        result = walk_forward_evaluate(
            sequences, targets, dates=dates, min_train_days=5
        )

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["test_days"], 7)
        self.assertEqual(len(result["predictions"]), 7)
        self.assertEqual(result["predictions"][0]["date"], "2026-01-06")
        self.assertEqual(set(result["predictions"][0]["probabilities"]), {str(b) for b in BUCKETS})
        self.assertTrue(0.0 <= result["top_bucket_accuracy"] <= 1.0)
        self.assertGreaterEqual(result["brier"], 0.0)
        self.assertGreaterEqual(result["log_loss"], 0.0)


if __name__ == "__main__":
    unittest.main()
