#!/usr/bin/env python3
"""Create and validate a conservative manual-review contract for Kamnik 2023.

The input Copernicus polygons are *candidates for review*, not automatic
positive training labels. A reviewer records only `flooded`, `not_flooded`, or
`uncertain`; every affirmative/negative decision needs a named evidence source.
Uncertain and pending cells must remain outside model fitting and scoring.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EVENT_DIR = ROOT / "validation" / "data" / "event_evidence"
CONTEXT_PATH = EVENT_DIR / "emsr680_kamnik_unreviewed_context.geojson"
QUEUE_PATH = EVENT_DIR / "kamnik_2023_review_queue.geojson"
SCHEMA_PATH = ROOT / "validation" / "review" / "kamnik_2023_label_schema.json"

ALLOWED_DECISIONS = {"flooded", "not_flooded", "uncertain"}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_id(feature):
    properties = feature.get("properties") or {}
    payload = {
        "source_product": properties.get("source_product"),
        "source_member": properties.get("source_member"),
        "source_feature_index": properties.get("source_feature_index"),
        "geometry": feature.get("geometry"),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"kamnik-2023-{digest[:16]}"


def review_priority(feature):
    properties = feature.get("properties") or {}
    # Flooded-area polygons are the clearest initial positives. Flood traces
    # remain queued but are intentionally lower priority for a first review.
    notation = str(properties.get("notation", "")).lower()
    return 1 if notation == "flooded area" else 2


def build_queue(context):
    features = []
    for feature in context.get("features", []):
        properties = feature.get("properties") or {}
        features.append({
            "type": "Feature",
            "geometry": feature.get("geometry"),
            "properties": {
                "review_id": canonical_id(feature),
                "review_status": "pending",
                "review_priority": review_priority(feature),
                "suggested_context": properties.get("notation"),
                "source_aoi": properties.get("source_aoi"),
                "source_product": properties.get("source_product"),
                "source_member": properties.get("source_member"),
                "source_feature_index": properties.get("source_feature_index"),
                "source_detection_method": properties.get("det_method"),
                "label_warning": "Copernicus context only; do not accept without independent imagery/context review.",
            },
        })
    features.sort(key=lambda item: (item["properties"]["review_priority"], item["properties"]["review_id"]))
    return {
        "type": "FeatureCollection",
        "name": "Kamnik/Kamniška Bistrica August-2023 manual review queue",
        "semantics": "pending-review-candidates-not-training-labels",
        "features": features,
    }


def validate_decision(decision):
    missing = [key for key in ("review_id", "decision", "reviewer", "reviewed_at") if not decision.get(key)]
    if "evidence" not in decision:
        missing.append("evidence")
    if missing:
        raise ValueError(f"Decision missing required field(s): {', '.join(missing)}")
    if decision["decision"] not in ALLOWED_DECISIONS:
        raise ValueError(f"Unsupported decision {decision['decision']!r}")
    if decision["decision"] in {"flooded", "not_flooded"} and not decision.get("evidence", {}).get("source"):
        raise ValueError("Flooded/not_flooded decisions require evidence.source")


def validate_decisions(decisions, queue_ids):
    seen = set()
    for decision in decisions:
        validate_decision(decision)
        review_id = decision["review_id"]
        if review_id not in queue_ids:
            raise ValueError(f"Decision references unknown review_id {review_id}")
        if review_id in seen:
            raise ValueError(f"Duplicate decision for {review_id}")
        seen.add(review_id)
    return {
        "decision_count": len(decisions),
        "flooded": sum(item["decision"] == "flooded" for item in decisions),
        "not_flooded": sum(item["decision"] == "not_flooded" for item in decisions),
        "uncertain": sum(item["decision"] == "uncertain" for item in decisions),
        "pending": len(queue_ids - seen),
    }


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("queue", "validate"))
    parser.add_argument("--decisions", type=Path,
                        help="Reviewer decision JSON matching validation/review/kamnik_2023_label_schema.json")
    args = parser.parse_args(argv)
    if not CONTEXT_PATH.exists():
        raise SystemExit(f"Missing {CONTEXT_PATH}; run extract_emsr680_observed_events.py first")
    queue = build_queue(read_json(CONTEXT_PATH))
    queue_ids = {feature["properties"]["review_id"] for feature in queue["features"]}
    if args.command == "queue":
        write_json(QUEUE_PATH, queue)
        print(json.dumps({
            "queue": str(QUEUE_PATH.relative_to(ROOT)).replace("\\", "/"),
            "candidate_count": len(queue_ids),
            "generated": datetime.now(timezone.utc).isoformat(),
            "semantics": queue["semantics"],
        }, indent=2))
        return
    if not args.decisions:
        parser.error("validate requires --decisions <path>")
    document = read_json(args.decisions)
    summary = validate_decisions(document.get("decisions", []), queue_ids)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
