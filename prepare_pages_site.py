#!/usr/bin/env python3
"""Build the bounded public Pages artifact without research-only heavy rasters."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "web"
DESTINATION = ROOT / "_site"
EXCLUDED_RASTER_NAMES = {"ndvi.png", "susceptibility.png"}
EXCLUDED_MANIFEST_KEYS = {"ndvi", "susceptibility", "d19_diagnostic"}


def public_manifest(manifest: dict) -> dict:
    """Return a copy whose file registry matches the bounded Pages artifact."""
    result = json.loads(json.dumps(manifest))
    for tile in result.get("tiles", []):
        files = tile.get("files", {})
        for key in EXCLUDED_MANIFEST_KEYS:
            files.pop(key, None)
    result["deployment_profile"] = {
        "name": "github-pages-bounded-v1",
        "omitted_layers": ["d19_diagnostic", "ndvi"],
        "reason": "Heavy research/context rasters remain local and are not part of the public Pages artifact.",
    }
    return result


def ignore_heavy_rasters(_directory: str, names: list[str]) -> set[str]:
    return set(names) & EXCLUDED_RASTER_NAMES


def build(source: Path, destination: Path) -> None:
    source = source.resolve()
    destination = destination.resolve()
    if source != SOURCE.resolve() or destination != DESTINATION.resolve():
        raise ValueError("Refusing an unsafe Pages destination")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=ignore_heavy_rasters)
    manifest_path = destination / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(
        json.dumps(public_manifest(manifest), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

if __name__ == "__main__":
    build(SOURCE, DESTINATION)
    print(f"Built bounded Pages artifact: {DESTINATION}")
