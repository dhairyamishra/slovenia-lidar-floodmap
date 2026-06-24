"""
Probe the data's hidden affordances to ground the brainstorm:
  1. Return-number structure -> is vertical/canopy work viable?
  2. Intensity & NIR distributions -> material discrimination potential
  3. "Stressed canopy" detection -> high-veg points with low NDVI (dead/sick trees)
  4. Does POFI_478_73 (2D infrared ortho) overlap GKOT_478_73 (3D cloud)?
     -> enables 2D-vs-3D NDVI cross-validation on identical ground.
"""
import laspy, numpy as np, rasterio
from pathlib import Path

DATA = Path("data")
las = laspy.read(str(DATA / "GKOT_478_73.laz"))

cls   = np.asarray(las.classification)
ret   = np.asarray(las.return_number)
nret  = np.asarray(las.number_of_returns)
inten = np.asarray(las.intensity)
red   = np.asarray(las.red).astype(np.float32)
nir   = np.asarray(las.nir).astype(np.float32)
z     = np.asarray(las.z)
denom = nir + red
ndvi  = np.where(denom > 0, (nir - red) / denom, 0.0)

N = len(cls)
print(f"Total points: {N:,}\n")

# 1. RETURN STRUCTURE — canopy penetration
print("-- Return structure (canopy penetration) --")
u, c = np.unique(nret, return_counts=True)
for val, cnt in zip(u, c):
    print(f"  number_of_returns={val}: {cnt:>12,} ({100*cnt/N:5.1f}%)")
multi = (nret > 1).sum()
print(f"  Multi-return points: {multi:,} ({100*multi/N:.1f}%) "
      f"-> canopy is penetrable, vertical structure recoverable")
# Of multi-return, how many are intermediate (not first, not last)? = understory
intermediate = ((ret > 1) & (ret < nret)).sum()
print(f"  Intermediate returns (mid-canopy/understory): {intermediate:,} "
      f"({100*intermediate/N:.1f}%)\n")

# 2. INTENSITY
print("-- Intensity --")
print(f"  min={inten.min()} max={inten.max()} mean={inten.mean():.0f} "
      f"median={np.median(inten):.0f}\n")

# 3. STRESSED CANOPY — tall vegetation (class 5) with anomalously low NDVI
print("-- Stressed/dead canopy candidates --")
high = cls == 5
hv_ndvi = ndvi[high]
print(f"  High-veg points: {high.sum():,}")
for thr in (0.1, 0.2, 0.3):
    n_stressed = (hv_ndvi < thr).sum()
    print(f"  High-veg with NDVI < {thr}: {n_stressed:,} "
          f"({100*n_stressed/high.sum():.1f}% of canopy)")
# Tall canopy only (truly elevated) to avoid ground-shadow confusion
zmin = z.min()
tall = high & ((z - zmin) > 15)  # >15m above tile floor is crude; just a probe
print(f"  (probe) very elevated high-veg points: {tall.sum():,}\n")

# 4. POFI overlap — does the 2D infrared ortho cover the same ground?
print("-- POFI_478_73 (2D IR ortho) vs GKOT_478_73 (3D cloud) overlap --")
gx0, gx1 = float(np.asarray(las.x).min()), float(np.asarray(las.x).max())
gy0, gy1 = float(np.asarray(las.y).min()), float(np.asarray(las.y).max())
print(f"  GKOT bbox:  X[{gx0:.0f},{gx1:.0f}] Y[{gy0:.0f},{gy1:.0f}]")
pofi = DATA / "POFI_478_73.tif"
if pofi.exists():
    with rasterio.open(str(pofi)) as src:
        b = src.bounds
        print(f"  POFI bbox:  X[{b.left:.0f},{b.right:.0f}] Y[{b.bottom:.0f},{b.top:.0f}]")
        ox = max(0, min(gx1, b.right) - max(gx0, b.left))
        oy = max(0, min(gy1, b.top) - max(gy0, b.bottom))
        print(f"  Overlap: {ox:.0f} x {oy:.0f} m  "
              f"-> {'SAME TILE — 2D/3D NDVI cross-validation is possible' if ox>900 and oy>900 else 'partial'}")
        print(f"  POFI bands: {src.count}, res {src.res[0]:.2f}m "
              f"(band1=NIR, band2=R, band3=G)")
else:
    print("  POFI_478_73.tif not found")
