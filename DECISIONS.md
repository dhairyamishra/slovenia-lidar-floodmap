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

*Append new entries as: `### D<N> — <short title>` under a `## YYYY-MM-DD` heading.*
