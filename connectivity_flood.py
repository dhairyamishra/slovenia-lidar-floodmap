#!/usr/bin/env python3
"""Physical, connectivity-first river-stage and inundation calculations.

This module deliberately does not produce a generic flood-risk score.  It
derives the minimum water-surface elevation needed to reach a cell from a
drainage source, then evaluates an explicit stage scenario against original
terrain.  D19 remains a separate frozen diagnostic baseline.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

import kernels


MODEL_VERSION = "connectivity-stage-v1"
SCHEMA_VERSION = 1
MAX_CHANNEL_DISTANCE_M = 2_000.0

CLASS_UNAVAILABLE = np.uint8(0)
CLASS_DRY = np.uint8(1)
CLASS_INUNDATED = np.uint8(2)
CLASS_UNCERTAIN = np.uint8(3)
CLASS_EDGE_CONTAMINATED = np.uint8(4)
CLASS_NAMES = {
    0: "unavailable",
    1: "dry-under-scenario",
    2: "inundated-under-scenario",
    3: "uncertain-connectivity",
    4: "edge-contaminated",
}


def digest_json(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _shape_mask(value, shape, name, default=False):
    if value is None:
        return np.full(shape, default, dtype=bool)
    result = np.asarray(value, dtype=bool)
    if result.shape != shape:
        raise ValueError(f"{name} shape {result.shape} does not match terrain {shape}")
    return result


def effective_barrier_surface(original_dtm, barrier_crest_m=None, culvert_mask=None):
    """Raise terrain at vetted barriers and reopen only vetted culvert cells."""
    original = np.asarray(original_dtm, dtype=np.float64)
    surface = original.copy()
    if barrier_crest_m is not None:
        crest = np.asarray(barrier_crest_m, dtype=np.float64)
        if crest.shape != original.shape:
            raise ValueError("barrier_crest_m shape does not match terrain")
        known = np.isfinite(crest)
        surface[known] = np.maximum(surface[known], crest[known])
    culverts = _shape_mask(culvert_mask, original.shape, "culvert_mask")
    surface[culverts] = original[culverts]
    return surface


def boundary_mask(shape, width_cells=1):
    """Explicit domain-edge mask; contamination is never inferred as dry."""
    if width_cells < 1:
        raise ValueError("width_cells must be at least one")
    result = np.zeros(shape, dtype=bool)
    width = min(width_cells, max(shape))
    result[:width, :] = True
    result[-width:, :] = True
    result[:, :width] = True
    result[:, -width:] = True
    return result


def compute_access_stage(
    original_dtm,
    stream_mask,
    *,
    stream_reach_id=None,
    valid_mask=None,
    basin_id=None,
    channel_distance_m=None,
    barrier_crest_m=None,
    culvert_mask=None,
    barrier_uncertainty_mask=None,
    edge_mask=None,
    max_channel_distance_m=MAX_CHANNEL_DISTANCE_M,
):
    """Derive physical access elevation and required stage in metres.

    The minimax traversal is restricted to each drainage basin.  A low/flat
    cell receives no definitive result unless a stream source can reach it and
    it lies inside the declared applicability distance.
    """
    dtm = np.asarray(original_dtm, dtype=np.float64)
    streams = _shape_mask(stream_mask, dtm.shape, "stream_mask")
    valid = _shape_mask(valid_mask, dtm.shape, "valid_mask", default=True)
    uncertain = _shape_mask(
        barrier_uncertainty_mask, dtm.shape, "barrier_uncertainty_mask"
    )
    edge = _shape_mask(edge_mask, dtm.shape, "edge_mask")
    if basin_id is None:
        basin = np.zeros(dtm.shape, dtype=np.int64)
    else:
        basin = np.asarray(basin_id, dtype=np.int64)
        if basin.shape != dtm.shape:
            raise ValueError("basin_id shape does not match terrain")
    surface = effective_barrier_surface(dtm, barrier_crest_m, culvert_mask)
    access, source, path_uncertain, path_edge = kernels.minimax_access(
        surface, streams, valid, basin, uncertain, edge
    )
    connected = source >= 0
    if stream_reach_id is None:
        stream_reaches = np.arange(dtm.size, dtype=np.int64).reshape(dtm.shape)
    else:
        stream_reaches = np.asarray(stream_reach_id, dtype=np.int64)
        if stream_reaches.shape != dtm.shape:
            raise ValueError("stream_reach_id shape does not match terrain")
    reach_id = np.full(dtm.shape, -1, dtype=np.int64)
    reach_id[connected] = stream_reaches.ravel()[source[connected]]
    source_elevation = np.full(dtm.shape, np.nan, dtype=np.float64)
    source_elevation[connected] = dtm.ravel()[source[connected]]
    required_stage = access - source_elevation
    required_stage[~connected] = np.nan
    required_stage = np.maximum(required_stage, 0.0)

    applicability = valid & connected
    if channel_distance_m is not None:
        distance = np.asarray(channel_distance_m, dtype=np.float64)
        if distance.shape != dtm.shape:
            raise ValueError("channel_distance_m shape does not match terrain")
        applicability &= np.isfinite(distance) & (distance <= max_channel_distance_m)

    return {
        "access_elevation_m": access,
        "required_stage_m": required_stage,
        "source_index": source,
        "source_channel_elevation_m": source_elevation,
        "reach_id": reach_id,
        "connected": connected,
        "applicability": applicability,
        "barrier_uncertainty": path_uncertain.astype(bool),
        "edge_contamination": path_edge.astype(bool),
        "effective_barrier_surface_m": surface,
    }


def validate_scenario(scenario):
    """Validate forcing and publication gates without inventing missing data."""
    if not isinstance(scenario, dict):
        raise ValueError("scenario must be an object")
    if scenario.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"scenario.schema_version must be {SCHEMA_VERSION}")
    if not scenario.get("id") or not scenario.get("source"):
        raise ValueError("scenario requires id and source provenance")
    forcing = scenario.get("forcing") or {}
    allowed = {
        "uniform_stage_above_channel",
        "reach_stage_above_channel",
        "reach_water_surface_elevation",
        "reach_discharge",
    }
    if forcing.get("type") not in allowed:
        raise ValueError(f"scenario forcing.type must be one of {sorted(allowed)}")
    if forcing["type"] == "uniform_stage_above_channel":
        value = forcing.get("value_m")
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError("uniform stage requires nonnegative forcing.value_m")
    elif forcing["type"] != "reach_discharge":
        values = forcing.get("values")
        if not isinstance(values, dict) or not values:
            raise ValueError("reach-specific forcing requires a nonempty values object")
        if any(not isinstance(v, (int, float)) for v in values.values()):
            raise ValueError("all reach-specific forcing values must be numeric")
    else:
        values = forcing.get("values_m3s")
        curves = forcing.get("rating_curves")
        if not isinstance(values, dict) or not values:
            raise ValueError("reach discharge requires nonempty values_m3s")
        if not isinstance(curves, dict) or not curves:
            raise ValueError("reach discharge requires rating_curves")
        for key, discharge in values.items():
            if not isinstance(discharge, (int, float)) or discharge < 0:
                raise ValueError("reach discharge values must be nonnegative numbers")
            curve = curves.get(str(key))
            if not isinstance(curve, dict):
                raise ValueError(f"missing rating curve for reach {key}")
            q = curve.get("discharge_m3s")
            stage = curve.get("stage_above_channel_m")
            if not isinstance(q, list) or not isinstance(stage, list) or len(q) != len(stage) or len(q) < 2:
                raise ValueError("rating curves require paired discharge/stage arrays")
            if any(not isinstance(v, (int, float)) for v in q + stage):
                raise ValueError("rating curve values must be numeric")
            if any(q[index] >= q[index + 1] for index in range(len(q) - 1)):
                raise ValueError("rating-curve discharge must increase strictly")
            if any(value < 0 for value in stage) or any(stage[index] > stage[index + 1] for index in range(len(stage) - 1)):
                raise ValueError("rating-curve stage must be nonnegative and monotonic")

    publication = scenario.get("publication_status", "research-only")
    if publication not in {"research-only", "approved-observed-hindcast"}:
        raise ValueError("invalid publication_status")
    if publication == "approved-observed-hindcast":
        gate = scenario.get("scientific_gate") or {}
        required = {
            "roc_auc_gain", "average_precision_gain", "iou_gain",
            "low_flat_reduction", "recall_change", "bias_ratio",
            "counterfactual_passed",
        }
        if set(gate) < required:
            raise ValueError("approved scenario is missing scientific_gate results")
        passes = (
            gate["roc_auc_gain"] >= 0.03
            and gate["average_precision_gain"] >= 0.03
            and gate["iou_gain"] >= 0.05
            and gate["low_flat_reduction"] >= 0.30
            and gate["recall_change"] >= -0.05
            and 0.80 <= gate["bias_ratio"] <= 1.25
            and gate["counterfactual_passed"] is True
        )
        if not passes:
            raise ValueError("approved scenario does not pass the frozen scientific gate")
    return scenario


def load_scenario(path):
    path = Path(path)
    return validate_scenario(json.loads(path.read_text(encoding="utf-8")))


def _reach_water_surface(access, scenario):
    source = access["source_index"]
    reach = access.get("reach_id", source)
    source_z = access["source_channel_elevation_m"]
    forcing = scenario["forcing"]
    water = np.full(source.shape, np.nan, dtype=np.float64)
    connected = source >= 0
    if forcing["type"] == "uniform_stage_above_channel":
        water[connected] = source_z[connected] + float(forcing["value_m"])
        return water

    if forcing["type"] == "reach_discharge":
        for key, discharge in forcing["values_m3s"].items():
            source_id = int(key)
            curve = forcing["rating_curves"][str(key)]
            stage = float(np.interp(
                float(discharge),
                np.asarray(curve["discharge_m3s"], dtype=float),
                np.asarray(curve["stage_above_channel_m"], dtype=float),
            ))
            mask = reach == source_id
            water[mask] = source_z[mask] + stage
        return water

    values = {int(key): float(value) for key, value in forcing["values"].items()}
    for source_id, value in values.items():
        mask = reach == source_id
        if forcing["type"] == "reach_stage_above_channel":
            water[mask] = source_z[mask] + value
        else:
            water[mask] = value
    return water


def scenario_inundation(original_dtm, access, scenario):
    """Evaluate one explicit stage scenario; no forcing means no classification."""
    scenario = validate_scenario(scenario)
    dtm = np.asarray(original_dtm, dtype=np.float64)
    if dtm.shape != access["required_stage_m"].shape:
        raise ValueError("terrain and access-stage shapes differ")
    water = _reach_water_surface(access, scenario)
    available = access["applicability"] & np.isfinite(water)
    candidate = (
        available
        & (water >= access["access_elevation_m"])
        & (water > dtm)
    )
    depth = np.full(dtm.shape, np.nan, dtype=np.float32)
    depth[available] = 0.0
    depth[candidate] = (water[candidate] - dtm[candidate]).astype(np.float32)

    classification = np.full(dtm.shape, CLASS_UNAVAILABLE, dtype=np.uint8)
    classification[available] = CLASS_DRY
    classification[candidate] = CLASS_INUNDATED
    classification[available & access["barrier_uncertainty"]] = CLASS_UNCERTAIN
    classification[available & access["edge_contamination"]] = CLASS_EDGE_CONTAMINATED
    return {
        "water_surface_elevation_m": water.astype(np.float32),
        "depth_m": depth,
        "inundated_candidate": candidate,
        "scenario_class": classification,
        "scenario": scenario,
        "scenario_digest": digest_json(scenario),
    }


def model_definition():
    definition = {
        "model_version": MODEL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "semantics": "physical-minimum-access-stage-and-scenario-depth-not-probability",
        "primary_outputs": ["required_stage_m", "scenario_depth_m"],
        "riverine_rules": [
            "assigned-to-drainage-source",
            "stage-accessible-minimax-path",
            "water-surface-above-original-terrain",
        ],
        "excluded_as_direct_causes": [
            "absolute-elevation", "flatness", "inverted-slope", "ndvi", "canopy",
        ],
        "default_max_channel_distance_m": MAX_CHANNEL_DISTANCE_M,
        "scenario_classes": CLASS_NAMES,
    }
    definition["definition_digest"] = digest_json(definition)
    return definition


def write_zarr_store(path, arrays, metadata, chunk_shape=(500, 500)):
    """Write restartable chunked analytical arrays without making Zarr mandatory.

    The dependency is loaded only for the whole-domain storage path so the
    verified NumPy/Numba reference and unit tests remain usable independently.
    """
    try:
        import zarr
    except ImportError as exc:  # pragma: no cover - exercised only without optional backend
        raise RuntimeError(
            "Zarr storage requested but zarr is not installed; install requirements.txt"
        ) from exc
    root = zarr.open_group(str(path), mode="w")
    for key, value in sorted(metadata.items()):
        root.attrs[key] = value
    for name, value in arrays.items():
        array = np.asarray(value)
        chunks = tuple(min(size, chunk) for size, chunk in zip(array.shape, chunk_shape))
        root.create_array(name, data=array, chunks=chunks, overwrite=True)
    return Path(path)
