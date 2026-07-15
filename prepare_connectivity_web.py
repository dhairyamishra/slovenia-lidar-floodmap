#!/usr/bin/env python3
"""Export connectivity-first physical products into optional web tile layers.

Minimum-stage surfaces may be exported as explicitly experimental physical
diagnostics.  Scenario depth is exported only after the scenario declares and
passes the frozen observed-event gate, unless ``--allow-research`` is supplied
for local technical review.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

import connectivity_flood as flood


ROOT = Path(__file__).resolve().parent
WEB_DATA = ROOT / "web" / "data"
WEB_MANIFEST = WEB_DATA / "manifest.json"
MOSAIC_ROOT = ROOT / "output" / "mosaic"


def _rgba(shape):
    return np.zeros((*shape, 4), dtype=np.uint8)


def required_stage_rgba(required_stage, applicability, uncertainty, edge):
    stage = np.asarray(required_stage, dtype=float)
    rgba = _rgba(stage.shape)
    assessed = np.asarray(applicability, dtype=bool) & np.isfinite(stage)
    bands = [
        (stage <= 0.5, (7, 89, 133, 235)),
        ((stage > 0.5) & (stage <= 1.0), (2, 132, 199, 225)),
        ((stage > 1.0) & (stage <= 2.0), (56, 189, 248, 205)),
        ((stage > 2.0) & (stage <= 3.0), (186, 230, 253, 150)),
        (stage > 3.0, (148, 163, 184, 45)),
    ]
    for mask, colour in bands:
        rgba[assessed & mask] = colour
    rgba[assessed & np.asarray(uncertainty, dtype=bool)] = (245, 158, 11, 190)
    rgba[assessed & np.asarray(edge, dtype=bool)] = (148, 163, 184, 175)
    return rgba


def depth_rgba(depth, scenario_class):
    depth = np.asarray(depth, dtype=float)
    classes = np.asarray(scenario_class, dtype=np.uint8)
    rgba = _rgba(depth.shape)
    wet = (classes == flood.CLASS_INUNDATED) & np.isfinite(depth)
    bands = [
        (depth < 0.5, (186, 230, 253, 210)),
        ((depth >= 0.5) & (depth < 1.5), (56, 189, 248, 220)),
        (depth >= 1.5, (7, 89, 133, 235)),
    ]
    for mask, colour in bands:
        rgba[wet & mask] = colour
    rgba[classes == flood.CLASS_UNCERTAIN] = (245, 158, 11, 180)
    rgba[classes == flood.CLASS_EDGE_CONTAMINATED] = (148, 163, 184, 170)
    return rgba


def applicability_rgba(applicability, uncertainty, edge):
    applicability = np.asarray(applicability, dtype=bool)
    uncertainty = np.asarray(uncertainty, dtype=bool)
    edge = np.asarray(edge, dtype=bool)
    rgba = _rgba(applicability.shape)
    row, col = np.indices(applicability.shape)
    hatch = ((row + col) % 8) < 2
    rgba[~applicability & hatch] = (100, 116, 139, 105)
    rgba[uncertainty & hatch] = (245, 158, 11, 145)
    rgba[edge & hatch] = (203, 213, 225, 150)
    return rgba


def encode_value_index(value_m, class_code):
    """Encode centimetres in R/G and semantic class in B for exact popups."""
    values = np.asarray(value_m, dtype=float)
    classes = np.asarray(class_code, dtype=np.uint8)
    if values.shape != classes.shape:
        raise ValueError("value and class shapes differ")
    centimetres = np.full(values.shape, 65535, dtype=np.uint16)
    finite = np.isfinite(values)
    centimetres[finite] = np.clip(np.rint(values[finite] * 100), 0, 65534).astype(np.uint16)
    rgb = np.zeros((*values.shape, 3), dtype=np.uint8)
    rgb[..., 0] = centimetres >> 8
    rgb[..., 1] = centimetres & 255
    rgb[..., 2] = classes
    return rgb


def encode_uint24_index(values):
    """Encode nonnegative integer IDs in RGB; 0xffffff means unavailable."""
    values = np.asarray(values, dtype=np.int64)
    encoded = np.where(values >= 0, values, 0xFFFFFF)
    if np.any(encoded > 0xFFFFFF):
        raise ValueError("integer index exceeds 24-bit web encoding")
    rgb = np.empty((*values.shape, 3), dtype=np.uint8)
    rgb[..., 0] = encoded >> 16
    rgb[..., 1] = (encoded >> 8) & 255
    rgb[..., 2] = encoded & 255
    return rgb


def _save(array, path, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.flipud(array), mode=mode).save(path, optimize=True)


def _safe_id(value):
    result = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    if not result:
        raise ValueError("scenario id has no filesystem-safe characters")
    return result


def export_region(region, *, allow_research=False, web_manifest_path=WEB_MANIFEST):
    base = MOSAIC_ROOT / region
    mosaic_manifest_path = base / "manifest.json"
    if not mosaic_manifest_path.exists():
        raise SystemExit(f"Missing {mosaic_manifest_path}; run mosaic_hydrology.py first")
    mosaic = json.loads(mosaic_manifest_path.read_text(encoding="utf-8"))
    model = mosaic.get("connectivity_model")
    if not model or not model.get("minimum_stage_available"):
        raise SystemExit("Mosaic has no connectivity-first products")

    scenario = model.get("scenario")
    scenario_exported = False
    scenario_id = None
    if scenario:
        flood.validate_scenario(scenario)
        scenario_exported = (
            scenario.get("publication_status") == "approved-observed-hindcast"
            or allow_research
        )
        scenario_id = _safe_id(scenario["id"])

    web_manifest_path = Path(web_manifest_path)
    web = json.loads(web_manifest_path.read_text(encoding="utf-8"))
    web_tiles = {tile["name"]: tile for tile in web["tiles"]}
    exported = []
    for entry in mosaic["tiles"]:
        tile_name = entry["tile"]
        if tile_name not in web_tiles:
            continue
        with np.load(ROOT / entry["path"], allow_pickle=False) as loaded:
            data = {name: loaded[name] for name in loaded.files}
        required = data["required_stage_m"]
        applicability = data["riverine_applicability"]
        uncertainty = data["barrier_uncertainty"]
        edge = data["edge_contamination"]
        semantic = np.where(edge, 4, np.where(uncertainty, 3, np.where(applicability, 1, 0))).astype(np.uint8)

        directory = WEB_DATA / "tiles" / tile_name
        required_path = directory / "required_stage.png"
        required_index_path = directory / "required_stage_index.png"
        reach_index_path = directory / "reach_index.png"
        applicability_path = directory / "riverine_applicability.png"
        _save(required_stage_rgba(required, applicability, uncertainty, edge), required_path, "RGBA")
        _save(encode_value_index(required, semantic), required_index_path, "RGB")
        _save(encode_uint24_index(data["reach_id"]), reach_index_path, "RGB")
        _save(applicability_rgba(applicability, uncertainty, edge), applicability_path, "RGBA")
        files = {
            "required_stage": f"tiles/{tile_name}/{required_path.name}",
            "required_stage_index": f"tiles/{tile_name}/{required_index_path.name}",
            "reach_index": f"tiles/{tile_name}/{reach_index_path.name}",
            "applicability": f"tiles/{tile_name}/{applicability_path.name}",
            "domain": region,
            "scenarios": {},
        }
        if scenario_exported:
            depth = data["scenario_depth_m"]
            classes = data["scenario_class"]
            depth_path = directory / f"scenario_depth_{scenario_id}.png"
            depth_index_path = directory / f"scenario_depth_{scenario_id}_index.png"
            _save(depth_rgba(depth, classes), depth_path, "RGBA")
            _save(encode_value_index(depth, classes), depth_index_path, "RGB")
            files["scenarios"][scenario_id] = {
                "depth": f"tiles/{tile_name}/{depth_path.name}",
                "depth_index": f"tiles/{tile_name}/{depth_index_path.name}",
            }
        web_tiles[tile_name]["files"]["connectivity"] = files
        exported.append(tile_name)

    existing = web.get("connectivity_model") or {"domains": {}}
    existing.update({
        "schema_version": flood.SCHEMA_VERSION,
        "model_version": flood.MODEL_VERSION,
        "semantics": "minimum-access-stage-and-explicit-scenario-depth-not-probability",
        "definition_digest": model["definition_digest"],
        "domains": existing.get("domains", {}),
    })
    existing["domains"][region] = {
        "tile_count": len(exported),
        "minimum_stage_available": True,
        "publication_status": model["publication_status"],
        "scenario": ({
            "id": scenario_id,
            "label": scenario["id"],
            "source": scenario["source"],
            "publication_status": scenario["publication_status"],
        } if scenario_exported else None),
    }
    web["connectivity_model"] = existing
    web_manifest_path.write_text(json.dumps(web, indent=2), encoding="utf-8")
    return {"region": region, "tile_count": len(exported), "scenario_exported": scenario_exported}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=("savinja", "ljubljana"), required=True)
    parser.add_argument("--allow-research", action="store_true", help="Export unapproved scenario only for local technical review")
    args = parser.parse_args()
    print(json.dumps(export_region(args.region, allow_research=args.allow_research), indent=2))
