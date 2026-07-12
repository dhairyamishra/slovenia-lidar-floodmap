import unittest

import numpy as np

import kernels
import mosaic_hydrology as mosaic


class ConditioningTests(unittest.TestCase):
    def test_priority_flood_removes_interior_sinks(self):
        dem = np.array([
            [5, 5, 5, 5, 5],
            [5, 4, 4, 4, 5],
            [5, 4, 1, 4, 5],
            [5, 4, 4, 4, 5],
            [5, 5, 4, 5, 5],
        ], dtype=float)
        filled = kernels.priority_flood_fill(dem, epsilon=1e-4)
        receivers = kernels.flow_receivers(filled, 1.0).reshape(dem.shape)
        self.assertEqual(int((receivers[1:-1, 1:-1] < 0).sum()), 0)
        self.assertGreater(filled[2, 2], dem[2, 2])

    def test_mfd_and_d8_route_all_cells_to_simple_outlet(self):
        dem = np.array([
            [9, 8, 7],
            [8, 7, 6],
            [7, 6, 5],
        ], dtype=float)
        receivers = kernels.flow_receivers(dem, 1.0)
        d8 = kernels.accumulate_receivers(dem, receivers)
        mfd = kernels.mfd_accumulation(dem, 1.0)
        self.assertAlmostEqual(float(d8[-1, -1]), 9.0)
        self.assertAlmostEqual(float(mfd[-1, -1]), 9.0)

    def test_hand_and_strahler_share_continuous_receiver_graph(self):
        dem = np.array([[9, 1, 9], [1, 8, 1], [1, 7, 6]], dtype=float)
        receivers = np.full(9, -1, dtype=np.int64)
        receivers[0] = 4
        receivers[2] = 4
        receivers[4] = 7
        receivers[7] = 8
        streams = np.zeros((3, 3), dtype=bool)
        streams.ravel()[[0, 2, 4, 7, 8]] = True
        hand = kernels.hand_from_receivers(dem, receivers, streams)
        order = kernels.strahler_order(dem, receivers, streams)
        self.assertTrue(np.all(hand >= 0))
        self.assertGreaterEqual(int(order.max()), 2)


class MosaicContractTests(unittest.TestCase):
    def test_threshold_selection_uses_d8_alignment_only(self):
        blocks = [
            {"method": "d8", "stream_area_m2": 10_000, "f1_20m": 0.4},
            {"method": "d8", "stream_area_m2": 50_000, "f1_20m": 0.7},
            {"method": "mfd", "stream_area_m2": 100_000, "f1_20m": 0.9},
        ]
        self.assertEqual(mosaic.select_stream_threshold(blocks), 50_000)

    def test_smooth_plane_has_no_artificial_seam_amplification(self):
        rows, cols = mosaic.SHAPE
        plane = np.add.outer(np.arange(rows, dtype=float), np.arange(cols, dtype=float))
        metrics = mosaic.seam_jump_metrics(plane)
        self.assertAlmostEqual(metrics["median_seam_ratio"], 1.0)

    def test_expected_savinja_tile_contract(self):
        paths = mosaic.tile_paths()
        self.assertEqual(len(paths), 25)
        self.assertEqual(paths[0].name, "GKOT_486_132.laz")
        self.assertEqual(paths[-1].name, "GKOT_490_136.laz")


if __name__ == "__main__":
    unittest.main()
