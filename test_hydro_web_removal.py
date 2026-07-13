import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class HydroVisualizationRemovalTests(unittest.TestCase):
    def test_public_app_has_no_hydro_controls_or_layer_wiring(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        for token in (
            "toggle-hydro",
            "toggle-hydro-risk",
            "hydro-date",
            "layer-hydro-trigger",
            "data/hydroclimate/manifest.json",
            "Terrain Candidates Under Trigger",
        ):
            self.assertNotIn(token, html + js)

    def test_hydro_calculation_pipeline_and_assets_are_retained(self):
        self.assertTrue((ROOT / "hydroclimate.py").exists())
        self.assertTrue((ROOT / "web" / "data" / "hydroclimate" / "manifest.json").exists())
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Retained hydroclimate calculations", readme)
        self.assertIn("python hydroclimate.py derive-fixture", readme)


if __name__ == "__main__":
    unittest.main()
