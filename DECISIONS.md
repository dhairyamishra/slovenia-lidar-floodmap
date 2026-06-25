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

*Append new entries as: `### D<N> — <short title>` under a `## YYYY-MM-DD` heading.*
