#!/usr/bin/env python3
"""Extract and spatially catalogue unreviewed flood polygons from EMSR680.

The output is deliberately named *unreviewed context*: Copernicus rapid
mapping is valuable independent evidence, but it is not a complete observed
flood footprint. It must not be used to fit/select a model until Phase-B image
review adds confirmed, negative, and uncertain labels.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import box, shape


ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "validation" / "data" / "event_evidence" / "emsr680_products.zip"
OUTPUT_DIR = ROOT / "validation" / "data" / "event_evidence"
KAMNIK_BOUNDS_3794 = (486000.0, 132000.0, 491000.0, 137000.0)


def sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def kamnik_bounds_wgs84():
    transformer = Transformer.from_crs("EPSG:3794", "EPSG:4326", always_xy=True)
    west, south, east, north = transformer.transform_bounds(*KAMNIK_BOUNDS_3794)
    return box(west, south, east, north)


def source_aoi(name):
    parts = name.split("_")
    return next((part for part in parts if part.startswith("AOI")), "unknown")


def observed_event_members(archive):
    """Yield one GeoJSON collection per unique inner product/member."""
    seen = set()
    with zipfile.ZipFile(archive) as outer:
        for product_name in outer.namelist():
            if product_name in seen or not product_name.lower().endswith(".zip"):
                continue
            seen.add(product_name)
            with zipfile.ZipFile(io.BytesIO(outer.read(product_name))) as product:
                for member in product.namelist():
                    if "observedEvent" not in member or not member.lower().endswith(".json"):
                        continue
                    payload = json.loads(product.read(member).decode("utf-8-sig"))
                    yield product_name, member, payload


def flood_features(collection, product_name, member_name):
    for number, feature in enumerate(collection.get("features", [])):
        properties = feature.get("properties") or {}
        if "flood" not in str(properties.get("event_type", "")).lower():
            continue
        geometry = feature.get("geometry")
        if not geometry:
            continue
        yield {
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "label_status": "unreviewed_external_context",
                "source_event": "EMSR680 Flood in Slovenia (2023-08-04)",
                "source_product": product_name,
                "source_member": member_name,
                "source_aoi": source_aoi(product_name),
                "source_feature_index": number,
                **properties,
            },
        }


def catalogue_features(archive):
    all_features = []
    products = []
    for product_name, member_name, collection in observed_event_members(archive):
        features = list(flood_features(collection, product_name, member_name))
        if not features:
            continue
        products.append({
            "product": product_name,
            "member": member_name,
            "aoi": source_aoi(product_name),
            "flood_feature_count": len(features),
        })
        all_features.extend(features)
    return all_features, products


def intersecting_features(features, bounds):
    return [feature for feature in features if shape(feature["geometry"]).intersects(bounds)]


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(path)}


def main():
    if not ARCHIVE.exists():
        raise SystemExit(f"Missing {ARCHIVE}; run prepare_event_evidence.py --source emsr680_products --download first")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_features, products = catalogue_features(ARCHIVE)
    bounds = kamnik_bounds_wgs84()
    kamnik_features = intersecting_features(all_features, bounds)
    all_output = OUTPUT_DIR / "emsr680_unreviewed_observed_events.geojson"
    kamnik_output = OUTPUT_DIR / "emsr680_kamnik_unreviewed_context.geojson"
    outputs = {
        "all_observed_event_features": write_json(all_output, {
            "type": "FeatureCollection", "features": all_features,
        }),
        "kamnik_intersecting_context": write_json(kamnik_output, {
            "type": "FeatureCollection", "features": kamnik_features,
        }),
    }
    catalogue = {
        "schema_version": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "semantics": "unreviewed-copernicus-rapid-mapping-context-not-final-observed-flood-label",
        "source_archive": {
            "path": str(ARCHIVE.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(ARCHIVE),
        },
        "source_crs": "OGC:CRS84 / longitude-latitude",
        "review_bounds": {
            "name": "current-5x5-kamnik-kamniska-bistrica-lidar-mosaic",
            "epsg3794": KAMNIK_BOUNDS_3794,
            "wgs84_bounds": list(bounds.bounds),
        },
        "product_count": len(products),
        "products": products,
        "all_flood_feature_count": len(all_features),
        "kamnik_intersecting_feature_count": len(kamnik_features),
        "outputs": outputs,
        "limitations": [
            "rapid-mapping-may-miss-transient-or-obscured-water",
            "no-unobserved-area-is-labelled-dry",
            "post-event-orthophoto-review-required-before-model-fitting",
            "not-a-live-forecast-or-inundation-depth-product",
        ],
    }
    catalogue_path = OUTPUT_DIR / "emsr680_observed_event_catalogue.json"
    write_json(catalogue_path, catalogue)
    print(json.dumps({
        "products": len(products),
        "all_flood_features": len(all_features),
        "kamnik_intersecting_features": len(kamnik_features),
        "catalogue": str(catalogue_path.relative_to(ROOT)).replace("\\", "/"),
    }, indent=2))


if __name__ == "__main__":
    main()
