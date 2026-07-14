import unittest

import extract_emsr680_observed_events as emsr


class EmsrExtractionTests(unittest.TestCase):
    def test_source_aoi_is_extracted_from_product_name(self):
        self.assertEqual(emsr.source_aoi("EMSR680_AOI03_DEL_PRODUCT_v1.zip"), "AOI03")

    def test_only_flood_event_features_are_preserved(self):
        collection = {"features": [
            {"geometry": {"type": "Point", "coordinates": [14.9, 46.3]},
             "properties": {"event_type": "5-Flood"}},
            {"geometry": {"type": "Point", "coordinates": [14.9, 46.3]},
             "properties": {"event_type": "Landslide"}},
        ]}
        actual = list(emsr.flood_features(collection, "EMSR680_AOI03_DEL_PRODUCT_v1.zip", "x.json"))
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0]["properties"]["label_status"], "unreviewed_external_context")
        self.assertEqual(actual[0]["properties"]["source_aoi"], "AOI03")

    def test_intersection_keeps_only_features_inside_bounds(self):
        bounds = emsr.kamnik_bounds_wgs84()
        inside = {"geometry": {"type": "Point", "coordinates": [bounds.centroid.x, bounds.centroid.y]}}
        outside = {"geometry": {"type": "Point", "coordinates": [10.0, 45.0]}}
        self.assertEqual(emsr.intersecting_features([inside, outside], bounds), [inside])


if __name__ == "__main__":
    unittest.main()
