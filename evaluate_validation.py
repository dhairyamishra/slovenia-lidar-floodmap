#!/usr/bin/env python3
"""Evaluate diagnostic samples against official IKPN Q100 polygons.

Only cells inside the official IKPN validity polygon are evaluated. Cells
outside that domain are unknown, not dry negatives. Metrics are descriptive
until spatially blocked folds and event-observed labels are added.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from shapely import contains_xy, from_geojson, union_all

import analyze_model


ROOT = Path(__file__).resolve().parent
SAMPLE_DIR = ROOT / "output" / "diagnostics" / "samples"
VALIDATION_DIR = ROOT / "validation" / "data"
OUTPUT_DIR = ROOT / "output" / "diagnostics"


def load_geometry_union(path: Path):
    dataset = json.loads(path.read_text(encoding="utf-8"))
    geometries = [
        from_geojson(json.dumps(feature["geometry"]))
        for feature in dataset.get("features", [])
        if feature.get("geometry")
    ]
    if not geometries:
        raise ValueError(f"No geometries found in {path}")
    return union_all(geometries), len(geometries)


def roc_auc(labels, scores):
    labels = np.asarray(labels, dtype=bool)
    scores = np.asarray(scores, dtype=np.float64)
    valid = np.isfinite(scores)
    labels, scores = labels[valid], scores[valid]
    positives = int(labels.sum())
    negatives = int((~labels).sum())
    if positives == 0 or negatives == 0:
        return None
    ranks = analyze_model.average_ranks(scores)
    value = (ranks[labels].sum() - positives * (positives + 1) / 2) / (positives * negatives)
    return float(value)


def average_precision(labels, scores):
    labels = np.asarray(labels, dtype=bool)
    scores = np.asarray(scores, dtype=np.float64)
    valid = np.isfinite(scores)
    labels, scores = labels[valid], scores[valid]
    positives = int(labels.sum())
    if positives == 0:
        return None
    order = np.argsort(-scores, kind="mergesort")
    ordered = labels[order]
    precision = np.cumsum(ordered) / np.arange(1, ordered.size + 1)
    return float(precision[ordered].sum() / positives)


def threshold_metrics(labels, scores, top_fraction):
    threshold = float(np.quantile(scores, 1.0 - top_fraction))
    predicted = scores >= threshold
    tp = int(np.sum(predicted & labels))
    fp = int(np.sum(predicted & ~labels))
    fn = int(np.sum(~predicted & labels))
    tn = int(np.sum(~predicted & ~labels))
    return {
        "top_fraction": top_fraction,
        "threshold": round(threshold, 6),
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else None,
        "f1": round(2 * tp / (2 * tp + fp + fn), 4) if 2 * tp + fp + fn else None,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }


def metric_block(labels, scores):
    return {
        "sample_count": int(labels.size),
        "positive_count": int(labels.sum()),
        "positive_fraction": round(float(labels.mean()), 4) if labels.size else None,
        "roc_auc": analyze_model.round_or_none(roc_auc(labels, scores)),
        "average_precision": analyze_model.round_or_none(average_precision(labels, scores)),
        "thresholds": [threshold_metrics(labels, scores, f) for f in (0.05, 0.10, 0.20)],
    }


def summarize_spatial_tiles(labels, scores, tiles):
    blocks = {}
    for tile in sorted(set(tiles.tolist())):
        mask = tiles == tile
        auc = roc_auc(labels[mask], scores[mask])
        ap = average_precision(labels[mask], scores[mask])
        blocks[tile] = {
            "sample_count": int(mask.sum()),
            "positive_fraction": round(float(labels[mask].mean()), 4),
            "roc_auc": analyze_model.round_or_none(auc),
            "average_precision": analyze_model.round_or_none(ap),
        }
    auc_values = [b["roc_auc"] for b in blocks.values() if b["roc_auc"] is not None]
    ap_values = [b["average_precision"] for b in blocks.values() if b["average_precision"] is not None]
    return {
        "tile_count": len(blocks),
        "tiles_with_both_classes": len(auc_values),
        "roc_auc_median": analyze_model.round_or_none(np.median(auc_values) if auc_values else None),
        "roc_auc_p25": analyze_model.round_or_none(np.percentile(auc_values, 25) if auc_values else None),
        "roc_auc_p75": analyze_model.round_or_none(np.percentile(auc_values, 75) if auc_values else None),
        "average_precision_median": analyze_model.round_or_none(np.median(ap_values) if ap_values else None),
        "tiles": blocks,
    }


def markdown_report(report):
    lines = [
        "# Official Q100 Baseline Evaluation",
        "",
        f"Generated: {report['generated']}",
        "",
        "> Descriptive evaluation against DRSV IKPN Q100 within the official validity domain. This is not event validation and does not use spatially blocked folds yet.",
        "",
        "## Coverage",
        "",
        f"- Full diagnostic samples: {report['coverage']['all_samples']}",
        f"- Samples inside official validity: {report['coverage']['validity_samples']}",
        f"- Q100-positive samples: {report['coverage']['q100_positive_samples']}",
        "",
        "## Model/baseline comparison",
        "",
        "| Score | ROC-AUC | Average precision |",
        "|---|---:|---:|",
    ]
    for name, block in report["models"].items():
        lines.append(f"| {name} | {block['roc_auc']} | {block['average_precision']} |")
    lines += [
        "",
        "## D19 by region",
        "",
        "| Region | Samples | Q100 share | ROC-AUC | Average precision |",
        "|---|---:|---:|---:|---:|",
    ]
    for region, block in report["d19_by_region"].items():
        lines.append(
            f"| {region} | {block['sample_count']} | {block['positive_fraction']} | "
            f"{block['roc_auc']} | {block['average_precision']} |"
        )
    spatial = report["d19_spatial_tile_stability"]
    lines += [
        "",
        "## Spatial tile stability",
        "",
        f"- Validity-intersecting tiles: {spatial['tile_count']}",
        f"- Tiles containing both Q100 and non-Q100 samples: {spatial['tiles_with_both_classes']}",
        f"- Median tile ROC-AUC: {spatial['roc_auc_median']} (IQR {spatial['roc_auc_p25']}–{spatial['roc_auc_p75']})",
        f"- Median tile average precision: {spatial['average_precision_median']}",
    ]
    lines += [
        "",
        "## Interpretation gate",
        "",
        "These metrics compare with official static Q100 mapping, not the observed August 2023 event. Use them to reject weak terrain formulations and define later spatial folds; do not optimize final weights on this same evaluation set.",
        "",
    ]
    return "\n".join(lines)


def main():
    validity_path = VALIDATION_DIR / "ikpn_validity.geojson"
    q100_path = VALIDATION_DIR / "ikpn_q100.geojson"
    for path in (validity_path, q100_path):
        if not path.exists():
            raise SystemExit(f"Missing {path}; run download_validation.py for IKPN validity and Q100")

    arrays, metadata = analyze_model.load_samples(SAMPLE_DIR)
    if not metadata:
        raise SystemExit("No diagnostic samples; run pipeline.py first")

    validity, validity_features = load_geometry_union(validity_path)
    q100, q100_features = load_geometry_union(q100_path)
    x = arrays["easting_3794"].astype(np.float64)
    y = arrays["northing_3794"].astype(np.float64)
    eligible = contains_xy(validity, x, y)
    labels_all = contains_xy(q100, x, y)
    labels = labels_all[eligible]

    manifest = json.loads((ROOT / "web" / "data" / "manifest.json").read_text(encoding="utf-8"))
    weights = manifest["model"]["weights"]
    model_scores = {
        "d19_smoothed": arrays["score"][eligible],
        "d19_unsmoothed": analyze_model.weighted_composite(arrays, weights)[eligible],
        "without_elevation_and_slope": analyze_model.weighted_composite(
            arrays, weights, excluded=["elev", "slope"])[eligible],
        "hand_only": (1.0 - arrays["norm_hand"])[eligible],
        "twi_only": arrays["norm_twi"][eligible],
        "hand_twi": analyze_model.weighted_composite(
            arrays, weights, included=["hand", "twi"])[eligible],
    }
    models = {name: metric_block(labels, score) for name, score in model_scores.items()}

    regions = arrays["_region"][eligible]
    tiles = arrays["_tile"][eligible]
    by_region = {}
    for region in sorted(set(regions.tolist())):
        mask = regions == region
        by_region[region] = metric_block(labels[mask], model_scores["d19_smoothed"][mask])

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "model_version": manifest["model"]["version"],
        "reference": {
            "validity": str(validity_path.relative_to(ROOT)).replace("\\", "/"),
            "validity_feature_count": validity_features,
            "q100": str(q100_path.relative_to(ROOT)).replace("\\", "/"),
            "q100_feature_count": q100_features,
        },
        "coverage": {
            "all_samples": int(x.size),
            "validity_samples": int(eligible.sum()),
            "validity_fraction": round(float(eligible.mean()), 4),
            "q100_positive_samples": int(labels.sum()),
        },
        "models": models,
        "d19_by_region": by_region,
        "d19_spatial_tile_stability": summarize_spatial_tiles(
            labels, model_scores["d19_smoothed"], tiles),
        "limitations": [
            "descriptive-sample-evaluation-not-spatial-cross-validation",
            "official-q100-static-hazard-not-august-2023-observed-extent",
            "diagnostic-samples-stratified-by-score-decile-and-tile",
            "no-boundary-uncertainty-buffer-yet",
        ],
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "validation_q100.json"
    md_path = OUTPUT_DIR / "validation_q100.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    for name, block in models.items():
        print(f"  {name:30s} ROC-AUC={block['roc_auc']} AP={block['average_precision']}")


if __name__ == "__main__":
    main()
