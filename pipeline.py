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
    python pipeline.py --calibrate       # derive global constants (run once)

Scores use GLOBAL fixed-range normalisation so they are comparable across tiles.
The ranges live in calibration.json, derived by --calibrate. The normal pipeline
warns if the dataset in data/ has changed since calibration (see DECISIONS.md D15).
"""

import os, sys, json, time, hashlib, warnings
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from scipy.ndimage import gaussian_filter, distance_transform_edt, binary_propagation
from pyproj import Transformer
from PIL import Image
import laspy

import kernels  # Numba-accelerated DTM grouped-min + D8 accumulation
from model_diagnostics import write_stratified_sample

warnings.filterwarnings("ignore")

# ── Paths & constants ─────────────────────────────────────────────────────────
DATA    = Path("data")
WEBDATA = Path("web/data")
TILES   = WEBDATA / "tiles"

GRID_RES = 2.0    # m — horizontal grid cell
VOXEL_H  = 2.0    # m — vertical voxel slice
OUT_SIZE = 1000   # pixels per exported PNG side
# A no-ground cell counts as no-data (transparent, excluded from calib/candidates)
# only if it is farther than this many cells from any ground return. Within it,
# gap-fill is well-constrained — keeps forest/building holes filled, masks only
# genuine large gaps (open water / sea). Tuned on real tiles (D19).
NODATA_FILL_CELLS = 8   # 16 m at 2 m resolution
TOP_N    = 20     # globally-ranked risk points to emit
SEP_M    = 50     # minimum separation between risk points (metres)
REGION_CAP = 7    # max risk points from any one CDN region. Scores are per-region
                  # normalised (D17), so the global top-N otherwise floods with the
                  # region holding the largest maximally-low-flat patch (e.g. Koper
                  # port). Capping de-clusters so every region's worst spots show.
GLOBAL_CANDS_N = 500  # max entries kept in the global candidates file
MODEL_VERSION = "D19-baseline-v1"
DIAG_SAMPLES_PER_TILE = 2500
DIAG_DIR = Path("output/diagnostics/samples")
COASTAL_REGION = "01-koper"
COASTAL_SLR_SCENARIOS = {
    "slr_0_5m": 0.5,
    "slr_1_0m": 1.0,
    "slr_2_0m": 2.0,
}

# Global normalisation constants (see DECISIONS.md D15). Each factor is scaled
# against a FIXED dataset-wide range so scores are comparable across tiles, not
# re-curved per tile. Derived once by `python pipeline.py --calibrate`, which
# writes calibration.json. These DEFAULTs are placeholders used only when no
# calibration.json exists yet — run --calibrate for real values.
CALIB_PATH = Path("calibration.json")
CALIB_PCTL = (2, 98)   # percentiles used to derive each factor's [lo, hi]
# Contributing-area threshold (m²) that defines the channel network for HAND.
# Tuned on real tiles (D19): ~0% streams on flat floodplains (HAND falls back to
# height-above-outlet, correctly ~uniformly low), 0.3–0.7% on valley/alpine tiles
# (sane drainage density). Per-tile accumulation is edge-truncated, so this is
# lower than a regional-DEM threshold would be.
STREAM_AREA_M2 = 10_000.0
DEFAULT_CONSTANTS = {
    "twi":    [4.0, 15.0],
    "hand":   [0.0, 60.0],
    "elev":   [200.0, 1500.0],
    "slope":  [0.0, 1.0],
    "interc": [0.0, 5.0],
    "ndvi":   [0.0, 0.15],
    "curv":   [-0.5, 0.5],
    "rough":  [0.0, 1.2],
}
DEFAULT_DISPLAY = {"susc": [0.2, 0.8]}

# Susceptibility model (D19 — HAND added). Each factor is normalised against
# PER-REGION fixed ranges, then combined with these weights. `invert=True` means
# risk RISES as the factor falls — low HAND (near the channel), low elevation,
# flat slope, and sparse canopy/vegetation are the risky ends. Roughness dropped.
# Weights match the flood-literature consensus (HANDOFF.md) and sum to 1.0.
# Land-cover/imperviousness (~5%) is still pending — would reclaim veg weight.
FACTOR_COLS = ["twi", "hand", "elev", "slope", "interc", "ndvi", "curv", "rough"]
FACTOR_KEYS = {  # model-factor name -> compute_factors() output key
    "twi": "twi", "hand": "hand", "elev": "dtm", "slope": "slope",
    "interc": "interc", "ndvi": "mn_ndvi", "curv": "plan_curv", "rough": "rough",
}
SUSC_WEIGHTS = [  # (factor, weight, invert)
    ("hand",   0.25, True),   # low height-above-drainage -> high risk (#1 factor)
    ("twi",    0.20, False),  # high topographic wetness
    ("elev",   0.15, True),   # low elevation  -> high risk
    ("slope",  0.15, True),   # flat terrain   -> high risk
    ("curv",   0.10, False),  # concave plan curvature
    ("interc", 0.075, True),  # less canopy interception
    ("ndvi",   0.075, True),  # sparser vegetation
]   # roughness intentionally weight 0; sums to 1.0


def composite_susc(norm_of):
    """Weighted susceptibility from a normaliser `norm_of(factor) -> [0,1] array`.
    Shared by export_tile (full grids) and calibrate (pooled samples) so the
    weights live in exactly one place."""
    s = 0.0
    for nm, w, inv in SUSC_WEIGHTS:
        v = norm_of(nm)
        s = s + w * ((1.0 - v) if inv else v)
    return s


def model_definition() -> dict:
    """Machine-readable provenance for manifests and diagnostic reports."""
    definition = {
        "version": MODEL_VERSION,
        "grid_res_m": GRID_RES,
        "stream_area_m2": STREAM_AREA_M2,
        "normalisation": "per-region-p2-p98",
        "weights": [
            {"factor": nm, "weight": w, "invert": inv}
            for nm, w, inv in SUSC_WEIGHTS
        ],
        "known_limitations": [
            "per-tile-flow-routing",
            "unconditioned-dem",
            "region-relative-scores",
            "not-probability-calibrated",
        ],
    }
    payload = json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
    definition["definition_digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()[:16]
    return definition


def file_digest(path: Path) -> str | None:
    """Short content digest for small provenance/configuration files."""
    if not path.exists():
        return None
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def write_diagnostic_sample(f: dict, normed: dict, susc: np.ndarray,
                            susc_disp: np.ndarray, region: str) -> None:
    """Write a deterministic, score-stratified full-grid sample for audits.

    Samples live under ignored ``output/`` and deliberately include the entire
    score distribution rather than only the top-ranked candidate tail. Equal
    quotas across score deciles preserve rare high/low cells while keeping the
    per-tile artifact small enough for routine full-dataset analysis.
    """
    write_stratified_sample(
        DIAG_DIR / f"{f['tile_name']}.npz",
        tile=f["tile_name"], region=region, model_version=MODEL_VERSION,
        rows=f["rows"], cols=f["cols"], x0=f["x0"], y0=f["y0"],
        grid_res=GRID_RES,
        raw_factors={nm: f[FACTOR_KEYS[nm]] for nm in FACTOR_COLS},
        normalized_factors=normed,
        score=susc, display_score=susc_disp,
        max_samples=DIAG_SAMPLES_PER_TILE,
    )

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

def norm_fixed(a, lo, hi):
    """Scale against a FIXED [lo, hi] range (global ruler), clip to [0, 1]."""
    return np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1)


# d8_accumulate (single-flow-direction upslope accumulation) is now Numba-
# accelerated in kernels.py — see kernels.d8_accumulate. Bit-identical output,
# ~70x faster (verified by bench_kernels.py).


def colormap_to_rgba(arr, cmap_name, vmin=0, vmax=1, nodata_mask=None):
    import matplotlib
    try:
        cmap = matplotlib.colormaps[cmap_name]
    except AttributeError:  # older matplotlib
        import matplotlib.cm as cm
        cmap = cm.get_cmap(cmap_name)
    normed = np.clip((arr - vmin) / max(vmax - vmin, 1e-6), 0, 1)
    rgba   = (cmap(normed) * 255).astype(np.uint8)
    if nodata_mask is not None:
        rgba[nodata_mask, 3] = 0
    # Row-0 in numpy = south; row-0 in image = north — flip vertically.
    return Image.fromarray(np.flipud(rgba), mode='RGBA').resize(
        (OUT_SIZE, OUT_SIZE), Image.LANCZOS)


def coastal_mask_to_rgba(mask):
    """Render a binary coastal-inundation mask as transparent/cyan RGBA."""
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[mask] = (56, 189, 248, 210)
    return Image.fromarray(np.flipud(rgba), mode='RGBA').resize(
        (OUT_SIZE, OUT_SIZE), Image.NEAREST)


def coastal_inundation_mask(dtm, ground_cov, sea_level_m):
    """
    First-order coastal bathtub mask for Koper (D20).

    Land is flagged only when its DTM elevation is below the selected sea-level
    scenario and it connects to a no-data/sea cell within the tile. This avoids
    filling isolated inland depressions while keeping the implementation local
    to the existing per-tile pipeline.
    """
    eligible = ground_cov & np.isfinite(dtm) & (dtm <= sea_level_m)
    sea = ~ground_cov
    if not sea.any() or not eligible.any():
        return np.zeros(dtm.shape, dtype=bool)
    connected = binary_propagation(sea, mask=(sea | eligible))
    return connected & eligible


# ── Per-tile processing ───────────────────────────────────────────────────────

def compute_factors(laz_path: Path) -> dict:
    """
    Load one GKOT tile and compute the five RAW (un-normalised) risk factors
    plus all grid metadata. Shared by both the normal pipeline and the
    calibration pass — neither normalises here, so the raw values can be pooled
    across tiles to derive the global constants.
    """
    tile_name = laz_path.stem.replace("GKOT_", "")
    out_dir   = TILES / tile_name
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print(f"\n{'-' * 60}")
    print(f"  Tile {tile_name}  ({laz_path.name})")
    print(f"{'-' * 60}")

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
    xg, yg, zg = xi[ground], yi[ground], z[ground]
    # lowest ground-return z per cell (NaN where none) — Numba grouped-min
    dtm = kernels.dtm_min_grid(rows, cols, yg, xg, zg)
    # Gap-fill every empty cell from its nearest ground return, and record how far
    # that fill reached. A cell counts as having data if it had a ground return or
    # sits within NODATA_FILL_CELLS of one (forest/building holes — gap-fill is
    # well-constrained there). Cells far from any ground return (open water / sea)
    # stay no-data: rendered transparent and kept out of calibration + candidates
    # (D18 mask, refined D19 to a distance threshold so dense canopy / urban tiles
    # don't get salt-and-pepper holes).
    dist, idx = distance_transform_edt(np.isnan(dtm),
                                       return_distances=True, return_indices=True)
    ground_cov = dist <= NODATA_FILL_CELLS
    dtm = gaussian_filter(dtm[tuple(idx)], sigma=1.5)
    print("ok")

    # ── Factor 1: TWI (Topographic Wetness Index) ─────────────────────────────
    print("  TWI...", end=" ", flush=True)
    dy_g, dx_g = np.gradient(dtm, GRID_RES, GRID_RES)
    slope_rad  = np.arctan(np.sqrt(dx_g**2 + dy_g**2)).clip(0.001, np.pi / 2 - 0.001)
    accum      = kernels.d8_accumulate(dtm, GRID_RES)
    twi        = gaussian_filter(
        np.log(accum * GRID_RES**2 / np.tan(slope_rad)), sigma=1.0)
    print("ok")

    # ── Factor 2: HAND (Height Above Nearest Drainage) ────────────────────────
    # Per-tile cut (D19): stream net from the D8 accumulation above, then each
    # cell's height above the channel it drains to. Flow is routed within the
    # tile, so paths crossing a tile edge terminate there (known approximation).
    print("  HAND...", end=" ", flush=True)
    hand = gaussian_filter(
        kernels.hand_grid(dtm, accum, GRID_RES, STREAM_AREA_M2), sigma=1.0)
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
    print("ok")

    # ── Factor 3: NDVI canopy health ─────────────────────────────────────────
    print("  NDVI...", end=" ", flush=True)
    veg_ndvi    = ndvi[veg]
    ns, nc_arr  = np.zeros((rows, cols)), np.zeros((rows, cols))
    valid       = ~np.isnan(veg_ndvi)
    np.add.at(ns,     (yv[valid], xv[valid]), veg_ndvi[valid])
    np.add.at(nc_arr, (yv[valid], xv[valid]), 1)
    # Fill cells with no veg returns with the tile median before smoothing
    # so gaussian_filter doesn't spread nan. Cells are masked for display later.
    ndvi_fill   = float(np.nanmedian(ns[nc_arr > 0] / nc_arr[nc_arr > 0])) \
                  if (nc_arr > 0).any() else 0.0
    mn_ndvi     = gaussian_filter(
        np.where(nc_arr > 0, ns / nc_arr, ndvi_fill), sigma=1.5)
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
    print("ok")

    return {
        "tile_name": tile_name, "out_dir": out_dir, "source": laz_path.name,
        "rows": rows, "cols": cols, "x0": x0, "y0": y0, "t0": t0,
        "bounds": bounds, "dtm": dtm, "ground_cov": ground_cov,
        # raw (un-normalised) factors ("dtm" above doubles as the elevation factor):
        "twi": twi, "hand": hand, "interc": interc, "mn_ndvi": mn_ndvi,
        "plan_curv": plan_curv, "rough": rough, "slope": slope_rad,
        # display / classification helpers:
        "nc_arr": nc_arr, "cls": cls, "xi": xi, "yi": yi,
    }


def export_tile(f: dict, const: dict, display: dict, region: str = "default") -> dict:
    """
    Normalise a tile's raw factors against the GLOBAL constants, build the
    composite, export PNGs, and return manifest meta + risk candidates.

    Returns a dict with:
      'meta'       — tile metadata for manifest.json
      'candidates' — list of risk-point dicts for global ranking
    """
    tile_name, out_dir = f["tile_name"], f["out_dir"]
    rows, cols         = f["rows"], f["cols"]
    x0, y0, dtm        = f["x0"], f["y0"], f["dtm"]
    nc_arr             = f["nc_arr"]

    # ── Composite susceptibility (PER-REGION fixed-range normalisation, D17) ──
    normed   = {nm: norm_fixed(f[FACTOR_KEYS[nm]], *const[nm]) for nm in FACTOR_COLS}
    susc     = composite_susc(lambda nm: normed[nm])
    susc     = gaussian_filter(susc, sigma=1.0)
    # Confine scoring + display to cells with real ground returns. Sea / no-data
    # cells (coastal tiles) become NaN -> transparent in the PNG and excluded
    # from candidates, rather than painting extrapolated terrain over water.
    ground_cov = f["ground_cov"]
    susc       = np.where(ground_cov, susc, np.nan)
    # Display also uses a fixed range so heatmap colours mean the same thing
    # across tiles. susc itself is now a global score, so candidates use it raw.
    susc_disp = norm_fixed(susc, *display["susc"])
    write_diagnostic_sample(f, normed, susc, susc_disp, region)

    # ── Export PNGs ───────────────────────────────────────────────────────────
    print("  Exporting PNGs...", end=" ", flush=True)

    colormap_to_rgba(susc_disp, "RdYlBu_r",
                     nodata_mask=~ground_cov).save(out_dir / "susceptibility.png")
    # NDVI display keeps its per-tile p5–p95 veg-cell stretch (D08): this layer
    # is a forest-health visualisation, not a cross-tile risk score.
    mn_ndvi     = f["mn_ndvi"]
    veg_cells   = mn_ndvi[nc_arr > 0]
    if veg_cells.size:
        ndvi_lo = float(np.percentile(veg_cells, 5))
        ndvi_hi = float(np.percentile(veg_cells, 95))
    else:                       # no vegetation returns (e.g. open-sea tile)
        ndvi_lo, ndvi_hi = 0.0, 0.15
    colormap_to_rgba(mn_ndvi, "RdYlGn", vmin=ndvi_lo, vmax=ndvi_hi,
                     nodata_mask=(nc_arr == 0)).save(out_dir / "ndvi.png")

    cls, xi, yi = f["cls"], f["xi"], f["yi"]
    cls_grid  = np.zeros((rows, cols), dtype=np.uint8)
    for c_val in [2, 3, 4, 5, 6, 1, 7, 18]:
        cls_grid[yi[cls == c_val], xi[cls == c_val]] = c_val
    rgba_cls = np.zeros((rows, cols, 4), dtype=np.uint8)
    for c_val, colour in CLASS_COLORS.items():
        rgba_cls[cls_grid == c_val] = colour
    Image.fromarray(np.flipud(rgba_cls), mode='RGBA').resize(
        (OUT_SIZE, OUT_SIZE), Image.NEAREST).save(out_dir / "classification.png")

    coastal_files = {}
    if region == COASTAL_REGION:
        for key, sea_level_m in COASTAL_SLR_SCENARIOS.items():
            mask = coastal_inundation_mask(dtm, ground_cov, sea_level_m)
            filename = f"coastal_{key}.png"
            coastal_mask_to_rgba(mask).save(out_dir / filename)
            coastal_files[key] = f"tiles/{tile_name}/{filename}"

    print("ok")

    # ── Risk candidates (kept for global ranking) ─────────────────────────────
    # Score on raw susc, which is now built from globally-normalised factors —
    # so the same terrain scores the same regardless of which tile it sits in.
    order      = np.argsort(-susc.ravel())
    used       = np.zeros(susc.shape, dtype=bool)
    sep_cells  = max(1, int(SEP_M / GRID_RES))
    candidates = []
    for flat_idx in order:
        r_i, c_i = flat_idx // cols, flat_idx % cols
        if not np.isfinite(susc[r_i, c_i]):
            break               # NaN (sea / no-data) cells sort to the end
        if not used[r_i, c_i]:
            ex  = float(x0 + c_i * GRID_RES)
            ey  = float(y0 + r_i * GRID_RES)
            lon, lat = XFORM.transform(ex, ey)
            candidates.append({
                "score":         float(susc[r_i, c_i]),
                "elevation_m":   round(float(dtm[r_i, c_i]), 1),
                "easting_3794":  round(ex, 1),
                "northing_3794": round(ey, 1),
                "lon": lon, "lat": lat,
                "tile": tile_name,
                "model_version": MODEL_VERSION,
            })
            r0 = max(0, r_i - sep_cells); r1 = min(rows, r_i + sep_cells + 1)
            c0 = max(0, c_i - sep_cells); c1 = min(cols, c_i + sep_cells + 1)
            used[r0:r1, c0:c1] = True
        # Collect 3× TOP_N per tile so global re-ranking has plenty of choice
        if len(candidates) >= TOP_N * 3:
            break

    elapsed = time.time() - f["t0"]
    print(f"  [done] {tile_name} in {elapsed:.0f}s")

    tile_prefix = f"tiles/{tile_name}"
    files = {
        "susceptibility": f"{tile_prefix}/susceptibility.png",
        "ndvi":           f"{tile_prefix}/ndvi.png",
        "classification": f"{tile_prefix}/classification.png",
    }
    if coastal_files:
        files["coastal"] = coastal_files

    return {
        "meta": {
            "name":   tile_name,
            "source": f["source"],
            "bounds": f["bounds"],
            "files": files,
            "model_version": MODEL_VERSION,
        },
        "candidates": candidates,
    }


# ── Parallelism ────────────────────────────────────────────────────────────────
# Tiles are independent, so compute_factors + export_tile fan out across processes.
# The big arrays never cross the process boundary: export_tile writes the PNGs to
# disk inside the worker and returns only the small manifest meta + risk candidates.
# Worker fns are module-level so they pickle under Windows `spawn`.

def _process_one(args):
    """Worker: process one tile end-to-end, return its small meta + candidates."""
    laz_path, const, display, region = args
    return export_tile(compute_factors(laz_path), const, display, region)


def _calib_sample_one(args):
    """Worker: compute one tile's factors, return a small (k, 5) subsample of the
    five raw factors for pooled percentile calibration. Per-tile seed keeps the
    subsample deterministic regardless of worker scheduling (statistically
    equivalent to the old single-stream RNG — p2/p98 over millions of pooled
    cells is insensitive to the exact subsample)."""
    laz_path, sample_frac, seed = args
    f    = compute_factors(laz_path)
    flat = [f[FACTOR_KEYS[nm]].ravel() for nm in FACTOR_COLS]
    # Calibrate on real terrain only: cells with a ground return AND finite
    # factors. Excludes coastal no-data (sea) so ranges aren't skewed by
    # gap-fill-extrapolated water; all-sea tiles contribute nothing.
    valid = f["ground_cov"].ravel().copy()
    for a in flat:
        valid &= np.isfinite(a)
    if not valid.any():
        return np.empty((0, len(FACTOR_COLS)), dtype=np.float32)
    flat = [a[valid] for a in flat]
    n    = flat[0].size
    k    = max(1, int(n * sample_frac))
    idx  = np.random.default_rng(seed).choice(n, size=k, replace=False)
    return np.column_stack([a[idx] for a in flat]).astype(np.float32)


def _default_workers() -> int:
    """Worker count bounded by available RAM, not core count. These tiles peak
    ~4-6 GB/worker (large point clouds + tall voxel grids), so memory is the wall;
    32 cores stay idle long before RAM does. Falls back conservatively if memory
    can't be queried (non-Windows / no ctypes)."""
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                        ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong),
                        ("e", ctypes.c_ulonglong)]

        ms = _MS(); ms.dwLength = ctypes.sizeof(ms)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        avail_gb = ms.ullAvailPhys / 1e9
    except Exception:
        avail_gb = 8.0
    return max(1, min(os.cpu_count() or 1, int(avail_gb // 5.0)))


# ── Calibration & dataset fingerprint ──────────────────────────────────────────

REGION_CACHE_PATH = Path(".tile_region_cache.json")


def _region_cache() -> dict:
    """tile_name -> CDN region slug (e.g. '05-ljubljana'). Built by download_tiles.py.
    Used here as the calibration-region grouping (D17)."""
    if REGION_CACHE_PATH.exists():
        try:
            return json.loads(REGION_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def tile_region(tile_name: str, cache: dict | None = None) -> str:
    cache = _region_cache() if cache is None else cache
    return cache.get(tile_name, "default")


def dataset_fingerprint() -> dict:
    """
    Fingerprint the FULL dataset in data/ as a {tile_name: file_size} map plus a
    short digest. Name + size catches tiles added, removed, or re-downloaded
    (CDN content change → different byte size) without hashing 15 GB of LAZ.
    """
    tiles = {p.stem.replace("GKOT_", ""): p.stat().st_size
             for p in sorted(DATA.glob("GKOT_*.laz"))}
    blob   = json.dumps(tiles, sort_keys=True).encode()
    digest = "sha256:" + hashlib.sha256(blob).hexdigest()[:16]
    return {"digest": digest, "tiles": tiles}


def load_region_constants() -> tuple[dict, tuple]:
    """
    Return (region -> (constants, display) map, default (constants, display)).
    Reads the per-region `regions` block in calibration.json (D17). Falls back to
    the legacy flat format (treated as one default region) or DEFAULTs.
    """
    default = (DEFAULT_CONSTANTS, DEFAULT_DISPLAY)
    if CALIB_PATH.exists():
        try:
            c = json.loads(CALIB_PATH.read_text(encoding="utf-8"))
            regions = c.get("regions")
            if regions:
                rc = {r: (v["constants"], v["display"]) for r, v in regions.items()}
                return rc, next(iter(rc.values()), default)
            if "constants" in c:   # legacy single-region format
                return {}, (c["constants"], c.get("display", DEFAULT_DISPLAY))
        except Exception:
            pass
    return {}, default


def check_calibration() -> None:
    """Warn if calibration is missing, legacy, or doesn't cover a region in data/."""
    if not CALIB_PATH.exists():
        print("\n" + "!" * 60)
        print("  NO calibration.json — using DEFAULT constants (placeholders).")
        print("  Run:  python pipeline.py --calibrate")
        print("!" * 60)
        return
    try:
        calib = json.loads(CALIB_PATH.read_text(encoding="utf-8"))
    except Exception:
        print("  WARNING: calibration.json unreadable — using DEFAULT constants.")
        return
    regions = calib.get("regions", {})
    gen = calib.get("generated", "?")[:10]
    if not regions:
        print("  WARNING: legacy single-region calibration — run --calibrate to "
              "refresh per-region (D17).")
        return
    cache = _region_cache()
    data_regions = sorted({tile_region(p.stem.replace("GKOT_", ""), cache)
                           for p in DATA.glob("GKOT_*.laz")})
    missing = [r for r in data_regions if r not in regions]
    print(f"  Calibration: regions [{', '.join(sorted(regions))}] ({gen}).")
    if missing:
        print("\n" + "!" * 60)
        print(f"  NO calibration for region(s) {missing} present in data/ "
              f"— those tiles use DEFAULT constants.")
        print("  Run:  python pipeline.py --calibrate   (calibrates all regions)")
        print("!" * 60)


def calibrate(sample_frac: float = 0.05, workers: int | None = None,
              region: str | None = None) -> None:
    """
    Derive PER-REGION normalisation constants (D17). Tiles are grouped by their
    CDN region (from .tile_region_cache.json); each region's factor cells are
    subsampled, pooled, and reduced to p2/p98 [lo, hi] per factor, plus a composite
    display range. Disjoint regions (Ljubljana basin vs alpine Kamnik vs coastal
    Koper) need their own rulers — one global elevation range would be meaningless.

    `region=None` (re)calibrates every region present in data/; `region=NAME`
    refreshes just that one. Other regions' constants in calibration.json are
    preserved. Does NOT export tiles.
    """
    laz_files = sorted(DATA.glob("GKOT_*.laz"))
    if not laz_files:
        print("No GKOT tiles in data/ — nothing to calibrate.")
        return
    if workers is None:
        workers = _default_workers()

    cache = _region_cache()
    by_region: dict[str, list] = {}
    for laz in laz_files:
        r = tile_region(laz.stem.replace("GKOT_", ""), cache)
        by_region.setdefault(r, []).append(laz)

    if region:
        if region not in by_region:
            print(f"No tiles for region '{region}' in data/. "
                  f"Available: {sorted(by_region)}")
            return
        targets = [region]
    else:
        targets = sorted(by_region)

    # Merge into existing calibration so untouched regions are preserved.
    calib = {}
    if CALIB_PATH.exists():
        try:
            calib = json.loads(CALIB_PATH.read_text(encoding="utf-8"))
        except Exception:
            calib = {}
    regions_out = calib.get("regions", {})

    lo_p, hi_p = CALIB_PCTL
    colidx     = {nm: i for i, nm in enumerate(FACTOR_COLS)}
    for r in targets:
        rfiles = by_region[r]
        w = max(1, min(workers, len(rfiles)))
        print(f"\nCalibrating region '{r}': {len(rfiles)} tile(s) "
              f"({sample_frac:.0%} of cells) across {w} worker(s)")
        tasks = [(laz, sample_frac, i) for i, laz in enumerate(rfiles)]
        if w == 1:
            samples = [_calib_sample_one(t) for t in tasks]
        else:
            with ProcessPoolExecutor(max_workers=w) as ex:
                samples = list(ex.map(_calib_sample_one, tasks))
        samples = [s for s in samples if s.shape[0] > 0]
        if not samples:
            print(f"  region '{r}': no ground-covered cells — skipped.")
            continue
        pooled = np.concatenate(samples, axis=0)

        # nan-safe: stray no-data cells must not collapse a range to NaN.
        constants = {}
        for nm in FACTOR_COLS:
            lo = float(np.nanpercentile(pooled[:, colidx[nm]], lo_p))
            hi = float(np.nanpercentile(pooled[:, colidx[nm]], hi_p))
            constants[nm] = [round(lo, 4), round(hi, 4)]

        def nf_pooled(nm):
            lo, hi = constants[nm]
            return np.clip((pooled[:, colidx[nm]] - lo) / max(hi - lo, 1e-6), 0, 1)
        susc_s  = composite_susc(nf_pooled)
        display = {"susc": [round(float(np.nanpercentile(susc_s, 2)), 4),
                            round(float(np.nanpercentile(susc_s, 98)), 4)]}

        regions_out[r] = {"constants": constants, "display": display,
                          "tile_count": len(rfiles)}
        print(f"  region '{r}' constants (p2–p98):")
        for nm in FACTOR_COLS:
            print(f"    {nm:7s} {constants[nm]}")
        print(f"    susc(display) {display['susc']}")

    out = {
        "generated":           datetime.now(timezone.utc).isoformat(),
        "model_version":       2,
        "percentiles":         list(CALIB_PCTL),
        "sample_frac":         sample_frac,
        "regions":             regions_out,
        "dataset_fingerprint": dataset_fingerprint(),
    }
    CALIB_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nWrote {CALIB_PATH}  (regions: {', '.join(sorted(regions_out))})")


# ── Orchestrator ──────────────────────────────────────────────────────────────

def main(tile_ids: list[str] | None = None, workers: int | None = None):
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

    # Per-region normalisation constants (D17) + calibration coverage check
    region_const, default_cd = load_region_constants()
    cache = _region_cache()
    check_calibration()

    if workers is None:
        workers = _default_workers()
    workers = max(1, min(workers, len(laz_files)))

    # Process tiles — fan out across processes (each worker writes its own PNGs).
    new_metas      = []
    all_candidates = []
    total_t0       = time.time()

    # Resolve each tile's constants by its region before dispatch.
    tasks = []
    for p in laz_files:
        region = tile_region(p.stem.replace("GKOT_", ""), cache)
        cd = region_const.get(region, default_cd)
        tasks.append((p, cd[0], cd[1], region))
    if workers == 1:
        print(f"\nProcessing {len(laz_files)} tile(s) serially")
        results = [_process_one(t) for t in tasks]
    else:
        print(f"\nProcessing {len(laz_files)} tile(s) across {workers} worker(s) "
              f"(RAM-bound; override with --workers N)")
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_process_one, tasks))

    for result in results:
        new_metas.append(result["meta"])
        all_candidates.extend(result["candidates"])

    # Merge with existing manifest so partial runs don't lose old tiles
    manifest_path = WEBDATA / "manifest.json"
    existing_tiles: dict[str, dict] = {}
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            existing_tiles = {t["name"]: t for t in old.get("tiles", [])}
        except Exception:
            pass

    # New tiles overwrite old entries with the same name; others are kept
    for meta in new_metas:
        existing_tiles[meta["name"]] = meta
    tile_metas = sorted(existing_tiles.values(), key=lambda t: t["name"])

    # Merge with global candidates file (subset-run safety).
    # Load the existing global list, drop stale entries for tiles we just
    # re-processed, add fresh candidates, keep the top GLOBAL_CANDS_N by score.
    global_cands_path = WEBDATA / "candidates.json"
    processed_names   = {laz.stem.replace("GKOT_", "") for laz in laz_files}
    if global_cands_path.exists():
        try:
            kept = [c for c in json.loads(global_cands_path.read_text(encoding="utf-8"))
                    if c["tile"] not in processed_names]
            all_candidates.extend(kept)
        except Exception:
            pass
    all_candidates.sort(key=lambda c: c["score"], reverse=True)
    all_candidates = all_candidates[:GLOBAL_CANDS_N]
    global_cands_path.write_text(
        json.dumps(all_candidates, indent=2), encoding="utf-8")
    print(f"Global candidates: {len(all_candidates)} entries saved.")

    # Global risk ranking — sort by score, de-duplicate across tile boundaries,
    # and cap per CDN region (REGION_CAP) so per-region-normalised scores don't
    # let one region's large flat-low patch monopolise the global top-N.
    all_candidates.sort(key=lambda c: c["score"], reverse=True)
    selected = []
    region_counts: dict[str, int] = {}
    for cand in all_candidates:
        region = tile_region(cand["tile"], cache)
        if region_counts.get(region, 0) >= REGION_CAP:
            continue
        too_close = any(
            (cand["easting_3794"]  - sel["easting_3794"])**2 +
            (cand["northing_3794"] - sel["northing_3794"])**2 < SEP_M**2
            for sel in selected
        )
        if not too_close:
            selected.append(cand)
            region_counts[region] = region_counts.get(region, 0) + 1
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
                "model_version": c.get("model_version", MODEL_VERSION),
                "score_semantics": "relative-susceptibility-not-probability",
            },
        }
        for rank, c in enumerate(selected, 1)
    ]
    (WEBDATA / "risk_points.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2))
    print(f"\nRisk points: {len(features)} globally-ranked points written.")

    # Union bounds across ALL tiles in the merged manifest
    union = {
        "west":   min(m["bounds"]["west"]  for m in tile_metas),
        "east":   max(m["bounds"]["east"]  for m in tile_metas),
        "south":  min(m["bounds"]["south"] for m in tile_metas),
        "north":  max(m["bounds"]["north"] for m in tile_metas),
    }
    union["center"] = [(union["west"] + union["east"]) / 2,
                       (union["south"] + union["north"]) / 2]

    # Write merged manifest
    manifest = {
        "generated":    datetime.now(timezone.utc).isoformat(),
        "model":        model_definition(),
        "calibration_digest": file_digest(CALIB_PATH),
        "dataset_digest": dataset_fingerprint()["digest"],
        "tile_count":   len(tile_metas),
        "union_bounds": union,
        "tiles":        tile_metas,
    }
    (WEBDATA / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    total_elapsed = time.time() - total_t0
    print(f"\nmanifest.json — {len(tile_metas)} tile(s).")
    print(f"Total time: {total_elapsed:.0f}s")
    print(f"\nAssets ready in {WEBDATA}/")
    print("Run:  python -m http.server 8765 --directory web")


if __name__ == "__main__":
    args = sys.argv[1:]

    workers = None
    if "--workers" in args:
        i = args.index("--workers")
        try:
            workers = int(args[i + 1])
            del args[i:i + 2]
        except (IndexError, ValueError):
            print("--workers needs an integer, e.g. --workers 4")
            sys.exit(1)

    region = None
    if "--region" in args:
        i = args.index("--region")
        try:
            region = args[i + 1]
            del args[i:i + 2]
        except IndexError:
            print("--region needs a name, e.g. --region 08-kamnik")
            sys.exit(1)

    if "--calibrate" in args:
        calibrate(workers=workers, region=region)
    else:
        main(tile_ids=[a for a in args if not a.startswith("-")] or None,
             workers=workers)
