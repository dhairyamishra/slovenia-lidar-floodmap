import unittest

import numpy as np

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

    def test_sample_splits_follow_frozen_region_rules(self):
        splits = evaluate_validation.assign_sample_splits(
            np.array(["461_100", "462_100", "463_100", "490_134", "400_46"]),
            np.array(["05-ljubljana", "05-ljubljana", "05-ljubljana", "08-kamnik", "01-koper"]),
        )
        self.assertEqual(
            splits.tolist(),
            ["development", "guard", "locked_test", "locked_test", "evaluation_only"],
        )

    def test_negative_controls_require_q100_negative_labels(self):
        arrays = {
            "norm_elev": np.array([0.1, 0.1, 0.8]),
            "norm_slope": np.array([0.1, 0.1, 0.1]),
            "norm_hand": np.array([0.1, 0.1, 0.3]),
        }
        controls = evaluate_validation.build_negative_controls(
            arrays, np.array([True, True, True]), np.array([False, True, False])
        )
        self.assertEqual(controls["low_flat_q100_negative"].tolist(), [True, False, False])
        self.assertEqual(controls["low_hand_q100_negative"].tolist(), [True, False, False])
        self.assertEqual(controls["flat_upland_q100_negative"].tolist(), [False, False, True])


if __name__ == "__main__":
    unittest.main()
