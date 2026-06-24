"""
Flood risk demo: logjam / canopy-overhang risk along drainage lines.
Pipeline:
  1. Build pseudo-DTM from GKOT ground returns (class 2) via scipy interpolation
  2. Compute slope + flow accumulation -> drainage network
  3. Buffer drainage lines -> query 3D canopy (class 5) for overhang density + NDVI
  4. Output: watercourse risk map + ranked segment list
"""
import laspy
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from pathlib import Path
from scipy.interpolate import griddata
from scipy.ndimage import (
    gaussian_filter, generic_filter, label, binary_dilation
)
import warnings
warnings.filterwarnings("ignore")

DATA = Path("data")
OUT  = Path("output")
OUT.mkdir(exist_ok=True)

print("Loading GKOT_478_73.laz...")
las = laspy.read(str(DATA / "GKOT_478_73.laz"))

x   = np.asarray(las.x)
y   = np.asarray(las.y)
z   = np.asarray(las.z)
cls = np.asarray(las.classification)
red = np.asarray(las.red).astype(np.float32)
nir = np.asarray(las.nir).astype(np.float32)
denom = nir + red
ndvi = np.where(denom > 0, (nir - red) / denom, 0.0)
print(f"  {len(x):,} points loaded")

# ── 1. Build pseudo-DTM from ground returns ───────────────────────────────────

GRID_RES = 2.0  # metres — coarser than DMR but fast enough for demo

x0, y0 = x.min(), y.min()
x1, y1 = x.max(), y.max()
cols = int((x1 - x0) / GRID_RES) + 1
rows = int((y1 - y0) / GRID_RES) + 1
print(f"\nBuilding pseudo-DTM at {GRID_RES}m grid ({cols}x{rows} cells)...")

ground = cls == 2
xg, yg, zg = x[ground], y[ground], z[ground]
print(f"  Ground points: {ground.sum():,}")

# Bin ground points: take min-Z per cell (bare earth)
xi = ((xg - x0) / GRID_RES).astype(int).clip(0, cols - 1)
yi = ((yg - y0) / GRID_RES).astype(int).clip(0, rows - 1)

dtm = np.full((rows, cols), np.nan)
for gx, gy, gz in zip(xi, yi, zg):
    cur = dtm[gy, gx]
    if np.isnan(cur) or gz < cur:
        dtm[gy, gx] = gz

# Fill small holes with nearest neighbour
from scipy.ndimage import distance_transform_edt
nan_mask = np.isnan(dtm)
if nan_mask.any():
    idx = distance_transform_edt(nan_mask, return_distances=False, return_indices=True)
    dtm = dtm[tuple(idx)]

dtm = gaussian_filter(dtm, sigma=1.0)
print(f"  DTM Z range: {dtm.min():.1f} – {dtm.max():.1f} m  (range={dtm.max()-dtm.min():.1f}m)")

# ── 2. Slope and flow accumulation ───────────────────────────────────────────

print("\nComputing slope and drainage...")

dy, dx_grad = np.gradient(dtm, GRID_RES, GRID_RES)
slope_deg = np.degrees(np.arctan(np.sqrt(dx_grad**2 + dy**2)))

# D8 flow direction -> accumulation (simplified)
# For each cell, find which of the 8 neighbours is steepest downslope
def flow_accumulate(dem, res):
    r, c = dem.shape
    accum = np.ones((r, c))
    # Sort cells high->low, route water downhill
    flat = dem.ravel()
    order = np.argsort(-flat)  # descending elevation
    ri = order // c
    ci = order % c

    dirs = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
    diag_dist = res * np.sqrt(2)
    adj_dist  = float(res)

    for idx in range(len(order)):
        row, col = ri[idx], ci[idx]
        best_slope = 0.0
        best_dr, best_dc = 0, 0
        for dr, dc in dirs:
            nr, nc = row + dr, col + dc
            if 0 <= nr < r and 0 <= nc < c:
                dist = diag_dist if (dr != 0 and dc != 0) else adj_dist
                s = (dem[row, col] - dem[nr, nc]) / dist
                if s > best_slope:
                    best_slope = s
                    best_dr, best_dc = dr, dc
        if best_dr != 0 or best_dc != 0:
            accum[row + best_dr, col + best_dc] += accum[row, col]
    return accum

accum = flow_accumulate(dtm, GRID_RES)
print(f"  Flow accumulation: max={accum.max():.0f} (= ~{accum.max()*GRID_RES**2:.0f} m2 catchment)")

# Extract drainage channels: cells accumulating flow from >1 ha
CHANNEL_THRESH = 10000 / (GRID_RES**2)  # cells draining >1 ha
channel_mask = accum >= CHANNEL_THRESH
n_channel_cells = channel_mask.sum()
print(f"  Channel cells (>1ha catchment): {n_channel_cells:,}")

# ── 3. Canopy overhang within buffer of drainage lines ────────────────────────

print("\nComputing canopy overhang risk along drainage lines...")

BUFFER_M = 15  # lateral metres either side of channel to look for overhanging trees
buffer_px = int(np.ceil(BUFFER_M / GRID_RES))
channel_buffer = binary_dilation(channel_mask, iterations=buffer_px)

high_veg = cls == 5
xv, yv, zv = x[high_veg], y[high_veg], z[high_veg]
ndvi_v = ndvi[high_veg]

xv_i = ((xv - x0) / GRID_RES).astype(int).clip(0, cols - 1)
yv_i = ((yv - y0) / GRID_RES).astype(int).clip(0, rows - 1)

# Per-cell canopy density and mean NDVI in buffer zone
canopy_count = np.zeros((rows, cols))
canopy_ndvi  = np.zeros((rows, cols))
ndvi_accum   = np.zeros((rows, cols))

for gx, gy, gn in zip(xv_i, yv_i, ndvi_v):
    canopy_count[gy, gx] += 1
    ndvi_accum[gy, gx] += gn

with np.errstate(invalid='ignore'):
    canopy_ndvi = np.where(canopy_count > 0, ndvi_accum / canopy_count, np.nan)

# Risk score: inside buffer, high canopy density + LOW ndvi = highest risk
#   (dense overhang + stressed/dry canopy = most likely to fall into channel)
pts_per_ha = canopy_count / (GRID_RES**2 / 10000)
max_density = pts_per_ha[channel_buffer].max() if channel_buffer.any() else 1.0
density_norm = np.clip(pts_per_ha / max(max_density, 1.0), 0, 1)
ndvi_risk = np.where(np.isnan(canopy_ndvi), 0.0, np.clip(1.0 - canopy_ndvi, 0, 1))
risk_score = np.where(channel_buffer, density_norm * ndvi_risk, 0.0)

print(f"  Risk score in buffer: mean={risk_score[channel_buffer].mean():.3f}  max={risk_score.max():.3f}")

# ── 4. Visualise ─────────────────────────────────────────────────────────────

print("\nRendering outputs...")

# Grid extent in real coords
extent = [x0, x0 + cols*GRID_RES, y0, y0 + rows*GRID_RES]

# --- 4a. DTM + channel network + risk heat map ---
fig, axes = plt.subplots(1, 3, figsize=(20, 7))
fig.suptitle("GKOT 478_73 — Flood/Logjam Risk Pipeline (from LiDAR ground returns)\n"
             "Steep forest tile · 429m relief · 6.4M ground points → pseudo-DTM at 2m",
             fontsize=12)

ax = axes[0]
im = ax.imshow(dtm, origin='lower', extent=extent, cmap='terrain', aspect='equal')
ax.set_title("Pseudo-DTM (from LiDAR ground class)")
ax.set_xlabel("Easting (m)")
ax.set_ylabel("Northing (m)")
plt.colorbar(im, ax=ax, label="Elevation (m)", shrink=0.7)

ax = axes[1]
ax.imshow(dtm, origin='lower', extent=extent, cmap='terrain', alpha=0.6, aspect='equal')
ch_display = np.where(channel_mask, 1.0, np.nan)
ax.imshow(ch_display, origin='lower', extent=extent, cmap='Blues', vmin=0, vmax=1,
          alpha=0.9, aspect='equal')
ax.set_title("Drainage network (D8, >1ha catchment)")
ax.set_xlabel("Easting (m)")
ax.set_ylabel("Northing (m)")

ax = axes[2]
ax.imshow(dtm, origin='lower', extent=extent, cmap='grey', alpha=0.5, aspect='equal')
risk_display = np.where(risk_score > 0.01, risk_score, np.nan)
im2 = ax.imshow(risk_display, origin='lower', extent=extent, cmap='YlOrRd',
                vmin=0, vmax=risk_score.max(), alpha=0.85, aspect='equal')
ax.set_title(f"Logjam/overhang risk\n(canopy density × stress, {BUFFER_M}m buffer)")
ax.set_xlabel("Easting (m)")
plt.colorbar(im2, ax=ax, label="Risk score (0-1)", shrink=0.7)

fig.tight_layout()
fig.savefig(OUT / "flood_risk_pipeline.png", dpi=180, bbox_inches="tight")
plt.close(fig)
print(f"  Saved {OUT/'flood_risk_pipeline.png'}")

# --- 4b. Combined hero: slope + channels + canopy health ---
fig, ax = plt.subplots(1, 1, figsize=(12, 12))

# Hillshade from slope for context
from matplotlib.colors import LightSource
ls = LightSource(azdeg=315, altdeg=35)
hillshade = ls.hillshade(dtm, vert_exag=2, dx=GRID_RES, dy=GRID_RES)
ax.imshow(hillshade, origin='lower', extent=extent, cmap='gray', aspect='equal', alpha=0.7)

# Drainage channels in blue
ax.imshow(np.where(channel_mask, 1.0, np.nan), origin='lower', extent=extent,
          cmap='Blues', vmin=0, vmax=1, alpha=0.8, aspect='equal')

# Risk heat in red-orange
im3 = ax.imshow(risk_display, origin='lower', extent=extent, cmap='YlOrRd',
                vmin=0, vmax=risk_score.max(), alpha=0.75, aspect='equal')

ax.set_title(
    "Logjam / woody-debris flood risk — GKOT 478_73\n"
    "Blue: drainage channels  |  Red/orange: canopy-overhang risk (density × stress)\n"
    "CLSS Slovenia LiDAR · 2m pseudo-DTM from 6.4M ground returns",
    fontsize=11
)
ax.set_xlabel("Easting (m)")
ax.set_ylabel("Northing (m)")
plt.colorbar(im3, ax=ax, label="Overhang risk", shrink=0.6)

from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0], [0], color='steelblue', lw=2, label='Drainage channel (>1ha)'),
    Line2D([0], [0], color='darkorange', lw=4, label='High overhang risk'),
    Line2D([0], [0], color='red', lw=4, label='Critical overhang risk'),
]
ax.legend(handles=legend_elements, loc='lower right', fontsize=9)

fig.savefig(OUT / "flood_risk_hero.png", dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"  Saved {OUT/'flood_risk_hero.png'}")

# --- 4c. Ranked segment table ---
# Sample along channels: find top-10 highest-risk 50m segments
seg_size_px = int(50 / GRID_RES)
channel_cells = np.argwhere(channel_mask)
n_seg = len(channel_cells) // seg_size_px
seg_risks = []
for i in range(n_seg):
    seg = channel_cells[i*seg_size_px:(i+1)*seg_size_px]
    mean_risk = risk_score[seg[:, 0], seg[:, 1]].mean()
    cx = x0 + seg[:, 1].mean() * GRID_RES
    cy = y0 + seg[:, 0].mean() * GRID_RES
    z_mean = dtm[seg[:, 0], seg[:, 1]].mean()
    seg_risks.append((mean_risk, cx, cy, z_mean))

seg_risks.sort(reverse=True)
print("\nTop-10 highest-risk watercourse segments (50m):")
print(f"  {'Rank':<5} {'Risk':>6} {'Easting':>10} {'Northing':>10} {'Elev(m)':>8}")
for rank, (risk, cx, cy, ze) in enumerate(seg_risks[:10], 1):
    print(f"  {rank:<5} {risk:>6.3f} {cx:>10.0f} {cy:>10.0f} {ze:>8.1f}")

print("\nDone. Outputs in output/")
