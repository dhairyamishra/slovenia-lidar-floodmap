import unittest
import tempfile
from pathlib import Path

import numpy as np

import connectivity_flood as flood


def scenario(stage):
    return {
        "schema_version": 1,
        "id": f"test-stage-{stage}",
        "source": {"kind": "synthetic-unit-test"},
        "publication_status": "research-only",
        "forcing": {"type": "uniform_stage_above_channel", "value_m": stage},
    }


class ConnectivityAccessTests(unittest.TestCase):
    def test_equally_flat_cells_differ_when_only_one_basin_has_a_stream(self):
        dtm = np.ones((3, 6), dtype=float) * 10.0
        streams = np.zeros_like(dtm, dtype=bool)
        streams[1, 0] = True
        basin = np.zeros_like(dtm, dtype=np.int64)
        basin[:, 3:] = 1
        result = flood.compute_access_stage(dtm, streams, basin_id=basin)
        self.assertTrue(result["connected"][1, 2])
        self.assertFalse(result["connected"][1, 4])
        self.assertTrue(np.isnan(result["required_stage_m"][1, 4]))

    def test_depression_requires_its_spill_height(self):
        dtm = np.array([[5, 5, 5, 5, 5], [1, 4, 2, 2, 5], [5, 5, 5, 5, 5]], dtype=float)
        streams = np.zeros_like(dtm, dtype=bool)
        streams[1, 0] = True
        result = flood.compute_access_stage(dtm, streams)
        self.assertEqual(result["access_elevation_m"][1, 2], 4.0)
        self.assertEqual(result["required_stage_m"][1, 2], 3.0)
        low = flood.scenario_inundation(dtm, result, scenario(2.9))
        high = flood.scenario_inundation(dtm, result, scenario(3.1))
        self.assertFalse(low["inundated_candidate"][1, 2])
        self.assertTrue(high["inundated_candidate"][1, 2])

    def test_barrier_blocks_until_overtopped_and_vetted_culvert_reopens(self):
        dtm = np.ones((3, 5), dtype=float) * 10.0
        streams = np.zeros_like(dtm, dtype=bool)
        streams[1, 0] = True
        crest = np.full_like(dtm, np.nan)
        crest[:, 2] = 13.0
        blocked = flood.compute_access_stage(dtm, streams, barrier_crest_m=crest)
        self.assertEqual(blocked["required_stage_m"][1, 4], 3.0)
        culvert = np.zeros_like(dtm, dtype=bool)
        culvert[1, 2] = True
        opened = flood.compute_access_stage(
            dtm, streams, barrier_crest_m=crest, culvert_mask=culvert
        )
        self.assertEqual(opened["required_stage_m"][1, 4], 0.0)

    def test_original_terrain_controls_reported_depth(self):
        dtm = np.array([[10.0, 9.0, 8.0]])
        streams = np.array([[True, False, False]])
        access = flood.compute_access_stage(dtm, streams)
        result = flood.scenario_inundation(dtm, access, scenario(2.0))
        self.assertAlmostEqual(float(result["depth_m"][0, 2]), 4.0)

    def test_discharge_uses_explicit_monotonic_rating_curve(self):
        dtm = np.array([[10.0, 9.0, 8.0]])
        streams = np.array([[True, False, False]])
        access = flood.compute_access_stage(dtm, streams)
        discharge = {
            "schema_version": 1,
            "id": "rated-flow",
            "source": {"kind": "unit-test-rating-curve"},
            "publication_status": "research-only",
            "forcing": {
                "type": "reach_discharge",
                "values_m3s": {"0": 50.0},
                "rating_curves": {"0": {
                    "discharge_m3s": [0.0, 100.0],
                    "stage_above_channel_m": [0.0, 2.0],
                }},
            },
        }
        result = flood.scenario_inundation(dtm, access, discharge)
        self.assertAlmostEqual(float(result["water_surface_elevation_m"][0, 2]), 11.0)
        self.assertAlmostEqual(float(result["depth_m"][0, 2]), 3.0)

    def test_reach_forcing_applies_to_all_sources_in_the_same_reach(self):
        dtm = np.array([[10.0, 9.0, 8.0]])
        streams = np.array([[True, False, False]])
        reach = np.array([[42, -1, -1]])
        access = flood.compute_access_stage(dtm, streams, stream_reach_id=reach)
        stage = {
            "schema_version": 1,
            "id": "reach-stage",
            "source": {"kind": "unit-test-gauge"},
            "publication_status": "research-only",
            "forcing": {"type": "reach_stage_above_channel", "values": {"42": 2.0}},
        }
        result = flood.scenario_inundation(dtm, access, stage)
        self.assertEqual(int(access["reach_id"][0, 2]), 42)
        self.assertAlmostEqual(float(result["depth_m"][0, 2]), 4.0)

    def test_edge_and_unknown_barrier_paths_are_not_definitive(self):
        dtm = np.ones((1, 4), dtype=float) * 10
        streams = np.array([[True, False, False, False]])
        edge = np.array([[True, False, False, False]])
        uncertain = np.array([[False, False, True, False]])
        access = flood.compute_access_stage(
            dtm, streams, edge_mask=edge, barrier_uncertainty_mask=uncertain
        )
        result = flood.scenario_inundation(dtm, access, scenario(1.0))
        self.assertEqual(result["scenario_class"][0, 1], flood.CLASS_EDGE_CONTAMINATED)
        # Edge contamination has stronger precedence than barrier uncertainty.
        self.assertEqual(result["scenario_class"][0, 3], flood.CLASS_EDGE_CONTAMINATED)

    def test_scientific_publication_gate_cannot_be_bypassed(self):
        approved = scenario(1.0)
        approved["publication_status"] = "approved-observed-hindcast"
        approved["scientific_gate"] = {
            "roc_auc_gain": 0.01,
            "average_precision_gain": 0.10,
            "iou_gain": 0.10,
            "low_flat_reduction": 0.50,
            "recall_change": 0.0,
            "bias_ratio": 1.0,
            "counterfactual_passed": True,
        }
        with self.assertRaisesRegex(ValueError, "does not pass"):
            flood.validate_scenario(approved)

    def test_chunked_zarr_store_preserves_arrays_and_provenance(self):
        import zarr
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.zarr"
            flood.write_zarr_store(
                path,
                {"required_stage_m": np.arange(20, dtype=np.float32).reshape(4, 5)},
                {"model_version": flood.MODEL_VERSION, "input_sha256": "abc"},
                chunk_shape=(2, 3),
            )
            root = zarr.open_group(str(path), mode="r")
            np.testing.assert_array_equal(
                root["required_stage_m"][:], np.arange(20).reshape(4, 5)
            )
            self.assertEqual(root.attrs["input_sha256"], "abc")


if __name__ == "__main__":
    unittest.main()
