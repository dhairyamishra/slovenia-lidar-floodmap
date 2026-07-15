import json
import unittest
from pathlib import Path

import domain_inventory


ROOT = Path(__file__).resolve().parent


class DomainInventoryTests(unittest.TestCase):
    def test_current_inventory_has_three_explicit_components(self):
        manifest = json.loads((ROOT / "web/data/manifest.json").read_text(encoding="utf-8"))
        regions = json.loads((ROOT / ".tile_region_cache.json").read_text(encoding="utf-8"))
        inventory = domain_inventory.build_inventory(manifest, regions)
        self.assertEqual(inventory["tile_count"], 391)
        counts = {component["id"]: component["tile_count"] for component in inventory["components"]}
        self.assertEqual(counts, {
            "central-validity": 345,
            "kamnik-event": 25,
            "koper-coastal": 21,
        })
        central = next(item for item in inventory["components"] if item["id"] == "central-validity")
        self.assertFalse(central["complete_rectangle"])
        self.assertEqual(central["missing_tile_policy"], "no-data-never-nearest-neighbour-filled")

    def test_components_use_edge_adjacency_not_envelope_membership(self):
        values = domain_inventory.connected_components(["1_1", "2_1", "4_1", "4_2"])
        self.assertEqual([len(value) for value in values], [2, 2])


if __name__ == "__main__":
    unittest.main()
