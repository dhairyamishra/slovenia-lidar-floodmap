# Handoff - Slovenia CLSS LiDAR Flood, Coastal & Hydroclimate Demo

**Status:** Phases 1–3 of `FLOOD_MODEL_REPLACEMENT_PLAN.md` are complete (D24–D26). D19 communication is repaired, validation is locked, and Savinja now has continuous conditioned mosaic hydrology. Phase 4 extends the same code path to Ljubljana.

**Goal:** A polished, honest screening tool for Aleks / sledilnik.org that shows where detailed flood/coastal investigation should start. It is not a hydraulic, coastal, or probabilistic forecast model.

> Authoritative context: `AGENTS.md`, `CLAUDE.md`, `DECISIONS.md`, and `PLAN.md`. This handoff is the current snapshot plus the latest implementation notes.
> The active review/implementation tracker is `ALEKS_REVIEW_AND_ALGORITHM_PLAN.md`.
> The focused red-map/model-replacement tracker is `FLOOD_MODEL_REPLACEMENT_PLAN.md`.

## D26 Phase-3 Savinja mosaic hydrology (2026-07-12)

- Added `mosaic_hydrology.py` and mosaic-safe Numba kernels for priority-flood conditioning, continuous receivers/accumulation, HAND, channel distance, Strahler order, and Freeman MFD sensitivity.
- Assembled all 25 Savinja tiles into one 2 m, 2500×2500 EPSG:3794 grid from 346,901,854 ground returns. Large arrays, per-tile feature bundles, the manifest, and QA overview remain reproducible under ignored `output/mosaic/savinja/`.
- Tested official flow-line alignment before terrain enforcement. The gentle burn failed its predeclared alignment acceptance test, so the selected terrain is the unburned priority-flood surface; the raw DTM and conditioning delta remain available.
- Selected the 50,000 m² D8 stream threshold by development-only official-line alignment (precision 0.7687, recall 0.6706, F1 0.7163). The 10k and 100k thresholds and MFD routing remain recorded sensitivities.
- Verified zero internal sinks, 14,340 receiver links crossing former tile seams, conditioned-DTM seam ratio 0.9968, HAND seam ratio 0.9742, and 75.84% of official seam cells within 20 m of a derived stream.
- Cut seven feature grids back into all 25 exact tile windows after routing. Automated verification reports `all_exact: true`; no tile-local hydrology fallback occurs.
- Development-only static Q100 benchmark: per-tile HAND AUC/AP 0.7387/0.1523; mosaic HAND 0.7894/0.1973. Guard and locked-test tiles were not evaluated (`locked_test_accessed: false`).
- Added six mosaic tests; full repository suite is 30/30 passing. The legacy real-tile kernel benchmark remains bit-identical (DTM 206×, D8 76× on `488_134`).

**Why:** D19's per-tile HAND terminates drainage at every 1 km edge. Routing the 5×5 terrain once removes artificial tile outlets and improves drainage-relative discrimination without reintroducing absolute elevation.

**Caveats:** Source LAZ tiles provide no overlap halo; the outer mosaic boundary is intentionally open. Priority fill is implemented, while least-cost breaching is not; the rejected gentle burn is the bounded carve sensitivity. D8 and MFD have similar official-alignment F1 but only 0.4046 stream-cell Jaccard, so exact channel paths remain uncertain. The comparison uses a static planning Q100 reference, not the August 2023 observed event.

**Next entry point:** Phase 4—parameterize the same mosaic pipeline for Ljubljana's 10×10 block, use memory-mapped/chunk-aware storage as needed, repeat seam/conditioning checks, and document underground urban-drainage limitations. Do not inspect replacement performance on the locked test during feature engineering.

## D25 Phase-2 validation lock (2026-07-12)

- Added committed `validation/evaluation_contract.json`: label layers, 2/10/20 m grids, 10/20 m boundary buffers, split rules, controls, and selection policy.
- Added `validation_grid.py` and `prepare_validation_contract.py`.
- Generated nine committed packed grids plus `validation/evaluation_manifest.json`; total size 1.82 MB with SHA-256 digests and positive-cell counts.
- Frozen split: Ljubljana E455–461 development / E462 guard / E463–464 locked; Savinja E486–488 development / E489 guard / E490 locked; Koper evaluation-only.
- Updated `evaluate_validation.py` to exclude the 10 m Q100 ambiguity band, report split metrics, and apply development top-10% thresholds to four negative-control cohorts.
- Eligible diagnostic samples: 128,737 after excluding 22,698 ambiguous boundary samples.
- Frozen locked-test result: D19 AUC/AP 0.6100/0.3737; HAND-only 0.7764/0.5548.
- Low-flat Q100-negative flagged fraction: D19 0.1334 vs HAND-only 0.0904 using development-selected thresholds.
- Added raster/split/control tests. Full repository verification is recorded with the Phase-2 commit.

**Why:** This prevents random-pixel leakage and post-hoc reshaping of the test. It also makes “outside official extent” meaningful only inside validity and away from ambiguous boundaries.

**Important discipline:** Do not inspect locked-test replacement results during Phase 3/4 feature engineering. Use development blocks and seam/physics tests. Open the locked test only at the final model-selection gate.

**Next entry point:** Phase 3—build conditioned, continuous Savinja mosaic routing/HAND/channel-distance features, prove seam continuity, and compare only on development blocks until the final gate.

## D24 Phase-1 communication repair (2026-07-12)

- Renamed the public control to **Experimental D19 Terrain Baseline** and kept it/review points off by default.
- Preserved every original `susceptibility.png`; diagnostic mode deliberately reuses that frozen red artifact.
- Added a purple sparse review asset at display score ≥0.925. This is an unvalidated display rule, not a probability/hazard threshold or area percentile.
- Added `prepare_d19_web.py` for one-time legacy asset migration and native future export in `pipeline.py`.
- Generated 146 palette-quantized review PNGs totaling 4.6 MB. Representative Ljubljana tile `460_100` is 11.8% visible in review mode.
- Extended `prepare_validation_web.py` to schema v2 with official validity and all three Q100 depth classes.
- Added validity, Q100 depth, and Q100 comparison controls. Comparison mode activates Q100 + validity + sparse D19; it is explicitly a visual overlay, not a combined score.
- Added `test_phase1_web.py`; all 14 repository tests pass. JavaScript syntax and diff checks pass.
- Browser verification: comparison state correct, no console errors, and no horizontal overflow at 390 × 844.

**Why:** D19 underperforms HAND-only and the full red map is misleading. Phase 1 fixes claim and display semantics without pretending to improve predictive skill or erasing the failed baseline.

**Next entry point:** Phase 2—create versioned evaluation rasters, fixed spatial development/test blocks, boundary uncertainty variants, and negative controls before fitting or choosing thresholds.

## D22 Phase-0 implementation (2026-07-11)

- Added `analyze_model.py`, `model_diagnostics.py`, `test_model_diagnostics.py`, and `requirements.txt`.
- Pipeline writes model/calibration/dataset provenance plus deterministic score-stratified samples under ignored `output/diagnostics/samples/`.
- Full 146-tile rerun succeeded in 516 s with 3 workers; 145 land-bearing tiles emitted 360,790 samples (`400_48` is all sea).
- Baseline audit fails as intended: median warm fraction 0.9879, strongly red 0.9219, full-grid score/elevation Pearson −0.4742 and Spearman −0.5057.
- Per-region Pearson: Koper −0.7675, Ljubljana −0.8181, Kamnik/Savinja −0.6239.
- UI now defaults D19 and review markers off, removes probability-like percentages, labels D19 as unvalidated and D21 as synthetic, and shows a screening-only notice.
- Verification: four unit tests pass, JS syntax passes, and the rendered local app was browser-checked. Only upstream basemap missing-sprite warnings appeared.

Next entry point: acquire/rasterize official Slovenian hazard maps and an observed August 2023 Savinja extent, then build mosaic-level Savinja hydrology before selecting new weights.

## D23 official-validation implementation (2026-07-11)

- Added `validation/sources.json`, `validation/README.md`, `download_validation.py`, `prepare_validation_web.py`, `evaluate_validation.py`, and validation tests.
- Official DRSV downloads are scoped to three separate EPSG:3794 study envelopes, paginated, deduplicated, checksummed, and kept under gitignored `validation/data/`.
- Acquired IKPN validity + Q10/Q100/Q500, all three IKG Q100 depth classes, four IKRPN classes, and official flow lines.
- Added optional blue official Q10/Q100/Q500 reference controls to the app; Q100 is selected but the layer is off by default.
- Static Q100 benchmark inside official validity: 151,435 samples, 55,309 positives. D19 AUC/AP = 0.5972/0.4109; HAND-only = 0.6908/0.4985. HAND-only is now the minimum baseline.
- Per-region D19 AUC: Koper 0.5368, Ljubljana 0.6117, Kamnik 0.6648. Median tile AUC across 91 two-class tiles: 0.6239 (IQR 0.5285–0.7415).
- Ten unit tests and JS/Python syntax checks pass; official selector and default-off semantics were browser-verified.

Updated next entry point: obtain a vetted August 2023 Savinja observed footprint and ARSO event forcing; meanwhile implement mosaic-level Savinja routing/HAND and evaluate it against the frozen HAND-only and D19 baselines. Do not tune D19 weights on the Q100 reference.

## Context

This repository builds an interactive web map from Slovenia's CLSS airborne LiDAR data. `pipeline.py` reads local `data/GKOT_*.laz` files, computes terrain/vegetation factors, exports PNG overlays under `web/data/tiles/<tile>/`, and writes `web/data/manifest.json`, `web/data/candidates.json`, and `web/data/risk_points.geojson` for the static web app.

Aleks provided two validation/extension directions: the Savinja valley flood area from Aug 2023 and Koper for sea-level-rise exposure. D20 handled Koper coastal exposure. D21 now implements the Copernicus/BGC idea Aleks shared as a separate hydroclimate trigger: use soil moisture, wetting trend, and 90-day water input to answer "when is the landscape primed?" while LiDAR susceptibility still answers "where is terrain susceptible?"

Live site: https://dhairyamishra.github.io/slovenia-lidar-floodmap/

## Current State

Recent implementation commits before this working tree:

- `83def46` - Update README and handoff for D20
- `47a1320` - Add Koper coastal SLR overlays
- `770a7b5` - docs: update README
- `1bccc73` - Add HAND flood factor (D19) - research-weighted model
- `f9281d7` - Add Koper coastal baseline (21 tiles) + D18 no-data mask

Done but not yet committed in the current working tree:

- D21 `hydroclimate.py` added.
- `web/data/hydroclimate/manifest.json` generated with one available date: `2023-08-04`.
- `web/data/hydroclimate/hydro_2023-08-04.geojson` generated as a deterministic fixture grid.
- `web/data/hydroclimate/dynamic_risk_2023-08-04.geojson` generated from existing `web/data/candidates.json`.
- `web/app.js`, `web/index.html`, and `web/style.css` updated for optional Hydroclimate Trigger controls and hydro-primed risk markers.
- `DECISIONS.md` D21 and `README.md` updated.

Current local note:

- `AGENTS.md` is untracked local context from before the D20 commit.

Verified facts from this implementation:

- Fixture/export commands completed:
  - `C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe hydroclimate.py derive-fixture`
  - `C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe hydroclimate.py export`
- Generated hydroclimate web assets total about 209 KB.
- The fixture dynamic ranking puts Savinja tile `488_132` at rank #1 for `2023-08-04` with `event_score: 0.777`, `static_risk_score: 0.953`, and `hydro_index: 0.816`.
- `web/data/manifest.json` still has `tile_count: 146`.

## Method

Current riverine model (D19):

- HAND: 25%, inverted - low height above drainage is high risk.
- TWI: 20%.
- Elevation: 15%, inverted.
- Slope: 15%, inverted.
- Plan curvature: 10%.
- Canopy interception: 7.5%, inverted.
- NDVI: 7.5%, inverted.
- Roughness: computed but weight 0.

Each factor is normalised by CDN region, not globally. `calibration.json` is `model_version: 2` and has one region block each for Ljubljana, Kamnik/Savinja, and Koper.

Risk points:

- Global candidate pool is capped at 500.
- Final top-20 is deduplicated at 50 m.
- `REGION_CAP = 7` prevents one per-region-normalised region from monopolising the list. Current split is balanced by design, not because cross-region scores are absolute probabilities.

Coastal D20 model:

- Applies only to CDN region `01-koper`.
- Outputs three scenario masks per Koper tile:
  - `coastal_slr_0_5m.png`
  - `coastal_slr_1_0m.png`
  - `coastal_slr_2_0m.png`
- A land cell is shaded when its DTM elevation is below the scenario and it connects, within that tile, to sea/no-data cells.
- Sea/no-data remains transparent. The overlay only shades exposed land.

Hydroclimate D21 model:

- Implemented in `hydroclimate.py`.
- App reads `web/data/hydroclimate/manifest.json` opportunistically. Missing hydroclimate data disables controls without breaking the base map.
- Formula: `hydro_score = soil_moisture_norm + water90_norm + 0.5 * wetting_trend_norm`.
- Normalized UI index: `hydro_index = hydro_score / 2.5`.
- Hydro-primed risk points use `event_score = static_susceptibility * hydro_index`.
- V1 fixture intentionally elevates Savinja/Kamnik for the `2023-08-04` hindcast. It is not real ERA5 evidence.
- Real NetCDF path expects ERA5-Land variables `swvl4`, `tp`, and `smlt` under `data/era5/` and requires xarray/NetCDF support.

## Active Thread

The current open work is validation and credibility.

1. D21 is implemented as a UI/data-contract feature, not a validated climate product.
   The deterministic fixture is useful for stakeholder review and front-end testing, but analytical claims require real ERA5-Land data from CDS. Do not present the fixture as evidence.

2. Real ERA5-Land ingestion is only partially proven.
   `hydroclimate.py derive` has a narrow xarray path for local NetCDF files, but no CDS download automation has been added and no real NetCDF file was available in this session. The next agent should test it against actual ERA5-Land data for Slovenia before expanding the UI.

3. ARSO / official flood-hazard validation is still pending.
   The D19 terrain model is literature-informed but not calibrated against observed flood footprints. This remains the biggest credibility step for sledilnik-style technical stakeholders.

4. Savinja Aug-2023 validation is pending.
   The model now highlights the valley floor, and D21 can show a temporal priming layer, but both need comparison against documented flood extent or hazard layers.

5. Per-tile HAND and coastal connectivity are still approximate.
   HAND computes inside each 1 km tile, so drainage paths terminate locally. Coastal connectivity is also per-tile. Whole-region / mosaic routing remains the real model-quality upgrade.

Recommended entry point:

First validate D21 with real ERA5-Land over the current app bbox for `2023-08-04`, then compare the hydro-primed Savinja ranking against ARSO or observed Aug-2023 flood evidence. If that comparison is credible, add CDS download automation; if not, fix the hydro indicators before polishing the UI further.

## Gotchas

- `python` is not on PATH in this desktop shell. Use the bundled runtime:
  `C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`
- Real ERA5 derive needs xarray/NetCDF support; fixture/export does not.
- Raw `.laz` files and future ERA5 NetCDF files in `data/` are gitignored and large.
- If you delete LAZ/PNG tiles manually, also purge them from `web/data/manifest.json`; subset runs merge and will keep old entries.
- Pipeline subset runs update global candidates by removing stale entries for reprocessed tiles and merging fresh candidates.
- Long pipeline/calibration runs have previously died when the machine slept. Keep the machine awake.
- Browser preview may not fully verify MapLibre if external basemap/sprite requests fail. DOM/static checks are still useful.
- `web/app.js` intentionally treats hydroclimate data as optional; do not change that unless the static site should hard-fail when hydro assets are absent.

## File Map

| Path | Purpose |
|---|---|
| `pipeline.py` | Canonical LiDAR pipeline; D19 riverine model; D20 coastal export. |
| `hydroclimate.py` | D21 hydroclimate trigger pipeline; fixture generation, real NetCDF derive path, web export. |
| `kernels.py` | Numba kernels for DTM min-grid, D8 accumulation, HAND. |
| `download_tiles.py` | CLSS CDN downloader and tile-region cache helper. |
| `calibration.json` | Per-region p2-p98 factor/display calibration. |
| `.tile_region_cache.json` | Tile ID to CDN region mapping. |
| `web/app.js` | MapLibre app, raster layers, risk markers, coastal scenario UI, hydroclimate UI. |
| `web/index.html` | Static app shell and layer panel. |
| `web/style.css` | App styling. |
| `web/data/manifest.json` | Tile registry consumed by the app. |
| `web/data/hydroclimate/` | D21 trigger grid, dynamic risk points, and manifest. |
| `web/data/tiles/<tile>/coastal_slr_*.png` | D20 Koper coastal scenario overlays. |
| `web/data/risk_points.geojson` | Top-20 balanced static risk markers. |
| `DECISIONS.md` | Chronological decision log; append here for significant changes. |
| `PLAN.md` | Multi-region execution plan and current open checklist. |

## How To Run

Local web app:

```powershell
python -m http.server 8765 --directory web
```

If `python` is unavailable in this desktop environment, use the bundled runtime:

```powershell
C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m http.server 8765 --directory web
```

Regenerate the D21 fixture and web hydroclimate assets:

```powershell
C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe hydroclimate.py derive-fixture
C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe hydroclimate.py export
```

Attempt real ERA5-Land derive after placing NetCDF files under `data/era5/` and installing xarray/NetCDF support:

```powershell
python hydroclimate.py derive --date 2023-08-04
python hydroclimate.py export --date 2023-08-04
```

Process all LiDAR tiles:

```powershell
python pipeline.py
```

Calibrate:

```powershell
python pipeline.py --calibrate
python pipeline.py --calibrate --region 01-koper
```

## References

- Live demo: https://dhairyamishra.github.io/slovenia-lidar-floodmap/
- CLSS / source CDN pattern: `https://assets.flycom.si/clss/raw/<region>/zls/gkot/GKOT_E_N.laz`
- Copernicus article from Aleks: https://climate.copernicus.eu/linking-landslide-activity-and-era-5-hydroclimatic-models-pro-active-infrastructure-management
- ERA5-Land dataset: https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land
