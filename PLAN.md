# Plan — Multi-Region Expansion + Model Redesign + Performance

> **Trigger:** Aleks (the stakeholder) saw the Ljubljana demo, called it "amazing," and offered to loop in his team at **[sledilnik.org](https://sledilnik.org/)** (the civic-data org behind Slovenia's national COVID-19 tracker). He flagged **two known flood sites** as test cases. This plan responds to that.
>
> **Companion docs:** [`HANDOFF.md`](HANDOFF.md) (snapshot + model deep-dive), [`DECISIONS.md`](DECISIONS.md) (decision log, append new ones here), [`CLAUDE.md`](CLAUDE.md) (authoritative context). This plan supersedes the "Open decisions / next steps" list at the bottom of HANDOFF.md.

## Why this changes the prior plan

The previous next-step list led with a **cosmetic marker-cap fix** for the Ljubljana demo. Aleks's message reorders everything: he isn't asking whether the Ljubljana pins look tidy — he's asking **"does it work on sites I know flooded?"** That makes **validation the headline** and **demotes cosmetics**. He also handed us two *contrasting* mechanisms, which forces a structural decision: one flood model can't serve both.

| Site | lat / lon | EPSG:3794 center tile | CDN region | Flood mechanism |
|---|---|---|---|---|
| Ljubljana (current demo) | 46.05 / 14.51 | `462_101` | `05-ljubljana` | mixed / urban |
| **Savinja valley** (Ljubno–Mozirje) | 46.347 / 14.846 | **`488_134`** | **`08-kamnik`** ✅ (probed) | **riverine** (Aug 2023 floods) |
| **Koper** | 45.548 / 13.730 | **`400_46`** | **`01-koper`** ✅ (probed) | **coastal / sea-level rise** |

## Goals

1. Pull a **5×5 (25-tile) block centered on each new site** and get both onto the map.
2. **Validate** the model against the Savinja valley's documented Aug-2023 flood footprint (real ground truth).
3. **Redesign the riverine model** (HAND + elevation + slope; demote vegetation) — now testable against Savinja.
4. Add a **separate coastal "bathtub" inundation mode** for Koper (sea-level-rise scenarios).
5. **Per-region calibration** so three disjoint extents with different elevation regimes stay comparable internally.
6. **Performance:** make the pipeline fast enough to iterate model→re-run repeatedly (multiprocessing + Numba; GPU evaluated honestly below).

Non-goal: this remains a **terrain screening tool** (spatial triage), not a hydraulic/hydrodynamic flood model. Keep telling Aleks that.

---

## Part A — Two new 5×5 regions (data acquisition)

`download_tiles.py` semantics (confirmed): `--radius R` = R tiles on each side of `--center`, so **`--radius 2` → 5×5 = 25 tiles**.

### Savinja valley — center tile `488_134`
- Tiles: **E 486–490 × N 132–136** (25 tiles).
- ✅ **Probed:** all **25/25 exist on the CDN**, region **`08-kamnik`** (now cached in `.tile_region_cache.json`).
- Download (and optionally pipeline):
  ```bash
  python download_tiles.py --center 488 134 --radius 2            # ~4.5 GB
  ```

### Koper — center tile `400_46`
- Tiles: **E 398–402 × N 44–48** (25 nominal).
- ✅ **Probed:** **21/25 exist** in region **`01-koper`**. The 4 NW-corner tiles **`398_48, 399_48, 398_47, 399_47` are over the Adriatic/border and not on the CDN** — exactly the coastal caveat anticipated. `download_tiles.py` simply skips them.
- Download:
  ```bash
  python download_tiles.py --center 400 46 --radius 2            # ~3.8 GB (21 tiles)
  ```

### Disk / cost
- 25 tiles × ~180 MB ≈ **~4.5 GB LAZ per region**, ~9 GB for both, on top of the existing ~19 GB in `data/` (gitignored). Fine.
- **Download is the new long pole**, not compute (see Part D). ~4.5 GB per region over the network.

---

## Part B — Per-region calibration (architecture change, candidate **D16**)

**Problem:** D15 global normalisation derives ONE fixed `[lo, hi]` per factor across all of `data/`. With three disjoint regions — Koper at ~0 m elevation, alpine Savinja walls near ~1000 m — a single normalisation blows the ranges out and makes scores meaningless. Cross-region comparison isn't even desirable: the flood mechanisms differ.

**Decision:** move from one global ruler to **per-region rulers**.
- Group tiles into regions (by CDN region, or by tile-coordinate cluster).
- `calibration.json` gains a `regions: { ljubljana: {...}, savinja: {...}, koper: {...} }` structure; each holds its own `constants` + `display` + `dataset_fingerprint`.
- `--calibrate` runs per region; the pipeline selects the right constants per tile from its region.
- **Reversal:** keep the old flat-`constants` path as a fallback for single-region datasets.

This is a `DECISIONS.md` entry to append once implemented.

---

## Part C — Two flood models (the substance)

### C1 — Riverine redesign (Savinja) — the main model work
Implements the re-weighting already discussed in [`HANDOFF.md`](HANDOFF.md) (§ "Proposed iterative re-weighting"). Current model over-weights "absence of vegetation + flatness" (canopy 25% + NDVI 15% + roughness 5% = 45%). Target:

| Factor | Current | Proposed | Notes |
|---|---|---|---|
| **HAND** (height above nearest drainage) | — | **25%** | New. #1 research factor. See below for the mosaic approach. |
| TWI | 40% | **20%** | already computed |
| **Elevation** (low = high risk) | — | **15%** | New, free from DTM |
| **Slope** (flat = high risk) | — | **15%** | New, already computed for TWI |
| Plan curvature | 15% | **10%** | keep |
| **Land cover / imperviousness** | — | **5%** | New, from LiDAR classification (buildings/bare) |
| NDVI health | 15% | **5%** | demote |
| Canopy interception | 25% | **5%** | demote |
| Roughness | 5% | **0%** | drop |

**Sequencing (cheapest first):**
1. **Elevation + slope + demote vegetation** — both already computed in `compute_factors`; this is a weights edit in `export_tile` + a recalibrate + run. ~15 min of work. Do this first and look at Savinja.
2. **HAND** — the involved one. Needs a stream network (threshold flow accumulation) then height-above-nearest-stream. **Do it on the stitched region mosaic, not per-tile** (the 5×5 → one 2500×2500 grid). This fixes the tile-edge flow-truncation problem HANDOFF flagged AND is the natural output of the library-based flow routing in Part D.

### C2 — Coastal "bathtub" inundation (Koper) — separate sub-model
The riverine factors (TWI, canopy) **cannot** represent sea-level-rise flooding, and shouldn't try. Coastal inundation is driven by **absolute elevation vs. sea level**.
- **Model:** threshold the DTM at sea-level-rise scenarios (e.g. **+0.5 / +1 / +2 m**); shade everything below each threshold as inundated. Optionally connectivity-constrain to the sea (flood-fill from the coast so isolated low basins aren't falsely flooded).
- Simpler than the riverine model and directly answers Aleks's second link.
- Output: a distinct overlay type (toggle in the side panel), with a scenario selector.

### C3 — Validation (the credibility step, now concrete)
- **Savinja:** overlay the documented **Aug 2023 flood footprint** and check the model fires on the valley floor / Savinja channel corridor. Baseline the **current** model first (run as-is on the new tiles) so we can show before/after of the redesign.
- **Both:** overlay **ARSO official flood-hazard zones** (EU Floods Directive). This moves from "nice to have" to "expected" given the sledilnik audience.

### C3-RESULT — Savinja baseline run (DONE, current model + Ljubljana calibration)
Ran the **current** model on the 25 Savinja tiles (806 s, ~32 s/tile; 92 M pts/tile) to baseline against the documented **Aug-2023 flood** footprint. **The model fails to identify the flood valley — strongest evidence yet for the redesign:**
- **Quantitative:** of the global **top-500** risk cells, only **4 are in Savinja** (496 Ljubljana); **0 of the top-20** (`risk_points.geojson` unchanged — `464_102` still sweeps it). Savinja max susc **0.9058** vs Ljubljana **0.9307**.
- **Absurdity check:** one of the 4 Savinja "risk" cells is at **1215 m elevation** (alpine `490_136`) — a physically impossible flood site, flagged only because it's flat + treeless.
- **Visual (heatmaps):** on valley-floor tile `488_132` the model paints **steep slopes red (high) and the river corridor / valley floor blue (low)** — *inverted*. The Ljubno center tile `488_134` is **almost entirely blue** — i.e. "no risk" exactly where the 2023 flood hit.
- **Honest caveats:** Savinja was scored against **Ljubljana calibration** (cross-region mismatch suppresses scores — per-region calib D16 needed to fully isolate), and per-tile D8 truncates valley drainage at edges (HAND-on-mosaic fixes). **But** the inverted *within-tile* pattern (slopes hot, valleys cool) is **model-structural** (the 45% vegetation/flatness weighting), robust to calibration. The redesign (HAND + elevation + slope; demote vegetation) should flip this and light up the valley floor — that's the "after" to produce next.

---

## Part D — Performance (multiprocessing + Numba + GPU, honest take)

> ✅ **DONE (D16).** Numba kernels in `kernels.py` (DTM grouped-min **153×**, D8 **71×**, bit-identical) + `ProcessPoolExecutor` across tiles in `main()`/`calibrate()` with a RAM-bound worker default + `--workers N`. Measured **806s → 244s** (3.3×) on the 25 Savinja tiles at 3 workers; full faithfulness verified (PNGs + candidates byte-identical to baseline). Next bottleneck = `np.add.at` scatter ops; GPU stays deferred. Design rationale below is preserved for reference.

### Hardware (measured this session)
- **GPU:** NVIDIA RTX 4080 Laptop, **12 GB VRAM**, CUDA-capable (driver 596.49).
- **CPU:** **32 logical cores**.
- **Installed:** neither `numba` nor `cupy` present yet. RAM not measured (`psutil` absent) — **measure it**, it caps worker count (below).

### Where the time actually goes (per tile)
Profiling target order, from reading `pipeline.py`:
1. **`laspy.read` (LAZ decompression)** — CPU-bound (`lazrs`), single-threaded *per tile*. Parallelizable **only across tiles**. No GPU benefit.
2. **DTM build loop** (`compute_factors`, ~line 184: `for gx,gy,gz in zip(...)`) — pure-Python iteration over **every ground point** (millions/tile). A **hidden bottleneck, possibly larger than D8.** Vectorizable (`np.minimum.at`) or Numba.
3. **`d8_accumulate`** (line 81) — pure-Python loop over **every cell** (~250k/tile × 8 neighbours). The known bottleneck. Numba target.
4. Everything else (curvature, voxel canopy, NDVI, roughness, normalize, composite, PNG) — already vectorized numpy; fast.

> Note: `--calibrate` calls `compute_factors` on **every** tile too, so it carries the same costs as a full run minus export.

### Lever 1 — Multiprocessing across tiles ★ biggest, safest win
Tiles are independent. Wrap the per-tile work in a `ProcessPoolExecutor`.
- **Two-pass structure** required for per-region calibration (Part B): **(A)** parallel `compute_factors` → cache raw factors (write `.npz` per tile, return the path — avoids pickling big arrays back across the process boundary); **(B)** serial reduce → derive per-region constants; **(C)** `export_tile` (cheap, parallel or serial).
- **Worker count is capped by RAM, not cores.** Each worker decompresses a ~180 MB LAZ into ~1–3 GB of point arrays (x/y/z/cls/red/nir for 10–40 M points). 32 workers would need 30–90 GB and **OOM a laptop**. Start at **~6–8 workers**; tune against measured RAM.
- **Windows uses `spawn`** (not fork): workers re-import the module — the existing `if __name__ == "__main__"` guard is correct; pass **file paths** (picklable), not loaded arrays.
- **Expected:** near-linear on the parallel fraction up to the RAM cap → roughly **6–8×** on a 25-tile region.

### Lever 2 — Numba JIT the two Python loops ★ do alongside Lever 1
- `@njit(cache=True)` on `d8_accumulate` (sorted-order scalar scan — ideal Numba shape) → typically **50–100×** on that loop.
- DTM build loop → either `np.minimum.at(dtm,(yg,xg),zg)` or a small Numba grouped-min kernel (Numba usually wins).
- `cache=True` persists the compiled artifact so each spawned worker pays compile cost **once**, not every run.
- Pure CPU, **no CUDA runtime dependency** → most robust. Install: `pip install numba`.

### Lever 3 — "Buy don't build" flow routing (RichDEM / pysheds) ★ strongly consider
Instead of hand-tuning the D8 loop, use a real flow library on the **per-region mosaic**:
- **RichDEM** (C++/OpenMP, multi-core internally) or **pysheds** (numba) compute flow direction + accumulation far faster, and give a real **stream network → HAND nearly for free**.
- Kills two birds: replaces the bottleneck **and** unlocks the #1 redesign factor (HAND) — and doing it on the stitched 2500×2500 region mosaic **fixes the tile-edge truncation** problem.
- Cost: new dependency + reworking the DTM→flow path. Worth a pilot precisely because the redesign needs HAND anyway.

### Lever 4 — GPU (CuPy) — honest assessment: **optional, not the primary lever**
The 4080 is tempting, but match it to the work:
- **Good GPU fit (data-parallel):** gradients/curvature, `gaussian_filter`, `distance_transform_edt`, roughness, NDVI scatter, normalization, compositing → drop-in via **CuPy** / `cupyx.scipy.ndimage`. **But these are already fast numpy and a small fraction of runtime** — accelerating them barely moves the total.
- **Poor GPU fit:** `d8_accumulate` (sequential dependency on sorted order — GPU-hostile), HAND's stream-distance (graph-ish), and **LAZ decompression** (CPU-only). These are exactly the bottlenecks.
- **GPU + multiprocessing don't compose:** one GPU, N processes all launching kernels → serialized on the GPU + 12 GB VRAM shared → contention / OOM. You pick **one**: CPU multiprocessing across tiles (scales with 32 cores) **or** a single-process GPU path. Given the bottlenecks are serial/CPU-bound, **CPU multiprocessing wins here.**
- **Verdict:** GPU is a **Tier-2, later** option — worthwhile only if we move to much larger mosaics or add many GPU-friendly factors. Reserve `cupy-cuda12x` for a future single-process whole-Slovenia mosaic pass. Don't build the plan around it.

### Recommended performance architecture
1. **Numba (`cache=True`) on both Python loops** + **`ProcessPoolExecutor` across tiles** (6–8 workers, RAM-tuned), with the **two-pass raw-factor cache** for per-region calibration. → the dependency-light path that does most of the work.
2. **Pilot RichDEM/pysheds** on a region mosaic to (a) replace flow routing and (b) deliver **HAND** + fix edge truncation. If it lands, it may **subsume Lever 2**.
3. **GPU/CuPy:** profile *after* 1–2; adopt only if the stencil math is shown to dominate. Never naively combined with multiprocessing.
4. **Keep the machine awake** during long runs — per `HANDOFF.md`, background `--calibrate` was silently sleep-killed twice. Re-runs are safe (downloads skip/resume; `calibration.json` writes only at the end).

### Expected outcome
Current ~28 min / 100 tiles (single-process, two Python loops). With Numba loops + ~8-way multiprocessing: a **25-tile region in well under a minute of compute** (then download-bound), and a full 100-tile run in the **low single-digit minutes**. Fast enough to iterate the model freely.

---

## Phased execution checklist

- [ ] **0. Measure RAM** (`pip install psutil` or check Task Manager) → sets worker count.
- [ ] **1. Probe** both regions with `--dry-run` (Savinja `488_134` r2, Koper `400_46` r2); confirm region names + which Koper tiles exist.
- [x] **2. Performance first** (so iteration is cheap): ✅ Numba both loops (`kernels.py`) + multiprocessing in `main()`/`calibrate()` + `--workers`. Verified byte-identical on the 25-tile re-run. (The "two-pass raw-factor cache" wasn't needed — each worker does compute+export and returns small meta; calibration is parallelized separately.)
- [ ] **3. Per-region calibration** (D16): region-keyed `calibration.json`.
- [ ] **4. Download Savinja**, run **current** model as baseline, screenshot vs. Aug-2023 footprint.
- [ ] **5. Riverine redesign:** elevation + slope + demote vegetation → recalibrate → re-run → compare. Then **HAND** (mosaic / RichDEM).
- [ ] **6. Download Koper**, build the **coastal bathtub** SLR mode (+0.5/+1/+2 m), wire a scenario toggle in `web/app.js`.
- [ ] **7. Validation:** overlay ARSO flood-hazard zones (+ 2023 footprint for Savinja).
- [ ] **8. Web app:** multi-region map (the side panel + `fitBounds` already fan out over `manifest.union_bounds`; with 3 disjoint blocks consider a region selector / per-region fit).
- [ ] **9. Update `DECISIONS.md`** (D16 per-region calibration, D17 coastal mode, D18 perf architecture) and refresh `HANDOFF.md`.

## Risks & caveats to keep telling Aleks
- Still a **screening tool**, not a hydraulic model. No rainfall, no soil, no calibrated channel network.
- Coastal "bathtub" is a **first-order** SLR estimate (ignores surge dynamics, drainage, defenses).
- HAND from per-tile flow is truncated at edges — **mosaic-level routing required** for a credible result.
- Weights are **literature-informed, not ground-truth-calibrated** until validated against ARSO / the 2023 footprint.

## Decisions (DECISIONS.md)
- **D16** — ✅ Performance: Numba hot loops + multiprocessing across tiles; GPU deferred. *(recorded)*
- **D17** — ✅ Per-region calibration + model redesign (elevation/slope factors). Flipped Savinja valley to #1. *(recorded)*
- **D18** — ✅ Ground-coverage no-data mask: sea / no-ground cells render transparent, are excluded from calibration + candidates. Koper riverine **baseline** processed (21 tiles, region 01-koper). *(recorded)*
- **D19** — ✅ HAND factor (per-tile) + research-weighted model (HAND 25 / TWI 20 / elev 15 / slope 15 / curv 10 / interc 7.5 / ndvi 7.5) + no-data mask refined to a distance threshold (no forest/urban speckle) + per-region risk-point cap. *(recorded)*
- **D20** — Separate coastal "bathtub" SLR inundation mode for Koper, distinct from the riverine model. *(pending)*
