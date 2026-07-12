#!/usr/bin/env python3
"""Audit committed flood-susceptibility outputs and full-grid samples.

The report is intentionally descriptive: it detects display saturation,
candidate concentration, score/elevation association, and factor shortcuts. It
does not claim model skill until independent official/observed labels exist.

Usage:
    python analyze_model.py
    python analyze_model.py --strict
    python analyze_model.py --output-dir output/diagnostics

Run ``pipeline.py`` first to populate ``output/diagnostics/samples/*.npz``.
Without samples, the script still audits committed PNGs and candidate outputs
but marks full-grid altitude/factor diagnostics unavailable.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parent
WEBDATA = ROOT / "web" / "data"
DEFAULT_SAMPLE_DIR = ROOT / "output" / "diagnostics" / "samples"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "diagnostics"

DEFAULT_THRESHOLDS = {
    "median_warm_fraction_max": 0.65,
    "median_strong_red_fraction_max": 0.35,
    "candidate_single_tile_fraction_max": 0.15,
    "abs_full_grid_score_elevation_pearson_max": 0.35,
    "abs_full_grid_score_elevation_spearman_max": 0.35,
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def finite_pair(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    mask = np.isfinite(a) & np.isfinite(b)
    return a[mask], b[mask]


def pearson(a, b):
    a, b = finite_pair(a, b)
    if a.size < 2 or np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def average_ranks(values):
    """Return one-based average ranks with deterministic tie handling."""
    values = np.asarray(values)
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks = np.empty(values.size, dtype=np.float64)
    start = 0
    while start < values.size:
        end = start + 1
        while end < values.size and sorted_values[end] == sorted_values[start]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    return ranks


def spearman(a, b):
    a, b = finite_pair(a, b)
    if a.size < 2:
        return None
    return pearson(average_ranks(a), average_ranks(b))


def round_or_none(value, digits=4):
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def region_cache():
    path = ROOT / ".tile_region_cache.json"
    if not path.exists():
        return {}
    return read_json(path)


def tile_region(tile, cache):
    value = cache.get(tile, "unknown")
    if isinstance(value, dict):
        return value.get("region", "unknown")
    return value


def audit_pngs():
    rows = []
    for path in sorted((WEBDATA / "tiles").glob("*/susceptibility.png")):
        image = Image.open(path).convert("RGBA").resize((100, 100), Image.Resampling.BILINEAR)
        rgba = np.asarray(image, dtype=np.float32)
        valid = rgba[:, :, 3] > 0
        valid_n = int(valid.sum())
        if not valid_n:
            rows.append({
                "tile": path.parent.name,
                "valid_pixels": 0,
                "warm_fraction": None,
                "strong_red_fraction": None,
            })
            continue
        red, _, blue = rgba[:, :, 0], rgba[:, :, 1], rgba[:, :, 2]
        warm = valid & (red > blue)
        strong_red = valid & (red > 180) & (red > 1.25 * blue)
        rows.append({
            "tile": path.parent.name,
            "valid_pixels": valid_n,
            "warm_fraction": float(warm.sum() / valid_n),
            "strong_red_fraction": float(strong_red.sum() / valid_n),
        })

    warm = [r["warm_fraction"] for r in rows if r["warm_fraction"] is not None]
    red = [r["strong_red_fraction"] for r in rows if r["strong_red_fraction"] is not None]
    return {
        "tile_count": len(rows),
        "valid_tile_count": len(warm),
        "median_warm_fraction": round_or_none(np.median(warm) if warm else None),
        "median_strong_red_fraction": round_or_none(np.median(red) if red else None),
        "p90_warm_fraction": round_or_none(np.percentile(warm, 90) if warm else None),
        "p90_strong_red_fraction": round_or_none(np.percentile(red, 90) if red else None),
        "highest_warm_tiles": sorted(
            [r for r in rows if r["warm_fraction"] is not None],
            key=lambda r: r["warm_fraction"], reverse=True,
        )[:10],
        "method": (
            "RGBA PNG resized to 100x100; warm means R>B; strongly red means "
            "R>180 and R>1.25*B. This is a display saturation diagnostic, not model skill."
        ),
    }


def audit_candidates(cache):
    path = WEBDATA / "candidates.json"
    candidates = read_json(path) if path.exists() else []
    by_tile = Counter(c.get("tile", "unknown") for c in candidates)
    by_region = Counter(tile_region(c.get("tile", ""), cache) for c in candidates)
    scores = np.array([c.get("score", np.nan) for c in candidates], dtype=np.float64)
    elev = np.array([c.get("elevation_m", np.nan) for c in candidates], dtype=np.float64)
    return {
        "count": len(candidates),
        "score_elevation_pearson": round_or_none(pearson(scores, elev)),
        "score_elevation_spearman": round_or_none(spearman(scores, elev)),
        "warning": "Candidate-tail correlations are selection-biased and are not a full-grid altitude audit.",
        "region_counts": dict(sorted(by_region.items())),
        "top_tile_counts": dict(by_tile.most_common(15)),
        "single_tile_max_fraction": round_or_none(
            max(by_tile.values()) / len(candidates) if candidates else None
        ),
        "elevation_m": {
            "min": round_or_none(np.nanmin(elev) if elev.size else None, 2),
            "median": round_or_none(np.nanmedian(elev) if elev.size else None, 2),
            "max": round_or_none(np.nanmax(elev) if elev.size else None, 2),
        },
    }


def load_samples(sample_dir: Path):
    records = defaultdict(list)
    metadata = []
    for path in sorted(sample_dir.glob("*.npz")):
        with np.load(path, allow_pickle=False) as data:
            region = str(data["region"].item())
            sample_count = int(data["score"].size)
            metadata.append({
                "tile": str(data["tile"].item()),
                "region": region,
                "model_version": str(data["model_version"].item()),
                "sample_count": sample_count,
            })
            records["_region"].append(np.full(sample_count, region, dtype="U32"))
            records["_tile"].append(np.full(sample_count, str(data["tile"].item()), dtype="U16"))
            for key in data.files:
                if key in {"tile", "region", "model_version"}:
                    continue
                records[key].append(np.asarray(data[key]))
    return {key: np.concatenate(parts) for key, parts in records.items()}, metadata


def weighted_composite(arrays, weights, excluded=(), included=None):
    excluded = set(excluded)
    included = set(included) if included is not None else None
    active = [w for w in weights
              if w["factor"] not in excluded
              and (included is None or w["factor"] in included)]
    total_weight = sum(float(w["weight"]) for w in active)
    if total_weight <= 0:
        raise ValueError("Ablation has no active model factors")
    result = np.zeros_like(arrays["score"], dtype=np.float64)
    for item in active:
        value = arrays[f"norm_{item['factor']}"].astype(np.float64)
        if item.get("invert"):
            value = 1.0 - value
        result += float(item["weight"]) * value
    return result / total_weight


def audit_samples(sample_dir: Path, model_definition=None):
    arrays, metadata = load_samples(sample_dir)
    if not metadata:
        return {
            "available": False,
            "sample_dir": str(sample_dir),
            "reason": "Run pipeline.py to generate deterministic full-grid diagnostic samples.",
        }

    score = arrays["score"]
    elev = arrays["raw_elev"]
    factors = {}
    for key in sorted(k for k in arrays if k.startswith("norm_")):
        factors[key.removeprefix("norm_")] = {
            "score_pearson": round_or_none(pearson(arrays[key], score)),
            "score_spearman": round_or_none(spearman(arrays[key], score)),
        }

    display = arrays["display_score"]
    per_region = {}
    for region in sorted(set(arrays["_region"].tolist())):
        mask = arrays["_region"] == region
        per_region[region] = {
            "sample_count": int(mask.sum()),
            "score_elevation_pearson": round_or_none(pearson(score[mask], elev[mask])),
            "score_elevation_spearman": round_or_none(spearman(score[mask], elev[mask])),
        }

    ablations = {}
    weights = (model_definition or {}).get("weights", [])
    if weights and all(f"norm_{w['factor']}" in arrays for w in weights):
        scenarios = {
            "current_unsmoothed": {},
            "without_elevation": {"excluded": ["elev"]},
            "without_slope": {"excluded": ["slope"]},
            "without_elevation_and_slope": {"excluded": ["elev", "slope"]},
            "drainage_only_hand_twi": {"included": ["hand", "twi"]},
        }
        for name, options in scenarios.items():
            ablated = weighted_composite(arrays, weights, **options)
            ablations[name] = {
                "score_elevation_pearson": round_or_none(pearson(ablated, elev)),
                "score_elevation_spearman": round_or_none(spearman(ablated, elev)),
            }
    return {
        "available": True,
        "sample_dir": str(sample_dir),
        "tile_count": len(metadata),
        "sample_count": int(score.size),
        "model_versions": sorted({m["model_version"] for m in metadata}),
        "score_elevation_pearson": round_or_none(pearson(score, elev)),
        "score_elevation_spearman": round_or_none(spearman(score, elev)),
        "per_region_score_elevation": per_region,
        "descriptive_ablations": ablations,
        "display_fraction_ge_0_8": round_or_none(float(np.mean(display >= 0.8))),
        "display_fraction_ge_0_9": round_or_none(float(np.mean(display >= 0.9))),
        "factor_score_associations": factors,
        "sampling_warning": (
            "Samples are stratified by score decile, so distributional area fractions are diagnostic, "
            "not unbiased land-area estimates. Correlations are suitable for shortcut screening but "
            "must be repeated on validation labels and spatial blocks. Ablations recompute the unsmoothed "
            "weighted index and diagnose shortcut sensitivity; they do not measure predictive skill."
        ),
    }


def apply_thresholds(audit, thresholds):
    checks = []

    def add(name, value, limit, mode="max"):
        if value is None:
            status = "unavailable"
        elif mode == "abs_max":
            status = "pass" if abs(value) <= limit else "fail"
        else:
            status = "pass" if value <= limit else "fail"
        checks.append({"name": name, "value": value, "limit": limit, "status": status})

    png = audit["display"]
    add("median_warm_fraction", png["median_warm_fraction"], thresholds["median_warm_fraction_max"])
    add("median_strong_red_fraction", png["median_strong_red_fraction"],
        thresholds["median_strong_red_fraction_max"])
    cand = audit["candidates"]
    add("candidate_single_tile_fraction", cand["single_tile_max_fraction"],
        thresholds["candidate_single_tile_fraction_max"])
    samples = audit["full_grid_samples"]
    add("full_grid_score_elevation_pearson", samples.get("score_elevation_pearson"),
        thresholds["abs_full_grid_score_elevation_pearson_max"], "abs_max")
    add("full_grid_score_elevation_spearman", samples.get("score_elevation_spearman"),
        thresholds["abs_full_grid_score_elevation_spearman_max"], "abs_max")
    return checks


def markdown_report(audit):
    failures = [c for c in audit["checks"] if c["status"] == "fail"]
    unavailable = [c for c in audit["checks"] if c["status"] == "unavailable"]
    lines = [
        "# Flood Model Audit",
        "",
        f"Generated: {audit['generated']}",
        "",
        "> This report diagnoses current outputs. It does not measure flood-prediction skill because independent validation labels are not yet wired into the pipeline.",
        "",
        "## Gate status",
        "",
        f"- Failed checks: **{len(failures)}**",
        f"- Unavailable checks: **{len(unavailable)}**",
        f"- Overall: **{'FAIL' if failures else 'PASS (available checks only)'}**",
        "",
        "| Check | Value | Limit | Status |",
        "|---|---:|---:|---|",
    ]
    for check in audit["checks"]:
        lines.append(f"| {check['name']} | {check['value']} | {check['limit']} | {check['status']} |")

    display = audit["display"]
    lines += [
        "",
        "## Display saturation",
        "",
        f"- Tiles inspected: {display['tile_count']}",
        f"- Median warm fraction: {display['median_warm_fraction']}",
        f"- Median strongly red fraction: {display['median_strong_red_fraction']}",
        f"- Method: {display['method']}",
        "",
        "## Candidate concentration",
        "",
        f"- Candidates: {audit['candidates']['count']}",
        f"- Largest single-tile share: {audit['candidates']['single_tile_max_fraction']}",
        f"- Candidate-tail score/elevation Pearson: {audit['candidates']['score_elevation_pearson']}",
        f"- Warning: {audit['candidates']['warning']}",
        "",
        "## Full-grid diagnostic samples",
        "",
    ]
    samples = audit["full_grid_samples"]
    if samples["available"]:
        lines += [
            f"- Tiles sampled: {samples['tile_count']}",
            f"- Samples: {samples['sample_count']}",
            f"- Score/elevation Pearson: {samples['score_elevation_pearson']}",
            f"- Score/elevation Spearman: {samples['score_elevation_spearman']}",
            "",
            "### Factor/score associations",
            "",
            "| Factor | Pearson | Spearman |",
            "|---|---:|---:|",
        ]
        for factor, values in samples["factor_score_associations"].items():
            lines.append(f"| {factor} | {values['score_pearson']} | {values['score_spearman']} |")
        lines += [
            "",
            "### Score/elevation association by region",
            "",
            "| Region | Samples | Pearson | Spearman |",
            "|---|---:|---:|---:|",
        ]
        for region, values in samples["per_region_score_elevation"].items():
            lines.append(
                f"| {region} | {values['sample_count']} | "
                f"{values['score_elevation_pearson']} | {values['score_elevation_spearman']} |"
            )
        lines += [
            "",
            "### Descriptive altitude ablations (not validation skill)",
            "",
            "| Scenario | Pearson | Spearman |",
            "|---|---:|---:|",
        ]
        for scenario, values in samples["descriptive_ablations"].items():
            lines.append(
                f"| {scenario} | {values['score_elevation_pearson']} | "
                f"{values['score_elevation_spearman']} |"
            )
    else:
        lines.append(f"Unavailable: {samples['reason']}")

    lines += [
        "",
        "## Next gate",
        "",
        "Acquire and rasterize official/observed flood labels, then add spatially blocked skill metrics and factor ablations. Do not select new weights from this descriptive report alone.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-dir", type=Path, default=DEFAULT_SAMPLE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when an available gate fails")
    args = parser.parse_args()

    cache = region_cache()
    manifest_path = WEBDATA / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    audit = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "manifest_model": manifest.get("model"),
        "manifest_generated": manifest.get("generated"),
        "thresholds": DEFAULT_THRESHOLDS,
        "display": audit_pngs(),
        "candidates": audit_candidates(cache),
        "full_grid_samples": audit_samples(args.sample_dir, manifest.get("model")),
    }
    audit["checks"] = apply_thresholds(audit, DEFAULT_THRESHOLDS)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "model_audit.json"
    md_path = args.output_dir / "model_audit.md"
    json_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(audit), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")

    failures = [c for c in audit["checks"] if c["status"] == "fail"]
    for check in audit["checks"]:
        print(f"  {check['status'].upper():11s} {check['name']}: {check['value']} (limit {check['limit']})")
    if args.strict and failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
