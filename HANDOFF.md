# Handoff — Slovenia CLSS LiDAR Flood & Forest Demo

**Status:** Built, committed, deployed. Now a **100-tile 10×10 grid** with **global fixed-range normalisation** live on GitHub Pages. The current open thread is a **flood-susceptibility model redesign** (see the deep-dive section below). · **Goal:** A polished, static, no-backend web app overlaying flood-susceptibility and forest-NDVI analysis (from Slovenia's national CLSS LiDAR) on an interactive dark map, to demo to a stakeholder named **Aleks**.

> Authoritative, continuously-maintained context: [`CLAUDE.md`](CLAUDE.md) + the decision log [`DECISIONS.md`](DECISIONS.md). This handoff is the higher-level snapshot and carries the latest analysis.

## Context

Slovenia's national airborne LiDAR (CLSS — *Ciklično lasersko skeniranje*, Geodetska uprava RS) feeds a Python pipeline that computes a multi-factor flood-susceptibility model + per-cell forest NDVI, then exports georeferenced raster overlays + ranked risk points for a MapLibre web viewer styled like the national viewer at <https://clss.si>. Ties to a real national priority: post-2023-flood reconstruction.

## Current state (latest commits on `main`)

- `f48d50d` — **Expand to 100-tile 10×10 grid + global-normalised overlays** (current HEAD).
- `1580216` — Global fixed-range normalisation + calibration (D15).
- `f2e78b4` — Fix risk points to span all tiles; single global `candidates.json` (D13/D14).

Verified working:
- `pipeline.py` processes all 100 tiles → per-tile PNGs, `manifest.json` (100), `candidates.json` (top-500), `risk_points.geojson` (top-20).
- Web app loads in a real browser: dark basemap (OpenFreeMap), susceptibility (blue→red), NDVI (red→green), classification, side-panel toggles + opacity sliders, geo-registration confirmed.
- Risk markers are DOM markers (`maplibregl.Marker`), numbered pins (see Technical notes for why DOM not GeoJSON).
- Auto-deploys to GitHub Pages on push to `main`. Live: https://dhairyamishra.github.io/slovenia-lidar-floodmap/

## Dataset

- **100 tiles**, contiguous **10 × 10 km block over Ljubljana** — EPSG:3794 easting **455–464 km × northing 96–105 km**. (Grown this session from the prior 9×9 / 81 tiles by adding the west column `455_96..455_105` and north row `456_105..464_105`, extending NW.)
- All data EPSG:3794 (Slovene National Grid); overlays reproject to EPSG:4326 via `pyproj`.
- Raw `.laz` (~19 GB) lives in `data/` and is **gitignored**; small `web/data/` overlays are committed. All 100 tiles are in CDN region `05-ljubljana`.

## Method (as currently implemented)

- **Composite weights:** TWI **40%** + 3D canopy interception **25%** + NDVI health **15%** + plan curvature **15%** + terrain roughness **5%**. DTM = pseudo-DTM from GKOT ground returns (class 2) at 2 m; D8 flow accumulation drives TWI; canopy uses a 2 m voxel grid.
- **Global normalisation (D15):** each factor scaled against a FIXED dataset-wide [lo,hi] (p2–p98) in `calibration.json`, so scores are comparable across tiles. Pipeline split into `compute_factors` (raw factors, shared) + `export_tile` (normalise vs constants → composite → PNG + candidates). `--calibrate` derives constants; a dataset fingerprint (tile name+size) warns on change.
- **Current 100-tile constants** (`calibration.json`, fingerprint `a4b004c6`): twi `[3.59, 9.22]`, interc `[0, 0.64]`, ndvi `[-0.146, 0.183]`, curv `[-0.0525, 0.0457]`, rough `[0.0001, 0.377]`, susc-display `[0.352, 0.857]`.
- **Risk points:** top-20 globally-ranked cells from `candidates.json` (top-500 pool, deduped to ≥50 m). Scored on **raw `susc`** (the display range is cosmetic only — see below).

---

## ⭐ Flood-susceptibility model — deep dive & redesign (THIS SESSION'S KEY WORK)

This is the live open thread. Read this before touching the model.

### The symptom

After moving to global normalisation on the 100-tile grid, the top-20 risk markers **concentrate 19-of-20 in a single tile (`464_102`, eastern Ljubljana)**, 1 in `461_103`. Candidate span dropped from 72 → 39 tiles. The susceptibility heatmap shows the **urban east as red (high), forested western hills as blue (low)**.

### Diagnosis — it's faithful, NOT a bug

Verified with code review + data:
- **Display scale ≠ ranking.** The PNG colours via `norm_fixed(susc, 0.352, 0.857)`, but candidates score on **raw `susc`**. So the display range is purely cosmetic; it does **not** affect which pins win. The clustering is not a display artifact.
- **Factor constants DO drive ranking** — intentionally (D15). Per-tile→global is the cause of the redistribution, and that's correct behaviour.
- **`464_102` is a genuine broad hotspot, not an edge artifact:** its risk points span the full tile width (464018–465000) and elevation varies only 8 m across the km² (genuinely flat). The eastern urban half dominates candidates (E461:125, E463:94, E464:92, E462:88, E460:72) while the western forested/hill half is near-empty (E455:1, E457:2). It wins by a hair (top score 0.9307 vs ~0.923 for the next tiles — bunched within ~0.008).
- **Refactor is faithful:** weights sum to 1.0, inversions (interc/ndvi/rough) preserved, no sign/index bug.

### Root cause — the model over-weights "absence of vegetation + flatness"

Three inverted factors — canopy interception (25%) + NDVI (15%) + roughness (5%) = **45% of the weight** — all reward *bare + flat + smooth* terrain. Under per-tile normalisation this was masked (each tile stretched to its own 0–1). Under global normalisation, a uniformly flat-treeless (urban) tile scores ~0.79 everywhere while a forested hill scores ~0.21. The model is effectively a **"flat, treeless land" detector** — which is why the urban footprint lights up and `464_102` sweeps the ranking.

### What trusted research says (literature review, this session)

Consensus across AHP / frequency-ratio / ML feature-importance studies — the dominant predictors are **hydrological/topographic proximity to drainage, not vegetation**:

| Factor | Higher risk when… | Typical lit. weight |
|---|---|---|
| Distance-to-river / **HAND** | near channel / low height above drainage | 17–32% (often #1) |
| **Elevation** | low | 10–16% |
| **Slope** | flat / low | 12–20% |
| **TWI** | high | 8–15% |
| Drainage density | region-dependent | 9–22% |
| Rainfall | high/intense | 7–16% |
| Curvature | concave | ~5% |
| Land use (LULC) | built-up / impervious / bare | **~2–5%** |
| NDVI / tree cover | low vegetation | **<10%** |
| Soil / lithology | clay / impermeable | ~3–5% |

**Our model vs consensus:** we over-weight vegetation (~45% vs ~5–15%) and **omit the strongest research-backed factors entirely** — no HAND/distance-to-drainage, no standalone elevation, no standalone slope. We have no rainfall/soil (data we lack). What we get right: TWI is a legit top factor; concave plan curvature is directionally correct.

### Proposed iterative re-weighting (DISCUSSED, NOT IMPLEMENTED)

| Factor | Current | Proposed | Feasibility |
|---|---|---|---|
| **HAND** | — | **25%** | New. From DTM + existing D8 flow accumulation (threshold → stream net → height above nearest stream). Highest-ROI add. ⚠ per-tile flow accumulation is truncated at tile edges; a proper HAND wants whole-mosaic accumulation (bigger change). Per-tile approx is a fine first cut. |
| TWI | 40% | **20%** | already computed |
| **Elevation** (low) | — | **15%** | New. Free from DTM (normalise, low=high). |
| **Slope** (flat) | — | **15%** | New. Already computed for TWI. |
| Plan curvature | 15% | **10%** | keep |
| **Land cover / imperviousness** | — | **5%** | New. From LiDAR classification (buildings/bare) — a real LULC factor replacing the vegetation backdoor. |
| NDVI health | 15% | **5%** | demote |
| Canopy interception | 25% | **5%** | demote |
| Roughness | 5% | **0%** | drop (weak proxy) |

Rebalances from "45% vegetation" → "~75% hydro/topographic, ~15% vegetation, ~5% land cover," pulling risk toward genuine low-lying near-channel terrain (Sava corridor, the marsh) instead of the urban footprint.

**Recommended starting point:** add **elevation + slope** and demote the vegetation cluster first (trivial — both already computed, ~15 min + a recalibrate + run). Then prototype **HAND** separately (the involved one). Validate against **ARSO official flood-hazard zones** (EU Floods Directive) when possible — that's the real credibility step.

### Honest caveats to keep telling Aleks
Still a **terrain/vegetation screening tool** (spatial triage — "where to look first"), not a hydraulic flood model. No rainfall, no soil, no real channel network yet. Weights are literature-informed, not ground-truth-calibrated.

---

## Open decisions / next steps (pick up here)

1. **Risk-marker distribution (display-level, cheap):** add a per-tile cap (~2/tile) or larger `SEP_M` so the top-20 spread across the region instead of 19-in-`464_102`. Does not require reprocessing tiles — only the ranking loop in `main()`.
2. **Model redesign (the big one):** implement the proposed re-weighting + new factors (elevation/slope first, then HAND). Requires `--calibrate` + full pipeline re-run (~30 min each on 100 tiles).
3. **Validation:** overlay ARSO flood-hazard zones to check the model tracks documented reality.
4. **Performance:** multiprocessing across tiles + Numba JIT on the D8 loop (`d8_accumulate`) — would cut a full run from ~28 min to a few minutes. No ML/GPU involved; the bottleneck is the pure-Python D8 loop.

**Comparison asset:** `archive_preD15/` (gitignored) holds the pre-D15 per-tile-normalised susceptibility PNGs + old risk JSONs, for before/after diffing against the current global-normalised output.

**Aleks message:** a short progress message + the live link is drafted (in session history). NOTE: the live site now reflects the 100-tile grid with the concentrated markers — decide whether to apply the per-tile cap before sharing.

## Technical notes & gotchas

- **`preview_*` (Claude Preview) can't fully verify this app** — the headless browser can't reach the OpenFreeMap CDN, so `map.on('load')` never fires; screenshot/promise `preview_eval` time out. Verify in a real browser or via DOM checks (`document.querySelectorAll('.risk-marker').length`).
- **Markers are DOM not GeoJSON** — the inline GeoJSON circle layer wasn't reliably indexed by MapLibre's worker; DOM markers render immediately and don't slip on pan (D02, D03). Code: `addRiskPoints()` / `setRiskVisible()` in `web/app.js`; `.risk-marker` in `web/style.css`.
- **Subset runs merge** into `manifest.json` + global `candidates.json` (D06, D12, D14). Manual tile deletion needs a manifest purge — see "Common pitfalls" in `CLAUDE.md`.
- **Calibration dies silently on machine sleep** — twice this session a background `--calibrate` was sleep-killed mid-run with no traceback and no completion notification. Keep the machine awake during long runs; re-run is safe (calibration.json only writes at the end; downloads resume/skip).
- Raster export flips vertically (`np.flipud`): numpy row-0 = south, image row-0 = north. MapLibre `ImageSource` corners ordered [TL, TR, BR, BL] as `[lon, lat]`.

## File map

| Path | Purpose |
|---|---|
| `pipeline.py` | Canonical pipeline. `compute_factors` + `export_tile`; `--calibrate`; subset runs. Composite weights + factor inversions live in `export_tile`. |
| `download_tiles.py` | CDN downloader, region auto-discovery + cache. `--bbox/--center/--tiles/--dry-run/--pipeline`. Skips tiles already in `data/`. |
| `calibration.json` | Global constants + dataset fingerprint (committed). |
| `web/app.js` / `index.html` / `style.css` | MapLibre app: per-tile overlays, DOM markers, controls. |
| `web/data/` | Committed assets: per-tile PNGs, `manifest.json`, `candidates.json`, `risk_points.geojson`. |
| `data/` | Raw CLSS LiDAR (gitignored, ~19 GB). |
| `archive_preD15/` | Pre-D15 susceptibility PNGs + risk JSONs for before/after (gitignored). |
| `CLAUDE.md` / `DECISIONS.md` | Authoritative context + decision log (D01–D15). |
| Legacy scripts | `flood_susceptibility.py`, `export_web_assets.py`, `gkot_ndvi.py`, `flood_risk.py`, `probe_affordances.py`, `inspect_data.py` — early single-tile/exploratory, superseded by `pipeline.py`. |

## How to run locally

```bash
python -m http.server 8765 --directory web   # open http://localhost:8765
```

Regenerate analysis after a model change: `python pipeline.py --calibrate` (once per dataset), then `python pipeline.py`. Requires `laspy`, `lazrs`, `numpy`, `scipy`, `pyproj`, `Pillow` (and `rasterio` for `inspect_data.py`).

## Research sources (flood-factor literature, this session)

- [Flood susceptibility AHP + frequency ratio review (ScienceDirect, 2025)](https://www.sciencedirect.com/science/article/pii/S0921818125001407)
- [Integrated GIS + AHP multi-criteria flood framework (MDPI Water, 2025)](https://www.mdpi.com/2073-4441/17/7/937)
- [Flood susceptibility via ML — factor importance (Nature Scientific Reports)](https://www.nature.com/articles/s41598-026-38391-0)
- [AHP + FR flash-flood susceptibility, weights & classes (Frontiers, 2022)](https://www.frontiersin.org/journals/environmental-science/articles/10.3389/fenvs.2022.1037547/full)
- [AHP flood risk weight table & directionality (Wiley IJGE, 2025)](https://onlinelibrary.wiley.com/doi/full/10.1155/ijge/6480655)
- [HAND terrain-analysis enhancements (AGU WRR, 2019)](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2019wr024837)
- [HAND in data-scarce regions vs hydrodynamic models (Springer, 2023)](https://link.springer.com/article/10.1007/s12145-023-01218-x)
- [National Water Model–HAND flood-mapping evaluation (NHESS, 2019)](https://nhess.copernicus.org/articles/19/2405/2019/)
