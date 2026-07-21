#!/usr/bin/env python3
"""Convert LAZ tiles once into restartable, domain-wide Zarr analysis bands.

The store contains direct observations only. Missing tiles and cells without
returns retain explicit no-data values; hydrological conditioning and the
bounded 16 m internal-gap policy belong to later continuous-domain stages.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import laspy
import numpy as np
import zarr


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
INVENTORY = ROOT / "output" / "connectivity" / "domain_inventory.json"
DIGESTS = ROOT / "output" / "connectivity" / "input_digests.json"
DEFAULT_STORE = ROOT / "output" / "connectivity" / "terrain.zarr"
PROVENANCE_NO_DATA = np.uint8(0)
PROVENANCE_LIDAR_DIRECT = np.uint8(1)


def summarize_points(x, y, z, classification, bounds, resolution_m):
    xmin, ymin, xmax, ymax = bounds
    cells = int(round((xmax - xmin) / resolution_m))
    shape = (cells, cells)
    dtm = np.full(shape, np.inf, dtype=np.float64)
    dsm = np.full(shape, -np.inf, dtype=np.float64)
    vegetation = np.full(shape, -np.inf, dtype=np.float64)
    point_density = np.zeros(shape, dtype=np.uint32)
    ground_density = np.zeros(shape, dtype=np.uint32)
    valid = (x >= xmin) & (x < xmax) & (y >= ymin) & (y < ymax)
    cols = ((x[valid] - xmin) / resolution_m).astype(np.int64)
    rows = ((y[valid] - ymin) / resolution_m).astype(np.int64)
    heights = z[valid]
    classes = classification[valid]
    np.maximum.at(dsm, (rows, cols), heights)
    np.add.at(point_density, (rows, cols), 1)
    ground = classes == 2
    np.minimum.at(dtm, (rows[ground], cols[ground]), heights[ground])
    np.add.at(ground_density, (rows[ground], cols[ground]), 1)
    veg = (classes >= 3) & (classes <= 5)
    np.maximum.at(vegetation, (rows[veg], cols[veg]), heights[veg])
    return dtm, dsm, vegetation, point_density, ground_density


def read_tile(path, resolution_m, chunk_size=4_000_000):
    easting, northing = (int(value) for value in path.stem.removeprefix("GKOT_").split("_"))
    bounds = (easting * 1000.0, northing * 1000.0, (easting + 1) * 1000.0, (northing + 1) * 1000.0)
    cells = int(round(1000.0 / resolution_m))
    shape = (cells, cells)
    dtm = np.full(shape, np.inf, dtype=np.float64)
    dsm = np.full(shape, -np.inf, dtype=np.float64)
    vegetation = np.full(shape, -np.inf, dtype=np.float64)
    point_density = np.zeros(shape, dtype=np.uint32)
    ground_density = np.zeros(shape, dtype=np.uint32)
    with laspy.open(path) as reader:
        for points in reader.chunk_iterator(chunk_size):
            bands = summarize_points(
                np.asarray(points.x), np.asarray(points.y), np.asarray(points.z),
                np.asarray(points.classification), bounds, resolution_m,
            )
            np.minimum(dtm, bands[0], out=dtm)
            np.maximum(dsm, bands[1], out=dsm)
            np.maximum(vegetation, bands[2], out=vegetation)
            point_density += bands[3]
            ground_density += bands[4]
    ground = np.isfinite(dtm)
    points = np.isfinite(dsm)
    dtm[~ground] = np.nan
    dsm[~points] = np.nan
    canopy = np.full(shape, np.nan, dtype=np.float32)
    canopy_valid = ground & np.isfinite(vegetation)
    canopy[canopy_valid] = np.maximum(vegetation[canopy_valid] - dtm[canopy_valid], 0).astype(np.float32)
    provenance = np.full(shape, PROVENANCE_NO_DATA, dtype=np.uint8)
    provenance[ground] = PROVENANCE_LIDAR_DIRECT
    return {
        "dtm_m": dtm.astype(np.float32),
        "dsm_m": dsm.astype(np.float32),
        "canopy_height_m": canopy,
        "point_density": np.clip(point_density, 0, 65535).astype(np.uint16),
        "ground_density": np.clip(ground_density, 0, 65535).astype(np.uint16),
        "lidar_point_coverage": points,
        "ground_coverage": ground,
        "provenance_code": provenance,
    }


def ensure_arrays(group, shape, chunk_cells):
    contracts = {
        "dtm_m": ("float32", np.nan),
        "dsm_m": ("float32", np.nan),
        "canopy_height_m": ("float32", np.nan),
        "point_density": ("uint16", 0),
        "ground_density": ("uint16", 0),
        "lidar_point_coverage": ("bool", False),
        "ground_coverage": ("bool", False),
        "provenance_code": ("uint8", 0),
    }
    for name, (dtype, fill) in contracts.items():
        if name not in group:
            group.create_array(
                name, shape=shape, chunks=(chunk_cells, chunk_cells),
                dtype=dtype, fill_value=fill,
            )


def build(domain_id, resolution_m=2, store_path=DEFAULT_STORE, limit=None):
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    digests = json.loads(DIGESTS.read_text(encoding="utf-8"))
    domain = next((item for item in inventory["components"] if item["id"] == domain_id), None)
    if domain is None:
        raise ValueError(f"Unknown domain {domain_id!r}")
    xmin, ymin, xmax, ymax = domain["bounds_epsg3794"]
    shape = (int((ymax - ymin) / resolution_m), int((xmax - xmin) / resolution_m))
    tile_cells = int(1000 / resolution_m)
    root = zarr.open_group(str(store_path), mode="a")
    group = root.require_group(f"{domain_id}/{resolution_m}m")
    ensure_arrays(group, shape, tile_cells)
    group.attrs.update({
        "schema_version": 1,
        "domain_id": domain_id,
        "bounds_epsg3794": domain["bounds_epsg3794"],
        "resolution_m": resolution_m,
        "row_order": "south-to-north",
        "missing_data_policy": "explicit-no-data-no-nearest-neighbour-fill",
        "provenance_codes": {"0": "no-data", "1": "direct-lidar"},
        "dataset_sha256": digests["dataset_sha256"],
    })
    status_path = Path(store_path).with_suffix(".status.json")
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {"completed": {}}
    key_prefix = f"{domain_id}/{resolution_m}m"
    completed = status["completed"].setdefault(key_prefix, {})
    tile_ids = domain["tile_ids"][:limit] if limit else domain["tile_ids"]
    for number, tile_id in enumerate(tile_ids, start=1):
        filename = f"GKOT_{tile_id}.laz"
        digest = digests["files"].get(filename)
        if digest is None:
            raise RuntimeError(f"Missing content digest for {filename}; run input_digests.py")
        if completed.get(tile_id) == digest["sha256"]:
            print(f"[{number}/{len(tile_ids)}] cached {tile_id}", flush=True)
            continue
        arrays = read_tile(DATA / filename, resolution_m)
        easting, northing = (int(value) for value in tile_id.split("_"))
        col = int((easting * 1000 - xmin) / resolution_m)
        row = int((northing * 1000 - ymin) / resolution_m)
        window = np.s_[row:row + tile_cells, col:col + tile_cells]
        for name, array in arrays.items():
            group[name][window] = array
        completed[tile_id] = digest["sha256"]
        status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
        print(f"[{number}/{len(tile_ids)}] wrote {tile_id}", flush=True)
    return {"domain": domain_id, "resolution_m": resolution_m, "tiles_complete": len(completed), "shape": shape}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=("central-validity", "upper-savinja-event", "koper-coastal"), required=True)
    parser.add_argument("--resolution", type=int, choices=(2, 10), default=2)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--limit", type=int, help="Development smoke-test tile limit")
    args = parser.parse_args()
    print(json.dumps(build(args.domain, args.resolution, args.store, args.limit), indent=2))
