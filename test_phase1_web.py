import json
import unittest
from pathlib import Path

import numpy as np

from pipeline import D19_REVIEW_THRESHOLD, d19_display_to_rgba


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
        self.assertEqual(len(manifest["tiles"]), 146)
        for tile in manifest["tiles"]:
            files = tile["files"]
            self.assertEqual(files["d19_diagnostic"], files["susceptibility"])
            self.assertTrue((ROOT / "web/data" / files["d19_review"]).exists())


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
