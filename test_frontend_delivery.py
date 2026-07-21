import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class FrontendDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web/app.js").read_text(encoding="utf-8")
        cls.html = (ROOT / "web/index.html").read_text(encoding="utf-8")

    def test_official_geojson_is_registered_on_demand(self):
        self.assertIn("function ensureScenario(key)", self.app)
        self.assertIn("function ensureValidity()", self.app)
        self.assertIn("function ensureDepth(key)", self.app)
        self.assertIn("if (active) validationState.ensureScenario(key)", self.app)

    def test_large_rasters_have_explicit_viewport_caps(self):
        for contract in (
            "d19_diagnostic: 16",
            "q100_comparison: 48",
            "ndvi: 16",
            "classification: 32",
        ):
            self.assertIn(contract, self.app)
        self.assertIn("map.on('moveend', update)", self.app)

    def test_guided_views_and_mobile_panel_are_accessible(self):
        for preset in ("ljubljana", "savinja", "koper"):
            self.assertIn(f'data-region-preset="{preset}"', self.html)
        self.assertIn('aria-controls="panel"', self.html)
        self.assertIn("function wireGuidedViews", self.app)

    def test_context_controls_have_accessible_names(self):
        for label in (
            "LiDAR-derived vegetation greenness",
            "Land Classification",
            "Connected Coastal Low-Land Exposure",
            "Experimental D19 Review Points",
        ):
            self.assertIn(f'aria-label="{label}"', self.html)
        for slider in (
            "opacity-susc", "opacity-required-stage", "opacity-official",
            "opacity-ndvi", "opacity-cls", "opacity-coastal",
        ):
            self.assertIn(f'for="{slider}"', self.html)


if __name__ == "__main__":
    unittest.main()
