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
ANCILLARY_LAYERS = {
    "validity": {
        "filename": "ikpn_validity.geojson",
        "kind": "official_hydraulic_study_validity",
        "label": "DRSV study validity",
    },
    "depth_lt_0_5m": {
        "filename": "ikg_q100_depth_lt_0_5m.geojson",
        "kind": "official_q100_depth_class",
        "label": "Q100 depth < 0.5 m",
        "depth_class": "<0.5 m",
    },
    "depth_0_5_to_1_5m": {
        "filename": "ikg_q100_depth_0_5_to_1_5m.geojson",
        "kind": "official_q100_depth_class",
        "label": "Q100 depth 0.5–1.5 m",
        "depth_class": "0.5–1.5 m",
    },
    "depth_ge_1_5m": {
        "filename": "ikg_q100_depth_ge_1_5m.geojson",
        "kind": "official_q100_depth_class",
        "label": "Q100 depth ≥ 1.5 m",
        "depth_class": "≥1.5 m",
    },
}
SIMPLIFY_M = 2.0


def load_geometries(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return [shape(f["geometry"]) for f in data.get("features", []) if f.get("geometry")]


def build_web_layer(source, output, transformer, properties):
    """Dissolve, simplify, transform, and write one compact web layer."""
    geometries = load_geometries(source)
    dissolved = unary_union(geometries).simplify(SIMPLIFY_M, preserve_topology=True)
    wgs84 = transform(transformer.transform, dissolved)
    collection = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": mapping(wgs84),
            "properties": properties,
        }],
    }
    payload = json.dumps(collection, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    output.write_bytes(payload)
    print(f"Wrote {output} ({len(payload):,} bytes)")
    return len(geometries), payload


def main():
    transformer = Transformer.from_crs("EPSG:3794", "EPSG:4326", always_xy=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for scenario, filename in SCENARIOS.items():
        source = VALIDATION_DIR / filename
        if not source.exists():
            raise SystemExit(f"Missing {source}; run download_validation.py first")
        output = WEB_DIR / f"ikpn_{scenario}.geojson"
        count, payload = build_web_layer(source, output, transformer, {
            "scenario": scenario.upper(),
            "source": "DRSV IKPN",
            "semantics": "official-static-hazard-reference",
        })
        entries.append({
            "scenario": scenario,
            "label": scenario.upper(),
            "file": output.name,
            "source_feature_count": count,
            "simplify_m": SIMPLIFY_M,
            "sha256": hashlib.sha256(payload).hexdigest(),
        })

    ancillary = {}
    for key, spec in ANCILLARY_LAYERS.items():
        source = VALIDATION_DIR / spec["filename"]
        if not source.exists():
            raise SystemExit(f"Missing {source}; run download_validation.py first")
        output = WEB_DIR / spec["filename"]
        properties = {
            "source": "DRSV",
            "semantics": spec["kind"],
            "label": spec["label"],
        }
        if "depth_class" in spec:
            properties["depth_class"] = spec["depth_class"]
        count, payload = build_web_layer(source, output, transformer, properties)
        ancillary[key] = {
            "kind": spec["kind"],
            "label": spec["label"],
            "file": output.name,
            "source_feature_count": count,
            "simplify_m": SIMPLIFY_M,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    manifest = {
        "schema_version": 2,
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": "Direkcija Republike Slovenije za vode (DRSV), IKPN",
        "source_crs": "EPSG:3794",
        "web_crs": "EPSG:4326",
        "semantics": "official static hazard reference; not observed August 2023 extent",
        "scenarios": entries,
        "layers": ancillary,
    }
    path = WEB_DIR / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
