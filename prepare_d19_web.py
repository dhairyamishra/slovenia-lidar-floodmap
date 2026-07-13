#!/usr/bin/env python3
"""Create honest D19 web displays from committed legacy susceptibility PNGs.

This migration avoids a full LAZ rerun. It recovers the fixed display-scale
index from the legacy RdYlBu_r colors, then writes a sparse purple review mask
and a neutral full diagnostic surface. Future pipeline runs write the same
assets directly from the unquantized display score.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

from pipeline import D19_REVIEW_THRESHOLD, d19_display_definition


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "web" / "data" / "manifest.json"


def legacy_palette():
    try:
        cmap = matplotlib.colormaps["RdYlBu_r"]
    except AttributeError:  # pragma: no cover - older matplotlib
        import matplotlib.cm as cm
        cmap = cm.get_cmap("RdYlBu_r")
    values = np.linspace(0.0, 1.0, 256)
    return values, (cmap(values)[:, :3] * 255).astype(np.float32)


def purple_rgba(score, valid, review):
    stops = np.array([0.0, 0.55, 1.0], dtype=np.float32)
    colors = np.array([[237, 233, 254], [167, 139, 250], [88, 28, 135]], dtype=np.float32)
    rgb = np.column_stack([
        np.interp(score.ravel(), stops, colors[:, channel])
        for channel in range(3)
    ]).reshape((*score.shape, 3)).astype(np.uint8)
    if review:
        strength = np.clip(
            (score - D19_REVIEW_THRESHOLD) / (1.0 - D19_REVIEW_THRESHOLD), 0, 1
        )
        alpha = np.where(score >= D19_REVIEW_THRESHOLD, 135 + 100 * strength, 0)
    else:
        alpha = 45 + 175 * score
    rgba = np.dstack([rgb, alpha.astype(np.uint8)])
    rgba[~valid, 3] = 0
    if review:
        rgba[rgba[..., 3] == 0, :3] = 0
    return rgba


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    values, palette = legacy_palette()
    tree = cKDTree(palette)
    for index, tile in enumerate(manifest["tiles"], start=1):
        files = tile["files"]
        source = ROOT / "web" / "data" / files["susceptibility"]
        image = np.asarray(Image.open(source).convert("RGBA"))
        valid = image[..., 3] > 0
        score = np.zeros(valid.shape, dtype=np.float32)
        if valid.any():
            _, palette_index = tree.query(image[..., :3][valid], workers=-1)
            score[valid] = values[palette_index]
        out_dir = source.parent
        review_name = "susceptibility_d19_review.png"
        review = Image.fromarray(purple_rgba(score, valid, True), "RGBA").quantize(
            colors=64, method=Image.Quantize.FASTOCTREE
        )
        review.save(out_dir / review_name, optimize=True)
        prefix = str(Path(files["susceptibility"]).parent).replace("\\", "/")
        files["d19_review"] = f"{prefix}/{review_name}"
        files["d19_diagnostic"] = files["susceptibility"]
        print(f"[{index:3d}/{len(manifest['tiles'])}] {tile['name']}")

    manifest["d19_display"] = d19_display_definition()
    manifest["d19_display"]["generation"] = "legacy-nearest-RdYlBu_r-palette-index"
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {MANIFEST}")


if __name__ == "__main__":
    main()
