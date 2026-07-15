import unittest

import numpy as np

import connectivity_gate


class ConnectivityGateTests(unittest.TestCase):
    def test_gate_reports_low_flat_reduction_and_operating_metrics(self):
        labels = np.array([True, True, True, False, False, False, False, False])
        baseline_scores = np.array([0.8, 0.7, 0.6, 0.9, 0.8, 0.7, 0.2, 0.1])
        candidate_scores = np.array([0.99, 0.95, 0.9, 0.6, 0.5, 0.4, 0.2, 0.1])
        baseline_flags = baseline_scores >= 0.6
        candidate_flags = candidate_scores >= 0.7
        low_flat = np.array([False, False, False, True, True, True, False, False])
        result = connectivity_gate.evaluate_gate(
            labels, candidate_scores, baseline_scores,
            candidate_flags, baseline_flags, low_flat, True,
        )
        self.assertEqual(result["low_flat_reduction"], 1.0)
        self.assertEqual(result["candidate_operating"]["false_positive"], 0)
        self.assertGreater(result["roc_auc_gain"], 0)

    def test_gate_rejects_single_class_labels(self):
        values = np.ones(4)
        with self.assertRaisesRegex(ValueError, "both flooded and not-flooded"):
            connectivity_gate.evaluate_gate(
                np.ones(4, dtype=bool), values, values,
                values.astype(bool), values.astype(bool),
                np.zeros(4, dtype=bool), True,
            )


if __name__ == "__main__":
    unittest.main()
