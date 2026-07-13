#!/usr/bin/env python3
"""
CLSS LiDAR tile downloader.

Fetches GKOT_*.laz tiles from the Flycom CLSS S3 bucket:
  https://assets.flycom.si/clss/raw/<region>/zls/gkot/GKOT_E_N.laz

Tile coordinates are 1 km grid cells in EPSG:3794 (easting_km, northing_km).
E.g. GKOT_460_105 covers easting [460 000 – 461 000 m], northing [105 000 – 106 000 m].

Usage
-----
  # 3x3 grid centred on 460_100 (default radius = 1)
  python download_tiles.py --center 460 100

  # 5x5 grid centred on 460_100
  python download_tiles.py --center 460 100 --radius 2

  # Explicit bounding box (inclusive, tile km)
  python download_tiles.py --bbox 458 98 462 102

  # Specific tiles by name
  python download_tiles.py --tiles 460_105 461_105 462_105

  # Preview which tiles exist on the CDN without downloading
  python download_tiles.py --center 460 100 --radius 2 --dry-run

  # Download then immediately run the flood-risk pipeline
  python download_tiles.py --center 460 100 --radius 2 --pipeline

  # Download a chunk with four concurrent, atomic transfers
  python download_tiles.py --bbox 445 90 449 94 --workers 4
"""

import sys
import json
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

# ---------------------------------------------------------------------------
# CDN constants
# ---------------------------------------------------------------------------
BASE_URL = "https://assets.flycom.si/clss/raw"
PRODUCT  = "zls/gkot"
DATA_DIR = Path(__file__).parent / "data"
CACHE    = Path(__file__).parent / ".tile_region_cache.json"

# All 16 survey regions ordered by geographic coverage size (most tiles first).
# The downloader tries these in order, starting with the last successful region,
# so nearby tiles are resolved with one probe instead of sixteen.
REGIONS = [
    "05-ljubljana",       # central – largest survey, incl. Ljubljana basin
    "04-jesenice",        # northwest – upper Sava, Jesenice, Bled area
    "09-celje",           # east – Savinja valley, Celje
    "07-novomesto",       # southeast – Novo Mesto, Dolenjska
    "03-postojna",        # southwest – Postojna, Notranjska, Kočevje fringe
    "08-kamnik",          # central-north – Kamnik Alps, Tuhinjska dolina
    "06-kocevje",         # south – Kočevje forest block
    "02-nova-gorica",     # west – Nova Gorica, Vipava
    "01-koper",           # southwest coast – Koper, Karst
    "11-maribor",         # northeast – Maribor, Drava
    "10-murskasobota",    # far northeast – Prekmurje
    "12-velenje",         # north – Velenje, Šaleška dolina
    "13-ljubljana-aneks", # gap-fill supplement for Ljubljana area
    "16-kamnik-aneks",    # gap-fill supplement for Kamnik area
    "17-novagorica-aneks",
    "18-jesenice-aneks",
]


# ---------------------------------------------------------------------------
# Region cache helpers
# ---------------------------------------------------------------------------
def _load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
HEADERS = {"User-Agent": "CLSS-Downloader/1.0"}


def _probe(url: str, timeout: int = 8) -> int:
    """Return HTTP status for a Range: bytes=0-1 request (fast existence check).

    Retries once with a longer timeout on a network hiccup. A read timeout is a
    raw TimeoutError (not wrapped in URLError), so it must be caught explicitly —
    otherwise one slow region probe aborts the whole grid run.
    """
    req = Request(url, headers={**HEADERS, "Range": "bytes=0-1"})
    for attempt in range(2):
        try:
            with urlopen(req, timeout=timeout * (attempt + 1)) as r:
                return r.status          # 200 or 206
        except HTTPError as ex:
            return ex.code              # definitive answer (e.g. 404) — don't retry
        except (URLError, TimeoutError, OSError):
            continue                     # transient — retry once, then give up
    return 0                              # unreachable after retries


def find_region(e: int, n: int, cache: dict, prefer: str | None = None) -> str | None:
    """
    Return the CDN region slug for tile (e, n), or None if not on the CDN.

    Results are cached in .tile_region_cache.json.
    `prefer` is tried first (use the last-successful region to short-circuit
    the search for tiles in the same geographic neighbourhood).
    """
    key = f"{e}_{n}"
    if key in cache:
        return cache[key]

    print(f"  probing {key}...", end=" ", flush=True)

    ordered = ([prefer] if prefer else []) + [r for r in REGIONS if r != prefer]
    for region in ordered:
        url = f"{BASE_URL}/{region}/{PRODUCT}/GKOT_{e}_{n}.laz"
        sc  = _probe(url)
        if sc in (200, 206):
            print(region)
            cache[key] = region
            _save_cache(cache)
            return region

    print("not on CDN")
    return None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def download_tile(e: int, n: int, region: str, show_progress: bool = True) -> bool:
    """Stream tile LAZ to data/. Returns True on success (or already present)."""
    dest = DATA_DIR / f"GKOT_{e}_{n}.laz"
    partial = dest.with_suffix(dest.suffix + ".part")
    if dest.exists():
        print(f"  [skip] GKOT_{e}_{n}  (already in data/)")
        return True

    url = f"{BASE_URL}/{region}/{PRODUCT}/GKOT_{e}_{n}.laz"
    print(f"  [dl]   GKOT_{e}_{n}  ({region})")

    try:
        req = Request(url, headers=HEADERS)
        DATA_DIR.mkdir(exist_ok=True)
        chunk = 1 << 20                     # 1 MB chunks
        if partial.exists():
            partial.unlink()
        with urlopen(req, timeout=600) as resp, open(partial, "wb") as fh:
            total    = int(resp.headers.get("Content-Length", 0))
            received = 0
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                fh.write(buf)
                received += len(buf)
                if total and show_progress:
                    pct = received / total * 100
                    print(f"\r  [dl]   GKOT_{e}_{n}  "
                          f"{pct:5.1f}%  ({received/1e6:.1f}/{total/1e6:.1f} MB)   ",
                          end="", flush=True)
        partial.replace(dest)
        prefix = "\r" if show_progress else ""
        print(f"{prefix}  [ok]   GKOT_{e}_{n}  {received/1e6:.1f} MB{' '*30}")
        return True
    except KeyboardInterrupt:
        if partial.exists():
            partial.unlink()
        raise
    except Exception as ex:
        print(f"\r  [err]  GKOT_{e}_{n}: {ex}{' '*40}")
        if partial.exists():
            partial.unlink()
        return False


# ---------------------------------------------------------------------------
# Grid construction
# ---------------------------------------------------------------------------
def build_grid(args) -> list[tuple[int, int]]:
    if args.center:
        e0, n0 = args.center
        r = args.radius
        return [
            (e, n)
            for n in range(n0 + r, n0 - r - 1, -1)   # north→south display order
            for e in range(e0 - r, e0 + r + 1)
        ]
    if args.bbox:
        e_min, n_min, e_max, n_max = args.bbox
        return [
            (e, n)
            for n in range(n_max, n_min - 1, -1)
            for e in range(e_min, e_max + 1)
        ]
    if args.tiles:
        result = []
        for t in args.tiles:
            parts = t.replace("-", "_").split("_")
            result.append((int(parts[0]), int(parts[1])))
        return result
    return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Download CLSS GKOT LiDAR tiles from the Flycom CDN.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--center", nargs=2, type=int, metavar=("E", "N"),
        help="Centre tile in km (easting northing), e.g. 460 100",
    )
    mode.add_argument(
        "--bbox", nargs=4, type=int,
        metavar=("E_MIN", "N_MIN", "E_MAX", "N_MAX"),
        help="Bounding box in km (inclusive), e.g. 458 98 462 102",
    )
    mode.add_argument(
        "--tiles", nargs="+", metavar="E_N",
        help="Explicit tile IDs, e.g. 460_105 461_105",
    )
    ap.add_argument(
        "--radius", type=int, default=1,
        help="Tiles on each side of --center (default 1 → 3×3 = 9 tiles)",
    )
    ap.add_argument(
        "--pipeline", action="store_true",
        help="Run pipeline.py on the newly downloaded tiles when done",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Show availability on CDN without downloading anything",
    )
    ap.add_argument(
        "--workers", type=int, default=1,
        help="Concurrent tile downloads after region probing (default 1)",
    )

    args = ap.parse_args()
    tiles = build_grid(args)

    if not tiles:
        ap.error("No tiles specified.")

    # Pretty header
    w = int(len(tiles) ** 0.5)
    grid_str = f"{w}x{w}" if w * w == len(tiles) else f"{len(tiles)}-tile"
    print(f"\nCLSS downloader — {grid_str} grid ({len(tiles)} tile(s))")
    print("-" * 50)
    for e, n in tiles:
        print(f"  GKOT_{e}_{n}")
    print()

    cache           = _load_cache()
    last_region     = None
    downloaded_ids  = []
    skipped_ids     = []
    unavailable_ids = []

    resolved = []
    for e, n in tiles:
        region = find_region(e, n, cache, prefer=last_region)
        if region is None:
            unavailable_ids.append(f"{e}_{n}")
            continue
        last_region = region

        if args.dry_run:
            dest = DATA_DIR / f"GKOT_{e}_{n}.laz"
            tag  = "local" if dest.exists() else "CDN"
            print(f"  [{tag:5s}] GKOT_{e}_{n}  ({region})")
            continue
        resolved.append((e, n, region))

    pending = []
    for e, n, region in resolved:
        dest = DATA_DIR / f"GKOT_{e}_{n}.laz"
        if dest.exists():
            skipped_ids.append(f"{e}_{n}")
            print(f"  [skip] GKOT_{e}_{n}  (already in data/)")
        else:
            pending.append((e, n, region))

    workers = max(1, args.workers)
    if workers == 1:
        results = [
            (e, n, download_tile(e, n, region, show_progress=True))
            for e, n, region in pending
        ]
    else:
        print(f"\nDownloading {len(pending)} tile(s) with {workers} workers...")
        results = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(download_tile, e, n, region, False): (e, n)
                for e, n, region in pending
            }
            for future in as_completed(futures):
                e, n = futures[future]
                results.append((e, n, future.result()))

    for e, n, succeeded in results:
        if succeeded:
            downloaded_ids.append(f"{e}_{n}")
        else:
            unavailable_ids.append(f"{e}_{n}")

    # Summary
    if not args.dry_run:
        print()
        print(f"Downloaded  : {len(downloaded_ids)}")
        if skipped_ids:
            print(f"Skipped     : {len(skipped_ids)} (already had them)")
        if unavailable_ids:
            print(f"Unavailable : {unavailable_ids}")

    # Optional pipeline pass on new tiles only
    if args.pipeline and downloaded_ids:
        print(f"\nRunning pipeline on {len(downloaded_ids)} new tile(s)...")
        import subprocess
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "pipeline.py")] + downloaded_ids
        )


if __name__ == "__main__":
    main()
