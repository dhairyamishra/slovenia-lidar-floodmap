"""
Export georeferenced web assets from the LiDAR analysis pipeline.
Outputs go to web/data/ and are consumed directly by the MapLibre app.

Produces:
  susceptibility.png  - flood susceptibility raster (blue->red, RGBA)
  ndvi.png            - canopy NDVI raster (red->green, RGBA)
  classification.png  - land cover classes (RGBA)
  bounds.json         - WGS84 bounding box
  risk_points.geojson - top-20 risk cells in WGS84
"""

import laspy
import numpy as np
import json
import warnings
from pathlib import Path
from PIL import Image
from scipy.ndimage import gaussian_filter, distance_transform_edt
from pyproj import Transformer

warnings.filterwarnings("ignore")

DATA   = Path("data")
WEBDATA = Path("web/data")
WEBDATA.mkdir(parents=True, exist_ok=True)

GRID_RES = 2.0
VOXEL_H  = 2.0
OUT_SIZE = 1000   # pixel resolution for exported PNGs

# ── Load ──────────────────────────────────────────────────────────────────────
print("Loading GKOT_478_73.laz...")
las = laspy.read(str(DATA / "GKOT_478_73.laz"))
x   = np.asarray(las.x);  y   = np.asarray(las.y);  z   = np.asarray(las.z)
cls = np.asarray(las.classification)
red = np.asarray(las.red).astype(np.float32)
nir = np.asarray(las.nir).astype(np.float32)
denom = nir + red
ndvi  = np.where(denom > 0, (nir - red) / denom, np.nan)
print(f"  {len(x):,} points")

x0, y0 = x.min(), y.min()
x1, y1 = x.max(), y.max()
z0, z1 = z.min(), z.max()

cols = int((x1 - x0) / GRID_RES) + 1
rows = int((y1 - y0) / GRID_RES) + 1
n_z  = int((z1 - z0) / VOXEL_H)  + 1

xi = ((x - x0) / GRID_RES).astype(np.int32).clip(0, cols - 1)
yi = ((y - y0) / GRID_RES).astype(np.int32).clip(0, rows - 1)
zi = ((z - z0) / VOXEL_H ).astype(np.int32).clip(0, n_z  - 1)

# ── Reproject bounding box to WGS84 ──────────────────────────────────────────
print("Reprojecting to WGS84...")
t = Transformer.from_crs("EPSG:3794", "EPSG:4326", always_xy=True)
lon0, lat0 = t.transform(float(x0), float(y0))
lon1, lat1 = t.transform(float(x1), float(y1))

# Corners for MapLibre ImageSource (coordinates must be [lon, lat])
# Order: top-left, top-right, bottom-right, bottom-left
corners = [
    [lon0, lat1],   # top-left  (NW)
    [lon1, lat1],   # top-right (NE)
    [lon1, lat0],   # bottom-right (SE)
    [lon0, lat0],   # bottom-left  (SW)
]
bounds = {"west": lon0, "east": lon1, "south": lat0, "north": lat1,
          "corners": corners,
          "center": [(lon0 + lon1) / 2, (lat0 + lat1) / 2],
          "epsg3794": {"x0": float(x0), "y0": float(y0),
                       "x1": float(x1), "y1": float(y1)}}
print(f"  WGS84 bbox: lon [{lon0:.5f}, {lon1:.5f}]  lat [{lat0:.5f}, {lat1:.5f}]")

(WEBDATA / "bounds.json").write_text(json.dumps(bounds, indent=2))
print(f"  Saved bounds.json")

# ── Build DTM + susceptibility (same logic as flood_susceptibility.py) ────────
print("\nBuilding DTM and susceptibility...")

ground = cls == 2
dtm = np.full((rows, cols), np.nan)
xg, yg, zg = xi[ground], yi[ground], z[ground]
for gx, gy, gz in zip(xg, yg, zg):
    cur = dtm[gy, gx]
    dtm[gy, gx] = gz if np.isnan(cur) else min(cur, gz)
nan_mask = np.isnan(dtm)
idx = distance_transform_edt(nan_mask, return_distances=False, return_indices=True)
dtm  = dtm[tuple(idx)]
dtm  = gaussian_filter(dtm, sigma=1.5)

dy_g, dx_g   = np.gradient(dtm, GRID_RES, GRID_RES)
slope_rad    = np.arctan(np.sqrt(dx_g**2 + dy_g**2)).clip(0.001, np.pi/2 - 0.001)
laplacian    = (np.gradient(np.gradient(dtm, GRID_RES, axis=1), GRID_RES, axis=1) +
                np.gradient(np.gradient(dtm, GRID_RES, axis=0), GRID_RES, axis=0))
plan_curv    = -laplacian

def d8_accumulate(dem, res):
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
            nr, nc = row+dr, col+dc
            if 0 <= nr < r and 0 <= nc < c:
                d = sq2 if (dr and dc) else float(res)
                s = (dem[row,col] - dem[nr,nc]) / d
                if s > bs: bs, bdr, bdc = s, dr, dc
        if bdr or bdc:
            accum[row+bdr, col+bdc] += accum[row, col]
    return accum

accum        = d8_accumulate(dtm, GRID_RES)
spec_area    = accum * (GRID_RES**2)
twi          = gaussian_filter(np.log(spec_area / np.tan(slope_rad)), sigma=1.0)

veg          = np.isin(cls, [3,4,5])
xv, yv       = xi[veg], yi[veg]
gnd_z_v      = dtm[yi[veg], xi[veg]]
z_abv        = z[veg] - gnd_z_v
zi_v         = np.clip((z_abv / VOXEL_H).astype(np.int32), 0, n_z-1)
vox          = np.zeros((rows, cols, n_z), dtype=np.int32)
np.add.at(vox, (yv, xv, zi_v), 1)
hw           = np.arange(1, n_z+1, dtype=np.float32) * VOXEL_H
ic_3d        = (vox * hw[np.newaxis, np.newaxis, :]).sum(axis=2).astype(np.float64)
tot          = np.zeros((rows, cols)); np.add.at(tot, (yi, xi), 1)
cveg         = np.zeros((rows, cols)); np.add.at(cveg, (yv, xv), 1)
cover        = np.where(tot > 0, cveg / tot, 0)
n_lay        = (vox > 0).sum(axis=2).astype(np.float64)
interc       = gaussian_filter(cover * (n_lay / max(n_z,1)) * np.log1p(ic_3d), sigma=1.5)
interc_n     = interc / max(interc.max(), 1e-6)

veg_ndvi     = ndvi[veg]
ns, nc_arr   = np.zeros((rows,cols)), np.zeros((rows,cols))
valid        = ~np.isnan(veg_ndvi)
np.add.at(ns, (yv[valid], xv[valid]), veg_ndvi[valid])
np.add.at(nc_arr, (yv[valid], xv[valid]), 1)
mn_ndvi      = gaussian_filter(np.where(nc_arr > 0, ns/nc_arr, 0.5), sigma=1.5)
ndvi_risk    = 1.0 - np.clip(mn_ndvi, 0, 1)

gs2, gs2s    = np.zeros((rows,cols)), np.zeros((rows,cols))
gn2          = np.zeros((rows,cols))
np.add.at(gs2,  (yg, xg), zg);  np.add.at(gs2s, (yg, xg), zg*zg)
np.add.at(gn2,  (yg, xg), 1)
with np.errstate(invalid='ignore'):
    mz  = np.where(gn2>0, gs2/gn2,  0)
    mz2 = np.where(gn2>0, gs2s/gn2, 0)
rough        = gaussian_filter(np.sqrt(np.clip(mz2 - mz**2, 0, None)), sigma=1.0)
rough_n      = np.clip(rough / max(np.percentile(rough, 95), 1e-6), 0, 1)

def norm01(a, lo=2, hi=98):
    pl, ph = np.percentile(a, lo), np.percentile(a, hi)
    return np.clip((a - pl) / max(ph-pl, 1e-6), 0, 1)

curv_n  = norm01(np.clip(plan_curv, -0.5, 0.5))
susc    = (0.40 * norm01(twi) + 0.25 * (1-interc_n) +
           0.15 * ndvi_risk   + 0.15 * curv_n + 0.05 * (1-rough_n))
susc    = gaussian_filter(susc, sigma=1.0)
susc_n  = norm01(susc, lo=1, hi=99)
print("  Susceptibility done.")

# ── Helper: array -> coloured RGBA PNG ───────────────────────────────────────

def colormap_to_rgba(arr, cmap_name, vmin=0, vmax=1, alpha=0.85,
                     nodata_mask=None):
    """
    Apply a matplotlib colormap and return a PIL RGBA Image.
    nodata_mask (bool array, True = transparent) applied before colouring.
    """
    import matplotlib.cm as cm
    cmap  = cm.get_cmap(cmap_name)
    normed = np.clip((arr - vmin) / max(vmax - vmin, 1e-6), 0, 1)
    rgba  = (cmap(normed) * 255).astype(np.uint8)      # H x W x 4
    if nodata_mask is not None:
        rgba[nodata_mask, 3] = 0
    # Flip vertically: numpy row-0 is south, image row-0 is north
    rgba  = np.flipud(rgba)
    img   = Image.fromarray(rgba, mode='RGBA')
    img   = img.resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
    return img

# ── Export: flood susceptibility ─────────────────────────────────────────────
print("Exporting susceptibility.png...")
susc_img = colormap_to_rgba(susc_n, "RdYlBu_r", alpha=0.85)
susc_img.save(WEBDATA / "susceptibility.png")
print(f"  Saved {WEBDATA/'susceptibility.png'}")

# ── Export: NDVI forest coverage ──────────────────────────────────────────────
print("Exporting ndvi.png...")
# Per-column mean NDVI (all points, not just veg — veg cells will dominate)
ndvi_img = colormap_to_rgba(mn_ndvi, "RdYlGn", vmin=0, vmax=0.85,
                             nodata_mask=(nc_arr == 0))
ndvi_img.save(WEBDATA / "ndvi.png")
print(f"  Saved {WEBDATA/'ndvi.png'}")

# ── Export: land classification ───────────────────────────────────────────────
print("Exporting classification.png...")
CLASS_COLORS = {
    1:  (128, 128, 128, 200),
    2:  (194, 154, 108, 220),
    3:  (154, 230, 102, 220),
    4:  ( 51, 180,  51, 220),
    5:  (  0, 102,   0, 220),
    6:  (230,  51,  51, 220),
    7:  ( 77,  77,  77, 180),
    18: ( 77,  77,  77, 180),
}
cls_grid = np.zeros((rows, cols), dtype=np.uint8)
for c_val in [2, 3, 4, 5, 6, 1, 7, 18]:
    mask = cls == c_val
    cls_grid[yi[mask], xi[mask]] = c_val

rgba_cls = np.zeros((rows, cols, 4), dtype=np.uint8)
for c_val, colour in CLASS_COLORS.items():
    m = cls_grid == c_val
    rgba_cls[m] = colour
rgba_cls = np.flipud(rgba_cls)
cls_img  = Image.fromarray(rgba_cls, mode='RGBA').resize((OUT_SIZE, OUT_SIZE), Image.NEAREST)
cls_img.save(WEBDATA / "classification.png")
print(f"  Saved {WEBDATA/'classification.png'}")

# ── Export: risk points GeoJSON ───────────────────────────────────────────────
print("Exporting risk_points.geojson...")

# Top-20 highest-risk cells (non-overlapping, min 5-cell separation)
flat_susc   = susc_n.ravel()
candidates  = np.argsort(-flat_susc)
selected    = []
used        = np.zeros(susc_n.shape, dtype=bool)
SEP         = 10   # cells

for idx in candidates:
    r_i, c_i = idx // cols, idx % cols
    if not used[r_i, c_i]:
        selected.append((float(susc_n[r_i, c_i]), r_i, c_i))
        r0 = max(0, r_i - SEP); r1 = min(rows, r_i + SEP + 1)
        c0 = max(0, c_i - SEP); c1 = min(cols, c_i + SEP + 1)
        used[r0:r1, c0:c1] = True
    if len(selected) >= 20:
        break

features = []
for rank, (score, r_i, c_i) in enumerate(selected, 1):
    ex = float(x0 + c_i * GRID_RES)
    ey = float(y0 + r_i * GRID_RES)
    lon, lat = t.transform(ex, ey)
    elev     = float(dtm[r_i, c_i])
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "rank":       rank,
            "risk_score": round(score, 3),
            "elevation_m": round(elev, 1),
            "easting_3794":  round(ex, 1),
            "northing_3794": round(ey, 1),
        }
    })

geojson = {"type": "FeatureCollection", "features": features}
(WEBDATA / "risk_points.geojson").write_text(json.dumps(geojson, indent=2))
print(f"  Saved risk_points.geojson ({len(features)} points)")

print("\nAll web assets ready in web/data/")
print(f"  Tile centre: lon={bounds['center'][0]:.5f}  lat={bounds['center'][1]:.5f}")
