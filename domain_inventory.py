#!/usr/bin/env python3
"""Inventory LiDAR tiles as connected analytical domains with explicit gaps."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WEB_MANIFEST = ROOT / "web" / "data" / "manifest.json"
REGION_CACHE = ROOT / ".tile_region_cache.json"
DEFAULT_OUTPUT = ROOT / "output" / "connectivity" / "domain_inventory.json"
INPUT_DIGESTS = ROOT / "output" / "connectivity" / "input_digests.json"


def tile_xy(name):
    return tuple(int(value) for value in name.split("_"))


def connected_components(names):
    remaining = {tile_xy(name) for name in names}
    components = []
    while remaining:
        seed = remaining.pop()
        component = {seed}
        stack = [seed]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.add(neighbor)
                    stack.append(neighbor)
        components.append(component)
    return sorted(components, key=lambda values: (-len(values), min(values)))


def component_name(component, regions):
    if all(regions.get(f"{x}_{y}") == "01-koper" for x, y in component):
        return "koper-coastal"
    if min(x for x, _ in component) >= 480:
        return "kamnik-event"
    return "central-validity"


def build_inventory(manifest, region_cache):
    names = [tile["name"] for tile in manifest["tiles"]]
    components = []
    for values in connected_components(names):
        xs = [x for x, _ in values]
        ys = [y for _, y in values]
        width = max(xs) - min(xs) + 1
        height = max(ys) - min(ys) + 1
        dense_positions = width * height
        region_counts = Counter(region_cache.get(f"{x}_{y}", "unknown") for x, y in values)
        tiles = sorted(f"{x}_{y}" for x, y in values)
        components.append({
            "id": component_name(values, region_cache),
            "tile_count": len(values),
            "tile_ids": tiles,
            "cdn_regions": dict(sorted(region_counts.items())),
            "bounds_epsg3794": [
                min(xs) * 1000, min(ys) * 1000,
                (max(xs) + 1) * 1000, (max(ys) + 1) * 1000,
            ],
            "tile_envelope_width_km": width,
            "tile_envelope_height_km": height,
            "dense_envelope_tile_positions": dense_positions,
            "lidar_coverage_fraction_of_envelope": round(len(values) / dense_positions, 6),
            "complete_rectangle": len(values) == dense_positions,
            "dense_cells": {"2m": width * 500 * height * 500, "10m": width * 100 * height * 100},
            "open_boundary_policy": "explicit-edge-contamination",
            "missing_tile_policy": "no-data-never-nearest-neighbour-filled",
        })
    payload = {
        "schema_version": 1,
        "semantics": "analytical-domain-inventory-not-flood-extent",
        "tile_count": len(names),
        "components": components,
    }
    digest_payload = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["inventory_digest"] = hashlib.sha256(digest_payload).hexdigest()
    return payload


def main(output=DEFAULT_OUTPUT):
    manifest = json.loads(WEB_MANIFEST.read_text(encoding="utf-8"))
    cache = json.loads(REGION_CACHE.read_text(encoding="utf-8"))
    inventory = build_inventory(manifest, cache)
    if INPUT_DIGESTS.exists():
        digests = json.loads(INPUT_DIGESTS.read_text(encoding="utf-8"))
        inventory["input_digests"] = {
            "algorithm": digests["algorithm"],
            "dataset_sha256": digests["dataset_sha256"],
            "file_count": len(digests["files"]),
        }
    else:
        inventory["input_digests"] = {"status": "not-yet-generated"}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print(f"Wrote {output}")
    for component in inventory["components"]:
        print(component["id"], component["tile_count"], component["bounds_epsg3794"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    main(args.output)
