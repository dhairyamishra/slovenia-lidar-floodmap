import json
import unittest
from pathlib import Path

import numpy as np
from shapely.geometry import box

import prepare_q100_comparison as comparison


ROOT = Path(__file__).resolve().parent


class ComparisonClassificationTests(unittest.TestCase):
    def test_official_masks_are_rasterized_per_tile_without_evaluation_grid(self):
        validity, q100 = comparison.official_masks_for_tile(
            "460_100",
            box(460_000, 100_000, 460_500, 101_000),
            box(460_250, 100_000, 460_750, 101_000),
        )
        self.assertEqual(validity.shape, (500, 500))
        self.assertEqual(int(validity.sum()), 125_000)
        # Pillow includes the polygon edge cell under the frozen center-anchor
        # rasterization convention used throughout validation_grid.py.
        self.assertEqual(int(q100.sum()), 63_000)

    def test_categories_distinguish_domain_neither_only_overlap_and_unavailable(self):
        validity = np.array([[False, True, True], [True, True, True]])
        q100 = np.array([[False, False, True], [False, True, True]])
        signal = np.array([[True, False, False], [True, True, False]])
        data = np.array([[True, True, True], [True, True, False]])
        actual = comparison.classify(validity, q100, signal, data)
        expected = np.array([
            [0, 1, 2],
            [3, 4, 6],
        ], dtype=np.uint8)
        np.testing.assert_array_equal(actual, expected)

    def test_area_shares_use_only_comparable_validity_cells(self):
        counts = {
            "outside_validity": 50,
            "neither": 40,
            "official_only": 30,
            "d19_only": 20,
            "overlap": 10,
            "d19_unavailable_official_no": 3,
            "d19_unavailable_official_yes": 2,
        }
        summary = comparison.summary_block("05-ljubljana", counts)
        self.assertEqual(summary["comparable_cell_count"], 100)
        self.assertEqual(summary["shares_percent"]["official_only"], 30.0)
        self.assertEqual(summary["comparable_coverage_of_validity_percent"], 95.24)

    def test_comparison_categories_use_distinct_requested_colors(self):
        category = np.array([[
            comparison.CATEGORY["official_only"],
            comparison.CATEGORY["d19_only"],
            comparison.CATEGORY["overlap"],
        ]], dtype=np.uint8)
        rgba = comparison.visual_rgba(category)
        self.assertEqual(tuple(rgba[0, 0]), (186, 222, 253, 102))
        self.assertEqual(tuple(rgba[0, 1]), (67, 56, 202, 225))
        self.assertEqual(tuple(rgba[0, 2]), (249, 115, 22, 240))


class ComparisonWebAssetTests(unittest.TestCase):
    def test_all_tiles_register_visual_and_click_index_assets(self):
        manifest = json.loads((ROOT / "web/data/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["q100_comparison"]["schema_version"], 2)
        self.assertEqual(manifest["q100_comparison"]["colors"]["official_only"], "#badefd")
        self.assertEqual(manifest["q100_comparison"]["colors"]["d19_only"], "#4338ca")
        self.assertEqual(manifest["q100_comparison"]["colors"]["overlap"], "#f97316")
        self.assertEqual(set(manifest["q100_comparison"]["regions"]), {
            "01-koper", "05-ljubljana", "08-kamnik",
        })
        for tile in manifest["tiles"]:
            for key in ("q100_comparison", "q100_comparison_index"):
                self.assertTrue((ROOT / "web/data" / tile["files"][key]).exists())

    def test_sidebar_and_app_use_derived_categories_not_blended_source_layers(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        app = (ROOT / "web/app.js").read_text(encoding="utf-8")
        for label in ("Official map only", "Experimental result only", "Both", "Neither"):
            self.assertIn(label, html)
        self.assertIn("q100_comparison", app)
        self.assertIn("q100_comparison_index", app)
        self.assertIn("Official map:", app)
        self.assertIn("Comparison area:", app)
        self.assertIn('id="toggle-q100-comparison"', html)
        self.assertIn('aria-label="Compare with official Q100 flood map" checked', html)
        self.assertIn('id="mobile-map-legend"', html)
        self.assertIn("document.getElementById('mobile-map-legend').hidden = !active", app)
        self.assertIn("registerMobileLayerRefresher(map, updateVisibility);\n  updateVisibility();", app)
        self.assertNotIn("visual overlap", html.lower())

    def test_tile_rasters_keep_desktop_coverage_with_mobile_memory_bound(self):
        app = (ROOT / "web/app.js").read_text(encoding="utf-8")
        self.assertIn("function ensureTileLayer", app)
        self.assertIn("function ensureCoastalLayer", app)
        self.assertIn("syncTileLayerSet(map, tiles, 'q100_comparison', active)", app)
        self.assertIn("if (!MOBILE_LAYOUT.matches) return tiles", app)
        self.assertIn("tilesForMobileViewport", app)
        self.assertIn("removeImageLayer(map, layerId, sourceId)", app)
        self.assertNotIn("manifest.tiles.forEach(tile => addTileLayers", app)


if __name__ == "__main__":
    unittest.main()
