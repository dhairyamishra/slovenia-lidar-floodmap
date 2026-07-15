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

    def test_flow_labels_propagate_outlet_and_downstream_stream(self):
        dem = np.array([[5, 4, 3, 2]], dtype=float)
        receivers = np.array([1, 2, 3, -1], dtype=np.int64)
        streams = np.array([[False, False, True, False]])
        outlet, downstream = kernels.flow_labels(dem, receivers, streams)
        np.testing.assert_array_equal(outlet, [[3, 3, 3, 3]])
        np.testing.assert_array_equal(downstream, [[2, 2, 2, -1]])

    def test_stream_reaches_split_at_a_confluence(self):
        dem = np.array([[9, 1, 8], [7, 6, 5]], dtype=float)
        receivers = np.array([3, -1, 5, 4, 5, -1], dtype=np.int64)
        streams = np.array([[True, False, True], [True, True, True]])
        order = np.array([[1, 0, 1], [1, 1, 2]], dtype=np.int16)
        reaches = kernels.stream_reach_ids(dem, receivers, streams, order)
        self.assertEqual(reaches[0, 0], reaches[1, 0])
        self.assertNotEqual(reaches[0, 0], reaches[1, 2])
        self.assertNotEqual(reaches[0, 2], reaches[1, 2])


class MosaicContractTests(unittest.TestCase):
    def tearDown(self):
        mosaic.configure_region("savinja")

    def test_threshold_selection_uses_d8_alignment_only(self):
        blocks = [
            {"method": "d8", "stream_area_m2": 10_000, "f1_20m": 0.4},
            {"method": "d8", "stream_area_m2": 50_000, "f1_20m": 0.7},
            {"method": "mfd", "stream_area_m2": 100_000, "f1_20m": 0.9},
        ]
        self.assertEqual(mosaic.select_stream_threshold(blocks), 50_000)

    def test_configuration_selection_uses_development_auc_then_ap(self):
        rows = [
            {"conditioning_variant": "a", "stream_area_m2": 10_000,
             "benchmark": {"available": True, "mosaic_hand": {"roc_auc": 0.7, "average_precision": 0.6}}},
            {"conditioning_variant": "b", "stream_area_m2": 50_000,
             "benchmark": {"available": True, "mosaic_hand": {"roc_auc": 0.71, "average_precision": 0.5}}},
        ]
        self.assertEqual(mosaic.select_configuration(rows)["conditioning_variant"], "b")

    def test_validation_lookup_honors_north_to_south_row_order(self):
        grid = {
            "xmin": 0.0, "ymin": 0.0, "xmax": 4.0, "ymax": 4.0,
            "resolution_m": 2.0, "width": 2, "height": 2,
        }
        masks = {
            "validity": np.array([[True, False], [False, True]]),
            "q100": np.array([[True, False], [False, False]]),
            "q100_boundary_10m": np.array([[False, False], [False, True]]),
        }
        original = mosaic.load_validation_masks
        mosaic.load_validation_masks = lambda _region: (grid, masks)
        try:
            inside, validity, boundary, q100 = mosaic.lookup_validation_masks(
                "test", np.array([1.0, 3.0, 5.0]), np.array([3.0, 1.0, 1.0])
            )
        finally:
            mosaic.load_validation_masks = original
        np.testing.assert_array_equal(inside, [True, True, False])
        np.testing.assert_array_equal(validity, [True, True, False])
        np.testing.assert_array_equal(boundary, [False, True, False])
        np.testing.assert_array_equal(q100, [True, False, False])

    def test_smooth_plane_has_no_artificial_seam_amplification(self):
        rows, cols = mosaic.SHAPE
        plane = np.add.outer(np.arange(rows, dtype=float), np.arange(cols, dtype=float))
        metrics = mosaic.seam_jump_metrics(plane)
        self.assertAlmostEqual(metrics["median_seam_ratio"], 1.0)

    def test_expected_savinja_tile_contract(self):
        mosaic.configure_region("savinja")
        paths = mosaic.tile_paths()
        self.assertEqual(len(paths), 25)
        self.assertEqual(paths[0].name, "GKOT_486_132.laz")
        self.assertEqual(paths[-1].name, "GKOT_490_136.laz")

    def test_expected_ljubljana_tile_contract(self):
        mosaic.configure_region("ljubljana")
        paths = mosaic.tile_paths()
        self.assertEqual(len(paths), 100)
        self.assertEqual(mosaic.SHAPE, (5000, 5000))
        self.assertEqual(paths[0].name, "GKOT_455_96.laz")
        self.assertEqual(paths[-1].name, "GKOT_464_105.laz")


if __name__ == "__main__":
    unittest.main()
