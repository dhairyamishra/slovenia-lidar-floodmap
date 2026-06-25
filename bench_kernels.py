"""
Benchmark + correctness gate for the Numba kernels (kernels.py) against the
original pure-Python loops, on one real tile.

Usage:  python bench_kernels.py [TILE_ID]   (default 488_134)

Proves: (a) the two loops are the bottleneck, (b) the Numba versions are
bit-identical, (c) the speedup. Safe to delete after validation.
"""
import sys, time
import numpy as np
import laspy
from scipy.ndimage import gaussian_filter, distance_transform_edt
import kernels

GRID_RES = 2.0
tile = sys.argv[1] if len(sys.argv) > 1 else "488_134"
path = f"data/GKOT_{tile}.laz"

t = time.time(); las = laspy.read(path); t_read = time.time() - t
x = np.asarray(las.x); y = np.asarray(las.y)
z = np.asarray(las.z); cls = np.asarray(las.classification)
print(f"tile {tile}: laspy.read {t_read:5.1f}s  ({len(x):,} pts)")

x0, y0 = x.min(), y.min(); x1, y1 = x.max(), y.max()
cols = int((x1 - x0) / GRID_RES) + 1
rows = int((y1 - y0) / GRID_RES) + 1
xi = ((x - x0) / GRID_RES).astype(np.int32).clip(0, cols - 1)
yi = ((y - y0) / GRID_RES).astype(np.int32).clip(0, rows - 1)
ground = cls == 2
xg, yg, zg = xi[ground], yi[ground], z[ground]
print(f"grid {rows}x{cols}  ground pts {zg.size:,}\n")

# ---- DTM grouped-min loop ----------------------------------------------------
t = time.time()
dtm_o = np.full((rows, cols), np.nan)
for gx, gy, gz in zip(xg, yg, zg):
    cur = dtm_o[gy, gx]
    dtm_o[gy, gx] = gz if np.isnan(cur) else min(cur, gz)
t_dtm_o = time.time() - t

kernels.dtm_min_grid(2, 2, np.array([0]), np.array([0]), np.array([1.0]))  # warm/compile
t = time.time()
dtm_n = kernels.dtm_min_grid(rows, cols, yg, xg, zg)
t_dtm_n = time.time() - t
ok_dtm = np.array_equal(dtm_o, dtm_n, equal_nan=True)
print(f"DTM loop   ORIG {t_dtm_o:7.1f}s   NUMBA {t_dtm_n:6.2f}s   "
      f"{t_dtm_o / max(t_dtm_n, 1e-9):5.0f}x   identical={ok_dtm}")

# smoothed DTM (same as pipeline) to feed d8
idx = distance_transform_edt(np.isnan(dtm_o), return_distances=False, return_indices=True)
dtm = gaussian_filter(dtm_o[tuple(idx)], sigma=1.5)

# ---- D8 accumulation ---------------------------------------------------------
def d8_orig(dem, res):
    r, c = dem.shape
    accum = np.ones((r, c), dtype=np.float64)
    order = np.argsort(-dem.ravel())
    ri, ci = order // c, order % c
    dirs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    sq2 = res * 1.41421356
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

t = time.time(); a_o = d8_orig(dtm, GRID_RES); t_d8_o = time.time() - t
kernels.d8_accumulate(np.ones((3, 3)), 2.0)  # warm/compile
t = time.time(); a_n = kernels.d8_accumulate(dtm, GRID_RES); t_d8_n = time.time() - t
ok_d8 = np.array_equal(a_o, a_n)
print(f"D8 accum   ORIG {t_d8_o:7.1f}s   NUMBA {t_d8_n:6.2f}s   "
      f"{t_d8_o / max(t_d8_n, 1e-9):5.0f}x   identical={ok_d8}  "
      f"(max|diff| {np.abs(a_o - a_n).max():.2e})")

print(f"\ntwo loops: ORIG {t_dtm_o + t_d8_o:6.1f}s  ->  NUMBA {t_dtm_n + t_d8_n:5.2f}s")
print(f"correctness gate: {'PASS' if (ok_dtm and ok_d8) else 'FAIL'}")
