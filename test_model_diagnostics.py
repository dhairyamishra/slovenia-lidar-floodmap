import tempfile
import unittest
from pathlib import Path

import numpy as np

import analyze_model
from model_diagnostics import write_stratified_sample


class StatisticsTests(unittest.TestCase):
    def test_average_ranks_handles_ties(self):
        actual = analyze_model.average_ranks(np.array([30.0, 10.0, 10.0, 20.0]))
        np.testing.assert_allclose(actual, [4.0, 1.5, 1.5, 3.0])

    def test_spearman_detects_inverse_order(self):
        self.assertAlmostEqual(
            analyze_model.spearman([1, 2, 3, 4], [8, 6, 4, 2]), -1.0
        )

    def test_weighted_composite_renormalizes_after_ablation(self):
        arrays = {
            "score": np.zeros(2),
            "norm_elev": np.array([0.0, 1.0]),
            "norm_twi": np.array([0.2, 0.8]),
        }
        weights = [
            {"factor": "elev", "weight": 0.25, "invert": True},
            {"factor": "twi", "weight": 0.75, "invert": False},
        ]
        np.testing.assert_allclose(
            analyze_model.weighted_composite(arrays, weights, excluded=["elev"]),
            [0.2, 0.8],
        )


class PipelineSampleTests(unittest.TestCase):
    def test_score_stratified_sample_contains_factor_contract(self):
        shape = (20, 20)
        base = np.arange(shape[0] * shape[1], dtype=np.float64).reshape(shape)
        raw_factors = {
            "twi": base / 20,
            "hand": base / 5,
            "elev": 250 + base / 10,
            "slope": base / 1000,
            "interc": base / 500,
            "ndvi": base / 2000,
            "curv": (base - 200) / 1000,
            "rough": base / 800,
        }
        normed = {name: np.clip(values / 100, 0, 1) for name, values in raw_factors.items()}
        score = np.linspace(0, 1, base.size).reshape(shape)

        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "test_001.npz"
            wrote = write_stratified_sample(
                artifact,
                tile="test_001", region="test-region", model_version="test-v1",
                rows=shape[0], cols=shape[1], x0=400000.0, y0=100000.0,
                grid_res=2.0, raw_factors=raw_factors,
                normalized_factors=normed, score=score, display_score=score,
                max_samples=2500,
            )
            self.assertTrue(wrote)
            self.assertTrue(artifact.exists())
            with np.load(artifact, allow_pickle=False) as sample:
                self.assertEqual(sample["model_version"].item(), "test-v1")
                self.assertEqual(sample["region"].item(), "test-region")
                self.assertEqual(sample["score"].size, base.size)
                for factor in raw_factors:
                    self.assertIn(f"raw_{factor}", sample.files)
                    self.assertIn(f"norm_{factor}", sample.files)


if __name__ == "__main__":
    unittest.main()
