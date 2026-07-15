#!/usr/bin/env python3
"""Build a restartable SHA-256 inventory for immutable LAZ analysis inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "output" / "connectivity" / "input_digests.json"


def file_digest(path, block_size=8 * 1024 * 1024):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory_digest(files):
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def build(paths, output=DEFAULT_OUTPUT):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    cached = existing.get("files", {})
    files = {}
    for number, path in enumerate(sorted(map(Path, paths)), start=1):
        stat = path.stat()
        previous = cached.get(path.name, {})
        if previous.get("size") == stat.st_size and previous.get("mtime_ns") == stat.st_mtime_ns:
            sha256 = previous["sha256"]
            status = "cached"
        else:
            sha256 = file_digest(path)
            status = "hashed"
        files[path.name] = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256,
        }
        payload = {
            "schema_version": 1,
            "algorithm": "sha256",
            "files": dict(sorted(files.items())),
            "dataset_sha256": inventory_digest(files),
        }
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[{number}/{len(paths)}] {status} {path.name}", flush=True)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    paths = args.paths or list((ROOT / "data").glob("GKOT_*.laz"))
    build(paths, args.output)
