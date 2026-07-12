#!/usr/bin/env python3
"""Build continuous, conditioned hydrology across a complete LiDAR region.

Large feature arrays are written under ignored output/mosaic/<region>/. The
script never evaluates replacement features on the frozen locked-test column;
its optional Q100 comparison is development-only and exists solely to verify
that mosaic HAND clears the frozen per-tile HAND engineering baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import laspy
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import (
    distance_transform_edt,
    gaussian_filter,
    maximum_filter,
    minimum_filter,
)
from shapely import contains_xy

import analyze_model
import evaluate_validation
import kernels
from validation_grid import assign_split, file_sha256


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
FLOW_LINES = ROOT / "validation" / "data" / "official_flow_lines.geojson"
VALIDITY = ROOT / "validation" / "data" / "ikpn_validity.geojson"
Q100 = ROOT / "validation" / "data" / "ikpn_q100.geojson"
SAMPLES = ROOT / "output" / "diagnostics" / "samples"

GRID_RES_M = 2.0
TILE_CELLS = 500
REGION_SPECS = {
    "savinja": {
        "cdn_region": "08-kamnik",
        "easting_range": (486, 491),
        "northing_range": (132, 137),
    },
    "ljubljana": {
        "cdn_region": "05-ljubljana",
        "easting_range": (455, 465),
        "northing_range": (96, 106),
    },
}
STREAM_THRESHOLDS_M2 = (10_000.0, 50_000.0, 100_000.0)
DEFAULT_STREAM_AREA_M2 = 50_000.0
OFFICIAL_TOLERANCE_M = 20.0
GENTLE_BURN_DEPTH_M = 0.5
GENTLE_BURN_HALF_WIDTH_M = 10.0
FILL_EPSILON_M = 1e-5


def configure_region(name):
    """Select one region for this process; all stages share this exact geometry."""
    global REGION_NAME, REGION, EASTING_RANGE, NORTHING_RANGE
    global BOUNDS, SHAPE, OUTPUT, TILE_OUTPUT
    if name not in REGION_SPECS:
        raise ValueError(f"Unknown region {name!r}; choose from {sorted(REGION_SPECS)}")
    spec = REGION_SPECS[name]
    REGION_NAME = name
    REGION = spec["cdn_region"]
    EASTING_RANGE = range(*spec["easting_range"])
    NORTHING_RANGE = range(*spec["northing_range"])
    BOUNDS = (
        EASTING_RANGE.start * 1000.0,
        NORTHING_RANGE.start * 1000.0,
        EASTING_RANGE.stop * 1000.0,
        NORTHING_RANGE.stop * 1000.0,
    )
    SHAPE = (
        len(NORTHING_RANGE) * TILE_CELLS,
        len(EASTING_RANGE) * TILE_CELLS,
    )  # row 0 is south; column 0 is west
    OUTPUT = ROOT / "output" / "mosaic" / REGION_NAME
    TILE_OUTPUT = OUTPUT / "tiles"


configure_region("savinja")


def tile_paths():
    return [
        DATA / f"GKOT_{easting}_{northing}.laz"
        for easting in EASTING_RANGE
        for northing in NORTHING_RANGE
    ]


def input_fingerprint(paths):
    items = {path.name: path.stat().st_size for path in paths}
    payload = json.dumps(items, sort_keys=True, separators=(",", ":")).encode()
    return {"files": items, "sha256": hashlib.sha256(payload).hexdigest()}


def assemble_ground_dtm(paths, chunk_size=4_000_000):
    xmin, ymin, xmax, ymax = BOUNDS
    dtm = np.full(SHAPE, np.inf, dtype=np.float64)
    total_ground = 0
    for number, path in enumerate(paths, start=1):
        print(f"[{number:2d}/{len(paths)}] decode {path.name}", flush=True)
        with laspy.open(path) as reader:
            for points in reader.chunk_iterator(chunk_size):
                classification = np.asarray(points.classification)
                ground = classification == 2
                if not ground.any():
                    continue
                x = np.asarray(points.x)[ground]
                y = np.asarray(points.y)[ground]
                z = np.asarray(points.z)[ground]
                valid = (x >= xmin) & (x < xmax) & (y >= ymin) & (y < ymax)
                if not valid.any():
                    continue
                cols = ((x[valid] - xmin) / GRID_RES_M).astype(np.int64)
                rows = ((y[valid] - ymin) / GRID_RES_M).astype(np.int64)
                kernels.dtm_min_update(dtm, rows, cols, z[valid])
                total_ground += int(valid.sum())

    missing = np.isinf(dtm)
    if missing.all():
        raise RuntimeError(f"{REGION_NAME} mosaic has no ground returns")
    distances, indices = distance_transform_edt(
        missing, return_distances=True, return_indices=True
    )
    ground_coverage = ~missing
    filled = dtm[tuple(indices)]
    smoothed = gaussian_filter(filled, sigma=1.5)
    metadata = {
        "ground_returns": total_ground,
        "direct_ground_cell_fraction": round(float(ground_coverage.mean()), 6),
        "max_nearest_ground_fill_distance_m": round(float(distances.max() * GRID_RES_M), 3),
    }
    return smoothed, ground_coverage, metadata


def load_or_build_dtm(paths, fingerprint, rebuild=False):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    dtm_path = OUTPUT / "dtm_smoothed.npy"
    coverage_path = OUTPUT / "ground_coverage.npy"
    cache_path = OUTPUT / "dtm_cache.json"
    if not rebuild and dtm_path.exists() and coverage_path.exists() and cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if cache.get("input_sha256") == fingerprint["sha256"]:
            print(f"Using cached {REGION_NAME} mosaic DTM", flush=True)
            return np.load(dtm_path, mmap_mode="r"), np.load(coverage_path, mmap_mode="r"), cache["assembly"]

    dtm, coverage, assembly = assemble_ground_dtm(paths)
    np.save(dtm_path, dtm.astype(np.float32))
    np.save(coverage_path, coverage)
    cache_path.write_text(json.dumps({
        "input_sha256": fingerprint["sha256"],
        "assembly": assembly,
        "bounds_epsg3794": BOUNDS,
        "shape": SHAPE,
        "resolution_m": GRID_RES_M,
    }, indent=2), encoding="utf-8")
    return dtm, coverage, assembly


def _line_parts(geometry):
    if not geometry:
        return []
    if geometry["type"] == "LineString":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiLineString":
        return geometry["coordinates"]
    return []


def rasterize_official_flow_lines(path=FLOW_LINES, width_cells=2):
    data = json.loads(path.read_text(encoding="utf-8"))
    image = Image.new("1", (SHAPE[1], SHAPE[0]), 0)
    draw = ImageDraw.Draw(image)
    xmin, ymin, xmax, ymax = BOUNDS
    feature_count = 0
    for feature in data.get("features", []):
        drew = False
        for coordinates in _line_parts(feature.get("geometry")):
            pixels = [
                ((x - xmin) / GRID_RES_M, (y - ymin) / GRID_RES_M)
                for x, y, *_ in coordinates
                if xmin - 20 <= x <= xmax + 20 and ymin - 20 <= y <= ymax + 20
            ]
            if len(pixels) >= 2:
                draw.line(pixels, fill=1, width=width_cells)
                drew = True
        if drew:
            feature_count += 1
    return np.asarray(image, dtype=bool), feature_count


def assess_flow_line_alignment(dtm, official_mask):
    local_minimum = minimum_filter(dtm, size=11, mode="nearest")
    offsets = dtm[official_mask] - local_minimum[official_mask]
    if offsets.size == 0:
        return {"accepted_for_gentle_burn": False, "line_cells": 0}
    metrics = {
        "line_cells": int(offsets.size),
        "median_height_above_20m_local_min_m": round(float(np.median(offsets)), 4),
        "p90_height_above_20m_local_min_m": round(float(np.percentile(offsets, 90)), 4),
    }
    metrics["accepted_for_gentle_burn"] = (
        metrics["median_height_above_20m_local_min_m"] <= 1.5
        and metrics["p90_height_above_20m_local_min_m"] <= 3.0
    )
    return metrics


def gentle_network_burn(dtm, official_mask):
    distance_m = distance_transform_edt(~official_mask) * GRID_RES_M
    strength = np.clip(1.0 - distance_m / GENTLE_BURN_HALF_WIDTH_M, 0.0, 1.0)
    return dtm - GENTLE_BURN_DEPTH_M * strength


def conditioning_metrics(original, conditioned):
    delta = conditioned - original
    changed = delta > 1e-9
    return {
        "changed_cell_fraction": round(float(changed.mean()), 6),
        "median_positive_change_m": round(float(np.median(delta[changed])), 6) if changed.any() else 0.0,
        "p99_positive_change_m": round(float(np.percentile(delta[changed], 99)), 6) if changed.any() else 0.0,
        "max_positive_change_m": round(float(delta.max()), 6),
    }


def stream_alignment(stream, official_mask, official_distance):
    if not stream.any() or not official_mask.any():
        return {"official_recall_20m": 0.0, "derived_precision_20m": 0.0, "f1_20m": 0.0}
    derived_distance = distance_transform_edt(~stream) * GRID_RES_M
    recall = float((derived_distance[official_mask] <= OFFICIAL_TOLERANCE_M).mean())
    precision = float((official_distance[stream] <= OFFICIAL_TOLERANCE_M).mean())
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    return {
        "official_recall_20m": round(recall, 4),
        "derived_precision_20m": round(precision, 4),
        "f1_20m": round(f1, 4),
        "stream_cell_fraction": round(float(stream.mean()), 6),
    }


def threshold_sensitivity(accumulation, official_mask, method):
    official_distance = distance_transform_edt(~official_mask) * GRID_RES_M
    blocks = []
    for threshold in STREAM_THRESHOLDS_M2:
        stream = accumulation * GRID_RES_M**2 >= threshold
        block = stream_alignment(stream, official_mask, official_distance)
        block.update({"method": method, "stream_area_m2": threshold})
        blocks.append(block)
    return blocks


def select_stream_threshold(blocks):
    d8 = [block for block in blocks if block["method"] == "d8"]
    return max(d8, key=lambda item: (item["f1_20m"], item["stream_area_m2"]))["stream_area_m2"]


def seam_jump_metrics(array):
    seam_values = []
    adjacent_values = []
    for boundary in range(TILE_CELLS, SHAPE[1], TILE_CELLS):
        seam_values.append(np.abs(array[:, boundary] - array[:, boundary - 1]))
        adjacent_values.append(np.abs(array[:, boundary + 1] - array[:, boundary]))
        adjacent_values.append(np.abs(array[:, boundary - 1] - array[:, boundary - 2]))
    for boundary in range(TILE_CELLS, SHAPE[0], TILE_CELLS):
        seam_values.append(np.abs(array[boundary, :] - array[boundary - 1, :]))
        adjacent_values.append(np.abs(array[boundary + 1, :] - array[boundary, :]))
        adjacent_values.append(np.abs(array[boundary - 1, :] - array[boundary - 2, :]))
    seam = np.concatenate(seam_values)
    adjacent = np.concatenate(adjacent_values)
    seam_median = float(np.median(seam))
    adjacent_median = float(np.median(adjacent))
    return {
        "median_seam_jump": round(seam_median, 6),
        "median_adjacent_jump": round(adjacent_median, 6),
        "median_seam_ratio": round(seam_median / max(adjacent_median, 1e-9), 4),
        "p95_seam_jump": round(float(np.percentile(seam, 95)), 6),
    }


def receiver_seam_metrics(recv, stream, official_mask):
    rows, cols = SHAPE
    indexes = np.arange(recv.size, dtype=np.int64)
    row = indexes // cols
    col = indexes % cols
    valid = recv >= 0
    receiver_row = np.zeros(recv.size, dtype=np.int64)
    receiver_col = np.zeros(recv.size, dtype=np.int64)
    receiver_row[valid] = recv[valid] // cols
    receiver_col[valid] = recv[valid] % cols
    crossed = valid & (
        (row // TILE_CELLS != receiver_row // TILE_CELLS)
        | (col // TILE_CELLS != receiver_col // TILE_CELLS)
    )
    interior = np.ones(SHAPE, dtype=bool)
    interior[[0, -1], :] = False
    interior[:, [0, -1]] = False
    internal_sinks = int(((recv.reshape(SHAPE) < 0) & interior).sum())

    seam_band = np.zeros(SHAPE, dtype=bool)
    for boundary in range(TILE_CELLS, cols, TILE_CELLS):
        seam_band[:, boundary - 1:boundary + 1] = True
    for boundary in range(TILE_CELLS, rows, TILE_CELLS):
        seam_band[boundary - 1:boundary + 1, :] = True
    stream_distance = distance_transform_edt(~stream) * GRID_RES_M
    official_seam = official_mask & seam_band
    return {
        "receiver_edges_crossing_tile_seams": int(crossed.sum()),
        "internal_sink_count": internal_sinks,
        "official_line_seam_cells": int(official_seam.sum()),
        "official_line_seam_cells_with_stream_20m_fraction": (
            round(float((stream_distance[official_seam] <= OFFICIAL_TOLERANCE_M).mean()), 4)
            if official_seam.any() else None
        ),
    }


def development_hand_benchmark(hand):
    arrays, metadata = analyze_model.load_samples(SAMPLES)
    if not metadata:
        return {"available": False, "reason": "missing diagnostic samples"}
    region = arrays["_region"] == REGION
    splits = np.asarray([
        assign_split(str(tile), str(sample_region))
        for tile, sample_region in zip(arrays["_tile"], arrays["_region"])
    ])
    development = region & (splits == "development")
    validity, _ = evaluate_validation.load_geometry_union(VALIDITY)
    q100, _ = evaluate_validation.load_geometry_union(Q100)
    x = arrays["easting_3794"].astype(np.float64)
    y = arrays["northing_3794"].astype(np.float64)
    eligible = (
        development
        & contains_xy(validity, x, y)
        & ~contains_xy(q100.boundary.buffer(10.0), x, y)
    )
    labels = contains_xy(q100, x[eligible], y[eligible])
    cols = np.clip(((x[eligible] - BOUNDS[0]) / GRID_RES_M).astype(int), 0, SHAPE[1] - 1)
    rows = np.clip(((y[eligible] - BOUNDS[1]) / GRID_RES_M).astype(int), 0, SHAPE[0] - 1)
    mosaic_score = -hand[rows, cols]
    per_tile_score = 1.0 - arrays["norm_hand"][eligible]
    return {
        "available": True,
        "semantics": "development-only-static-q100-engineering-check",
        "sample_count": int(eligible.sum()),
        "positive_count": int(labels.sum()),
        "per_tile_hand": {
            "roc_auc": round(evaluate_validation.roc_auc(labels, per_tile_score), 4),
            "average_precision": round(evaluate_validation.average_precision(labels, per_tile_score), 4),
        },
        "mosaic_hand": {
            "roc_auc": round(evaluate_validation.roc_auc(labels, mosaic_score), 4),
            "average_precision": round(evaluate_validation.average_precision(labels, mosaic_score), 4),
        },
        "locked_test_accessed": False,
    }


def configuration_sensitivity(variants):
    """Evaluate allowed conditioning/threshold variants on development only."""
    rows = []
    for variant_name, conditioned, recv, accumulation in variants:
        for threshold in STREAM_THRESHOLDS_M2:
            stream = accumulation * GRID_RES_M**2 >= threshold
            hand = kernels.hand_from_receivers(conditioned, recv, stream)
            benchmark = development_hand_benchmark(hand)
            rows.append({
                "conditioning_variant": variant_name,
                "stream_area_m2": threshold,
                "benchmark": benchmark,
            })
    return rows


def select_configuration(rows):
    available = [row for row in rows if row["benchmark"].get("available")]
    if not available:
        raise RuntimeError("No development benchmark is available for configuration selection")
    return max(
        available,
        key=lambda row: (
            row["benchmark"]["mosaic_hand"]["roc_auc"],
            row["benchmark"]["mosaic_hand"]["average_precision"],
        ),
    )


def save_feature(name, array):
    path = OUTPUT / f"{name}.npy"
    backing_file = getattr(array, "filename", None)
    same_backing_file = (
        backing_file is not None
        and Path(backing_file).resolve() == path.resolve()
    )
    if not same_backing_file:
        np.save(path, array)
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "dtype": str(array.dtype),
        "shape": list(array.shape),
        "sha256": file_sha256(path),
    }


def cut_tiles(features):
    TILE_OUTPUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for easting in EASTING_RANGE:
        for northing in NORTHING_RANGE:
            c0 = (easting - EASTING_RANGE.start) * TILE_CELLS
            r0 = (northing - NORTHING_RANGE.start) * TILE_CELLS
            path = TILE_OUTPUT / f"{easting}_{northing}.npz"
            np.savez_compressed(
                path,
                **{
                    name: value[r0:r0 + TILE_CELLS, c0:c0 + TILE_CELLS]
                    for name, value in features.items()
                },
                metadata=np.array(json.dumps({
                    "tile": f"{easting}_{northing}",
                    "source": f"continuous-{REGION_NAME}-mosaic",
                    "row_order": "south-to-north",
                    "resolution_m": GRID_RES_M,
                }, sort_keys=True)),
            )
            entries.append({
                "tile": f"{easting}_{northing}",
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": file_sha256(path),
            })
    return entries


def verify_tile_exports(features, entries):
    failures = []
    for entry in entries:
        easting, northing = (int(value) for value in entry["tile"].split("_"))
        c0 = (easting - EASTING_RANGE.start) * TILE_CELLS
        r0 = (northing - NORTHING_RANGE.start) * TILE_CELLS
        data = np.load(ROOT / entry["path"])
        for name, source in features.items():
            expected = source[r0:r0 + TILE_CELLS, c0:c0 + TILE_CELLS]
            if not np.array_equal(data[name], expected, equal_nan=True):
                failures.append(f"{entry['tile']}:{name}")
    return {
        "tile_count": len(entries),
        "feature_count": len(features),
        "all_exact": not failures,
        "failures": failures,
    }


def render_qa_overview(conditioned, accumulation, hand, stream, official_mask):
    import os
    config_dir = OUTPUT / ".matplotlib"
    config_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(config_dir)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    qa_path = OUTPUT / "qa_overview.png"
    stride = max(1, int(np.ceil(max(SHAPE) / 2500)))
    view = np.s_[::stride, ::stride]
    figure, axes = plt.subplots(2, 2, figsize=(12, 12), constrained_layout=True)
    dy, dx = np.gradient(conditioned[view])
    hillshade = np.clip(0.55 - 0.7 * dx + 0.7 * dy, 0, 1)
    axes[0, 0].imshow(np.flipud(hillshade), cmap="gray", vmin=0, vmax=1)
    axes[0, 0].set_title("Conditioned DTM hillshade")

    positive = accumulation[accumulation > 1]
    axes[0, 1].imshow(
        np.flipud(accumulation[view]), cmap="viridis",
        norm=LogNorm(vmin=1, vmax=max(float(np.percentile(positive, 99.9)), 2)),
    )
    axes[0, 1].set_title("Continuous D8 accumulation (log scale)")

    hand_max = max(float(np.percentile(hand, 98)), 1.0)
    axes[1, 0].imshow(np.flipud(hand[view]), cmap="magma", vmin=0, vmax=hand_max)
    axes[1, 0].set_title(f"Mosaic HAND (0–p98={hand_max:.1f} m)")

    stream_view = stream[view]
    official_view = official_mask[view]
    comparison = np.zeros((*stream_view.shape, 3), dtype=np.uint8)
    comparison[official_view] = (56, 189, 248)
    comparison[stream_view] = (168, 85, 247)
    comparison[official_view & stream_view] = (255, 255, 255)
    axes[1, 1].imshow(np.flipud(comparison))
    axes[1, 1].set_title("Streams: official cyan / D8 purple / overlap white")
    for axis in axes.ravel():
        axis.set_axis_off()
        for boundary in range(TILE_CELLS, SHAPE[1], TILE_CELLS):
            axis.axvline(boundary / stride - 0.5, color="lime", alpha=0.25, linewidth=0.5)
        for boundary in range(TILE_CELLS, SHAPE[0], TILE_CELLS):
            axis.axhline(boundary / stride - 0.5, color="lime", alpha=0.25, linewidth=0.5)
    figure.savefig(qa_path, dpi=140)
    plt.close(figure)
    return {
        "path": str(qa_path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": file_sha256(qa_path),
    }


def main(region="savinja", rebuild_dtm=False):
    configure_region(region)
    started = time.time()
    paths = tile_paths()
    missing = [path for path in paths if not path.exists()]
    if missing:
        raise SystemExit(f"Missing {len(missing)} {REGION_NAME} LAZ tiles, first: {missing[0]}")
    for required in (FLOW_LINES, VALIDITY, Q100):
        if not required.exists():
            raise SystemExit(f"Missing {required}")

    fingerprint = input_fingerprint(paths)
    dtm, ground_coverage, assembly = load_or_build_dtm(paths, fingerprint, rebuild_dtm)
    dtm = np.asarray(dtm, dtype=np.float64)
    official_mask, official_feature_count = rasterize_official_flow_lines()
    alignment = assess_flow_line_alignment(dtm, official_mask)

    print("Priority-flood conditioning unburned mosaic", flush=True)
    conditioned_unburned = kernels.priority_flood_fill(dtm, FILL_EPSILON_M)
    unburned_metrics = conditioning_metrics(dtm, conditioned_unburned)

    burn_input = gentle_network_burn(dtm, official_mask)
    print("Priority-flood conditioning gentle network-burn sensitivity", flush=True)
    conditioned_burned = kernels.priority_flood_fill(burn_input, FILL_EPSILON_M)
    burned_metrics = conditioning_metrics(burn_input, conditioned_burned)
    print("Continuous D8 receivers and accumulation", flush=True)
    recv_unburned = kernels.flow_receivers(conditioned_unburned, GRID_RES_M)
    accumulation_unburned = kernels.accumulate_receivers(conditioned_unburned, recv_unburned)
    variants = [("priority-flood-only", conditioned_unburned, recv_unburned, accumulation_unburned)]
    if alignment.get("accepted_for_gentle_burn"):
        recv_burned = kernels.flow_receivers(conditioned_burned, GRID_RES_M)
        accumulation_burned = kernels.accumulate_receivers(conditioned_burned, recv_burned)
        variants.append((
            "gentle-official-network-burn-plus-priority-flood",
            conditioned_burned,
            recv_burned,
            accumulation_burned,
        ))

    configuration_rows = configuration_sensitivity(variants)
    if REGION_NAME == "savinja":
        # D26 is a frozen accepted feature version; do not reshape it post hoc.
        selected_configuration = next(
            row for row in configuration_rows
            if row["conditioning_variant"] == "priority-flood-only"
            and row["stream_area_m2"] == DEFAULT_STREAM_AREA_M2
        )
        selection_rule = "frozen-d26-unburned-50000m2"
    else:
        selected_configuration = select_configuration(configuration_rows)
        selection_rule = "maximum-development-mosaic-hand-roc-auc-with-ap-tiebreak"

    conditioning_variant = selected_configuration["conditioning_variant"]
    selected_threshold = selected_configuration["stream_area_m2"]
    selected_tuple = next(item for item in variants if item[0] == conditioning_variant)
    _, conditioned, recv, accumulation_d8 = selected_tuple
    print("MFD sensitivity accumulation", flush=True)
    accumulation_mfd = kernels.mfd_accumulation(conditioned, GRID_RES_M)

    sensitivity = (
        threshold_sensitivity(accumulation_d8, official_mask, "d8")
        + threshold_sensitivity(accumulation_mfd, official_mask, "mfd")
    )
    stream = accumulation_d8 * GRID_RES_M**2 >= selected_threshold
    stream_mfd = accumulation_mfd * GRID_RES_M**2 >= selected_threshold
    union = stream | stream_mfd
    stream_jaccard = float((stream & stream_mfd).sum() / union.sum()) if union.any() else 1.0

    print(f"HAND, distance, and stream order at {selected_threshold:.0f} m²", flush=True)
    hand = kernels.hand_from_receivers(conditioned, recv, stream)
    channel_distance = distance_transform_edt(~stream) * GRID_RES_M
    stream_order = kernels.strahler_order(conditioned, recv, stream)
    outlet_id, downstream_stream_id = kernels.flow_labels(conditioned, recv, stream)
    neighborhood_cells = max(3, int(round(250.0 / GRID_RES_M)))
    local_minimum = minimum_filter(conditioned, size=neighborhood_cells, mode="nearest")
    local_maximum = maximum_filter(conditioned, size=neighborhood_cells, mode="nearest")
    valley_relative_elevation = conditioned - local_minimum
    local_relief = local_maximum - local_minimum

    seam_metrics = receiver_seam_metrics(recv, stream, official_mask)
    seam_metrics["conditioned_dtm"] = seam_jump_metrics(conditioned)
    seam_metrics["hand"] = seam_jump_metrics(hand)

    feature_arrays = {
        "conditioned_dtm": conditioned,
        "accumulation_cells": accumulation_d8.astype(np.float32),
        "hand_m": hand.astype(np.float32),
        "channel_distance_m": channel_distance.astype(np.float32),
        "stream_order": stream_order.astype(np.int16),
        "stream_mask": stream,
        "receiver_index": recv.reshape(SHAPE).astype(np.int32),
        "terminal_outlet_id": outlet_id.astype(np.int32),
        "downstream_stream_id": downstream_stream_id.astype(np.int32),
        "connected_to_stream": downstream_stream_id >= 0,
        "valley_relative_elevation_250m": valley_relative_elevation.astype(np.float32),
        "local_relief_250m": local_relief.astype(np.float32),
        "ground_coverage": ground_coverage,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    outputs = {name: save_feature(name, value) for name, value in feature_arrays.items()}
    tile_entries = cut_tiles(feature_arrays)
    tile_verification = verify_tile_exports(feature_arrays, tile_entries)
    if not tile_verification["all_exact"]:
        raise RuntimeError(f"Mosaic tile export mismatch: {tile_verification['failures'][:3]}")
    qa = render_qa_overview(conditioned, accumulation_d8, hand, stream, official_mask)
    benchmark = development_hand_benchmark(hand)

    manifest = {
        "schema_version": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "region_name": REGION_NAME,
        "region": REGION,
        "semantics": "continuous-mosaic-hydrology-features-not-flood-probability",
        "bounds_epsg3794": BOUNDS,
        "shape": SHAPE,
        "resolution_m": GRID_RES_M,
        "row_order": "south-to-north",
        "input_fingerprint": fingerprint,
        "assembly": assembly,
        "official_flow_lines": {
            "source": str(FLOW_LINES.relative_to(ROOT)).replace("\\", "/"),
            "feature_count_in_mosaic": official_feature_count,
            "alignment": alignment,
            "burn_depth_m": GENTLE_BURN_DEPTH_M,
            "burn_half_width_m": GENTLE_BURN_HALF_WIDTH_M,
        },
        "conditioning": {
            "selected_variant": conditioning_variant,
            "selection_rule": selection_rule,
            "development_configuration_sensitivity": configuration_rows,
            "epsilon_m": FILL_EPSILON_M,
            "unburned": unburned_metrics,
            "gentle_network_burn_sensitivity": burned_metrics,
            "least_cost_breaching": "not-implemented; gentle network burn is the bounded breach sensitivity",
        },
        "routing": {
            "primary": "d8",
            "sensitivity": "freeman-mfd-exponent-1.1",
            "selected_stream_area_m2": selected_threshold,
            "stream_threshold_sensitivity": sensitivity,
            "d8_mfd_stream_jaccard_at_selected_threshold": round(stream_jaccard, 4),
            "max_strahler_order": int(stream_order.max()),
        },
        "seams": seam_metrics,
        "development_only_hand_benchmark": benchmark,
        "outputs": outputs,
        "tiles": tile_entries,
        "tile_export_verification": tile_verification,
        "qa": qa,
        "runtime_seconds": round(time.time() - started, 2),
        "limitations": [
            "open-outer-mosaic-boundaries",
            "priority-fill-and-gentle-network-burn-not-engineering-breach-model",
            "official-network-alignment-does-not-prove-channel-bed-elevation",
            "underground-urban-drainage-not-represented",
            "locked-test-not-accessed-during-feature-engineering",
        ],
    }
    path = OUTPUT / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {path}")
    print(json.dumps({
        "selected_stream_area_m2": selected_threshold,
        "internal_sinks": seam_metrics["internal_sink_count"],
        "seam_crossings": seam_metrics["receiver_edges_crossing_tile_seams"],
        "development_benchmark": benchmark,
        "runtime_seconds": manifest["runtime_seconds"],
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=sorted(REGION_SPECS), default="savinja")
    parser.add_argument("--rebuild-dtm", action="store_true", help="Decode every region LAZ tile even if the DTM cache matches")
    args = parser.parse_args()
    main(region=args.region, rebuild_dtm=args.rebuild_dtm)
