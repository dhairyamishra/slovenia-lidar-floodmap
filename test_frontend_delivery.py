import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class FrontendDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web/app.js").read_text(encoding="utf-8")
        cls.html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "web/style.css").read_text(encoding="utf-8")

    def test_official_geojson_is_registered_on_demand(self):
        self.assertIn("function ensureScenario(key)", self.app)
        self.assertIn("function ensureValidity()", self.app)
        self.assertIn("function ensureDepth(key)", self.app)
        self.assertIn("if (active) validationState.ensureScenario(key)", self.app)

    def test_aerial_basemap_is_off_by_default_and_slovenia_bounded(self):
        self.assertIn("SI.GURS.ZPDZ%3ADOF025", self.app)
        self.assertIn("BBOX={bbox-epsg-3857}", self.app)
        self.assertIn("FORMAT=image%2Fpng8&TRANSPARENT=true", self.app)
        self.assertIn("layout: { visibility: 'none' }", self.app)
        self.assertIn("bounds: [13.3400608, 44.9641309, 17.2035352, 46.8958681]", self.app)
        self.assertIn('name="basemap" value="aerial"', self.html)
        self.assertIn("Ortofoto Â© GURS (CC BY 4.0)", self.app)

    def test_desktop_keeps_complete_overlays_while_mobile_is_bounded(self):
        self.assertIn("function syncTileLayerSet", self.app)
        self.assertIn("if (!MOBILE_LAYOUT.matches) return tiles", self.app)
        self.assertIn("const MOBILE_TILE_LIMIT = 12", self.app)
        self.assertIn("function tilesForMobileViewport", self.app)
        self.assertIn("function tileIntersectsBounds", self.app)
        self.assertIn(".slice(0, MOBILE_TILE_LIMIT)", self.app)
        self.assertIn("map.on('moveend'", self.app)

    def test_mobile_low_memory_mode_releases_and_bounds_heavy_data(self):
        self.assertIn("const MOBILE_INDEX_CACHE_LIMIT = 3", self.app)
        self.assertIn("function cacheCanvasPromise", self.app)
        self.assertIn("validationState.removeScenario(key)", self.app)
        self.assertIn("validationState.removeValidity()", self.app)
        self.assertIn("validationState.removeDepth(key)", self.app)
        self.assertIn("const MOBILE_HEAVY_TOGGLE_IDS", self.app)
        self.assertIn("mapOptions.maxTileCacheSize = 24", self.app)
        self.assertIn("mapOptions.pixelRatio", self.app)
        self.assertIn("Mobile low-memory mode", self.html)

    def test_guided_views_and_mobile_panel_are_accessible(self):
        for preset in ("ljubljana", "savinja", "koper"):
            self.assertIn(f'data-region-preset="{preset}"', self.html)
        self.assertIn('aria-controls="panel"', self.html)
        self.assertIn("function wireGuidedViews", self.app)

    def test_mobile_panel_is_an_accessible_touch_bottom_sheet(self):
        self.assertIn("viewport-fit=cover", self.html)
        self.assertIn('id="panel-backdrop"', self.html)
        self.assertIn('id="panel-close"', self.html)
        self.assertIn("panel.inert = mobile && !open", self.app)
        self.assertIn("panel.setAttribute('aria-modal', 'true')", self.app)
        self.assertIn("event.key === 'Escape'", self.app)
        self.assertIn("(max-width: 768px), (hover: none) and (pointer: coarse)", self.css)
        self.assertIn("max-height: min(82dvh, 720px)", self.css)
        self.assertIn("env(safe-area-inset-bottom)", self.css)
        self.assertIn("min-height: 44px", self.css)

    def test_desktop_panel_geometry_remains_unchanged(self):
        desktop_panel = self.css.split(".panel {", 1)[1].split("}", 1)[0]
        self.assertIn("top: 58px", desktop_panel)
        self.assertIn("left: 12px", desktop_panel)
        self.assertIn("width: 304px", desktop_panel)
        self.assertIn("max-height: calc(100vh - 70px)", desktop_panel)
        memory_rule = self.css.split(".mobile-memory-note {", 1)[1].split("}", 1)[0]
        self.assertIn("display: none", memory_rule)

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

    def test_marker_hover_does_not_transform_maplibre_anchor(self):
        self.assertIn("anchor.className = 'risk-marker-anchor'", self.app)
        self.assertIn("const el = document.createElement('button')", self.app)
        self.assertIn("new maplibregl.Marker({ element: anchor", self.app)
        self.assertIn("event.stopPropagation()", self.app)
        self.assertIn(".risk-marker:hover", self.css)
        self.assertIn("transform: scale(1.18)", self.css)
        anchor_rule = self.css.split(".risk-marker-anchor {", 1)[1].split("}", 1)[0]
        self.assertNotIn("transform", anchor_rule)

    def test_review_point_artifact_is_cache_versioned(self):
        self.assertIn("risk_points.geojson?v=2", self.app)


if __name__ == "__main__":
    unittest.main()
