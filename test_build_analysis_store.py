import unittest

import numpy as np

import build_analysis_store as store


class AnalysisStoreTests(unittest.TestCase):
    def test_point_summary_preserves_missing_cells_and_physical_bands(self):
        arrays = store.summarize_points(
            np.array([0.5, 0.6, 0.7, 2.5]),
            np.array([0.5, 0.6, 0.7, 2.5]),
            np.array([10.0, 15.0, 12.0, 20.0]),
            np.array([2, 5, 2, 1], dtype=np.uint8),
            (0.0, 0.0, 4.0, 4.0), 2.0,
        )
        dtm, dsm, vegetation, point_density, ground_density = arrays
        self.assertEqual(dtm[0, 0], 10.0)
        self.assertEqual(dsm[0, 0], 15.0)
        self.assertEqual(vegetation[0, 0], 15.0)
        self.assertEqual(point_density[0, 0], 3)
        self.assertEqual(ground_density[0, 0], 2)
        self.assertTrue(np.isinf(dtm[1, 1]))


if __name__ == "__main__":
    unittest.main()
