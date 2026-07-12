#!/usr/bin/env python3
"""Build compact WGS84 official hazard reference layers for the static app."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union


ROOT = Path(__file__).resolve().parent
VALIDATION_DIR = ROOT / "validation" / "data"
WEB_DIR = ROOT / "web" / "data" / "validation"
SCENARIOS = {
    "q10": "ikpn_q10.geojson",
    "q100": "ikpn_q100.geojson",
    "q500": "ikpn_q500.geojson",
}
SIMPLIFY_M = 2.0


def load_geometries(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return [shape(f["geometry"]) for f in data.get("features", []) if f.get("geometry")]


def main():
    transformer = Transformer.from_crs("EPSG:3794", "EPSG:4326", always_xy=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for scenario, filename in SCENARIOS.items():
        source = VALIDATION_DIR / filename
        if not source.exists():
            raise SystemExit(f"Missing {source}; run download_validation.py first")
        geometries = load_geometries(source)
        dissolved = unary_union(geometries).simplify(SIMPLIFY_M, preserve_topology=True)
        wgs84 = transform(transformer.transform, dissolved)
        collection = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": mapping(wgs84),
                "properties": {
                    "scenario": scenario.upper(),
                    "source": "DRSV IKPN",
                    "semantics": "official-static-hazard-reference",
                },
            }],
        }
        payload = json.dumps(collection, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        output = WEB_DIR / f"ikpn_{scenario}.geojson"
        output.write_bytes(payload)
        entries.append({
            "scenario": scenario,
            "label": scenario.upper(),
            "file": output.name,
            "source_feature_count": len(geometries),
            "simplify_m": SIMPLIFY_M,
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
        print(f"Wrote {output} ({len(payload):,} bytes)")

    manifest = {
        "schema_version": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": "Direkcija Republike Slovenije za vode (DRSV), IKPN",
        "source_crs": "EPSG:3794",
        "web_crs": "EPSG:4326",
        "semantics": "official static hazard reference; not observed August 2023 extent",
        "scenarios": entries,
    }
    path = WEB_DIR / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
