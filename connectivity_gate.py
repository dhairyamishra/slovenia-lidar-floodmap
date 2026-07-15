#!/usr/bin/env python3
"""Frozen scientific selection gate for connectivity-first hindcasts."""

from __future__ import annotations

import numpy as np

import evaluate_validation


THRESHOLDS = {
    "roc_auc_gain": 0.03,
    "average_precision_gain": 0.03,
    "iou_gain": 0.05,
    "low_flat_reduction": 0.30,
    "minimum_recall_change": -0.05,
    "minimum_bias_ratio": 0.80,
    "maximum_bias_ratio": 1.25,
}


def _operating(labels, flags):
    labels = np.asarray(labels, dtype=bool)
    flags = np.asarray(flags, dtype=bool)
    tp = int((labels & flags).sum())
    fp = int((~labels & flags).sum())
    fn = int((labels & ~flags).sum())
    union = tp + fp + fn
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "recall": tp / (tp + fn) if tp + fn else None,
        "iou": tp / union if union else None,
        "bias_ratio": flags.sum() / labels.sum() if labels.sum() else None,
    }


def evaluate_gate(labels, candidate_scores, baseline_scores, candidate_flags,
                  baseline_flags, low_flat_negative, counterfactual_passed):
    """Return the exact D34 gate block accepted by scenario validation."""
    labels = np.asarray(labels, dtype=bool)
    candidate_scores = np.asarray(candidate_scores, dtype=float)
    baseline_scores = np.asarray(baseline_scores, dtype=float)
    candidate_flags = np.asarray(candidate_flags, dtype=bool)
    baseline_flags = np.asarray(baseline_flags, dtype=bool)
    low_flat = np.asarray(low_flat_negative, dtype=bool) & ~labels
    arrays = (candidate_scores, baseline_scores, candidate_flags, baseline_flags, low_flat)
    if any(value.shape != labels.shape for value in arrays):
        raise ValueError("all gate arrays must have the same shape")
    if labels.size == 0 or not labels.any() or labels.all():
        raise ValueError("scientific gate requires both flooded and not-flooded labels")
    if not np.isfinite(candidate_scores).all() or not np.isfinite(baseline_scores).all():
        raise ValueError("gate scores must be finite on every evaluated cell")

    candidate = _operating(labels, candidate_flags)
    baseline = _operating(labels, baseline_flags)
    candidate_low = float(candidate_flags[low_flat].mean()) if low_flat.any() else None
    baseline_low = float(baseline_flags[low_flat].mean()) if low_flat.any() else None
    reduction = (
        (baseline_low - candidate_low) / baseline_low
        if baseline_low not in (None, 0) and candidate_low is not None else None
    )
    result = {
        "roc_auc_gain": evaluate_validation.roc_auc(labels, candidate_scores)
        - evaluate_validation.roc_auc(labels, baseline_scores),
        "average_precision_gain": evaluate_validation.average_precision(labels, candidate_scores)
        - evaluate_validation.average_precision(labels, baseline_scores),
        "iou_gain": candidate["iou"] - baseline["iou"],
        "low_flat_reduction": reduction,
        "recall_change": candidate["recall"] - baseline["recall"],
        "bias_ratio": candidate["bias_ratio"],
        "counterfactual_passed": bool(counterfactual_passed),
        "candidate_operating": candidate,
        "baseline_operating": baseline,
        "low_flat_candidate_flagged_fraction": candidate_low,
        "low_flat_baseline_flagged_fraction": baseline_low,
        "thresholds": THRESHOLDS,
    }
    result["passes"] = (
        result["roc_auc_gain"] >= THRESHOLDS["roc_auc_gain"]
        and result["average_precision_gain"] >= THRESHOLDS["average_precision_gain"]
        and result["iou_gain"] >= THRESHOLDS["iou_gain"]
        and result["low_flat_reduction"] is not None
        and result["low_flat_reduction"] >= THRESHOLDS["low_flat_reduction"]
        and result["recall_change"] >= THRESHOLDS["minimum_recall_change"]
        and THRESHOLDS["minimum_bias_ratio"] <= result["bias_ratio"] <= THRESHOLDS["maximum_bias_ratio"]
        and result["counterfactual_passed"]
    )
    return result
