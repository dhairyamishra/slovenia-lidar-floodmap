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


# ── HAND (Height Above Nearest Drainage) ──────────────────────────────────────
# HAND = a cell's elevation minus the elevation of the stream cell it drains to,
# following the D8 steepest-descent flow path. The #1 research-backed flood
# factor (proximity/height above the channel network). This is the PER-TILE cut:
# flow is routed within the tile, so paths leaving a tile edge terminate there
# (a known approximation — a true HAND needs whole-mosaic routing).

@njit(cache=True)
def _d8_receivers(dem, res):
    """For each cell, the flat index of its steepest-descent neighbour, or -1
    if none is lower (pit / outlet). Identical neighbour order + strict-`>`
    tie-break to _d8_core, so receivers are consistent with the accumulation."""
    r, c = dem.shape
    recv = np.full(r * c, -1, dtype=np.int64)
    sq2 = res * _SQRT2
    drs = np.array([-1, -1, -1, 0, 0, 1, 1, 1], dtype=np.int64)
    dcs = np.array([-1, 0, 1, -1, 1, -1, 0, 1], dtype=np.int64)
    for row in range(r):
        for col in range(c):
            bs = 0.0
            brc = -1
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
                        brc = nr * c + nc
            recv[row * c + col] = brc
    return recv


@njit(cache=True)
def _hand_core(dem_flat, recv, is_stream):
    """Walk each cell downstream along `recv` to the first stream cell and record
    that stream's elevation as the cell's drainage base. Path memoisation makes
    it O(n) amortised. Pits/outlets that never reach a stream drain to
    themselves (HAND 0 there)."""
    n = dem_flat.size
    drain_z = np.full(n, np.nan)
    stack = np.empty(n, dtype=np.int64)
    for start in range(n):
        if not np.isnan(drain_z[start]):
            continue
        sp = 0
        cur = start
        while np.isnan(drain_z[cur]):
            if is_stream[cur]:
                drain_z[cur] = dem_flat[cur]
                break
            rcv = recv[cur]
            if rcv < 0:                       # interior pit / tile-edge outlet
                drain_z[cur] = dem_flat[cur]
                break
            stack[sp] = cur
            sp += 1
            cur = rcv
        dz = drain_z[cur]
        for k in range(sp):
            drain_z[stack[k]] = dz
    hand = dem_flat - drain_z
    for i in range(n):                        # clamp tiny negatives from ties
        if hand[i] < 0.0:
            hand[i] = 0.0
    return hand


def hand_grid(dem, accum, res, stream_area_m2):
    """
    Height Above Nearest Drainage for every cell (metres).

    dem            : 2-D gap-filled DTM (same array fed to d8_accumulate)
    accum          : 2-D D8 upslope-cell-count grid from d8_accumulate(dem, res)
    res            : cell size (m)
    stream_area_m2 : contributing-area threshold defining the channel network;
                     a cell is "stream" when accum * res**2 >= this.
    """
    dem = np.ascontiguousarray(dem, dtype=np.float64)
    rows, cols = dem.shape
    recv = _d8_receivers(dem, np.float64(res))
    thresh_cells = stream_area_m2 / (res * res)
    is_stream = (accum.ravel() >= thresh_cells)
    hand = _hand_core(dem.ravel(), recv, is_stream)
    return hand.reshape(rows, cols)
