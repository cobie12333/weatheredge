import unittest

from weatheredge.reservoir import EchoStateTmax, ReservoirConfig


class ReservoirTests(unittest.TestCase):
    def test_fit_and_probability_distribution(self):
        model = EchoStateTmax(
            input_size=2,
            buckets=[20, 21, 22],
            config=ReservoirConfig(size=16, seed=7),
        )
        sequences = [
            [[0.1, 0.0], [0.2, 0.1]],
            [[0.8, 0.1], [0.9, 0.2]],
            [[0.4, 0.0], [0.5, 0.1]],
            [[0.2, 0.0], [0.3, 0.1]],
            [[0.9, 0.2], [1.0, 0.2]],
            [[0.5, 0.1], [0.6, 0.1]],
        ]
        targets = [20, 22, 21, 20, 22, 21]
        model.fit(sequences, targets)
        probs = model.predict_proba([[0.85, 0.2], [0.95, 0.2]])
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=5)
        self.assertEqual(set(probs), {"20", "21", "22"})


if __name__ == "__main__":
    unittest.main()
