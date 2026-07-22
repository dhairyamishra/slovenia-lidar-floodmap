#!/usr/bin/env python3
"""Build categorical D19-vs-official-Q100 comparison tiles and summaries.

Official geometries are rasterized independently for every current web tile at
2 m. This deliberately does not reuse or expand the frozen model-evaluation
rasters: public map coverage may grow while the locked evaluation contract stays
unchanged. D19 is the frozen 0.925 review-display mask, not a fitted hazard
threshold. Outside official validity is unavailable rather than negative.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from shapely import from_geojson, union_all

from validation_grid import file_sha256, grid_definition, rasterize_geometry


ROOT = Path(__file__).resolve().parent
WEB_MANIFEST = ROOT / "web" / "data" / "manifest.json"
REGION_CACHE = ROOT / ".tile_region_cache.json"
OFFICIAL_VALIDITY = ROOT / "validation" / "data" / "ikpn_validity.geojson"
OFFICIAL_Q100 = ROOT / "validation" / "data" / "ikpn_q100.geojson"
CELL_SIZE_M = 2
ANALYSIS_TILE_SIZE = 500
WEB_TILE_SIZE = 1000

CATEGORY = {
    "outside_validity": 0,
    "neither": 1,
    "official_only": 2,
    "d19_only": 3,
    "overlap": 4,
    "d19_unavailable_official_no": 5,
    "d19_unavailable_official_yes": 6,
}
VISUAL_COLORS = {
    CATEGORY["official_only"]: (56, 189, 248, 220),
    CATEGORY["d19_only"]: (249, 115, 22, 225),
    CATEGORY["overlap"]: (192, 132, 252, 240),
}
REGION_LABELS = {
    "01-koper": "Koper",
    "05-ljubljana": "Ljubljana",
    "08-kamnik": "Upper Savinja / Ljubno ob Savinji",
}


def load_union(path):
    collection = json.loads(path.read_text(encoding="utf-8"))
    geometries = [
        from_geojson(json.dumps(feature["geometry"]))
        for feature in collection.get("features", [])
        if feature.get("geometry")
    ]
    if not geometries:
        raise ValueError(f"No polygon geometry in {path}")
    return union_all(geometries)


def official_masks_for_tile(tile_name, validity_geometry, q100_geometry):
    easting, northing = (int(value) for value in tile_name.split("_"))
    grid = grid_definition((
        easting * 1000.0,
        northing * 1000.0,
        (easting + 1) * 1000.0,
        (northing + 1) * 1000.0,
    ), CELL_SIZE_M)
    validity = rasterize_geometry(validity_geometry, grid)
    q100 = rasterize_geometry(q100_geometry, grid) & validity
    return validity, q100


def load_d19_masks(tile):
    data_root = ROOT / "web" / "data"
    review = Image.open(data_root / tile["files"]["d19_review"]).convert("RGBA")
    diagnostic = Image.open(data_root / tile["files"]["d19_diagnostic"]).convert("RGBA")
    review_small = np.asarray(review.resize(
        (ANALYSIS_TILE_SIZE, ANALYSIS_TILE_SIZE), Image.Resampling.NEAREST
    ))
    diagnostic_small = np.asarray(diagnostic.resize(
        (ANALYSIS_TILE_SIZE, ANALYSIS_TILE_SIZE), Image.Resampling.NEAREST
    ))
    return review_small[..., 3] > 0, diagnostic_small[..., 3] > 0


def classify(validity, q100, d19_signal, d19_data):
    category = np.full(validity.shape, CATEGORY["outside_validity"], dtype=np.uint8)
    unavailable = validity & ~d19_data
    comparable = validity & d19_data
    category[unavailable & ~q100] = CATEGORY["d19_unavailable_official_no"]
    category[unavailable & q100] = CATEGORY["d19_unavailable_official_yes"]
    category[comparable] = CATEGORY["neither"]
    category[comparable & q100 & ~d19_signal] = CATEGORY["official_only"]
    category[comparable & ~q100 & d19_signal] = CATEGORY["d19_only"]
    category[comparable & q100 & d19_signal] = CATEGORY["overlap"]
    return category


def visual_rgba(category):
    rgba = np.zeros((*category.shape, 4), dtype=np.uint8)
    for value, color in VISUAL_COLORS.items():
        rgba[category == value] = color
    unavailable = np.isin(category, [
        CATEGORY["d19_unavailable_official_no"],
        CATEGORY["d19_unavailable_official_yes"],
    ])
    rows, cols = np.indices(category.shape)
    hatch = unavailable & ((rows + cols) % 8 < 2)
    rgba[hatch] = (148, 163, 184, 90)
    return rgba


def empty_counts():
    return {name: 0 for name in CATEGORY}


def add_counts(target, category):
    for name, value in CATEGORY.items():
        target[name] += int((category == value).sum())


def summary_block(region, counts):
    comparable = sum(counts[name] for name in ("neither", "official_only", "d19_only", "overlap"))
    validity = comparable + counts["d19_unavailable_official_no"] + counts["d19_unavailable_official_yes"]
    shares = {
        name: round(100.0 * counts[name] / comparable, 2) if comparable else None
        for name in ("official_only", "d19_only", "overlap", "neither")
    }
    return {
        "label": REGION_LABELS.get(region, region),
        "denominator": "inside-official-validity-with-d19-data",
        "comparable_cell_count": comparable,
        "comparable_area_km2": round(comparable * CELL_SIZE_M**2 / 1_000_000, 3),
        "validity_cell_count": validity,
        "comparable_coverage_of_validity_percent": (
            round(100.0 * comparable / validity, 2) if validity else None
        ),
        "shares_percent": shares,
        "counts": counts,
    }


def main():
    manifest = json.loads(WEB_MANIFEST.read_text(encoding="utf-8"))
    tile_regions = json.loads(REGION_CACHE.read_text(encoding="utf-8"))
    validity_geometry = load_union(OFFICIAL_VALIDITY)
    q100_geometry = load_union(OFFICIAL_Q100)
    region_counts = {}

    for number, tile in enumerate(manifest["tiles"], start=1):
        tile_name = tile["name"]
        region = tile_regions.get(tile_name)
        if region is None:
            raise RuntimeError(f"Missing CDN region cache entry for {tile_name}")
        region_counts.setdefault(region, empty_counts())
        validity, q100 = official_masks_for_tile(
            tile_name, validity_geometry, q100_geometry)
        d19_signal, d19_data = load_d19_masks(tile)
        category = classify(validity, q100, d19_signal, d19_data)
        add_counts(region_counts[region], category)

        tile_dir = ROOT / "web" / "data" / "tiles" / tile_name
        visual_path = tile_dir / "q100_d19_comparison.png"
        index_path = tile_dir / "q100_d19_comparison_index.png"
        Image.fromarray(visual_rgba(category), "RGBA").resize(
            (WEB_TILE_SIZE, WEB_TILE_SIZE), Image.Resampling.NEAREST
        ).save(visual_path, optimize=True)
        Image.fromarray(category, "L").resize(
            (WEB_TILE_SIZE, WEB_TILE_SIZE), Image.Resampling.NEAREST
        ).save(index_path, optimize=True)
        prefix = f"tiles/{tile_name}"
        tile["files"]["q100_comparison"] = f"{prefix}/{visual_path.name}"
        tile["files"]["q100_comparison_index"] = f"{prefix}/{index_path.name}"
        print(f"[{number:3d}/{len(manifest['tiles'])}] {tile_name}")

    region_summaries = {
        region: summary_block(region, counts)
        for region, counts in sorted(region_counts.items())
    }
    manifest["q100_comparison"] = {
        "schema_version": 2,
        "generated": datetime.now(timezone.utc).isoformat(),
        "semantics": "categorical-frozen-d19-review-mask-versus-official-static-q100",
        "resolution_m": CELL_SIZE_M,
        "d19_review_threshold": manifest["d19_display"]["review_threshold"],
        "d19_threshold_semantics": manifest["d19_display"]["threshold_semantics"],
        "official_semantics": "DRSV-IKPN-Q100-static-planning-reference-not-observed-event",
        "categories": CATEGORY,
        "colors": {
            "official_only": "#38bdf8",
            "d19_only": "#f97316",
            "overlap": "#c084fc",
            "neither": "transparent",
            "outside_validity": "transparent-with-dashed-validity-boundary",
            "d19_unavailable_official_no": "sparse-gray-hatch",
            "d19_unavailable_official_yes": "sparse-gray-hatch",
        },
        "regions": region_summaries,
        "source_digests": {
            "official_validity_geojson": file_sha256(OFFICIAL_VALIDITY),
            "official_q100_geojson": file_sha256(OFFICIAL_Q100),
            "tile_region_cache": file_sha256(REGION_CACHE),
        },
        "evaluation_contract_unchanged": True,
        "limitations": [
            "D19-cutoff-is-display-rule-not-hazard-threshold",
            "official-Q100-is-static-planning-reference-not-observed-event",
            "neither-is-not-proof-of-safety",
            "outside-validity-is-comparison-unavailable",
        ],
    }
    WEB_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {WEB_MANIFEST}")
    print(json.dumps(region_summaries, indent=2))


if __name__ == "__main__":
    main()
