"""Dependency-light diagnostic sampling shared by pipeline and tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np


def write_stratified_sample(
    output_path: Path,
    *,
    tile: str,
    region: str,
    model_version: str,
    rows: int,
    cols: int,
    x0: float,
    y0: float,
    grid_res: float,
    raw_factors: dict[str, np.ndarray],
    normalized_factors: dict[str, np.ndarray],
    score: np.ndarray,
    display_score: np.ndarray,
    max_samples: int,
) -> bool:
    """Write a deterministic sample with equal quotas across score deciles."""
    valid_flat = np.flatnonzero(np.isfinite(score.ravel()))
    if valid_flat.size == 0:
        return False

    valid_scores = score.ravel()[valid_flat]
    quantile_edges = np.quantile(valid_scores, np.linspace(0.0, 1.0, 11))
    bins = np.searchsorted(quantile_edges[1:-1], valid_scores, side="right")
    seed = int(hashlib.sha256(tile.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    quota = max(1, max_samples // 10)
    chosen_parts = []
    for bin_idx in range(10):
        members = valid_flat[bins == bin_idx]
        if members.size:
            take = min(quota, members.size)
            chosen_parts.append(rng.choice(members, size=take, replace=False))
    if not chosen_parts:
        return False

    chosen = np.concatenate(chosen_parts)
    target = min(max_samples, valid_flat.size)
    if chosen.size < target:
        remaining = np.setdiff1d(valid_flat, chosen, assume_unique=False)
        take = min(target - chosen.size, remaining.size)
        if take:
            chosen = np.concatenate([chosen, rng.choice(remaining, size=take, replace=False)])

    row = chosen // cols
    col = chosen % cols
    arrays = {
        "row": row.astype(np.int32),
        "col": col.astype(np.int32),
        "easting_3794": (x0 + col * grid_res).astype(np.float64),
        "northing_3794": (y0 + row * grid_res).astype(np.float64),
        "score": score.ravel()[chosen].astype(np.float32),
        "display_score": display_score.ravel()[chosen].astype(np.float32),
    }
    for name in sorted(raw_factors):
        arrays[f"raw_{name}"] = raw_factors[name].ravel()[chosen].astype(np.float32)
        arrays[f"norm_{name}"] = normalized_factors[name].ravel()[chosen].astype(np.float32)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_path,
        tile=np.array(tile),
        region=np.array(region),
        model_version=np.array(model_version),
        **arrays,
    )
    return True
