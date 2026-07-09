# Project Decision Log

Chronological record of significant technical and data decisions.
Each entry includes the rationale and how to reverse/revisit if needed.

---

## 2026-06-24

### D01 — MapLibre image overlays instead of vector tiles
**Decision:** Render pipeline outputs as georeferenced PNG image sources per tile, not as vector/MVT tiles.
**Why:** The pipeline produces raster grids (2m × 2m cells). Converting to vector would require rasterio → GeoTIFF → tippecanoe or similar, adding significant complexity. PNG image sources are trivial to add to MapLibre and work at any zoom.
**Trade-off:** No zoom-dependent detail, fixed resolution PNGs. Fine for this use case — the overlays are analytical, not basemap-style.
**Reversible:** Yes. Switch to `addLayer` with a raster-tiles source backed by a tile server, or use `addLayer` with a `type: fill` GeoJSON layer from the pipeline's per-cell output.

---

### D02 — DOM markers for high-risk points (not GeoJSON canvas layers)
**Decision:** Risk points rendered as `maplibregl.Marker` DOM elements, created inside `map.on('load')`.
**Why:** GeoJSON canvas layers go through async web-worker tiling, causing a one-frame slip during pan against the pre-cached basemap. DOM markers use `map.project(lngLat)` every render frame and never slip.
**Trade-off:** Performance degrades if marker count gets very large (hundreds+). Currently capped at 20.
**Reversible:** Yes, but expect pan slip. Alternatively use a custom WebGL layer for large counts.

---

### D03 — CSS `scale` property instead of `transform: scale()` for marker hover
**Decision:** Hover effect on `.risk-marker` uses `scale: 1.18` (individual CSS transform property) with `transition: scale`, NOT `transform: scale(1.18)` with `transition: transform`.
**Why:** MapLibre writes `transform: translate(x,y)` directly on the marker element every render frame. A `transition: transform` rule animated every position update with a 120ms delay, causing markers to visibly lag behind the map during pan.
**Reversible:** Revert `style.css` — but pan lag returns immediately.

---

### D04 — Root-anchored `.gitignore` pattern for `data/`
**Decision:** `.gitignore` uses `/data/` (root-anchored) not `data/` (matches anywhere).
**Why:** The non-anchored pattern `data/` also matched `web/data/`, which excluded all tile PNGs and the manifest from git. Discovered after first commit had no web assets.
**Reversible:** Change back to `data/` only if you want `web/data/` ignored too (you don't).

---

### D05 — Manifest-driven multi-tile web app
**Decision:** `app.js` fetches `data/manifest.json` at runtime and builds all map layers dynamically from it. No tile names are hardcoded in JS.
**Why:** Originally the app was hardcoded for a single tile (478_73). The multi-tile harness needed the app to scale to any number of tiles without code changes.
**How it works:** `pipeline.py` writes `manifest.json` after each run. `app.js` reads it and calls `addTileLayers()` for each entry.
**Reversible:** Yes, but you'd need to hardcode every tile name in JS — impractical at 81+ tiles.

---

### D06 — Pipeline subset runs MERGE into existing manifest
**Decision:** When `pipeline.py` is run with specific tile IDs (e.g. `python pipeline.py 460_100`), it reads the existing `manifest.json`, updates/adds only those tiles, and writes the merged result. It does NOT overwrite the full manifest.
**Why:** Early runs overwrote the manifest with only the subset tiles, losing all other entries. Discovered after a 3-tile run replaced a 10-tile manifest.
**Caveat:** If you delete a tile's LAZ and PNG files manually, you must also purge its entry from `manifest.json` (use the Python snippet in session history or re-run the purge script).
**Reversible:** Delete `manifest.json` and run `python pipeline.py` (all tiles) to regenerate from scratch.

---

### D07 — CDN region discovery via S3 bucket listing
**Decision:** Region slugs for the Flycom CDN were discovered by reading the S3 bucket XML listing at `https://assets.flycom.si/clss/` rather than guessing.
**Why:** Initial guesses (e.g. `07-jugovzhodna-slovenija`) were all wrong. The actual 16 regions use city-based names (e.g. `07-novomesto`, `06-kocevje`).
**The 16 regions:** `01-koper`, `02-nova-gorica`, `03-postojna`, `04-jesenice`, `05-ljubljana`, `06-kocevje`, `07-novomesto`, `08-kamnik`, `09-celje`, `10-murskasobota`, `11-maribor`, `12-velenje`, `13-ljubljana-aneks`, `16-kamnik-aneks`, `17-novagorica-aneks`, `18-jesenice-aneks`.
**Cache:** `.tile_region_cache.json` stores tile→region mappings so probing only happens once per tile.

---

### D08 — NDVI percentile-stretch display (fix for inverted appearance)
**Decision:** NDVI PNGs are rendered with `vmin` = p5, `vmax` = p95 of each tile's vegetation-cell NDVI values, not a fixed `vmin=0, vmax=0.85`.
**Why:** The CLSS scanner's NIR channel is radiometrically compressed relative to satellite sensors. Vegetation NDVI median ≈ 0.09 (vs expected 0.4–0.8). With the fixed scale, healthy forest plotted at 9% of the RdYlGn scale (solid red) — visually inverted. Diagnosis confirmed by inspecting raw Red/NIR channel values on a processed tile.
**Risk model fix:** Also changed `ndvi_risk = 1 - clip(mn_ndvi, 0, 1)` → `1 - norm01(mn_ndvi)`. The old formula gave forest risk ≈ 0.921, bare ground ≈ 1.0 — a 0.08 difference making the NDVI factor nearly inert in the composite.
**Reversible:** Change `vmin`/`vmax` in `colormap_to_rgba` call and revert `ndvi_risk` formula in `pipeline.py`, then re-run.

---

### D09 — Dataset trimmed to Ljubljana-only 9×9 block
**Decision:** Removed 10 scattered outlier tiles from the dataset: `401_129` (Tolmin), `430_150` (Jesenice), `434_77`/`435_75` (Postojna), `443_145`/`452_145` (Radovljica), `478_73`/`478_74` (Ribnica), `505_100`/`509_100` (Litija).
**Why:** They appeared as isolated specks on the map with no neighbouring tiles, providing no contiguous coverage. The main 9×9 Ljubljana block (456–464 E × 96–104 N) is the analytical focus.
**Current state:** 81 tiles, ~15 GB LAZ, covering central Ljubljana and surroundings.
**Reversible:** Re-download with `python download_tiles.py --tiles 401_129 430_150 ...` and re-run pipeline. The tiles are still on the CDN.

---

### D10 — GitHub Pages deployment via GitHub Actions
**Decision:** The `web/` directory is deployed to GitHub Pages on every push to `main` via `.github/workflows/deploy-pages.yml`.
**Why:** Zero-config static hosting for the map app. No server required.
**URL:** `https://dhairyamishra.github.io/slovenia-lidar-floodmap/`
**Reversible:** Disable the Pages workflow in GitHub repo settings.

---

### D11 — `download_tiles.py` with region auto-discovery and cache
**Decision:** Built a dedicated CDN downloader (`download_tiles.py`) that auto-discovers the correct region slug per tile via HEAD requests, caches results in `.tile_region_cache.json`, and supports `--center/--radius`, `--bbox`, `--tiles`, `--dry-run`, and `--pipeline` flags.
**Why:** The CDN organises tiles under 16 region subdirectories (city-based names, not geographic/NUTS names). There is no direct coordinate→region lookup table — probing is required. Caching means each tile is probed at most once. The `--pipeline` flag enables a single command for the full download→process→deploy workflow.
**Key detail:** The downloader tries the last successful region first for each new tile (geographic locality means adjacent tiles are almost always in the same region), so a square grid typically resolves every tile in one probe after the first.
**Reversible:** Script can be deleted; tiles can still be downloaded manually from the CDN URL pattern.

---

### D12 — Manual tile deletion requires manifest purge
**Decision:** When LAZ files and PNG directories are deleted manually, the `manifest.json` entry must be purged separately. The pipeline merge logic retains entries for tiles it did not process.
**Why:** Discovered when 10 scattered tiles were deleted from disk but the pipeline re-run (which only processed the 81 remaining tiles) still produced a 91-entry manifest. The web app would then try to load PNGs that no longer existed.
**Fix applied:** After the delete, ran a Python one-liner to filter the manifest to only tiles whose names were not in the removal set, then recalculated union bounds.
**Going forward:** Any time tiles are deleted, immediately purge the manifest before the next pipeline run. See "Common pitfalls" in `CLAUDE.md` for the purge command.
**Reversible:** Re-download deleted tiles with `download_tiles.py --tiles <IDs>` and re-run pipeline.

---

### D13 — Per-tile candidates.json + raw susc scoring for global risk ranking
**Decision:** Each processed tile now writes `web/data/tiles/<name>/candidates.json` with its top-60 risk candidates scored by raw `susc`. The global ranking in `main()` loads ALL existing `candidates.json` files (not just tiles in the current run) before selecting the top-20 globally.
**Why:** Two bugs caused all 20 risk points to cluster in a single tile:
1. `risk_points.geojson` was rebuilt only from tiles in the current pipeline run — a prior subset run on `456_100` left all 20 points in that one tile.
2. Candidates were scored with `susc_n` (per-tile re-normalised to [0,1]) so every tile's best candidates scored 1.0, making cross-tile comparison meaningless.
**Fix:** Candidates now use raw `susc` (weighted composite before renormalisation). `susc_n` is still used for PNG display. Persisting `candidates.json` per tile means subset runs stay accurate globally.
**Limitation:** Raw `susc` is still built from per-tile normalised factors (TWI, curvature, etc.), so cross-tile comparability is approximate rather than absolute. This is a known model constraint — a truly flat tile will produce candidates that score similarly to a hilly tile if both happen to have the same relative factor values.
**Reversible:** Remove the `candidates.json` write and the `processed_names`/load loop in `main()`, and revert `order`/`score` back to `susc_n`.

---

### D14 — Single global candidates.json replaces per-tile files
**Decision:** Replaced 81 per-tile `candidates.json` files with a single `web/data/candidates.json` capped at 500 entries (GLOBAL_CANDS_N). The pipeline loads this file, strips stale entries for any tiles in the current run, merges in fresh candidates, sorts by score, truncates to 500, and writes it back.
**Why:** Per-tile files produced 81 × 542 = ~44,000 lines of generated JSON — too large to commit comfortably. A single capped file is ~4,500 lines, small enough to commit, and carries the same subset-run safety (old tile entries are removed by tile name before new ones are inserted).
**Reversible:** Revert main() to write per-tile candidates.json and load from tile directories. See D13 for the previous approach.

---

## 2026-06-25

### D15 — Global fixed-range normalisation with calibration + dataset fingerprint
**Decision:** Replaced per-tile `norm01` normalisation of each factor with FIXED dataset-wide ranges (p2–p98) stored in `calibration.json`. Constants are derived once by `python pipeline.py --calibrate`, which subsamples ~5% of raw factor cells per tile, pools them, and computes global percentiles. The normal pipeline loads these constants and normalises every tile against the same ruler, so the composite `susc` (and therefore candidate scores) is comparable across tiles. The susceptibility PNG also uses a fixed display range so heatmap colours are consistent tile-to-tile.
**Why:** Per-tile normalisation curved each tile to its own 0–1 range. A flat flood-plain tile and a steep hillside tile both produced a max score of 1.0, so the global risk ranking could not tell genuinely risky terrain from the least-bad cell of a benign tile. Global normalisation gives an honest cross-tile scale.
**Calibration trigger:** `calibration.json` stores a dataset fingerprint — a `{tile_name: file_size}` map plus a short sha256 digest. Every normal run fingerprints the current `data/` and compares; if tiles were added, removed, or re-downloaded (size change), it prints a loud warning to re-run `--calibrate`. Name+size is used instead of content hashing to avoid hashing 15 GB on every run. Removal also warns even though it only makes constants slightly conservative.
**Architecture:** `process_tile` was split into `compute_factors` (load + 5 raw factors, shared by calibration and normal runs) and `export_tile` (normalise against constants + composite + PNG + candidates). Unused `norm01` removed from pipeline.py (legacy copies remain in `export_web_assets.py` / `flood_susceptibility.py`).
**Behaviour without calibration:** Falls back to DEFAULT_CONSTANTS (placeholders) and warns — never blocks. Optional future `--strict` flag could make a stale/missing calibration a hard stop.
**Limitation:** Constants are tuned to the Ljubljana basin. Expanding into dramatically different terrain (Alps, coast) needs a recalibration, which the fingerprint check will prompt.
**Reversible:** Revert `export_tile` to use `norm01` per-tile and drop the calibration/fingerprint functions. See D08 and D13 for prior normalisation/scoring behaviour.

---

### D16 — Performance: Numba hot loops + multiprocessing across tiles
**Decision:** The two pure-Python loops in `compute_factors` — the DTM grouped-min over every ground point, and `d8_accumulate` over every grid cell — are moved to Numba `@njit(cache=True)` kernels in a new module `kernels.py`. Separately, `main()` and `calibrate()` fan tiles out across processes with `ProcessPoolExecutor`; each worker processes one tile and writes its own PNGs, returning only small meta + candidates (no large arrays cross the process boundary). Worker count defaults to a RAM-bound estimate (`available_GB // 5`, capped at `cpu_count`) and is overridable with `--workers N`.
**Why:** A full 100-tile run took ~28 min; the dense 92M-point Kamnik/Savinja tiles pushed a 25-tile run to ~13 min (806s). The DTM loop scales with point count and dominated.
**Measured:** DTM loop **153×** (9.2s→0.06s), D8 **71×** (1.0s→0.01s), both bit-identical. Multiprocessing added **3.3×** at 3 workers (806s→244s on the 25 Savinja tiles). Memory, not cores, is the cap: each worker peaks ~4–6 GB on these tiles, so only ~3 workers fit in ~19 GB free; the 32 logical cores idle first.
**Faithfulness:** Verified byte-identical, not merely close. `bench_kernels.py` asserts the kernels match the original loops on a real tile; a full 25-tile re-run reproduced PNGs and `candidates.json` identical to the committed baseline (`git diff` empty). Kernels preserve the D8 tie-break (strict `>`, fixed neighbour order) and run the argsort in numpy so iteration order matches across elevation ties.
**Caveats:** The next per-tile cost after Numba is the `np.add.at` scatter ops (voxel canopy / NDVI / roughness) + laspy decode — not yet optimised; this is why big tiles still dominate and the gain is 3.3×, not higher. More free RAM → more workers → higher speedup. GPU deferred (D8 is serial, LAZ decode is CPU-bound, and one GPU contends with multiprocessing).
**Reversible:** Re-inline the DTM loop and restore the pure-Python `d8_accumulate` in `pipeline.py`; delete `kernels.py`; revert the `ProcessPoolExecutor` blocks to serial `for` loops and drop `--workers`. New dependency: `numba` (`pip install numba`).

---

### D17 — Model redesign: elevation + slope factors, per-region calibration
**Decision:** Added elevation and slope as first-class risk factors (replacing terrain roughness, which was near-zero weight and provided no signal). Weights restructured: TWI 30%, elevation 20% (inverted — low elevation → high risk), slope 20% (inverted — flat terrain → high risk), plan curvature 10%, canopy interception 10%, NDVI 10%. Roughness dropped (weight 0). Simultaneously switched from a single global calibration to per-region calibration: `calibration.json` now stores a `regions` dict keyed by CDN region slug, each with its own p2–p98 factor ranges and display range. Normal pipeline runs resolve each tile's calibration constants from its CDN region (stored in `.tile_region_cache.json`).
**Why:** The original model (TWI 40%, canopy 25%, NDVI 15%, curvature 15%, roughness 5%) produced completely inverted heatmaps for the Savinja alpine valley: high-risk alpine slopes showed red, low-elevation valley floors showed blue. Root cause was two-fold: (1) without elevation or slope, the model had no terrain-scale gradient — TWI-dominated scores peaked on steep forested hillsides, not flat floodplains; (2) the single global calibration (derived on Ljubljana basin, 285–417m) was meaningless for the Savinja/Kamnik region (401–1269m). Aleks Jakulin identified the Savinja Aug-2023 flood site as a validation target; the "before" model put 0 of top-20 risk cells there and ranked a 1215m alpine cell as the best Savinja candidate.
**Measured result (after):** Savinja valley floor (tile 488_132, ~403m elevation) is now the **global #1 risk candidate** (score 0.950). 3 of 10 global top-10 points are Savinja valley-floor cells. The 1215m alpine cell is gone from the top-20. Heatmap for 488_132: nearly all deep red (flat alluvial valley). Heatmap for 488_134 (alpine center tile): mostly blue with red traces along valley drainage lines. Both visually correct.
**Architecture:** `calibrate()` now groups tiles by CDN region, samples each independently, computes per-region p2–p98 factor ranges, writes `{"model_version":2, "regions": {"05-ljubljana":{...}, "08-kamnik":{...}, ...}}` to `calibration.json`. `main()` resolves each tile's constants before dispatch: `region_const.get(tile_region(...), default_cd)`. Falls back to `DEFAULT_CONSTANTS` if a region has no calibration data (prints a warning). `check_calibration()` validates model_version and compares the tile fingerprint per-region. `slope_rad` was already computed during TWI calculation — just added to `compute_factors` return dict. Elevation factor maps to the existing `dtm` key via `FACTOR_KEYS`.
**Reversible:** Revert `SUSC_WEIGHTS` in `pipeline.py` to the D15 weights (TWI 40%, canopy 25%, NDVI 15%, curvature 15%, roughness 5%), remove the `"slope"` key from `compute_factors` return dict, and revert `calibrate()`/`check_calibration()`/`load_region_constants()` to the flat single-region format. Re-run `--calibrate` on the Ljubljana dataset to restore `calibration.json` v1.

---

## 2026-06-26

### D18 — Ground-coverage no-data mask + Koper riverine baseline
**Decision:** `compute_factors` now captures `ground_cov` — a boolean grid of cells that had at least one ground return (classification 2) BEFORE the DTM gap-fill. This mask is threaded through three places: (1) calibration samples only ground-covered, finite cells, so a region's factor ranges reflect real terrain rather than gap-fill-extrapolated water; (2) `export_tile` sets `susc = NaN` outside ground coverage and passes `nodata_mask=~ground_cov` to the susceptibility PNG, so sea / no-data cells render transparent (the basemap shows through) instead of being painted as terrain; (3) the risk-candidate loop breaks on the first non-finite `susc`, so no NaN-elevation point can enter the global ranking. Calibration percentiles also switched from `np.percentile` to `np.nanpercentile`, and the empty-vegetation NDVI percentile is guarded. With these fixes the 21-tile Koper block (region `01-koper`) was processed as a **riverine baseline**: manifest now 146 tiles (100 Ljubljana + 25 Savinja + 21 Koper).
**Why:** Koper is coastal. Tile `400_48` has **zero ground returns** (entirely Adriatic), so its DTM is all-NaN even after gap-fill, and several other tiles are 0.1–3% ground. The first `--calibrate --region 01-koper` returned `[NaN, NaN]` for every DTM-derived factor (twi, elev, slope, curv) because plain `np.percentile` propagates a single NaN. Beyond the calibration break, the un-masked riverine model would have painted the open sea bright red (low + flat ⇒ high risk) — visually broken for the Aleks/sledilnik demo. The mask makes the model honest about where it has data: it scores land, and stays silent over water.
**Result:** Koper calibration is now finite with elevation range **[-0.11, 189.46] m** — sea level, fully disjoint from Ljubljana (285–417 m) and Savinja (402–1269 m), confirming per-region calibration (D17) is mandatory. `400_46` (Koper port) renders scored urban land with a transparent harbour/sea; `400_48` renders fully transparent. The global top-20 now spans all three regions (14 Ljubljana, 3 Savinja, 3 Koper), elevations 0.2–403 m, each scored on its own ruler.
**Scope / caveat:** This is the riverine model applied to a coastal site — a **baseline**, not a sea-level-rise product. It flags low-flat coastal land (which partly overlaps SLR exposure) but cannot model tidal/marine inundation; that is handled separately by the coastal "bathtub" mode added later in D20. Cross-region top-20 entries are each normalised on their own per-region ruler, so they are "worst within region", not absolutely comparable (a known consequence of D17). **Forward-effect:** the no-data mask is now unconditional in the code, so a future *full* re-run would also turn inland no-data cells (under dense buildings, water bodies) transparent on the Ljubljana/Savinja PNGs. Only the 21 Koper tiles were processed this run, so the committed inland overlays are unchanged.
**Reversible:** Drop the `ground_cov` capture in `compute_factors` and its three consumers (calibration mask, `export_tile` susc NaN + `nodata_mask`, candidate finite-break); revert the four `np.nanpercentile` calls and the NDVI guard. Re-run `--calibrate --region 01-koper` to restore the (broken) un-masked behaviour. To remove Koper entirely, delete its 21 LAZ + PNG dirs, purge the manifest (see CLAUDE.md pitfalls), and drop the `01-koper` block from `calibration.json`.

---

## 2026-06-27

### D19 — HAND factor + research-weighted model + no-data mask refinement + per-region cap
**Decision:** Added **HAND (Height Above Nearest Drainage)** as the model's lead factor — the #1 predictor in the flood literature (HANDOFF.md), previously missing entirely. New Numba kernels in `kernels.py`: `_d8_receivers` (steepest-descent receiver per cell, identical neighbour order + strict-`>` tie-break to `_d8_core`, so receivers are consistent with the accumulation) and `_hand_core` (walks each cell downstream to the first stream cell with O(n)-amortised path memoisation). `hand_grid(dem, accum, res, stream_area_m2)` thresholds the D8 accumulation into a channel network (`STREAM_AREA_M2 = 10_000`) and returns height above it. This is the **per-tile cut**: flow is routed within each tile, so paths crossing a tile edge terminate there (a known approximation — true HAND needs whole-mosaic routing). With HAND available, weights were rebalanced to the literature consensus: **HAND 25%, TWI 20% (down from the inflated 30% that was standing in for drainage proximity), elevation 15%, slope 15%, plan curvature 10%, canopy interception 7.5%, NDVI 7.5%** (sum 1.0). HAND is per-region calibrated like every other factor.
**Why:** Every AHP / frequency-ratio / ML flood study ranks proximity/height-above-drainage as the top factor (17–32% weight); the D17 model had none of it and propped up TWI at 30% as a weak proxy. HAND captures what elevation alone cannot — a cell 30 m above the river on a terrace is low-risk even if its absolute elevation is low. Validated on three terrains before wiring in: HAND traces the drainage network correctly (dendritic on alpine `488_134`, valley-corridor on `488_132`, ~uniformly low on the flat Ljubljana floodplain where the whole tile sits near base level). The 10k m² stream threshold gives 0.3–0.7 % stream density on relief tiles and falls back gracefully (height-above-outlet) on flat tiles where per-tile accumulation never reaches it.
**No-data mask refinement (was D18 strict):** The D18 mask (`ground_cov = ~isnan(dtm)`, any no-ground cell transparent) was about to speckle the forested Savinja and urban Ljubljana tiles with salt-and-pepper holes on their first post-D18 re-run (alpine 11 % no-ground under canopy, urban 20 % under building footprints — but **all within 16 m** of real ground). Refined to a **distance threshold**: `ground_cov = dist_to_nearest_ground <= NODATA_FILL_CELLS (8 cells / 16 m)`. Forest/building gaps (well-constrained gap-fill) stay filled; only genuine large gaps (open water / Adriatic, hundreds of m from ground) render transparent. Verified: alpine 100 % data, urban 99.7 %, Koper port 35 % land / 65 % sea, all-sea `400_48` 100 % transparent.
**Per-region risk-point cap:** Per-region normalisation (D17) makes the raw `susc` of each region's worst cells all ~0.95 and **not cross-region comparable**, so the global top-20 flooded with whichever region holds the largest maximally-flat-low patch — after the mask fix un-masked the Koper port, 15 of 20 points landed there. Added `REGION_CAP = 7`: no CDN region may contribute more than 7 of the global top-N. Result is balanced (Savinja 6 / Koper 7 / Ljubljana 7) with the Savinja Aug-2023 flood valley back at **#1** — the demo narrative Aleks flagged.
**Result:** Full 146-tile re-run. Heatmaps are clean across all three regions and HAND sharpens the riverine signal (alpine flood risk now follows the valley drainage, not just low absolute elevation). Faithfulness gate (`bench_kernels.py`) still PASS — the DTM/D8 kernels were not touched, only new functions added.
**Caveats:** (1) Per-tile HAND is edge-truncated — a 1 km tile only "sees" drainage accumulating within itself, so the channel network is local, not the true Savinja/Sava. Whole-mosaic routing is the upgrade. (2) `calibration.json` was derived under the D18 strict mask (run `bg13yq4du`); the export uses the refined distance mask. The difference is immaterial (inland coverage 98 %→100 % barely moves p2–p98), so it was not re-derived to avoid 146 PNGs of churn — a future `--calibrate` will reconcile it. (3) Land-cover/imperviousness (~5 % in the research target) is still unbuilt; veg sits at 15 % absorbing it. (4) Still a screening tool, not a hydraulic model — no rainfall/soil, weights literature-informed not ground-truth-calibrated (ARSO validation pending).
**Reversible:** Revert `SUSC_WEIGHTS` to the D17 weights, drop `"hand"` from `FACTOR_COLS`/`FACTOR_KEYS`/`DEFAULT_CONSTANTS`, remove the HAND block in `compute_factors` and the three HAND functions in `kernels.py`; restore `ground_cov = ~np.isnan(dtm)` and drop `NODATA_FILL_CELLS`; remove `REGION_CAP` and its loop guard. Then `--calibrate` + full run.

---

## 2026-07-09

### D20 — Koper coastal bathtub sea-level-rise overlay
**Decision:** Added a separate coastal inundation layer for the Koper region (`01-koper`) instead of folding sea-level-rise exposure into the riverine susceptibility score. The pipeline now exports three Koper-only PNG masks per tile: `coastal_slr_0_5m.png`, `coastal_slr_1_0m.png`, and `coastal_slr_2_0m.png`. These are recorded under `files.coastal` in `web/data/manifest.json`; the MapLibre app adds optional raster layers for those entries and exposes a side-panel scenario selector plus opacity control.
**Why:** Aleks specifically called out Koper as a sea-level-rise case, which is a different mechanism from riverine flooding. HAND/TWI/elevation/slope can flag low flat coastal terrain, but they cannot answer "what land is below a given sea-level scenario?" A simple bathtub screen is more honest and directly legible for a stakeholder demo.
**Model:** A land cell is marked inundated when its gap-filled DTM elevation is below the selected scenario and it is connected, within the same tile, to mapped sea/no-data cells. This keeps isolated inland low spots from filling by default while staying compatible with the existing per-tile pipeline. Sea/no-data itself remains transparent; the overlay only shades land exposed under the scenario.
**Result:** Regenerated the 21 Koper tiles. `manifest.json` remains 146 tiles and now has 21 coastal-enabled tiles with 63 scenario PNGs total. On `400_46` (Koper port), visible inundation grows from roughly 59k pixels at +0.5 m to 128k at +2.0 m; all-sea tile `400_48` stays fully transparent for all scenarios.
**Caveats:** This is a first-order screening layer, not a coastal hydraulic model. It ignores tides, storm surge, waves, groundwater, drainage, levees/defenses, and tile-to-tile coastal connectivity. The connection test is local to each 1 km tile, so inland tiles without a no-data/sea seed will not fill even if they would connect through a neighbouring tile in a stitched coastal DEM. A future mosaic-level coastal pass should replace the per-tile connectivity constraint.
**Reversible:** Remove `COASTAL_REGION`, `COASTAL_SLR_SCENARIOS`, `coastal_inundation_mask`, `coastal_mask_to_rgba`, and the Koper coastal export block from `pipeline.py`; remove the `files.coastal` handling and coastal UI controls from `web/app.js` / `web/index.html`; delete `web/data/tiles/*/coastal_slr_*.png`; re-run the Koper subset or full pipeline to refresh `manifest.json`.

### D21 — ERA5-Land hydroclimate trigger as a separate temporal layer

**Decision:** Added a new hydroclimate trigger feature instead of folding weather/climate state into the static LiDAR susceptibility PNGs. `hydroclimate.py` builds app-ready GeoJSON assets under `web/data/hydroclimate/`: a coarse trigger grid and hydro-primed risk points for a selected date. V1 ships one deterministic fixture date (`2023-08-04`, Savinja Aug-2023 hindcast) so the UI and data contract work without CDS credentials or large ERA5 downloads.

**Model:** The trigger follows the Copernicus/BGC article Aleks shared: `hydro_score = soil_moisture_norm + water90_norm + 0.5 * wetting_trend_norm`; `hydro_index = hydro_score / 2.5`. The fixture intentionally elevates the Savinja/Kamnik block for the August 2023 flood-hindcast story. Real ERA5-Land derive support expects NetCDF files with `swvl4`, `tp`, and `smlt` variables in `data/era5/` and uses xarray when available.

**Why separate:** The LiDAR model answers "where is terrain susceptible?" ERA5-Land answers "when is the landscape hydroclimatically primed?" Keeping the layers separate avoids presenting a coarse, fixture-backed temporal signal as calibrated flood probability. The app can still combine the two for a ranked exploratory view via `event_score = static_susceptibility * hydro_index`.

**Result:** The web app now loads `data/hydroclimate/manifest.json` opportunistically, adds a MapLibre GeoJSON fill layer, and exposes a hydro-primed marker toggle. Missing hydroclimate data disables those controls without breaking existing riverine, coastal, NDVI, classification, or static marker layers.

**Caveats:** V1 is not an operational forecast and not a trained Random Forest model. It does not download from CDS automatically, does not estimate probability, and has not been validated against ARSO or observed flood footprints. The fixture is for UI validation and stakeholder explanation only; replace it with ERA5-Land-derived outputs before using it analytically.

**Reversible:** Remove `hydroclimate.py`, `web/data/hydroclimate/`, the hydro controls from `web/index.html`, the hydro layer/marker logic from `web/app.js`, and the `.hydro-risk-marker` CSS. Existing LiDAR and coastal products are independent.

---

*Append new entries as: `### D<N> — <short title>` under a `## YYYY-MM-DD` heading.*
