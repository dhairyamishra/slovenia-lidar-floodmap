import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class ConnectivityFrontendTests(unittest.TestCase):
    def test_specialist_connectivity_controls_are_hidden_from_public_sidebar(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        for control in (
            "toggle-required-stage", "opacity-required-stage",
            "toggle-scenario-depth", "connectivity-scenario",
        ):
            self.assertNotIn(f'id="{control}"', html)

    def test_app_registers_only_manifest_backed_connectivity_assets(self):
        app = (ROOT / "web/app.js").read_text(encoding="utf-8")
        self.assertIn("manifest.connectivity_model", app)
        self.assertIn("tile.files.connectivity?.required_stage", app)
        self.assertIn("function decodePhysicalIndex", app)
        self.assertIn("Minimum stage rise:", app)
        self.assertIn("not proof of safety", app)

    def test_mobile_connectivity_releases_offscreen_images(self):
        app = (ROOT / "web/app.js").read_text(encoding="utf-8")
        self.assertIn("if (MOBILE_LAYOUT.matches)", app)
        self.assertIn("tilesForMobileViewport(map, availableTiles)", app)
        self.assertIn("removeImageLayer(map, requiredLayer, requiredSource)", app)
        self.assertIn("registerMobileLayerRefresher(map, update)", app)


if __name__ == "__main__":
    unittest.main()
