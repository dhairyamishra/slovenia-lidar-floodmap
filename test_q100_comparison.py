import json
import unittest
from pathlib import Path

import numpy as np

import prepare_q100_comparison as comparison


ROOT = Path(__file__).resolve().parent


class ComparisonClassificationTests(unittest.TestCase):
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


class ComparisonWebAssetTests(unittest.TestCase):
    def test_all_tiles_register_visual_and_click_index_assets(self):
        manifest = json.loads((ROOT / "web/data/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["q100_comparison"]["schema_version"], 1)
        self.assertEqual(set(manifest["q100_comparison"]["regions"]), {
            "01-koper", "05-ljubljana", "08-kamnik",
        })
        for tile in manifest["tiles"]:
            for key in ("q100_comparison", "q100_comparison_index"):
                self.assertTrue((ROOT / "web/data" / tile["files"][key]).exists())

    def test_sidebar_and_app_use_derived_categories_not_blended_source_layers(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        app = (ROOT / "web/app.js").read_text(encoding="utf-8")
        for label in ("Official Q100 only", "D19 only", "Both", "Neither"):
            self.assertIn(label, html)
        self.assertIn("q100_comparison", app)
        self.assertIn("q100_comparison_index", app)
        self.assertIn("Official Q100:", app)
        self.assertIn("Official study validity:", app)
        self.assertNotIn("visual overlap", html.lower())


if __name__ == "__main__":
    unittest.main()
