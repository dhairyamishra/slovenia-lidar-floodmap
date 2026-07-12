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


def dtm_min_update(dtm, yg, xg, zg):
    """Update an existing inf-initialized mosaic DTM with ground returns."""
    return _dtm_min_core(
        dtm,
        yg.astype(np.int64),
        xg.astype(np.int64),
        zg.astype(np.float64),
    )


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


# ── Mosaic hydrology (D26) ──────────────────────────────────────────────────

@njit(cache=True)
def _heap_push(heap_idx, heap_z, size, idx, z):
    pos = size
    heap_idx[pos] = idx
    heap_z[pos] = z
    size += 1
    while pos > 0:
        parent = (pos - 1) // 2
        if heap_z[parent] <= z:
            break
        heap_idx[pos] = heap_idx[parent]
        heap_z[pos] = heap_z[parent]
        pos = parent
    heap_idx[pos] = idx
    heap_z[pos] = z
    return size


@njit(cache=True)
def _heap_pop(heap_idx, heap_z, size):
    idx = heap_idx[0]
    z = heap_z[0]
    size -= 1
    if size > 0:
        last_idx = heap_idx[size]
        last_z = heap_z[size]
        pos = 0
        while True:
            left = pos * 2 + 1
            if left >= size:
                break
            right = left + 1
            child = left
            if right < size and heap_z[right] < heap_z[left]:
                child = right
            if heap_z[child] >= last_z:
                break
            heap_idx[pos] = heap_idx[child]
            heap_z[pos] = heap_z[child]
            pos = child
        heap_idx[pos] = last_idx
        heap_z[pos] = last_z
    return idx, z, size


@njit(cache=True)
def _priority_flood_core(dem, epsilon):
    """Priority-flood with epsilon gradients and open outer boundaries."""
    rows, cols = dem.shape
    n = rows * cols
    filled = dem.copy()
    visited = np.zeros(n, dtype=np.uint8)
    heap_idx = np.empty(n, dtype=np.int64)
    heap_z = np.empty(n, dtype=np.float64)
    size = 0

    # Seed each outer-boundary cell exactly once.
    for col in range(cols):
        top = col
        bottom = (rows - 1) * cols + col
        if visited[top] == 0:
            visited[top] = 1
            size = _heap_push(heap_idx, heap_z, size, top, filled[0, col])
        if visited[bottom] == 0:
            visited[bottom] = 1
            size = _heap_push(heap_idx, heap_z, size, bottom, filled[rows - 1, col])
    for row in range(rows):
        left = row * cols
        right = row * cols + cols - 1
        if visited[left] == 0:
            visited[left] = 1
            size = _heap_push(heap_idx, heap_z, size, left, filled[row, 0])
        if visited[right] == 0:
            visited[right] = 1
            size = _heap_push(heap_idx, heap_z, size, right, filled[row, cols - 1])

    drs = np.array([-1, -1, -1, 0, 0, 1, 1, 1], dtype=np.int64)
    dcs = np.array([-1, 0, 1, -1, 1, -1, 0, 1], dtype=np.int64)
    while size > 0:
        idx, z, size = _heap_pop(heap_idx, heap_z, size)
        row = idx // cols
        col = idx % cols
        for direction in range(8):
            nr = row + drs[direction]
            nc = col + dcs[direction]
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            nidx = nr * cols + nc
            if visited[nidx] != 0:
                continue
            visited[nidx] = 1
            nz = filled[nr, nc]
            if nz <= z:
                nz = z + epsilon
                filled[nr, nc] = nz
            size = _heap_push(heap_idx, heap_z, size, nidx, nz)
    return filled


def priority_flood_fill(dem, epsilon=1e-5):
    """Condition a finite DEM so every interior cell has a descending outlet."""
    dem = np.ascontiguousarray(dem, dtype=np.float64)
    if not np.isfinite(dem).all():
        raise ValueError("priority_flood_fill requires a finite DEM")
    return _priority_flood_core(dem, np.float64(epsilon))


def flow_receivers(dem, res):
    """Public mosaic-safe D8 receiver wrapper."""
    dem = np.ascontiguousarray(dem, dtype=np.float64)
    return _d8_receivers(dem, np.float64(res))


@njit(cache=True)
def _accumulate_receivers_core(recv, order):
    accum = np.ones(recv.size, dtype=np.float64)
    for position in range(order.size):
        idx = order[position]
        receiver = recv[idx]
        if receiver >= 0:
            accum[receiver] += accum[idx]
    return accum


def accumulate_receivers(dem, recv):
    """Accumulate cell counts along a precomputed D8 receiver graph."""
    dem = np.ascontiguousarray(dem, dtype=np.float64)
    recv = np.ascontiguousarray(recv, dtype=np.int64)
    order = np.argsort(-dem.ravel())
    return _accumulate_receivers_core(recv, order).reshape(dem.shape)


def hand_from_receivers(dem, recv, stream_mask):
    """HAND from an existing continuous receiver graph and stream mask."""
    dem = np.ascontiguousarray(dem, dtype=np.float64)
    recv = np.ascontiguousarray(recv, dtype=np.int64)
    streams = np.ascontiguousarray(stream_mask, dtype=np.bool_).ravel()
    return _hand_core(dem.ravel(), recv, streams).reshape(dem.shape)


@njit(cache=True)
def _strahler_core(recv, stream, order):
    n = recv.size
    result = np.zeros(n, dtype=np.int16)
    max_up = np.zeros(n, dtype=np.int16)
    max_count = np.zeros(n, dtype=np.int16)
    for position in range(order.size):
        idx = order[position]
        if not stream[idx]:
            continue
        current = max_up[idx]
        if current == 0:
            current = 1
        elif max_count[idx] >= 2:
            current += 1
        result[idx] = current
        receiver = recv[idx]
        if receiver >= 0 and stream[receiver]:
            if current > max_up[receiver]:
                max_up[receiver] = current
                max_count[receiver] = 1
            elif current == max_up[receiver]:
                max_count[receiver] += 1
    return result


def strahler_order(dem, recv, stream_mask):
    """Strahler order on the D8 stream graph; zero outside the stream mask."""
    dem = np.ascontiguousarray(dem, dtype=np.float64)
    recv = np.ascontiguousarray(recv, dtype=np.int64)
    stream = np.ascontiguousarray(stream_mask, dtype=np.bool_).ravel()
    order = np.argsort(-dem.ravel())
    return _strahler_core(recv, stream, order).reshape(dem.shape)


@njit(cache=True)
def _mfd_accumulation_core(dem, res, order, exponent):
    rows, cols = dem.shape
    accum = np.ones(rows * cols, dtype=np.float64)
    drs = np.array([-1, -1, -1, 0, 0, 1, 1, 1], dtype=np.int64)
    dcs = np.array([-1, 0, 1, -1, 1, -1, 0, 1], dtype=np.int64)
    slopes = np.empty(8, dtype=np.float64)
    sq2 = res * _SQRT2
    for position in range(order.size):
        idx = order[position]
        row = idx // cols
        col = idx % cols
        total = 0.0
        for direction in range(8):
            nr = row + drs[direction]
            nc = col + dcs[direction]
            weight = 0.0
            if 0 <= nr < rows and 0 <= nc < cols:
                distance = sq2 if drs[direction] != 0 and dcs[direction] != 0 else res
                slope = (dem[row, col] - dem[nr, nc]) / distance
                if slope > 0:
                    weight = slope ** exponent
            slopes[direction] = weight
            total += weight
        if total > 0:
            for direction in range(8):
                if slopes[direction] <= 0:
                    continue
                nr = row + drs[direction]
                nc = col + dcs[direction]
                accum[nr * cols + nc] += accum[idx] * slopes[direction] / total
    return accum.reshape((rows, cols))


def mfd_accumulation(dem, res, exponent=1.1):
    """Freeman-style MFD cell-count accumulation for sensitivity analysis."""
    dem = np.ascontiguousarray(dem, dtype=np.float64)
    order = np.argsort(-dem.ravel())
    return _mfd_accumulation_core(dem, np.float64(res), order, np.float64(exponent))
