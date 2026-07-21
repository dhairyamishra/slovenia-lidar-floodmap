import json
import unittest
from pathlib import Path

import numpy as np

from pipeline import (
    D19_REVIEW_THRESHOLD,
    REVIEW_POINT_SEP_M,
    d19_display_to_rgba,
    select_review_candidates,
)


ROOT = Path(__file__).resolve().parent


class D19DisplayTests(unittest.TestCase):
    def test_review_mask_is_transparent_below_display_cutoff(self):
        scores = np.array([
            [D19_REVIEW_THRESHOLD - 0.01, D19_REVIEW_THRESHOLD],
            [0.95, 1.0],
        ], dtype=np.float32)
        image = d19_display_to_rgba(scores, review=True)
        rgba = np.asarray(image.convert("RGBA"))
        self.assertEqual(int(rgba[..., 3].min()), 0)
        self.assertGreater(int(rgba[..., 3].max()), 0)

    def test_original_raster_and_review_assets_are_both_registered(self):
        manifest = json.loads((ROOT / "web/data/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["d19_display"]["review_threshold"], D19_REVIEW_THRESHOLD)
        self.assertEqual(
            manifest["d19_display"]["generation"],
            "direct-from-unquantized-fixed-regional-display-score",
        )
        self.assertEqual(manifest["tile_count"], 391)
        self.assertEqual(len(manifest["tiles"]), manifest["tile_count"])
        for tile in manifest["tiles"]:
            files = tile["files"]
            self.assertEqual(files["d19_diagnostic"], files["susceptibility"])
            self.assertTrue((ROOT / "web/data" / files["d19_review"]).exists())

    def test_review_selector_spreads_markers_across_distinct_hotspots(self):
        cache = {"a": "region-a", "b": "region-a", "c": "region-b"}
        candidates = [
            {"tile": "a", "score": 1.00, "easting_3794": 0, "northing_3794": 0},
            {"tile": "a", "score": 0.99, "easting_3794": 100, "northing_3794": 0},
            {"tile": "b", "score": 0.98, "easting_3794": 900, "northing_3794": 0},
            {"tile": "c", "score": 0.97, "easting_3794": 2000, "northing_3794": 0},
        ]
        selected = select_review_candidates(
            candidates, cache, top_n=3, region_cap=2,
            separation_m=REVIEW_POINT_SEP_M,
        )
        self.assertEqual([c["score"] for c in selected], [1.00, 0.98, 0.97])

    def test_published_review_points_meet_coverage_spacing(self):
        risk_points = json.loads(
            (ROOT / "web/data/risk_points.geojson").read_text(encoding="utf-8")
        )["features"]
        points = [feature["properties"] for feature in risk_points]
        for index, point in enumerate(points):
            for other in points[index + 1:]:
                distance = np.hypot(
                    point["easting_3794"] - other["easting_3794"],
                    point["northing_3794"] - other["northing_3794"],
                )
                self.assertGreaterEqual(distance, REVIEW_POINT_SEP_M)
        self.assertGreaterEqual(len({point["tile"] for point in points}), 18)


class OfficialWebContractTests(unittest.TestCase):
    def test_validity_and_depth_layers_are_registered(self):
        path = ROOT / "web/data/validation/manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 2)
        expected = {
            "validity",
            "depth_lt_0_5m",
            "depth_0_5_to_1_5m",
            "depth_ge_1_5m",
        }
        self.assertEqual(set(manifest["layers"]), expected)
        for entry in manifest["layers"].values():
            self.assertTrue((path.parent / entry["file"]).exists())

    def test_sidebar_exposes_phase1_controls(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        for control_id in (
            "d19-display-mode",
            "toggle-official-validity",
            "toggle-official-depth",
            "toggle-q100-comparison",
        ):
            self.assertIn(f'id="{control_id}"', html)


if __name__ == "__main__":
    unittest.main()
