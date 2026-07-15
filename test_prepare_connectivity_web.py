import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

import connectivity_flood as flood
import prepare_connectivity_web as web


class ConnectivityWebEncodingTests(unittest.TestCase):
    def test_required_stage_display_emphasizes_low_access_and_fades_upland(self):
        stage = np.array([[0.25, 0.75, 1.5, 2.5, 4.0]])
        applicable = np.ones(stage.shape, dtype=bool)
        clear = np.zeros(stage.shape, dtype=bool)
        rgba = web.required_stage_rgba(stage, applicable, clear, clear)
        self.assertEqual(tuple(rgba[0, 0]), (7, 89, 133, 235))
        self.assertEqual(tuple(rgba[0, 4]), (148, 163, 184, 45))
        self.assertGreater(rgba[0, 0, 3], rgba[0, 4, 3])

    def test_physical_value_index_round_trips_centimetres_and_class(self):
        values = np.array([[0.0, 1.23, np.nan]])
        classes = np.array([[1, 2, 0]], dtype=np.uint8)
        encoded = web.encode_value_index(values, classes)
        centimetres = encoded[..., 0].astype(np.uint16) * 256 + encoded[..., 1]
        np.testing.assert_array_equal(centimetres, [[0, 123, 65535]])
        np.testing.assert_array_equal(encoded[..., 2], classes)

    def test_depth_display_distinguishes_wet_uncertain_and_edge(self):
        depth = np.array([[0.2, 1.0, 2.0, 2.0]])
        classes = np.array([[
            flood.CLASS_INUNDATED,
            flood.CLASS_INUNDATED,
            flood.CLASS_UNCERTAIN,
            flood.CLASS_EDGE_CONTAMINATED,
        ]])
        rgba = web.depth_rgba(depth, classes)
        self.assertNotEqual(tuple(rgba[0, 0]), tuple(rgba[0, 1]))
        self.assertEqual(tuple(rgba[0, 2, :3]), (245, 158, 11))
        self.assertEqual(tuple(rgba[0, 3, :3]), (148, 163, 184))

    def test_research_scenario_is_not_exported_without_explicit_review_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web_data = root / "web" / "data"
            mosaic_root = root / "output" / "mosaic"
            tile_dir = mosaic_root / "savinja" / "tiles"
            tile_dir.mkdir(parents=True)
            (web_data / "tiles" / "1_1").mkdir(parents=True)
            arrays = {
                "required_stage_m": np.ones((2, 2), dtype=np.float32),
                "riverine_applicability": np.ones((2, 2), dtype=bool),
                "barrier_uncertainty": np.zeros((2, 2), dtype=bool),
                "edge_contamination": np.zeros((2, 2), dtype=bool),
                "reach_id": np.full((2, 2), 42, dtype=np.int32),
                "scenario_depth_m": np.ones((2, 2), dtype=np.float32),
                "scenario_class": np.full((2, 2), flood.CLASS_INUNDATED, dtype=np.uint8),
            }
            tile_path = tile_dir / "1_1.npz"
            np.savez(tile_path, **arrays)
            scenario = {
                "schema_version": 1,
                "id": "research event",
                "source": {"kind": "unit-test"},
                "publication_status": "research-only",
                "forcing": {"type": "uniform_stage_above_channel", "value_m": 1.0},
            }
            model = flood.model_definition()
            model.update({
                "minimum_stage_available": True,
                "publication_status": "research-only",
                "scenario": scenario,
            })
            (mosaic_root / "savinja" / "manifest.json").write_text(json.dumps({
                "connectivity_model": model,
                "tiles": [{"tile": "1_1", "path": "output/mosaic/savinja/tiles/1_1.npz"}],
            }), encoding="utf-8")
            manifest_path = web_data / "manifest.json"
            manifest_path.write_text(json.dumps({
                "tiles": [{"name": "1_1", "files": {}}],
            }), encoding="utf-8")
            with patch.object(web, "ROOT", root), patch.object(web, "WEB_DATA", web_data), patch.object(web, "MOSAIC_ROOT", mosaic_root):
                result = web.export_region("savinja", web_manifest_path=manifest_path)
            self.assertFalse(result["scenario_exported"])
            generated = json.loads(manifest_path.read_text(encoding="utf-8"))
            files = generated["tiles"][0]["files"]["connectivity"]
            self.assertTrue((web_data / files["required_stage"]).exists())
            self.assertTrue((web_data / files["reach_index"]).exists())
            self.assertEqual(files["scenarios"], {})

    def test_reach_index_round_trips_and_reserves_unavailable(self):
        values = np.array([[0, 42, -1]], dtype=np.int64)
        encoded = web.encode_uint24_index(values)
        decoded = (
            encoded[..., 0].astype(np.int64) * 65536
            + encoded[..., 1].astype(np.int64) * 256
            + encoded[..., 2].astype(np.int64)
        )
        np.testing.assert_array_equal(decoded, [[0, 42, 0xFFFFFF]])


if __name__ == "__main__":
    unittest.main()
