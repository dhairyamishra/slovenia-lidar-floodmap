import unittest
import json
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon, box

from validation_grid import (
    assign_split,
    grid_definition,
    pack_mask,
    rasterize_geometry,
    region_bounds,
    unpack_mask,
    file_sha256,
)


ROOT = Path(__file__).resolve().parent


class SpatialSplitTests(unittest.TestCase):
    def test_ljubljana_has_full_guard_column(self):
        self.assertEqual(assign_split("461_100", "05-ljubljana"), "development")
        self.assertEqual(assign_split("462_100", "05-ljubljana"), "guard")
        self.assertEqual(assign_split("463_100", "05-ljubljana"), "locked_test")

    def test_savinja_has_full_guard_column(self):
        self.assertEqual(assign_split("488_134", "08-kamnik"), "development")
        self.assertEqual(assign_split("489_134", "08-kamnik"), "guard")
        self.assertEqual(assign_split("490_134", "08-kamnik"), "locked_test")

    def test_koper_is_evaluation_only(self):
        self.assertEqual(assign_split("400_46", "01-koper"), "evaluation_only")


class RasterContractTests(unittest.TestCase):
    def test_region_bounds_follow_tile_kilometres(self):
        self.assertEqual(
            region_bounds(["486_132", "490_136"]),
            (486000.0, 132000.0, 491000.0, 137000.0),
        )

    def test_rasterize_cell_centers_and_polygon_hole(self):
        grid = grid_definition((0.0, 0.0, 10.0, 10.0), 2)
        geometry = Polygon(
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            holes=[[(4, 4), (6, 4), (6, 6), (4, 6)]],
        )
        mask = rasterize_geometry(geometry, grid)
        self.assertEqual(mask.shape, (5, 5))
        self.assertFalse(mask[2, 2])
        self.assertGreater(int(mask.sum()), 20)

    def test_pack_round_trip(self):
        mask = np.array([[True, False, True], [False, True, False]], dtype=bool)
        restored = unpack_mask(pack_mask(mask), mask.shape)
        np.testing.assert_array_equal(restored, mask)

    def test_clipping_outside_grid_is_empty(self):
        grid = grid_definition((0.0, 0.0, 10.0, 10.0), 2)
        self.assertFalse(rasterize_geometry(box(20, 20, 30, 30), grid).any())

    def test_committed_manifest_covers_all_region_resolution_pairs(self):
        path = ROOT / "validation/evaluation_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["rasters"]), 9)
        pairs = {(entry["region"], entry["resolution_m"]) for entry in manifest["rasters"]}
        self.assertEqual(
            pairs,
            {
                (region, resolution)
                for region in ("01-koper", "05-ljubljana", "08-kamnik")
                for resolution in (2, 10, 20)
            },
        )
        for entry in manifest["rasters"]:
            raster = ROOT / entry["path"]
            self.assertTrue(raster.exists())
            self.assertEqual(file_sha256(raster), entry["sha256"])


if __name__ == "__main__":
    unittest.main()
