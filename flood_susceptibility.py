"""
Flood susceptibility map from 3D LiDAR voxels.

Four-factor model:
  1. TWI  (Topographic Wetness Index) — terrain convergence & slope
  2. 3D canopy interception capacity  — voxel density × height layers
  3. Canopy health (NDVI)             — stressed canopy intercepts less
  4. Terrain roughness                — rough ground = more infiltration

The key differentiator over satellite-based maps: factors 2 & 3 use
per-voxel point density across height layers, not a flat 2D NDVI pixel.
"""
import laspy
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.colors import LinearSegmentedColormap
from scipy.ndimage import gaussian_filter, binary_dilation, distance_transform_edt
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

DATA = Path("data")
OUT  = Path("output")
OUT.mkdir(exist_ok=True)

GRID_RES  = 2.0   # horizontal grid resolution (metres)
VOXEL_H   = 2.0   # vertical voxel slice height (metres)

# ── Load ──────────────────────────────────────────────────────────────────────
print("Loading GKOT_478_73.laz...")
las = laspy.read(str(DATA / "GKOT_478_73.laz"))

x   = np.asarray(las.x)
y   = np.asarray(las.y)
z   = np.asarray(las.z)
cls = np.asarray(las.classification)
red = np.asarray(las.red).astype(np.float32)
nir = np.asarray(las.nir).astype(np.float32)
ret = np.asarray(las.return_number)

denom = nir + red
ndvi  = np.where(denom > 0, (nir - red) / denom, np.nan)
print(f"  {len(x):,} points")

x0, y0 = x.min(), y.min()
x1, y1 = x.max(), y.max()
z0, z1 = z.min(), z.max()

cols = int((x1 - x0) / GRID_RES) + 1
rows = int((y1 - y0) / GRID_RES) + 1
n_z  = int((z1 - z0) / VOXEL_H) + 1

xi = ((x - x0) / GRID_RES).astype(np.int32).clip(0, cols - 1)
yi = ((y - y0) / GRID_RES).astype(np.int32).clip(0, rows - 1)
zi = ((z - z0) / VOXEL_H ).astype(np.int32).clip(0, n_z  - 1)

print(f"  Grid: {cols}x{rows} horizontal, {n_z} vertical slices @ {VOXEL_H}m each")

# ── Factor 1: DTM → slope → flow accumulation → TWI ──────────────────────────
print("\n[1/4] Building DTM and TWI...")

ground = cls == 2
dtm = np.full((rows, cols), np.nan)
# use minimum Z per cell from ground points (bare earth)
xg, yg, zg = xi[ground], yi[ground], z[ground]
for gx, gy, gz in zip(xg, yg, zg):
    cur = dtm[gy, gx]
    dtm[gy, gx] = gz if np.isnan(cur) else min(cur, gz)

# Fill gaps
nan_mask = np.isnan(dtm)
idx = distance_transform_edt(nan_mask, return_distances=False, return_indices=True)
dtm = dtm[tuple(idx)]
dtm = gaussian_filter(dtm, sigma=1.5)

# Slope
dy_grad, dx_grad = np.gradient(dtm, GRID_RES, GRID_RES)
slope_rad = np.arctan(np.sqrt(dx_grad**2 + dy_grad**2))
slope_rad = np.clip(slope_rad, 0.001, np.pi / 2 - 0.001)

# Curvature (plan) — positive = convergent = flood-prone
laplacian = np.gradient(np.gradient(dtm, GRID_RES, axis=1), GRID_RES, axis=1) + \
            np.gradient(np.gradient(dtm, GRID_RES, axis=0), GRID_RES, axis=0)
plan_curv = -laplacian  # positive = concave = water collects

# D8 flow accumulation
def d8_accumulate(dem, res):
    r, c = dem.shape
    accum = np.ones((r, c), dtype=np.float64)
    flat = dem.ravel()
    order = np.argsort(-flat)
    ri, ci = order // c, order % c
    dirs = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
    sqrt2 = res * 1.41421356
    for idx in range(len(order)):
        row, col = ri[idx], ci[idx]
        best_s, bdr, bdc = 0.0, 0, 0
        for dr, dc in dirs:
            nr, nc = row + dr, col + dc
            if 0 <= nr < r and 0 <= nc < c:
                dist = sqrt2 if (dr and dc) else float(res)
                s = (dem[row, col] - dem[nr, nc]) / dist
                if s > best_s:
                    best_s, bdr, bdc = s, dr, dc
        if bdr or bdc:
            accum[row + bdr, col + bdc] += accum[row, col]
    return accum

accum = d8_accumulate(dtm, GRID_RES)
specific_area = accum * (GRID_RES ** 2)  # m² of catchment per unit width

# TWI = ln(a / tan(β))
twi = np.log(specific_area / np.tan(slope_rad))
twi = gaussian_filter(twi, sigma=1.0)
print(f"  TWI range: {twi.min():.2f} – {twi.max():.2f}")

# ── Factor 2: 3D canopy interception capacity ─────────────────────────────────
print("[2/4] Building 3D voxel canopy interception...")

veg = np.isin(cls, [3, 4, 5])  # all vegetation classes

# Height above ground per veg point
ground_z_per_col = dtm[yi[veg], xi[veg]]  # DTM elevation at that column
z_above_ground   = z[veg] - ground_z_per_col

# Voxel grid: count veg points per (col, row, height_slice)
# Then sum voxel occupancy weighted by height (taller interception = more)
veg_xi = xi[veg]
veg_yi = yi[veg]
veg_zi = np.clip((z_above_ground / VOXEL_H).astype(np.int32), 0, n_z - 1)

# 3D occupancy cube
print(f"  Building voxel cube ({rows}x{cols}x{n_z})...")
voxel_cube = np.zeros((rows, cols, n_z), dtype=np.int32)
np.add.at(voxel_cube, (veg_yi, veg_xi, veg_zi), 1)

# Height-weighted interception: higher canopy layers get higher weight
# (rainfall momentum dissipated over longer fall distance)
height_weights = np.arange(1, n_z + 1, dtype=np.float32) * VOXEL_H  # metres
interception_3d = voxel_cube * height_weights[np.newaxis, np.newaxis, :]
interception_col = interception_3d.sum(axis=2).astype(np.float64)

# Normalize per-column count to get density (not just total)
total_pts_col = np.zeros((rows, cols))
np.add.at(total_pts_col, (yi, xi), 1)
canopy_pts_col = np.zeros((rows, cols))
np.add.at(canopy_pts_col, (veg_yi, veg_xi), 1)
cover_fraction = np.where(total_pts_col > 0, canopy_pts_col / total_pts_col, 0)

# Canopy depth: number of distinct height layers occupied per column
n_layers_col = (voxel_cube > 0).sum(axis=2).astype(np.float64)

# Combined interception score: density × depth × total weighted points
interception_score = cover_fraction * (n_layers_col / max(n_z, 1)) * \
                     np.log1p(interception_col)
interception_smooth = gaussian_filter(interception_score, sigma=1.5)

max_i = interception_smooth.max()
interception_norm = interception_smooth / max(max_i, 1e-6)
print(f"  Canopy layers present: 1–{int(n_layers_col.max())}")
print(f"  Cover fraction: mean={cover_fraction.mean():.2f}")

# ── Factor 3: Canopy NDVI health per column ───────────────────────────────────
print("[3/4] NDVI health map (veg points only)...")

veg_ndvi = ndvi[veg]
ndvi_col_sum   = np.zeros((rows, cols))
ndvi_col_count = np.zeros((rows, cols))
valid = ~np.isnan(veg_ndvi)
np.add.at(ndvi_col_sum,   (veg_yi[valid], veg_xi[valid]), veg_ndvi[valid])
np.add.at(ndvi_col_count, (veg_yi[valid], veg_xi[valid]), 1)
with np.errstate(invalid='ignore'):
    mean_ndvi = np.where(ndvi_col_count > 0, ndvi_col_sum / ndvi_col_count, 0.5)
mean_ndvi_smooth = gaussian_filter(mean_ndvi, sigma=1.5)
# Low NDVI → less interception → higher susceptibility  (so invert for risk)
ndvi_risk = 1.0 - np.clip(mean_ndvi_smooth, 0, 1)

# ── Factor 4: Terrain roughness ───────────────────────────────────────────────
print("[4/4] Terrain roughness (ground point Z variance per cell)...")

ground_z_sum  = np.zeros((rows, cols))
ground_z_sum2 = np.zeros((rows, cols))
ground_n      = np.zeros((rows, cols))
np.add.at(ground_z_sum,  (yg, xg), zg)
np.add.at(ground_z_sum2, (yg, xg), zg * zg)
np.add.at(ground_n,      (yg, xg), 1)
with np.errstate(invalid='ignore'):
    mean_z  = np.where(ground_n > 0, ground_z_sum  / ground_n, 0)
    mean_z2 = np.where(ground_n > 0, ground_z_sum2 / ground_n, 0)
variance = np.clip(mean_z2 - mean_z**2, 0, None)
roughness = np.sqrt(variance)
roughness_smooth = gaussian_filter(roughness, sigma=1.0)
# Rough ground → more infiltration → lower risk
roughness_norm = np.clip(roughness_smooth / np.percentile(roughness_smooth, 95), 0, 1)
roughness_risk = 1.0 - roughness_norm

# ── Combine: Flood Susceptibility Index ───────────────────────────────────────
print("\nCombining factors into susceptibility index...")

def norm01(arr, lo=2, hi=98):
    p_lo, p_hi = np.percentile(arr, lo), np.percentile(arr, hi)
    return np.clip((arr - p_lo) / max(p_hi - p_lo, 1e-6), 0, 1)

twi_norm   = norm01(twi)
interc_inv = 1.0 - interception_norm   # more interception = lower risk
curv_norm  = norm01(np.clip(plan_curv, -0.5, 0.5))  # concave = flood-prone

# Weights — TWI is the dominant terrain signal
W_TWI    = 0.40
W_INTERC = 0.25  # 3D canopy interception (the LiDAR differentiator)
W_NDVI   = 0.15  # canopy health
W_CURV   = 0.15  # plan curvature (convergent areas)
W_ROUGH  = 0.05  # surface roughness

susceptibility = (
    W_TWI    * twi_norm    +
    W_INTERC * interc_inv  +
    W_NDVI   * ndvi_risk   +
    W_CURV   * curv_norm   +
    W_ROUGH  * roughness_risk
)
susceptibility = gaussian_filter(susceptibility, sigma=1.0)
susc_norm = norm01(susceptibility, lo=1, hi=99)

# Classify into 5 zones
breaks = [0, 0.2, 0.4, 0.6, 0.8, 1.01]
labels = ["Very Low", "Low", "Moderate", "High", "Very High"]
colors_list = ["#2166ac", "#74add1", "#fee090", "#f46d43", "#a50026"]
zone_map = np.zeros_like(susc_norm, dtype=int)
for i, (lo, hi) in enumerate(zip(breaks[:-1], breaks[1:])):
    zone_map[(susc_norm >= lo) & (susc_norm < hi)] = i

print("Susceptibility zone distribution:")
for i, label in enumerate(labels):
    pct = (zone_map == i).sum() / zone_map.size * 100
    print(f"  {label:12s}: {pct:5.1f}%")

# ── Render ────────────────────────────────────────────────────────────────────
print("\nRendering...")
extent = [x0, x0 + cols*GRID_RES, y0, y0 + rows*GRID_RES]

from matplotlib.colors import LightSource
ls = LightSource(azdeg=315, altdeg=35)
hillshade = ls.hillshade(dtm, vert_exag=3, dx=GRID_RES, dy=GRID_RES)

# Custom diverging susceptibility colourmap
susc_cmap = LinearSegmentedColormap.from_list(
    "susc", ["#2166ac","#74add1","#ffffbf","#f46d43","#a50026"], N=256
)

# ── Figure 1: 5-panel component breakdown ────────────────────────────────────
fig, axes = plt.subplots(2, 3, figsize=(22, 14))
fig.suptitle(
    "Flood Susceptibility — GKOT 478_73 · Four-Factor 3D LiDAR Model\n"
    "CLSS Slovenia · 2m voxel grid · 23.6M points",
    fontsize=13, y=0.98
)

def show(ax, data, title, cmap, label, alpha=1.0, hs=True):
    if hs:
        ax.imshow(hillshade, origin='lower', extent=extent, cmap='gray',
                  aspect='equal', alpha=0.4)
    im = ax.imshow(data, origin='lower', extent=extent, cmap=cmap,
                   aspect='equal', alpha=alpha)
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Easting (m)", fontsize=8)
    ax.set_ylabel("Northing (m)", fontsize=8)
    plt.colorbar(im, ax=ax, shrink=0.65, label=label)
    return im

show(axes[0,0], twi_norm,         "Factor 1: TWI (terrain convergence)\nHigh = flat+convergent = flood-prone",
     "RdYlBu_r", "TWI (norm)")
show(axes[0,1], interception_norm, "Factor 2: 3D canopy interception\nHigh = dense multilayer canopy = less runoff",
     "YlGn",      "Interception (norm)")
show(axes[0,2], mean_ndvi_smooth,  "Factor 3: Canopy NDVI health\nLow = stressed = less interception",
     "RdYlGn",    "NDVI")
show(axes[1,0], roughness_smooth,  "Factor 4: Terrain roughness\nHigh = more infiltration",
     "Purples",   "Roughness (m)")
show(axes[1,1], susc_norm,         "Combined flood susceptibility\n(TWI 40% · Canopy 25% · NDVI 15% · Curv 15% · Rough 5%)",
     susc_cmap,   "Susceptibility")

# Classified map
cmap_zones = mcolors.ListedColormap(colors_list)
bounds_zones = [0, 1, 2, 3, 4, 5]
norm_zones = mcolors.BoundaryNorm(bounds_zones, cmap_zones.N)
axes[1,2].imshow(hillshade, origin='lower', extent=extent, cmap='gray',
                 aspect='equal', alpha=0.4)
im_z = axes[1,2].imshow(zone_map, origin='lower', extent=extent,
                         cmap=cmap_zones, norm=norm_zones, aspect='equal', alpha=0.8)
axes[1,2].set_title("Classified zones (5 classes)\nReady for GIS delivery", fontsize=10)
axes[1,2].set_xlabel("Easting (m)", fontsize=8)
axes[1,2].set_ylabel("Northing (m)", fontsize=8)
from matplotlib.patches import Patch
patches = [Patch(color=c, label=l) for c, l in zip(colors_list, labels)]
axes[1,2].legend(handles=patches, loc='lower right', fontsize=8, title="Risk class")

fig.tight_layout(rect=[0, 0, 1, 0.96])
fig.savefig(OUT / "flood_susceptibility_components.png", dpi=160, bbox_inches="tight")
plt.close(fig)
print(f"  Saved flood_susceptibility_components.png")

# ── Figure 2: Hero map ────────────────────────────────────────────────────────
fig, ax = plt.subplots(1, 1, figsize=(13, 13))
ax.imshow(hillshade, origin='lower', extent=extent, cmap='gray',
          aspect='equal', alpha=0.45)
im = ax.imshow(susc_norm, origin='lower', extent=extent,
               cmap=susc_cmap, vmin=0, vmax=1, aspect='equal', alpha=0.8)
cb = plt.colorbar(im, ax=ax, shrink=0.65, label="Flood susceptibility (0 = low, 1 = high)")

# Mark top-20 highest-risk cells
flat_idx = np.argsort(susc_norm.ravel())[-20:][::-1]
top_r, top_c = np.unravel_index(flat_idx, susc_norm.shape)
top_x = x0 + top_c * GRID_RES
top_y = y0 + top_r * GRID_RES
ax.scatter(top_x, top_y, s=80, c='white', edgecolors='black', zorder=5,
           linewidths=1.2, label='Top-20 risk cells')
for i, (tx, ty) in enumerate(zip(top_x[:5], top_y[:5])):
    ax.annotate(f" {i+1}", (tx, ty), color='white', fontsize=8,
                fontweight='bold', ha='left')

ax.set_title(
    "Flood Susceptibility — GKOT 478_73\n"
    "3D LiDAR model: terrain convergence · canopy interception · vegetation health\n"
    "CLSS Slovenia · 23.6M LiDAR points · 2m voxel grid",
    fontsize=12
)
ax.set_xlabel("Easting (m)")
ax.set_ylabel("Northing (m)")
ax.legend(loc='lower right', fontsize=9)

fig.savefig(OUT / "flood_susceptibility_hero.png", dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"  Saved flood_susceptibility_hero.png")

# ── Figure 3: 3D voxel height profile (the "different heights in colour" view) ─
print("  Building 3D voxel slice diagram...")
fig, axes = plt.subplots(1, 4, figsize=(20, 6))
fig.suptitle(
    "3D Voxel Canopy Profile — point density by height layer\n"
    "What the 2D susceptibility map is drawing on (each slice = 2m vertical band)",
    fontsize=11
)

# Show 4 representative height slices above ground
slice_heights = [2, 8, 18, 32]   # metres above ground (rough: low, mid, canopy base, canopy top)
for ax, h_m in zip(axes, slice_heights):
    h_idx = int(h_m / VOXEL_H)
    if h_idx < n_z:
        slice_data = voxel_cube[:, :, h_idx].astype(float)
        slice_data[slice_data == 0] = np.nan
        ax.imshow(hillshade, origin='lower', extent=extent, cmap='gray',
                  aspect='equal', alpha=0.5)
        im = ax.imshow(slice_data, origin='lower', extent=extent,
                       cmap='plasma', aspect='equal', alpha=0.85)
        ax.set_title(f"Height layer: {h_m}–{h_m+2}m above ground\n"
                     f"({int(np.nansum(slice_data)):,} points in slice)")
        ax.set_xlabel("Easting (m)")
        plt.colorbar(im, ax=ax, shrink=0.6, label="Pts/voxel")

fig.tight_layout()
fig.savefig(OUT / "voxel_height_slices.png", dpi=160, bbox_inches="tight")
plt.close(fig)
print(f"  Saved voxel_height_slices.png")

print("\nAll done. Outputs in output/")
