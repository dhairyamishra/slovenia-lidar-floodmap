import unittest

import numpy as np

import benchmark_replacement as benchmark


class ReplacementBenchmarkTests(unittest.TestCase):
    def test_monotonic_logistic_coefficients_are_nonnegative(self):
        x = np.array([[-2.0], [-1.0], [1.0], [2.0]])
        y = np.array([False, False, True, True])
        parameters = benchmark._fit_monotonic_logistic(x, y, l2=0.1)
        self.assertGreaterEqual(parameters[1], 0.0)
        scores = benchmark._predict_logistic(parameters, x)
        self.assertGreater(scores[-1], scores[0])

    def test_spatial_fold_excludes_adjacent_same_region_columns(self):
        dataset = {
            "regions": np.array(["a", "a", "a", "a", "b", "b"]),
            "eastings": np.array([1, 2, 3, 4, 8, 9]),
            "labels": np.array([False, True, False, True, False, True]),
        }
        folds = benchmark.spatial_folds(dataset)
        for name, train, validation in folds:
            region, column = name.split(":E")
            column = int(column)
            same_region_train = train & (dataset["regions"] == region)
            self.assertTrue(np.all(np.abs(dataset["eastings"][same_region_train] - column) > 1))
            self.assertTrue(np.all(dataset["eastings"][validation] == column))

    def test_operating_metrics_are_consistent(self):
        labels = np.array([True, True, False, False])
        scores = np.array([0.9, 0.8, 0.7, 0.1])
        metrics = benchmark._operating_metrics(labels, scores, 0.75)
        self.assertEqual(metrics["confusion"], {"tp": 2, "fp": 0, "fn": 0, "tn": 2})
        self.assertEqual(metrics["f1"], 1.0)


if __name__ == "__main__":
    unittest.main()
