#!/usr/bin/env python3
"""
Multi-tile LiDAR pipeline.

Discovers all GKOT_*.laz tiles in data/, processes each through the
four-factor flood-susceptibility model, writes per-tile PNG overlays to
web/data/tiles/<tile>/, and produces a combined manifest.json and a
globally-ranked risk_points.geojson for the MapLibre web app.

Usage:
    python pipeline.py                   # process every GKOT tile in data/
    python pipeline.py 478_73            # one specific tile
    python pipeline.py 478_73 478_74     # explicit list
"""

import sys, json, time, warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter, distance_transform_edt
from pyproj import Transformer
from PIL import Image
import laspy

warnings.filterwarnings("ignore")

# ── Paths & constants ─────────────────────────────────────────────────────────
DATA    = Path("data")
WEBDATA = Path("web/data")
TILES   = WEBDATA / "tiles"

GRID_RES = 2.0    # m — horizontal grid cell
VOXEL_H  = 2.0    # m — vertical voxel slice
OUT_SIZE = 1000   # pixels per exported PNG side
TOP_N    = 20     # globally-ranked risk points to emit
SEP_M    = 50     # minimum separation between risk points (metres)

XFORM = Transformer.from_crs("EPSG:3794", "EPSG:4326", always_xy=True)

CLASS_COLORS = {
    1:  (128, 128, 128, 200),   # unclassified
    2:  (194, 154, 108, 220),   # ground
    3:  (154, 230, 102, 220),   # low veg
    4:  ( 51, 180,  51, 220),   # mid veg
    5:  (  0, 102,   0, 220),   # high veg
    6:  (230,  51,  51, 220),   # building
    7:  ( 77,  77,  77, 180),   # low point / noise
   18:  ( 77,  77,  77, 180),   # high noise
}

# ── Shared helpers ────────────────────────────────────────────────────────────

def norm01(a, lo=2, hi=98):
    pl, ph = np.percentile(a, lo), np.percentile(a, hi)
    return np.clip((a - pl) / max(ph - pl, 1e-6), 0, 1)


def d8_accumulate(dem, res):
    """Single-flow-direction (D8) upslope area accumulation."""
    r, c   = dem.shape
    accum  = np.ones((r, c), dtype=np.float64)
    order  = np.argsort(-dem.ravel())
    ri, ci = order // c, order % c
    dirs   = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
    sq2    = res * 1.41421356
    for i in range(len(order)):
        row, col = ri[i], ci[i]
        bs, bdr, bdc = 0.0, 0, 0
        for dr, dc in dirs:
            nr, nc = row + dr, col + dc
            if 0 <= nr < r and 0 <= nc < c:
                d = sq2 if (dr and dc) else float(res)
                s = (dem[row, col] - dem[nr, nc]) / d
                if s > bs:
                    bs, bdr, bdc = s, dr, dc
        if bdr or bdc:
            accum[row + bdr, col + bdc] += accum[row, col]
    return accum


def colormap_to_rgba(arr, cmap_name, vmin=0, vmax=1, nodata_mask=None):
    import matplotlib.cm as cm
    cmap   = cm.get_cmap(cmap_name)
    normed = np.clip((arr - vmin) / max(vmax - vmin, 1e-6), 0, 1)
    rgba   = (cmap(normed) * 255).astype(np.uint8)
    if nodata_mask is not None:
        rgba[nodata_mask, 3] = 0
    # Row-0 in numpy = south; row-0 in image = north — flip vertically.
    return Image.fromarray(np.flipud(rgba), mode='RGBA').resize(
        (OUT_SIZE, OUT_SIZE), Image.LANCZOS)


# ── Per-tile processing ───────────────────────────────────────────────────────

def process_tile(laz_path: Path) -> dict:
    """
    Full pipeline for one GKOT tile.

    Returns a dict with:
      'meta'       — tile metadata for manifest.json
      'candidates' — list of risk-point dicts for global ranking
    """
    tile_name = laz_path.stem.replace("GKOT_", "")
    out_dir   = TILES / tile_name
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print(f"\n{'─' * 60}")
    print(f"  Tile {tile_name}  ({laz_path.name})")
    print(f"{'─' * 60}")

    # ── Load ─────────────────────────────────────────────────────────────────
    print("  Loading...", end=" ", flush=True)
    las = laspy.read(str(laz_path))
    x   = np.asarray(las.x)
    y   = np.asarray(las.y)
    z   = np.asarray(las.z)
    cls = np.asarray(las.classification)

    try:
        red   = np.asarray(las.red).astype(np.float32)
        nir   = np.asarray(las.nir).astype(np.float32)
        denom = nir + red
        ndvi  = np.where(denom > 0, (nir - red) / denom, np.nan)
        has_nir = True
    except Exception:
        # Some tiles only carry intensity, no RGB/NIR
        ndvi    = np.full(len(x), np.nan)
        has_nir = False

    print(f"{len(x):,} pts  NIR={'yes' if has_nir else 'no (NDVI skipped)'}")

    x0, y0 = x.min(), y.min()
    x1, y1 = x.max(), y.max()
    z0, z1 = z.min(), z.max()

    cols = int((x1 - x0) / GRID_RES) + 1
    rows = int((y1 - y0) / GRID_RES) + 1
    n_z  = int((z1 - z0) / VOXEL_H)  + 1

    xi = ((x - x0) / GRID_RES).astype(np.int32).clip(0, cols - 1)
    yi = ((y - y0) / GRID_RES).astype(np.int32).clip(0, rows - 1)

    # ── Reproject bbox → WGS84 ───────────────────────────────────────────────
    lon0, lat0 = XFORM.transform(float(x0), float(y0))
    lon1, lat1 = XFORM.transform(float(x1), float(y1))
    corners = [[lon0, lat1], [lon1, lat1], [lon1, lat0], [lon0, lat0]]
    bounds  = {
        "west": lon0, "east": lon1, "south": lat0, "north": lat1,
        "corners": corners,
        "center": [(lon0 + lon1) / 2, (lat0 + lat1) / 2],
        "epsg3794": {"x0": float(x0), "y0": float(y0),
                     "x1": float(x1), "y1": float(y1)},
    }
    print(f"  lon [{lon0:.5f}, {lon1:.5f}]  lat [{lat0:.5f}, {lat1:.5f}]")

    # ── DTM from ground returns ───────────────────────────────────────────────
    print("  DTM...", end=" ", flush=True)
    ground = cls == 2
    dtm    = np.full((rows, cols), np.nan)
    xg, yg, zg = xi[ground], yi[ground], z[ground]
    for gx, gy, gz in zip(xg, yg, zg):
        cur = dtm[gy, gx]
        dtm[gy, gx] = gz if np.isnan(cur) else min(cur, gz)
    idx = distance_transform_edt(np.isnan(dtm),
                                  return_distances=False, return_indices=True)
    dtm = gaussian_filter(dtm[tuple(idx)], sigma=1.5)
    print("ok")

    # ── Factor 1: TWI (Topographic Wetness Index) ─────────────────────────────
    print("  TWI...", end=" ", flush=True)
    dy_g, dx_g = np.gradient(dtm, GRID_RES, GRID_RES)
    slope_rad  = np.arctan(np.sqrt(dx_g**2 + dy_g**2)).clip(0.001, np.pi / 2 - 0.001)
    accum      = d8_accumulate(dtm, GRID_RES)
    twi        = gaussian_filter(
        np.log(accum * GRID_RES**2 / np.tan(slope_rad)), sigma=1.0)
    print("ok")

    # ── Factor 2: 3D canopy interception ─────────────────────────────────────
    print("  Canopy interception...", end=" ", flush=True)
    laplacian  = (np.gradient(np.gradient(dtm, GRID_RES, axis=1), GRID_RES, axis=1) +
                  np.gradient(np.gradient(dtm, GRID_RES, axis=0), GRID_RES, axis=0))
    plan_curv  = -laplacian

    veg        = np.isin(cls, [3, 4, 5])
    xv, yv     = xi[veg], yi[veg]
    z_abv      = z[veg] - dtm[yi[veg], xi[veg]]
    zi_v       = np.clip((z_abv / VOXEL_H).astype(np.int32), 0, n_z - 1)
    vox        = np.zeros((rows, cols, n_z), dtype=np.int32)
    np.add.at(vox, (yv, xv, zi_v), 1)
    hw         = np.arange(1, n_z + 1, dtype=np.float32) * VOXEL_H
    ic_3d      = (vox * hw[np.newaxis, np.newaxis, :]).sum(axis=2).astype(np.float64)
    tot        = np.zeros((rows, cols))
    cveg       = np.zeros((rows, cols))
    np.add.at(tot,  (yi, xi), 1)
    np.add.at(cveg, (yv, xv), 1)
    cover      = np.where(tot > 0, cveg / tot, 0)
    n_lay      = (vox > 0).sum(axis=2).astype(np.float64)
    interc     = gaussian_filter(
        cover * (n_lay / max(n_z, 1)) * np.log1p(ic_3d), sigma=1.5)
    interc_n   = interc / max(interc.max(), 1e-6)
    print("ok")

    # ── Factor 3: NDVI canopy health ─────────────────────────────────────────
    print("  NDVI...", end=" ", flush=True)
    veg_ndvi    = ndvi[veg]
    ns, nc_arr  = np.zeros((rows, cols)), np.zeros((rows, cols))
    valid       = ~np.isnan(veg_ndvi)
    np.add.at(ns,     (yv[valid], xv[valid]), veg_ndvi[valid])
    np.add.at(nc_arr, (yv[valid], xv[valid]), 1)
    mn_ndvi     = gaussian_filter(
        np.where(nc_arr > 0, ns / nc_arr, 0.5), sigma=1.5)
    ndvi_risk   = 1.0 - np.clip(mn_ndvi, 0, 1)
    print("ok")

    # ── Factor 4: terrain roughness ───────────────────────────────────────────
    print("  Roughness...", end=" ", flush=True)
    gs2  = np.zeros((rows, cols))
    gs2s = np.zeros((rows, cols))
    gn2  = np.zeros((rows, cols))
    np.add.at(gs2,  (yg, xg), zg)
    np.add.at(gs2s, (yg, xg), zg * zg)
    np.add.at(gn2,  (yg, xg), 1)
    with np.errstate(invalid='ignore'):
        mz  = np.where(gn2 > 0, gs2  / gn2, 0)
        mz2 = np.where(gn2 > 0, gs2s / gn2, 0)
    rough   = gaussian_filter(np.sqrt(np.clip(mz2 - mz**2, 0, None)), sigma=1.0)
    rough_n = np.clip(rough / max(np.percentile(rough, 95), 1e-6), 0, 1)
    print("ok")

    # ── Composite susceptibility ──────────────────────────────────────────────
    curv_n = norm01(np.clip(plan_curv, -0.5, 0.5))
    susc   = (0.40 * norm01(twi)
            + 0.25 * (1 - interc_n)
            + 0.15 * ndvi_risk
            + 0.15 * curv_n
            + 0.05 * (1 - rough_n))
    susc   = gaussian_filter(susc, sigma=1.0)
    susc_n = norm01(susc, lo=1, hi=99)

    # ── Export PNGs ───────────────────────────────────────────────────────────
    print("  Exporting PNGs...", end=" ", flush=True)

    colormap_to_rgba(susc_n, "RdYlBu_r").save(out_dir / "susceptibility.png")
    colormap_to_rgba(mn_ndvi, "RdYlGn", vmin=0, vmax=0.85,
                     nodata_mask=(nc_arr == 0)).save(out_dir / "ndvi.png")

    cls_grid  = np.zeros((rows, cols), dtype=np.uint8)
    for c_val in [2, 3, 4, 5, 6, 1, 7, 18]:
        cls_grid[yi[cls == c_val], xi[cls == c_val]] = c_val
    rgba_cls = np.zeros((rows, cols, 4), dtype=np.uint8)
    for c_val, colour in CLASS_COLORS.items():
        rgba_cls[cls_grid == c_val] = colour
    Image.fromarray(np.flipud(rgba_cls), mode='RGBA').resize(
        (OUT_SIZE, OUT_SIZE), Image.NEAREST).save(out_dir / "classification.png")

    print("ok")

    # ── Risk candidates (kept for global ranking) ─────────────────────────────
    order      = np.argsort(-susc_n.ravel())
    used       = np.zeros(susc_n.shape, dtype=bool)
    sep_cells  = max(1, int(SEP_M / GRID_RES))
    candidates = []
    for flat_idx in order:
        r_i, c_i = flat_idx // cols, flat_idx % cols
        if not used[r_i, c_i]:
            ex  = float(x0 + c_i * GRID_RES)
            ey  = float(y0 + r_i * GRID_RES)
            lon, lat = XFORM.transform(ex, ey)
            candidates.append({
                "score":         float(susc_n[r_i, c_i]),
                "elevation_m":   round(float(dtm[r_i, c_i]), 1),
                "easting_3794":  round(ex, 1),
                "northing_3794": round(ey, 1),
                "lon": lon, "lat": lat,
                "tile": tile_name,
            })
            r0 = max(0, r_i - sep_cells); r1 = min(rows, r_i + sep_cells + 1)
            c0 = max(0, c_i - sep_cells); c1 = min(cols, c_i + sep_cells + 1)
            used[r0:r1, c0:c1] = True
        # Collect 3× TOP_N per tile so global re-ranking has plenty of choice
        if len(candidates) >= TOP_N * 3:
            break

    elapsed = time.time() - t0
    print(f"  ✓ {tile_name} in {elapsed:.0f}s")

    tile_prefix = f"tiles/{tile_name}"
    return {
        "meta": {
            "name":   tile_name,
            "source": laz_path.name,
            "bounds": bounds,
            "files": {
                "susceptibility": f"{tile_prefix}/susceptibility.png",
                "ndvi":           f"{tile_prefix}/ndvi.png",
                "classification": f"{tile_prefix}/classification.png",
            },
        },
        "candidates": candidates,
    }


# ── Orchestrator ──────────────────────────────────────────────────────────────

def main(tile_ids: list[str] | None = None):
    TILES.mkdir(parents=True, exist_ok=True)

    # Discover tiles
    if tile_ids:
        laz_files = []
        for tid in tile_ids:
            p = DATA / f"GKOT_{tid}.laz"
            if p.exists():
                laz_files.append(p)
            else:
                print(f"WARNING: {p} not found — skipping")
    else:
        laz_files = sorted(DATA.glob("GKOT_*.laz"))

    if not laz_files:
        print("No GKOT tiles found. Add GKOT_*.laz files to data/ and re-run.")
        return

    print(f"Pipeline: {len(laz_files)} tile(s) to process")
    for p in laz_files:
        print(f"  {p.stem}")

    # Process tiles
    tile_metas     = []
    all_candidates = []
    total_t0       = time.time()

    for laz_path in laz_files:
        result = process_tile(laz_path)
        tile_metas.append(result["meta"])
        all_candidates.extend(result["candidates"])

    # Global risk ranking — sort by score, de-duplicate across tile boundaries
    all_candidates.sort(key=lambda c: c["score"], reverse=True)
    selected = []
    for cand in all_candidates:
        too_close = any(
            (cand["easting_3794"]  - sel["easting_3794"])**2 +
            (cand["northing_3794"] - sel["northing_3794"])**2 < SEP_M**2
            for sel in selected
        )
        if not too_close:
            selected.append(cand)
        if len(selected) >= TOP_N:
            break

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
            "properties": {
                "rank":          rank,
                "risk_score":    round(c["score"], 3),
                "elevation_m":   c["elevation_m"],
                "easting_3794":  c["easting_3794"],
                "northing_3794": c["northing_3794"],
                "tile":          c["tile"],
            },
        }
        for rank, c in enumerate(selected, 1)
    ]
    (WEBDATA / "risk_points.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2))
    print(f"\nRisk points: {len(features)} globally-ranked points written.")

    # Union bounds (for map fitBounds)
    union = {
        "west":   min(m["bounds"]["west"]  for m in tile_metas),
        "east":   max(m["bounds"]["east"]  for m in tile_metas),
        "south":  min(m["bounds"]["south"] for m in tile_metas),
        "north":  max(m["bounds"]["north"] for m in tile_metas),
    }
    union["center"] = [(union["west"] + union["east"]) / 2,
                       (union["south"] + union["north"]) / 2]

    # Write manifest
    manifest = {
        "generated":    datetime.now(timezone.utc).isoformat(),
        "tile_count":   len(tile_metas),
        "union_bounds": union,
        "tiles":        tile_metas,
    }
    (WEBDATA / "manifest.json").write_text(json.dumps(manifest, indent=2))

    total_elapsed = time.time() - total_t0
    print(f"\nmanifest.json — {len(tile_metas)} tile(s).")
    print(f"Total time: {total_elapsed:.0f}s")
    print(f"\nAssets ready in {WEBDATA}/")
    print("Run:  python -m http.server 8765 --directory web")


if __name__ == "__main__":
    main(tile_ids=sys.argv[1:] or None)
