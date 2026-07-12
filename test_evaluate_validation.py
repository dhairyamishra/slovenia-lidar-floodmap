import unittest

import evaluate_validation


class MetricTests(unittest.TestCase):
    def test_roc_auc_is_one_for_perfect_order(self):
        self.assertAlmostEqual(
            evaluate_validation.roc_auc([False, False, True, True], [0.1, 0.2, 0.8, 0.9]),
            1.0,
        )

    def test_roc_auc_is_half_for_tied_scores(self):
        self.assertAlmostEqual(
            evaluate_validation.roc_auc([False, True, False, True], [0.5, 0.5, 0.5, 0.5]),
            0.5,
        )

    def test_average_precision_is_one_for_perfect_order(self):
        self.assertAlmostEqual(
            evaluate_validation.average_precision([False, False, True, True], [0.1, 0.2, 0.8, 0.9]),
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
