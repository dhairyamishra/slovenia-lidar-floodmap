#!/usr/bin/env python3
"""Spatially benchmark drainage-relative replacements for frozen D19.

`develop` uses only frozen development tiles and writes an out-of-fold report.
`finalize` is deliberately separate and refuses to run unless the development
report names a candidate that clears the predeclared gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.stats import rankdata
from shapely import contains_xy
from sklearn.ensemble import HistGradientBoostingClassifier

import analyze_model
import evaluate_validation
from validation_grid import assign_split, file_sha256


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "replacement_model"
REPORT = OUTPUT / "development_report.json"
MODEL_CARD = OUTPUT / "MODEL_CARD.md"
FEATURE_NAMES = (
    "low_mosaic_hand",
    "near_channel",
    "low_valley_position",
    "low_local_relief",
    "contributing_area",
    "stream_order",
    "topographic_wetness",
    "flatness",
)
FEATURE_SETS = {
    "base": tuple(range(6)),
    "plus_twi": tuple(range(7)),
    "plus_slope": (0, 1, 2, 3, 4, 5, 7),
    "plus_twi_slope": tuple(range(8)),
}
REGION_CONFIG = {
    "08-kamnik": {"name": "savinja", "bounds": (486000.0, 132000.0)},
    "05-ljubljana": {"name": "ljubljana", "bounds": (455000.0, 96000.0)},
}
TOP_FRACTION = 0.10
MAX_CHANNEL_DISTANCE_M = 2000.0
CHANNEL_DISTANCE_CANDIDATES_M = (250.0, 500.0, 1000.0, 2000.0)
RANDOM_SEED = 20260712


def _digest_payload(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _sample_mosaic_features(regions, x, y):
    result = {name: np.full(x.size, np.nan, dtype=np.float64) for name in (
        "hand_m", "channel_distance_m", "valley_relative_elevation_250m",
        "local_relief_250m", "accumulation_cells", "stream_order",
        "connected_to_stream",
    )}
    manifests = {}
    for region, config in REGION_CONFIG.items():
        mask = regions == region
        if not mask.any():
            continue
        base = ROOT / "output" / "mosaic" / config["name"]
        manifest_path = base / "manifest.json"
        if not manifest_path.exists():
            raise SystemExit(f"Missing {manifest_path}; run mosaic_hydrology.py first")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifests[region] = {
            "path": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": file_sha256(manifest_path),
            "input_sha256": manifest["input_fingerprint"]["sha256"],
            "selected_stream_area_m2": manifest["routing"]["selected_stream_area_m2"],
        }
        cols = ((x[mask] - config["bounds"][0]) / 2.0).astype(np.int64)
        rows = ((y[mask] - config["bounds"][1]) / 2.0).astype(np.int64)
        for name in result:
            grid = np.load(base / f"{name}.npy", mmap_mode="r")
            result[name][mask] = grid[rows, cols]
    return result, manifests


def load_split_dataset(split):
    arrays, metadata = analyze_model.load_samples(evaluate_validation.SAMPLE_DIR)
    if not metadata:
        raise SystemExit("Missing diagnostic samples; run pipeline.py first")
    regions_all = arrays["_region"]
    tiles_all = arrays["_tile"]
    riverine = np.isin(regions_all, list(REGION_CONFIG))
    splits_all = evaluate_validation.assign_sample_splits(tiles_all, regions_all)
    requested = riverine & (splits_all == split)

    validity, _ = evaluate_validation.load_geometry_union(
        evaluate_validation.VALIDATION_DIR / "ikpn_validity.geojson")
    q100, _ = evaluate_validation.load_geometry_union(
        evaluate_validation.VALIDATION_DIR / "ikpn_q100.geojson")
    x_all = arrays["easting_3794"].astype(np.float64)
    y_all = arrays["northing_3794"].astype(np.float64)
    indexes = np.flatnonzero(requested)
    x = x_all[indexes]
    y = y_all[indexes]
    eligible_local = contains_xy(validity, x, y) & ~contains_xy(
        q100.boundary.buffer(10.0), x, y)
    indexes = indexes[eligible_local]
    x = x_all[indexes]
    y = y_all[indexes]
    labels = contains_xy(q100, x, y)
    regions = regions_all[indexes]
    tiles = tiles_all[indexes]
    mosaic, manifests = _sample_mosaic_features(regions, x, y)

    hand = mosaic["hand_m"]
    distance = mosaic["channel_distance_m"]
    valley = mosaic["valley_relative_elevation_250m"]
    relief = mosaic["local_relief_250m"]
    accumulation = mosaic["accumulation_cells"]
    order = mosaic["stream_order"]
    features = np.column_stack((
        -np.log1p(hand),
        -np.log1p(distance),
        -np.log1p(valley),
        -np.log1p(relief),
        np.log1p(accumulation),
        order,
        arrays["norm_twi"][indexes].astype(np.float64),
        1.0 - arrays["norm_slope"][indexes].astype(np.float64),
    ))
    if not np.isfinite(features).all():
        raise RuntimeError("Non-finite mosaic model features")
    eastings = np.asarray([int(str(tile).split("_")[0]) for tile in tiles])
    return {
        "labels": labels.astype(bool),
        "features": features,
        "regions": regions,
        "tiles": tiles,
        "eastings": eastings,
        "d19": arrays["score"][indexes].astype(np.float64),
        "per_tile_hand": (1.0 - arrays["norm_hand"][indexes]).astype(np.float64),
        "mosaic_hand": -hand,
        "channel_distance_m": distance,
        "raw_elevation_m": arrays["raw_elev"][indexes].astype(np.float64),
        "norm_elev": arrays["norm_elev"][indexes].astype(np.float64),
        "norm_slope": arrays["norm_slope"][indexes].astype(np.float64),
        "norm_hand": arrays["norm_hand"][indexes].astype(np.float64),
        "manifests": manifests,
        "sample_metadata_count": len(metadata),
    }


def spatial_folds(dataset):
    folds = []
    regions = dataset["regions"]
    eastings = dataset["eastings"]
    for region in sorted(set(regions.tolist())):
        for easting in sorted(set(eastings[regions == region].tolist())):
            validation = (regions == region) & (eastings == easting)
            train = ~validation & ~((regions == region) & (np.abs(eastings - easting) <= 1))
            if validation.any() and train.any() and dataset["labels"][train].any() and (~dataset["labels"][train]).any():
                folds.append((f"{region}:E{easting}", train, validation))
    return folds


def _fit_transform(train, validation):
    centre = np.median(train, axis=0)
    scale = np.percentile(train, 75, axis=0) - np.percentile(train, 25, axis=0)
    scale[scale < 1e-6] = 1.0
    return (train - centre) / scale, (validation - centre) / scale


def _fit_monotonic_logistic(x, y, l2=1.0):
    positive = max(int(y.sum()), 1)
    negative = max(int((~y).sum()), 1)
    weights = np.where(y, y.size / (2 * positive), y.size / (2 * negative))

    def objective(parameters):
        intercept = parameters[0]
        coefficients = parameters[1:]
        logits = intercept + x @ coefficients
        loss = np.sum(weights * (np.logaddexp(0.0, logits) - y * logits)) / weights.sum()
        loss += 0.5 * l2 * np.sum(coefficients**2) / x.shape[1]
        probabilities = 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))
        residual = weights * (probabilities - y) / weights.sum()
        gradient = np.concatenate((
            [residual.sum()],
            x.T @ residual + l2 * coefficients / x.shape[1],
        ))
        return loss, gradient

    initial = np.zeros(x.shape[1] + 1)
    initial[0] = np.log(positive / negative)
    fit = minimize(
        objective, initial, jac=True, method="L-BFGS-B",
        bounds=[(None, None)] + [(0.0, None)] * x.shape[1],
        options={"maxiter": 200},
    )
    if not fit.success:
        raise RuntimeError(f"Constrained logistic fit failed: {fit.message}")
    return fit.x


def _predict_logistic(parameters, x):
    logits = parameters[0] + x @ parameters[1:]
    return 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))


def _drainage_rule(train, validation):
    lo = np.percentile(train, 2, axis=0)
    hi = np.percentile(train, 98, axis=0)
    scaled = np.clip((validation - lo) / np.maximum(hi - lo, 1e-6), 0, 1)
    weights = np.array([0.40, 0.20, 0.15, 0.10, 0.10, 0.05])
    return scaled[:, :6] @ weights


def _metric(labels, scores):
    return {
        "roc_auc": round(evaluate_validation.roc_auc(labels, scores), 4),
        "average_precision": round(evaluate_validation.average_precision(labels, scores), 4),
    }


def _operating_metrics(labels, scores, threshold):
    predicted = scores >= threshold
    tp = int((predicted & labels).sum())
    fp = int((predicted & ~labels).sum())
    fn = int((~predicted & labels).sum())
    tn = int((~predicted & ~labels).sum())
    union = tp + fp + fn
    return {
        "threshold": round(float(threshold), 8),
        "predicted_fraction": round(float(predicted.mean()), 4),
        "precision": round(tp / max(tp + fp, 1), 4),
        "recall": round(tp / max(tp + fn, 1), 4),
        "false_positive_rate": round(fp / max(fp + tn, 1), 4),
        "f1": round(2 * tp / max(2 * tp + fp + fn, 1), 4),
        "iou": round(tp / max(union, 1), 4),
        "bias_ratio": round((tp + fp) / max(tp + fn, 1), 4),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }


def _controls(dataset):
    negative = ~dataset["labels"]
    return {
        "low_flat_q100_negative": negative & (dataset["norm_elev"] <= 0.35) & (dataset["norm_slope"] <= 0.25),
        "low_hand_q100_negative": negative & (dataset["norm_hand"] <= 0.20),
        "flat_upland_q100_negative": negative & (dataset["norm_elev"] >= 0.65) & (dataset["norm_slope"] <= 0.25),
        "terrace_like_q100_negative": negative & (dataset["norm_hand"] > 0.20) & (dataset["norm_hand"] <= 0.45) & (dataset["norm_slope"] <= 0.35),
    }


def _association(score, elevation):
    return {
        "pearson": round(float(np.corrcoef(score, elevation)[0, 1]), 4),
        "spearman": round(float(np.corrcoef(rankdata(score), rankdata(elevation))[0, 1]), 4),
    }


def develop():
    dataset = load_split_dataset("development")
    labels = dataset["labels"]
    folds = spatial_folds(dataset)
    predictions = {
        "b0_mosaic_hand": dataset["mosaic_hand"].copy(),
        "b1_drainage_rules": np.full(labels.size, np.nan),
        "b2_frozen_d19": dataset["d19"].copy(),
        "per_tile_hand": dataset["per_tile_hand"].copy(),
    }
    for feature_set in FEATURE_SETS:
        predictions[f"m1_{feature_set}"] = np.full(labels.size, np.nan)
        predictions[f"m2_{feature_set}"] = np.full(labels.size, np.nan)
    permutation_deltas = {name: [] for name in FEATURE_NAMES}
    fold_reports = []
    rng = np.random.default_rng(RANDOM_SEED)
    for fold_name, train, validation in folds:
        x_train_raw = dataset["features"][train]
        x_validation_raw = dataset["features"][validation]
        y_train = labels[train]
        y_validation = labels[validation]
        x_train, x_validation = _fit_transform(x_train_raw, x_validation_raw)
        predictions["b1_drainage_rules"][validation] = _drainage_rule(x_train_raw, x_validation_raw)

        for feature_set, columns in FEATURE_SETS.items():
            columns = np.asarray(columns)
            train_subset = x_train[:, columns]
            validation_subset = x_validation[:, columns]
            logistic = _fit_monotonic_logistic(train_subset, y_train)
            predictions[f"m1_{feature_set}"][validation] = _predict_logistic(
                logistic, validation_subset)

            tree = HistGradientBoostingClassifier(
                learning_rate=0.06,
                max_iter=180,
                max_leaf_nodes=15,
                min_samples_leaf=80,
                l2_regularization=1.0,
                class_weight="balanced",
                monotonic_cst=[1] * len(columns),
                random_state=RANDOM_SEED,
            )
            tree.fit(train_subset, y_train)
            tree_score = tree.predict_proba(validation_subset)[:, 1]
            predictions[f"m2_{feature_set}"][validation] = tree_score
            if feature_set == "plus_twi_slope":
                base_auc = evaluate_validation.roc_auc(y_validation, tree_score)
                if base_auc is not None:
                    for local_column, global_column in enumerate(columns):
                        permuted = validation_subset.copy()
                        permuted[:, local_column] = rng.permutation(permuted[:, local_column])
                        permuted_auc = evaluate_validation.roc_auc(
                            y_validation, tree.predict_proba(permuted)[:, 1])
                        if permuted_auc is not None:
                            permutation_deltas[FEATURE_NAMES[global_column]].append(base_auc - permuted_auc)
        fold_reports.append({
            "fold": fold_name,
            "train_samples": int(train.sum()),
            "validation_samples": int(validation.sum()),
            "validation_positive_fraction": round(float(y_validation.mean()), 4),
        })

    available = np.ones(labels.size, dtype=bool)
    fitted_names = [key for key in predictions if key.startswith(("b1_", "m1_", "m2_"))]
    for name in fitted_names:
        available &= np.isfinite(predictions[name])
    masked_predictions = {
        "b2_frozen_d19": predictions["b2_frozen_d19"],
        "per_tile_hand": predictions["per_tile_hand"],
    }
    for name in ["b0_mosaic_hand", *fitted_names]:
        for distance_m in CHANNEL_DISTANCE_CANDIDATES_M:
            score = predictions[name].copy()
            outside = dataset["channel_distance_m"] > distance_m
            score[outside] = np.nanmin(score) - 1.0
            masked_predictions[f"{name}_d{int(distance_m)}m"] = score
    predictions = masked_predictions
    labels_eval = labels[available]
    scores = {name: values[available] for name, values in predictions.items()}
    controls = {name: mask[available] for name, mask in _controls(dataset).items()}
    elevations = dataset["raw_elevation_m"][available]
    regions = dataset["regions"][available]

    models = {}
    for name, score in scores.items():
        threshold = float(np.quantile(score, 1.0 - TOP_FRACTION))
        block = _metric(labels_eval, score)
        block["operating_point"] = _operating_metrics(labels_eval, score, threshold)
        block["altitude_association"] = _association(score, elevations)
        block["by_region"] = {
            region: {
                **_metric(labels_eval[regions == region], score[regions == region]),
                "altitude_association": _association(
                    score[regions == region], elevations[regions == region]),
            }
            for region in sorted(set(regions.tolist()))
        }
        block["negative_controls"] = {
            control_name: {
                "sample_count": int(mask.sum()),
                "flagged_fraction": round(float((score[mask] >= threshold).mean()), 4) if mask.any() else None,
            }
            for control_name, mask in controls.items()
        }
        models[name] = block

    baseline_name = max(
        [name for name in models if name.startswith("b0_mosaic_hand_d")],
        key=lambda name: (models[name]["roc_auc"], models[name]["average_precision"]),
    )
    baseline = models[baseline_name]
    baseline_low_flat = baseline["negative_controls"]["low_flat_q100_negative"]["flagged_fraction"]
    baseline_recall = baseline["operating_point"]["recall"]
    candidate_gates = {}
    candidate_names = [name for name in models if name.startswith(("b1_", "m1_", "m2_"))]
    for name in candidate_names:
        block = models[name]
        low_flat = block["negative_controls"]["low_flat_q100_negative"]["flagged_fraction"]
        reduction = (
            (baseline_low_flat - low_flat) / baseline_low_flat
            if baseline_low_flat not in (None, 0) and low_flat is not None else None
        )
        gate = {
            "auc_gain_over_mosaic_hand": round(block["roc_auc"] - baseline["roc_auc"], 4),
            "ap_gain_over_mosaic_hand": round(block["average_precision"] - baseline["average_precision"], 4),
            "low_flat_control_relative_reduction": round(reduction, 4) if reduction is not None else None,
            "recall_change": round(block["operating_point"]["recall"] - baseline_recall, 4),
        }
        gate["passes"] = (
            gate["auc_gain_over_mosaic_hand"] >= 0.03
            and gate["ap_gain_over_mosaic_hand"] >= 0.03
            and gate["low_flat_control_relative_reduction"] is not None
            and gate["low_flat_control_relative_reduction"] >= 0.30
            and gate["recall_change"] >= -0.05
        )
        candidate_gates[name] = gate
    passing = [name for name, gate in candidate_gates.items() if gate["passes"]]
    selected = max(
        passing,
        key=lambda name: (models[name]["average_precision"], models[name]["roc_auc"]),
        default=None,
    )

    contract = json.loads(evaluate_validation.CONTRACT_PATH.read_text(encoding="utf-8"))
    report = {
        "schema_version": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "mode": "development-only-spatial-cross-validation",
        "locked_test_accessed": False,
        "feature_names": FEATURE_NAMES,
        "feature_semantics": "all risk-oriented; no absolute elevation feature",
        "maximum_channel_distance_candidates_m": CHANNEL_DISTANCE_CANDIDATES_M,
        "selected_b0_reference": baseline_name,
        "operating_top_fraction": TOP_FRACTION,
        "evaluation_contract_sha256": _digest_payload(contract),
        "mosaic_manifests": dataset["manifests"],
        "coverage": {
            "eligible_development_samples": int(labels.size),
            "out_of_fold_samples": int(available.sum()),
            "positive_count": int(labels_eval.sum()),
            "fold_count": len(folds),
        },
        "folds": fold_reports,
        "models": models,
        "candidate_gates": candidate_gates,
        "selected_candidate": selected,
        "m2_permutation_auc_drop": {
            name: round(float(np.mean(values)), 5) if values else None
            for name, values in permutation_deltas.items()
        },
        "limitations": [
            "official-static-q100-not-observed-event",
            "score-decile-stratified-diagnostic-samples-not-area-prevalence",
            "one-spatial-column-fold-family-not-independent-basin-corpus",
            "no-absolute-elevation-feature-by-design",
            "tree-explained-with-out-of-fold-permutation-not-shap",
            "locked-test-not-accessed",
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_model_card(report)
    print(json.dumps({
        "report": str(REPORT),
        "coverage": report["coverage"],
        "selected_candidate": selected,
        "models": {name: {"roc_auc": block["roc_auc"], "average_precision": block["average_precision"]} for name, block in models.items()},
        "candidate_gates": candidate_gates,
        "locked_test_accessed": False,
    }, indent=2))


def write_model_card(report):
    lines = [
        "# Drainage-relative replacement model card",
        "",
        f"Generated: {report['generated']}",
        "",
        "Status: development benchmark only. No replacement is approved or published unless a candidate clears every gate and is evaluated once on the locked spatial test.",
        "",
        "## Candidate results",
        "",
        "| Candidate | ROC-AUC | AP | Low-flat control flagged | Gate |",
        "|---|---:|---:|---:|---|",
    ]
    for name, block in report["models"].items():
        low_flat = block["negative_controls"]["low_flat_q100_negative"]["flagged_fraction"]
        gate = report["candidate_gates"].get(name, {}).get("passes")
        lines.append(f"| {name} | {block['roc_auc']} | {block['average_precision']} | {low_flat} | {gate if gate is not None else 'reference'} |")
    lines += [
        "",
        "## Intended use",
        "",
        "Rank terrain for drainage-relative flood-susceptibility review inside the validated riverine domain. Scores are not annual probability, modeled depth, event extent, or risk (which also requires exposure and consequence).",
        "",
        "## Features",
        "",
        "Base features are mosaic HAND, horizontal channel distance, 250 m valley-relative elevation, 250 m local relief, contributing area, and stream order. TWI and slope/flatness are tested one at a time and together as declared challengers. Every feature is oriented so larger values mean more susceptible before fitting. Absolute elevation is excluded.",
        "",
        "## Known failure modes",
        "",
        "- Underground stormwater, culverts, pumps, levees, and engineered barriers are absent.",
        "- Static Q100 polygons are planning references, not the observed August 2023 footprint.",
        "- Diagnostic samples are D19-score-stratified and do not estimate flooded land-area prevalence.",
        "- Spatial column folds do not substitute for independent events and basins.",
        "- D8/MFD channel paths and official-line alignment remain uncertain, especially in Ljubljana.",
        "",
        f"Selected development candidate: `{report['selected_candidate']}`.",
        "",
    ]
    MODEL_CARD.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("develop", "finalize"))
    args = parser.parse_args()
    if args.mode == "develop":
        develop()
    else:
        raise SystemExit(
            "Finalization is intentionally locked until development_report.json names a passing candidate; "
            "implement/run the one-time locked evaluation only after reviewing that report."
        )


if __name__ == "__main__":
    main()
