#!/usr/bin/env python3
"""Generate packed official-label rasters and expanded frozen split metadata."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from shapely import from_geojson, union_all

from validation_grid import (
    assign_split,
    contract_digest,
    file_sha256,
    grid_definition,
    pack_mask,
    rasterize_geometry,
    region_bounds,
)


ROOT = Path(__file__).resolve().parent
CONTRACT_PATH = ROOT / "validation" / "evaluation_contract.json"
SOURCE_DIR = ROOT / "validation" / "data"
OUTPUT_DIR = ROOT / "validation"
RASTER_DIR = OUTPUT_DIR / "rasters"
REGION_CACHE = ROOT / ".tile_region_cache.json"


def load_union(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    geometries = [
        from_geojson(json.dumps(feature["geometry"]))
        for feature in data.get("features", [])
        if feature.get("geometry")
    ]
    if not geometries:
        raise ValueError(f"No geometry in {path}")
    return union_all(geometries)


def main():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    tile_regions = json.loads(REGION_CACHE.read_text(encoding="utf-8"))
    by_region = {}
    for tile, region in tile_regions.items():
        by_region.setdefault(region, []).append(tile)

    geometries = {
        key: load_union(SOURCE_DIR / filename)
        for key, filename in contract["label_layers"].items()
    }
    split_assignments = {
        tile: {"region": region, "split": assign_split(tile, region)}
        for tile, region in sorted(tile_regions.items())
    }

    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    raster_entries = []
    for region, tiles in sorted(by_region.items()):
        bounds = region_bounds(tiles)
        for resolution in contract["grid_resolutions_m"]:
            grid = grid_definition(bounds, resolution)
            arrays = {}
            counts = {}
            for key, geometry in geometries.items():
                mask = rasterize_geometry(geometry, grid)
                arrays[key] = pack_mask(mask)
                counts[key] = int(mask.sum())
            q100_boundary = geometries["q100"].boundary
            for distance in contract["boundary_uncertainty_buffers_m"]:
                key = f"q100_boundary_{distance}m"
                mask = rasterize_geometry(q100_boundary.buffer(distance), grid)
                arrays[key] = pack_mask(mask)
                counts[key] = int(mask.sum())

            output = RASTER_DIR / f"{region}_{resolution}m.npz"
            np.savez_compressed(
                output,
                **arrays,
                metadata=np.array(json.dumps(grid, sort_keys=True)),
            )
            raster_entries.append({
                "region": region,
                "resolution_m": resolution,
                "path": str(output.relative_to(ROOT)).replace("\\", "/"),
                "sha256": file_sha256(output),
                "grid": grid,
                "positive_cell_counts": counts,
            })
            print(f"Wrote {output} ({grid['width']} × {grid['height']})")

    manifest = {
        "schema_version": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "contract": str(CONTRACT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "contract_sha256": contract_digest(contract),
        "source_crs": contract["crs"],
        "split_assignments": split_assignments,
        "rasters": raster_entries,
        "semantics": {
            "outside_validity": "unknown-not-dry",
            "q100_boundary_masks": "ambiguous-exclude-or-report-separately",
            "locked_test": "not-for-feature-threshold-or-hyperparameter-selection",
        },
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "evaluation_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
