"""Versioned official-label grids and spatial split helpers."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box


def tile_coordinates(tile_name: str) -> tuple[int, int]:
    easting, northing = tile_name.split("_")
    return int(easting), int(northing)


def assign_split(tile_name: str, region: str) -> str:
    """Apply the frozen split rules in validation/evaluation_contract.json."""
    easting, _ = tile_coordinates(tile_name)
    if region == "05-ljubljana":
        if easting <= 461:
            return "development"
        if easting == 462:
            return "guard"
        return "locked_test"
    if region == "08-kamnik":
        if easting <= 488:
            return "development"
        if easting == 489:
            return "guard"
        return "locked_test"
    if region == "01-koper":
        return "evaluation_only"
    raise ValueError(f"No frozen split rule for region {region!r}")


def region_bounds(tile_names: list[str]) -> tuple[float, float, float, float]:
    coordinates = [tile_coordinates(name) for name in tile_names]
    eastings = [item[0] for item in coordinates]
    northings = [item[1] for item in coordinates]
    return (
        min(eastings) * 1000.0,
        min(northings) * 1000.0,
        (max(eastings) + 1) * 1000.0,
        (max(northings) + 1) * 1000.0,
    )


def grid_definition(bounds, resolution_m: int) -> dict:
    xmin, ymin, xmax, ymax = bounds
    width = int(round((xmax - xmin) / resolution_m))
    height = int(round((ymax - ymin) / resolution_m))
    if width <= 0 or height <= 0:
        raise ValueError("Grid has no cells")
    return {
        "xmin": xmin,
        "ymin": ymin,
        "xmax": xmax,
        "ymax": ymax,
        "resolution_m": resolution_m,
        "width": width,
        "height": height,
        "cell_anchor": "center",
        "row_order": "north-to-south",
    }


def _polygons(geometry):
    if geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, (MultiPolygon, GeometryCollection)):
        for child in geometry.geoms:
            yield from _polygons(child)


def _pixel_ring(coordinates, grid):
    xmin = grid["xmin"]
    ymax = grid["ymax"]
    resolution = grid["resolution_m"]
    return [
        ((x - xmin) / resolution - 0.5, (ymax - y) / resolution - 0.5)
        for x, y, *_ in coordinates
    ]


def rasterize_geometry(geometry, grid) -> np.ndarray:
    """Rasterize polygon cell centers to a north-up boolean grid."""
    clipped = geometry.intersection(box(
        grid["xmin"], grid["ymin"], grid["xmax"], grid["ymax"]
    ))
    image = Image.new("1", (grid["width"], grid["height"]), 0)
    draw = ImageDraw.Draw(image)
    for polygon in _polygons(clipped):
        draw.polygon(_pixel_ring(polygon.exterior.coords, grid), fill=1)
        for interior in polygon.interiors:
            draw.polygon(_pixel_ring(interior.coords, grid), fill=0)
    return np.asarray(image, dtype=bool)


def pack_mask(mask: np.ndarray) -> np.ndarray:
    return np.packbits(mask.reshape(-1), bitorder="little")


def unpack_mask(packed: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    size = int(math.prod(shape))
    return np.unpackbits(packed, count=size, bitorder="little").reshape(shape).astype(bool)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contract_digest(contract: dict) -> str:
    payload = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
