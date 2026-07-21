import unittest

from prepare_pages_site import public_manifest


class PagesArtifactTests(unittest.TestCase):
    def test_public_manifest_omits_only_heavy_nonessential_rasters(self):
        manifest = {
            "tiles": [{
                "name": "460_100",
                "files": {
                    "ndvi": "tiles/460_100/ndvi.png",
                    "susceptibility": "tiles/460_100/susceptibility.png",
                    "d19_diagnostic": "tiles/460_100/susceptibility.png",
                    "d19_review": "tiles/460_100/susceptibility_d19_review.png",
                    "classification": "tiles/460_100/classification.png",
                },
            }],
        }
        result = public_manifest(manifest)
        self.assertEqual(
            set(result["tiles"][0]["files"]),
            {"d19_review", "classification"},
        )
        self.assertEqual(
            result["deployment_profile"]["omitted_layers"],
            ["d19_diagnostic", "ndvi"],
        )


if __name__ == "__main__":
    unittest.main()
