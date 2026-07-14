import unittest

import observed_event_labels as labels


class ObservedEventLabelTests(unittest.TestCase):
    def test_queue_ids_are_stable_and_flood_area_is_prioritized(self):
        feature = {
            "geometry": {"type": "Point", "coordinates": [14.85, 46.35]},
            "properties": {
                "source_product": "AOI07.zip", "source_member": "event.json",
                "source_feature_index": 3, "notation": "Flooded area",
            },
        }
        queue = labels.build_queue({"features": [feature]})
        item = queue["features"][0]["properties"]
        self.assertEqual(item["review_priority"], 1)
        self.assertEqual(item["review_id"], labels.canonical_id(feature))

    def test_confirmed_decisions_require_evidence_source(self):
        decision = {
            "review_id": "a", "decision": "flooded", "reviewer": "r",
            "reviewed_at": "2026-07-13T00:00:00Z", "evidence": {},
        }
        with self.assertRaisesRegex(ValueError, "evidence.source"):
            labels.validate_decision(decision)

    def test_uncertain_decision_is_valid_but_not_a_training_label(self):
        decision = {
            "review_id": "a", "decision": "uncertain", "reviewer": "r",
            "reviewed_at": "2026-07-13T00:00:00Z", "evidence": {"source": "RGB"},
        }
        result = labels.validate_decisions([decision], {"a", "b"})
        self.assertEqual(result, {"decision_count": 1, "flooded": 0, "not_flooded": 0, "uncertain": 1, "pending": 1})


if __name__ == "__main__":
    unittest.main()
