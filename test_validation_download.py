import unittest

import download_validation


class ValidationEnvelopeTests(unittest.TestCase):
    def test_envelopes_are_grouped_by_region_not_disjoint_union(self):
        manifest = {
            "tiles": [
                {"name": "a", "bounds": {"epsg3794": {"x0": 0, "y0": 10, "x1": 5, "y1": 15}}},
                {"name": "b", "bounds": {"epsg3794": {"x0": 5, "y0": 8, "x1": 9, "y1": 17}}},
                {"name": "c", "bounds": {"epsg3794": {"x0": 100, "y0": 200, "x1": 110, "y1": 210}}},
            ]
        }
        regions = {"a": "west", "b": "west", "c": "east"}
        actual = download_validation.study_envelopes_by_region(manifest, regions)
        self.assertEqual(actual["west"]["xmin"], 0)
        self.assertEqual(actual["west"]["ymin"], 8)
        self.assertEqual(actual["west"]["xmax"], 9)
        self.assertEqual(actual["west"]["ymax"], 17)
        self.assertEqual(actual["east"]["xmin"], 100)
        self.assertEqual(actual["east"]["xmax"], 110)

    def test_feature_identity_prefers_arcgis_feature_id(self):
        feature = {"id": 42, "properties": {"OBJECTID": 99}}
        self.assertEqual(download_validation.feature_identity(feature), ("id", "42"))

    def test_duplicate_features_are_identified_across_region_queries(self):
        feature_a = {"id": 7, "properties": {"name": "same"}}
        feature_b = {"id": 7, "properties": {"name": "same"}}
        merged = {
            download_validation.feature_identity(feature_a): feature_a,
            download_validation.feature_identity(feature_b): feature_b,
        }
        self.assertEqual(len(merged), 1)

    def test_large_envelope_is_split_into_bounded_query_cells(self):
        envelope = {
            "xmin": 0, "ymin": 0, "xmax": 12000, "ymax": 7000,
            "spatialReference": {"wkid": 3794},
        }
        cells = list(download_validation.subdivide_envelope(envelope, 5000))
        self.assertEqual(len(cells), 6)
        self.assertEqual(cells[0]["xmax"], 5000)
        self.assertEqual(cells[-1]["xmin"], 10000)
        self.assertEqual(cells[-1]["xmax"], 12000)
        self.assertEqual(cells[-1]["ymax"], 7000)
        self.assertTrue(all(cell["xmax"] - cell["xmin"] <= 5000 for cell in cells))
        self.assertTrue(all(cell["ymax"] - cell["ymin"] <= 5000 for cell in cells))


if __name__ == "__main__":
    unittest.main()
