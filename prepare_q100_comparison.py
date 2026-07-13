#!/usr/bin/env python3
"""Build categorical D19-vs-official-Q100 comparison tiles and summaries.

Categories are derived on the committed 2 m official grid. D19 is the frozen
0.925 review-display mask, not a fitted hazard threshold. Outside the official
validity domain is explicitly unavailable rather than negative.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from validation_grid import file_sha256, unpack_mask


ROOT = Path(__file__).resolve().parent
WEB_MANIFEST = ROOT / "web" / "data" / "manifest.json"
EVALUATION_MANIFEST = ROOT / "validation" / "evaluation_manifest.json"
RASTER_DIR = ROOT / "validation" / "rasters"
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
    CATEGORY["overlap"]: (248, 250, 252, 240),
}
REGION_LABELS = {
    "01-koper": "Koper",
    "05-ljubljana": "Ljubljana",
    "08-kamnik": "Savinja / Kamnik",
}


def load_region_grid(region):
    path = RASTER_DIR / f"{region}_2m.npz"
    data = np.load(path)
    metadata = json.loads(str(data["metadata"]))
    shape = (metadata["height"], metadata["width"])
    return {
        "path": path,
        "metadata": metadata,
        "validity": unpack_mask(data["validity"], shape),
        "q100": unpack_mask(data["q100"], shape),
    }


def tile_window(tile_name, metadata):
    easting, northing = (int(value) for value in tile_name.split("_"))
    x0 = easting * 1000.0
    y1 = (northing + 1) * 1000.0
    col0 = int(round((x0 - metadata["xmin"]) / CELL_SIZE_M))
    row0 = int(round((metadata["ymax"] - y1) / CELL_SIZE_M))
    return np.s_[row0:row0 + ANALYSIS_TILE_SIZE, col0:col0 + ANALYSIS_TILE_SIZE]


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
    evaluation = json.loads(EVALUATION_MANIFEST.read_text(encoding="utf-8"))
    assignments = evaluation["split_assignments"]
    region_grids = {}
    region_counts = {}

    for number, tile in enumerate(manifest["tiles"], start=1):
        tile_name = tile["name"]
        region = assignments[tile_name]["region"]
        if region not in region_grids:
            region_grids[region] = load_region_grid(region)
            region_counts[region] = empty_counts()
        grid = region_grids[region]
        window = tile_window(tile_name, grid["metadata"])
        validity = grid["validity"][window]
        q100 = grid["q100"][window]
        if validity.shape != (ANALYSIS_TILE_SIZE, ANALYSIS_TILE_SIZE):
            raise RuntimeError(f"Invalid official window for {tile_name}: {validity.shape}")
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
        "schema_version": 1,
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
            "overlap": "#f8fafc",
            "neither": "transparent",
            "outside_validity": "transparent-with-dashed-validity-boundary",
            "d19_unavailable_official_no": "sparse-gray-hatch",
            "d19_unavailable_official_yes": "sparse-gray-hatch",
        },
        "regions": region_summaries,
        "source_digests": {
            "evaluation_manifest": file_sha256(EVALUATION_MANIFEST),
            **{
                f"{region}_2m": file_sha256(grid["path"])
                for region, grid in sorted(region_grids.items())
            },
        },
        "limitations": [
            "D19-cutoff-is-display-rule-not-hazard-threshold",
            "official-Q100-is-static-planning-reference-not-observed-event",
            "neither-is-not-proof-of-safety",
            "outside-validity-is-comparison-unavailable",
        ],
    }
    WEB_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {WEB_MANIFEST}")
    print(json.dumps(region_summaries, indent=2))


if __name__ == "__main__":
    main()
