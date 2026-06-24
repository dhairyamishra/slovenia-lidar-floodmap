"""
GKOT 478_73 — Load, sanity-check, compute per-point NDVI, render first views.
Target: dense forest tile, 23.6M pts, 429m relief.
"""
import laspy
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from pathlib import Path
import time

DATA = Path("data")
OUT = Path("output")
OUT.mkdir(exist_ok=True)

FILE = DATA / "GKOT_478_73.laz"

# ── 1. Load ──────────────────────────────────────────────────────────────────

print(f"Loading {FILE.name}...")
t0 = time.time()
las = laspy.read(str(FILE))
print(f"  Loaded {len(las.points):,} points in {time.time()-t0:.1f}s")

x = np.asarray(las.x)
y = np.asarray(las.y)
z = np.asarray(las.z)
red = np.asarray(las.red)
green = np.asarray(las.green)
blue = np.asarray(las.blue)
nir = np.asarray(las.nir)
cls = np.asarray(las.classification)
ret = np.asarray(las.return_number)
n_ret = np.asarray(las.number_of_returns)

# ── 2. Sanity checks ────────────────────────────────────────────────────────

print("\n-- Classification histogram --")
CLASS_NAMES = {
    0: "Never classified", 1: "Unclassified", 2: "Ground",
    3: "Low veg", 4: "Med veg", 5: "High veg", 6: "Building",
    7: "Low noise", 8: "Reserved", 18: "High noise",
}
unique, counts = np.unique(cls, return_counts=True)
total = len(cls)
for c, n in sorted(zip(unique, counts)):
    label = CLASS_NAMES.get(int(c), f"Class {c}")
    print(f"  {c:>3d} {label:<20s} {n:>12,}  ({100*n/total:5.1f}%)")

print("\n-- Colour & NIR ranges --")
for name, arr in [("Red", red), ("Green", green), ("Blue", blue), ("NIR", nir)]:
    print(f"  {name:<6s}  min={arr.min():>6d}  max={arr.max():>6d}  "
          f"mean={arr.mean():>8.1f}  dtype={arr.dtype}")

bit16 = red.max() > 255 or green.max() > 255 or blue.max() > 255 or nir.max() > 255
print(f"  -> {'16-bit' if bit16 else '8-bit'} colour values detected")

# ── 3. Compute NDVI ─────────────────────────────────────────────────────────

print("\nComputing per-point NDVI...")
nir_f = nir.astype(np.float32)
red_f = red.astype(np.float32)
denom = nir_f + red_f
ndvi = np.where(denom > 0, (nir_f - red_f) / denom, 0.0)

print(f"  NDVI  min={ndvi.min():.4f}  max={ndvi.max():.4f}  "
      f"mean={ndvi.mean():.4f}  median={np.median(ndvi):.4f}")

# Per-class NDVI
print("\n-- NDVI by class --")
for c in sorted(np.unique(cls)):
    mask = cls == c
    if mask.sum() < 100:
        continue
    label = CLASS_NAMES.get(int(c), f"Class {c}")
    vals = ndvi[mask]
    print(f"  {c:>3d} {label:<20s}  mean={vals.mean():.4f}  std={vals.std():.4f}")

# ── 4. Render ────────────────────────────────────────────────────────────────

print("\nRendering...")

# Decimate for rendering — every Nth point
N = len(x)
STRIDE = max(1, N // 2_000_000)  # target ~2M points for plotting
idx = np.arange(0, N, STRIDE)
print(f"  Decimated: {len(idx):,} points (stride={STRIDE})")

xd, yd, zd = x[idx], y[idx], z[idx]
ndvi_d = ndvi[idx]
cls_d = cls[idx]

# --- 4a. Top-down NDVI view ---
fig, ax = plt.subplots(1, 1, figsize=(12, 12))
sc = ax.scatter(xd, yd, c=ndvi_d, cmap="RdYlGn", s=0.05, vmin=-0.2, vmax=0.8,
                rasterized=True)
ax.set_aspect("equal")
ax.set_xlabel("Easting (m)")
ax.set_ylabel("Northing (m)")
ax.set_title("GKOT 478_73 — Per-point NDVI (top-down)\n"
             "CLSS Slovenia · 23.6M LiDAR pts with native NIR")
cb = plt.colorbar(sc, ax=ax, shrink=0.7, label="NDVI")
fig.savefig(OUT / "ndvi_topdown.png", dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"  Saved {OUT/'ndvi_topdown.png'}")

# --- 4b. Top-down classified view ---
CLASS_COLORS = {
    1: (0.5, 0.5, 0.5),   # unclassified
    2: (0.76, 0.60, 0.42), # ground — tan
    3: (0.6, 0.9, 0.4),    # low veg — light green
    4: (0.2, 0.7, 0.2),    # med veg — green
    5: (0.0, 0.4, 0.0),    # high veg — dark green
    6: (0.9, 0.2, 0.2),    # building — red
    7: (0.3, 0.3, 0.3),    # low noise — dark grey
    18: (0.3, 0.3, 0.3),   # high noise — dark grey
}
colors = np.array([CLASS_COLORS.get(int(c), (0.5, 0.5, 0.5)) for c in cls_d])

fig, ax = plt.subplots(1, 1, figsize=(12, 12))
ax.scatter(xd, yd, c=colors, s=0.05, rasterized=True)
ax.set_aspect("equal")
ax.set_xlabel("Easting (m)")
ax.set_ylabel("Northing (m)")
ax.set_title("GKOT 478_73 — Classification (top-down)\n"
             "Ground (tan) · Low/Med/High Veg (green shades) · Building (red)")
fig.savefig(OUT / "classification_topdown.png", dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"  Saved {OUT/'classification_topdown.png'}")

# --- 4c. Side profile (X-Z) coloured by NDVI ---
fig, ax = plt.subplots(1, 1, figsize=(16, 6))
sc = ax.scatter(xd, zd, c=ndvi_d, cmap="RdYlGn", s=0.02, vmin=-0.2, vmax=0.8,
                rasterized=True)
ax.set_xlabel("Easting (m)")
ax.set_ylabel("Elevation (m)")
ax.set_title("GKOT 478_73 — Side profile (East → West) coloured by NDVI\n"
             "429m relief · Dense forest canopy visible in cross-section")
ax.set_aspect(2)
cb = plt.colorbar(sc, ax=ax, shrink=0.7, label="NDVI")
fig.savefig(OUT / "ndvi_side_profile.png", dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"  Saved {OUT/'ndvi_side_profile.png'}")

# --- 4d. NDVI histogram ---
fig, ax = plt.subplots(1, 1, figsize=(10, 5))
veg_mask = np.isin(cls, [3, 4, 5])
ax.hist(ndvi[~veg_mask], bins=200, alpha=0.5, label="Non-vegetation", density=True, color="tan")
ax.hist(ndvi[veg_mask], bins=200, alpha=0.5, label="Vegetation (cls 3-5)", density=True, color="green")
ax.set_xlabel("NDVI")
ax.set_ylabel("Density")
ax.set_title("NDVI Distribution — Vegetation vs Non-vegetation")
ax.legend()
ax.set_xlim(-0.5, 1.0)
fig.savefig(OUT / "ndvi_histogram.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"  Saved {OUT/'ndvi_histogram.png'}")

# --- 4e. RGB natural colour (top-down) ---
if bit16:
    rgb_d = np.column_stack([red[idx], green[idx], blue[idx]]).astype(np.float32) / 65535.0
else:
    rgb_d = np.column_stack([red[idx], green[idx], blue[idx]]).astype(np.float32) / 255.0
rgb_d = np.clip(rgb_d, 0, 1)

fig, ax = plt.subplots(1, 1, figsize=(12, 12))
ax.scatter(xd, yd, c=rgb_d, s=0.05, rasterized=True)
ax.set_aspect("equal")
ax.set_xlabel("Easting (m)")
ax.set_ylabel("Northing (m)")
ax.set_title("GKOT 478_73 — Natural colour RGB (top-down)\n"
             "Colour from LiDAR-native RGB channels")
fig.savefig(OUT / "rgb_topdown.png", dpi=200, bbox_inches="tight")
plt.close(fig)
print(f"  Saved {OUT/'rgb_topdown.png'}")

print("\nDone. All outputs in output/")
