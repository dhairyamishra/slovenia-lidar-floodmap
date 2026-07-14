#!/usr/bin/env python3
"""Inventory and safely acquire public evidence for the Kamnik 2023 hindcast.

This script is deliberately provenance-first.  It records availability, final
URL, content metadata and checksums before any source is treated as model
evidence.  Large imagery archives are refused unless the caller explicitly
opts in; the small orthophoto sheet index must be acquired first so that later
work can request only the relevant source sheets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCES_PATH = ROOT / "validation" / "sources.json"
OUTPUT_DIR = ROOT / "validation" / "data" / "event_evidence"
MANIFEST_PATH = OUTPUT_DIR / "acquisition_manifest.json"
USER_AGENT = "slovenia-lidar-floodmap-event-evidence/1.0"
LARGE_DOWNLOAD_BYTES = 500 * 1024 * 1024


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def event_sources():
    sources = read_json(SOURCES_PATH)
    return {source["id"]: source for source in sources.get("event_sources", [])}


def sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_filename(source):
    suffix = Path(urllib.request.url2pathname(source["url"].split("?")[0])).suffix
    return f"{source['id']}{suffix or '.bin'}"


def request_metadata(source, opener=urllib.request.urlopen):
    """Return HTTP metadata without downloading an entire potentially huge asset."""
    request = urllib.request.Request(source["url"], method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=60) as response:
            return response_metadata(response, "HEAD")
    except urllib.error.HTTPError as exc:
        if exc.code not in {403, 405, 501}:
            return {"status": exc.code, "method": "HEAD", "error": str(exc)}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"status": None, "method": "HEAD", "error": str(exc)}

    # Some public CDNs reject HEAD. A one-byte range request confirms that the
    # URL is reachable without accidentally pulling a multi-gigabyte archive.
    range_request = urllib.request.Request(
        source["url"], headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"}
    )
    try:
        with opener(range_request, timeout=60) as response:
            return response_metadata(response, "GET-range-0")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        return {"status": getattr(exc, "code", None), "method": "GET-range-0", "error": str(exc)}


def response_metadata(response, method):
    headers = response.headers
    length = headers.get("Content-Length")
    return {
        "status": getattr(response, "status", response.getcode()),
        "method": method,
        "final_url": response.geturl(),
        "content_type": headers.get("Content-Type"),
        "content_length": int(length) if length and length.isdigit() else None,
        "content_range": headers.get("Content-Range"),
        "last_modified": headers.get("Last-Modified"),
        "etag": headers.get("ETag"),
    }


def source_record(source, availability):
    return {
        "id": source["id"],
        "kind": source["kind"],
        "url": source["url"],
        "landing_page": source.get("landing_page"),
        "catalogue": source.get("catalogue"),
        "license": source.get("license"),
        "download_priority": source.get("download_priority"),
        "date_captured": source.get("date_captured"),
        "date_range": source.get("date_range"),
        "use": source.get("use"),
        "limitation": source.get("limitation"),
        "estimated_size_bytes": source.get("estimated_size_bytes"),
        "availability": availability,
    }


def download_source(source, allow_large=False, opener=urllib.request.urlopen):
    estimated = source.get("estimated_size_bytes")
    if estimated and estimated > LARGE_DOWNLOAD_BYTES and not allow_large:
        raise RuntimeError(
            f"{source['id']} is estimated at {estimated:,} bytes. Acquire its sheet index "
            "and subset it first, or pass --allow-large-download deliberately."
        )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / safe_filename(source)
    temporary = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(source["url"], headers={"User-Agent": USER_AGENT})
    with opener(request, timeout=300) as response, temporary.open("wb") as stream:
        shutil.copyfileobj(response, stream, length=1024 * 1024)
    temporary.replace(target)
    return {
        "path": str(target.relative_to(ROOT)).replace("\\", "/"),
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
    }


def merge_records(previous, records):
    merged = {record["id"]: record for record in previous.get("sources", [])}
    merged.update({record["id"]: record for record in records})
    return [merged[source_id] for source_id in sorted(merged)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", dest="source_ids",
                        help="Source id from validation/sources.json; repeatable")
    parser.add_argument("--download", action="store_true",
                        help="Download requested source files after inventorying them")
    parser.add_argument("--allow-large-download", action="store_true",
                        help="Allow a source estimated above 500 MiB; use only after subsetting imagery")
    args = parser.parse_args(argv)

    available = event_sources()
    requested = args.source_ids or sorted(available)
    unknown = sorted(set(requested) - set(available))
    if unknown:
        parser.error(f"Unknown event source id(s): {', '.join(unknown)}")
    if args.allow_large_download and not args.download:
        parser.error("--allow-large-download requires --download")

    records = []
    for source_id in requested:
        source = available[source_id]
        print(f"Inventory {source_id} ...", flush=True)
        record = source_record(source, request_metadata(source))
        if args.download:
            record["download"] = download_source(source, args.allow_large_download)
            print(f"  downloaded {record['download']['path']}", flush=True)
        records.append(record)

    previous = read_json(MANIFEST_PATH) if MANIFEST_PATH.exists() else {}
    manifest = {
        "schema_version": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "purpose": "Kamnik/Kamniška Bistrica August-2023 observed-event evidence inventory; not a flood-label dataset",
        "sources": merge_records(previous, records),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {MANIFEST_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
