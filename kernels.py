"""
Numba-accelerated hot loops for pipeline.py.

Two pure-Python loops dominated per-tile runtime:
  1. the DTM grouped-min over every ground point (pipeline.compute_factors)
  2. d8_accumulate over every grid cell

These njit replacements are written to be BIT-IDENTICAL to the originals
(verified by bench_kernels.py), not merely close:
  - same grouped-min semantics (lowest z per cell, NaN where no ground point),
  - same D8 tie-break (strict `>`, fixed neighbour order),
  - the argsort is done in numpy OUTSIDE njit, so iteration order matches the
    original exactly even across elevation ties.

`cache=True` persists the compiled artifact to disk, so it compiles once and is
reused across runs and across spawned multiprocessing workers.
"""
import numpy as np
from numba import njit

_SQRT2 = 1.41421356  # matches the literal used in the original d8_accumulate


@njit(cache=True)
def _dtm_min_core(dtm, yg, xg, zg):
    for k in range(zg.size):
        v = zg[k]
        r = yg[k]
        c = xg[k]
        if v < dtm[r, c]:
            dtm[r, c] = v
    return dtm


def dtm_min_grid(rows, cols, yg, xg, zg):
    """
    Lowest ground-return z per grid cell; NaN where no ground point.
    Equivalent to the original inline loop:
        dtm[gy, gx] = gz if isnan(cur) else min(cur, gz)
    """
    dtm = np.full((rows, cols), np.inf)
    _dtm_min_core(dtm,
                  yg.astype(np.int64),
                  xg.astype(np.int64),
                  zg.astype(np.float64))
    dtm[np.isinf(dtm)] = np.nan
    return dtm


@njit(cache=True)
def _d8_core(dem, res, order):
    r, c = dem.shape
    accum = np.ones((r, c), dtype=np.float64)
    sq2 = res * _SQRT2
    # neighbour order identical to the original `dirs` list
    drs = np.array([-1, -1, -1, 0, 0, 1, 1, 1], dtype=np.int64)
    dcs = np.array([-1, 0, 1, -1, 1, -1, 0, 1], dtype=np.int64)
    for i in range(order.size):
        idx = order[i]
        row = idx // c
        col = idx % c
        bs = 0.0
        bdr = 0
        bdc = 0
        for j in range(8):
            dr = drs[j]
            dc = dcs[j]
            nr = row + dr
            nc = col + dc
            if 0 <= nr < r and 0 <= nc < c:
                d = sq2 if (dr != 0 and dc != 0) else res
                s = (dem[row, col] - dem[nr, nc]) / d
                if s > bs:
                    bs = s
                    bdr = dr
                    bdc = dc
        if bdr != 0 or bdc != 0:
            accum[row + bdr, col + bdc] += accum[row, col]
    return accum


def d8_accumulate(dem, res):
    """
    Single-flow-direction (D8) upslope area accumulation.
    Drop-in for the original pipeline.d8_accumulate. The argsort runs in numpy
    (same as the original) so the iteration order is identical.
    """
    dem = np.ascontiguousarray(dem, dtype=np.float64)
    order = np.argsort(-dem.ravel())
    return _d8_core(dem, np.float64(res), order)
