#!/usr/bin/env python3
"""Download versioned DRSV validation layers for the current study envelope."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCES_PATH = ROOT / "validation" / "sources.json"
MANIFEST_PATH = ROOT / "web" / "data" / "manifest.json"
REGION_CACHE_PATH = ROOT / ".tile_region_cache.json"
OUTPUT_DIR = ROOT / "validation" / "data"
PAGE_SIZE = 2000
USER_AGENT = "slovenia-lidar-floodmap-validation/1.0"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def study_envelope_3794(manifest):
    extents = [tile["bounds"]["epsg3794"] for tile in manifest["tiles"]]
    return {
        "xmin": min(float(e["x0"]) for e in extents),
        "ymin": min(float(e["y0"]) for e in extents),
        "xmax": max(float(e["x1"]) for e in extents),
        "ymax": max(float(e["y1"]) for e in extents),
        "spatialReference": {"wkid": 3794},
    }


def study_envelopes_by_region(manifest, region_cache):
    grouped = {}
    for tile in manifest["tiles"]:
        region = region_cache.get(tile["name"], "unknown")
        grouped.setdefault(region, []).append(tile["bounds"]["epsg3794"])
    envelopes = {}
    for region, extents in grouped.items():
        envelopes[region] = {
            "xmin": min(float(e["x0"]) for e in extents),
            "ymin": min(float(e["y0"]) for e in extents),
            "xmax": max(float(e["x1"]) for e in extents),
            "ymax": max(float(e["y1"]) for e in extents),
            "spatialReference": {"wkid": 3794},
        }
    return dict(sorted(envelopes.items()))


def request_json(url, params=None, retries=3):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Request failed after {retries} attempts: {url}") from last_error


def layer_metadata(layer):
    return request_json(layer["url"], {"f": "json"})


def query_layer(layer, envelope, page_size=PAGE_SIZE):
    query_url = layer["url"].rstrip("/") + "/query"
    features = []
    offset = 0
    while True:
        page = request_json(query_url, {
            "where": "1=1",
            "geometry": json.dumps(envelope, separators=(",", ":")),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "3794",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "3794",
            "resultOffset": str(offset),
            "resultRecordCount": str(page_size),
            "f": "geojson",
        })
        if "error" in page:
            raise RuntimeError(f"ArcGIS query error for {layer['id']}: {page['error']}")
        batch = page.get("features", [])
        features.extend(batch)
        if len(batch) < page_size:
            break
        offset += len(batch)
    return {"type": "FeatureCollection", "features": features}


def feature_identity(feature):
    if feature.get("id") is not None:
        return ("id", str(feature["id"]))
    properties = feature.get("properties") or {}
    for key in ("OBJECTID", "objectid", "ObjectId"):
        if properties.get(key) is not None:
            return (key, str(properties[key]))
    return ("content", hashlib.sha256(canonical_bytes(feature)).hexdigest())


def query_layer_envelopes(layer, envelopes, page_size=PAGE_SIZE):
    merged = {}
    counts = {}
    for region, envelope in envelopes.items():
        collection = query_layer(layer, envelope, page_size)
        counts[region] = len(collection["features"])
        for feature in collection["features"]:
            merged[feature_identity(feature)] = feature
    return {
        "type": "FeatureCollection",
        "features": list(merged.values()),
    }, counts


def canonical_bytes(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def write_layer(layer, metadata, collection, envelopes, regional_counts):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(collection)
    path = OUTPUT_DIR / f"{layer['id']}.geojson"
    path.write_bytes(payload)
    return {
        "id": layer["id"],
        "kind": layer["kind"],
        "source_url": layer["url"],
        "source_name": metadata.get("name"),
        "source_service_item_id": metadata.get("serviceItemId"),
        "source_last_edit_date": (metadata.get("editingInfo") or {}).get("lastEditDate"),
        "source_copyright": metadata.get("copyrightText"),
        "query_envelopes_epsg3794": envelopes,
        "regional_feature_counts_before_deduplication": regional_counts,
        "feature_count": len(collection["features"]),
        "output": str(path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", action="append", dest="layers",
                        help="Layer id from validation/sources.json; repeatable")
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE)
    args = parser.parse_args()

    sources = read_json(SOURCES_PATH)
    manifest = read_json(MANIFEST_PATH)
    region_cache = read_json(REGION_CACHE_PATH)
    envelopes = study_envelopes_by_region(manifest, region_cache)
    available = {layer["id"]: layer for layer in sources["layers"]}
    requested = args.layers or list(available)
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise SystemExit(f"Unknown layer id(s): {', '.join(unknown)}")

    records = []
    for layer_id in requested:
        layer = available[layer_id]
        print(f"Downloading {layer_id} ...", flush=True)
        metadata = layer_metadata(layer)
        collection, regional_counts = query_layer_envelopes(
            layer, envelopes, args.page_size)
        record = write_layer(layer, metadata, collection, envelopes, regional_counts)
        records.append(record)
        print(f"  {record['feature_count']} feature(s) -> {record['output']}")

    acquisition = {
        "schema_version": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "provider": sources["provider"],
        "license_from_sources_file": sources["license"],
        "study_manifest_generated": manifest.get("generated"),
        "study_model": (manifest.get("model") or {}).get("version"),
        "query_envelopes_epsg3794": envelopes,
        "layers": records,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_manifest = OUTPUT_DIR / "acquisition_manifest.json"
    if output_manifest.exists():
        try:
            previous = read_json(output_manifest)
            merged = {item["id"]: item for item in previous.get("layers", [])}
            merged.update({item["id"]: item for item in records})
            acquisition["layers"] = [merged[key] for key in sorted(merged)]
        except (OSError, ValueError, KeyError):
            pass
    output_manifest.write_text(json.dumps(acquisition, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output_manifest}")


if __name__ == "__main__":
    main()
