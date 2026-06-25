# Slovenia LiDAR Floodmap — Project Context

> **Decision log:** All significant technical and data decisions are recorded in [`DECISIONS.md`](DECISIONS.md) with rationale and reversal instructions. Read it before making architectural changes and append to it after making new decisions.

## What this is
A flood & forest risk analysis web app built on Slovenia's national CLSS LiDAR dataset.
Four-factor susceptibility model rendered as MapLibre GL image overlays on a dark basemap.

## Stack
- **Frontend**: MapLibre GL JS v4.7.1, OpenFreeMap dark basemap, vanilla JS
- **Pipeline**: Python (`pipeline.py`) — reads `.laz` files, outputs PNGs + manifest. Hot loops Numba-JIT'd in `kernels.py`; tiles fan out across processes (D16). Requires `numba`.
- **Hosting**: GitHub Pages (`web/` directory), deployed via GitHub Actions on push to main
- **Local dev**: `python -m http.server 8765 --directory web`

## Data
- **Source**: Flycom CLSS S3 CDN — `https://assets.flycom.si/clss/raw/<region>/zls/gkot/GKOT_E_N.laz`
- **CRS**: EPSG:3794 (Slovene national grid), tile coords = km (e.g. `460_100` = easting 460km, northing 100km)
- **Current dataset**: 81 tiles — contiguous 9×9 km² block covering Ljubljana (456–464 E × 96–104 N)
- **LAZ files**: stored in `data/` (gitignored), ~170–200 MB each, ~15 GB total on disk
- **Scattered outliers removed**: 10 tiles outside the Ljubljana block were deleted (D09)

## Key scripts
| Script | Purpose |
|---|---|
| `pipeline.py` | Process all `GKOT_*.laz` in `data/`, write PNGs + manifest. Run `python pipeline.py` (all tiles) or `python pipeline.py 460_100 461_100` (subset — merges into existing manifest). `python pipeline.py --calibrate` derives the global normalisation constants (run once per dataset). Tiles run in parallel; `--workers N` overrides the RAM-bound default (works with both modes). |
| `kernels.py` | Numba `@njit(cache=True)` hot loops (`dtm_min_grid`, `d8_accumulate`) — bit-identical to the old pure-Python loops, ~70–150× faster (D16). |
| `bench_kernels.py` | Correctness + speed gate: asserts the Numba kernels match the originals on one real tile. `python bench_kernels.py [TILE_ID]`. |
| `download_tiles.py` | Download tiles from CDN. `--center E N --radius R` for a square grid, `--bbox E_min N_min E_max N_max`, or `--tiles E_N ...`. `--pipeline` runs pipeline after download. `--dry-run` checks CDN availability without downloading. |

## Performance (D16)
- Hot loops are Numba-JIT'd in `kernels.py` (`cache=True` → compiled once, reused across runs + workers). DTM grouped-min ~153×, D8 ~71×, both **bit-identical** to the old loops.
- Tiles process in parallel via `ProcessPoolExecutor` in both `main()` and `calibrate()`. Worker default is **RAM-bound** (`available_GB // 5`, capped at `cpu_count`) — each worker peaks ~4–6 GB on dense tiles, so memory is the wall, not cores. Override with `--workers N`.
- Measured: 25 Savinja tiles 806s → 244s at 3 workers (~3.3×). Close other apps / free RAM → more workers → higher.
- Next bottleneck (not yet optimised): the `np.add.at` scatter ops (voxel canopy / NDVI / roughness) + laspy decode. GPU deferred — D8 is serial, LAZ decode is CPU, and one GPU contends with multiprocessing.
- **Verify faithfulness after any change to these loops**: `python bench_kernels.py <TILE>` then re-run a tile and confirm `git diff` on its PNGs is empty.

## Common pitfalls
- **Deleting tiles manually**: If you delete a LAZ file and its PNG dir, you must also purge its entry from `manifest.json`. The pipeline merge logic keeps old entries for tiles it doesn't re-process. Purge with: `python -c "import json; m=json.load(open('web/data/manifest.json')); m['tiles']=[t for t in m['tiles'] if t['name'] not in {'TILE_ID'}]; m['tile_count']=len(m['tiles']); json.dump(m,open('web/data/manifest.json','w'),indent=2)"`
- **Pipeline print says wrong tile count**: The `manifest.json — N tile(s)` line shows tiles processed this run, not total tiles in the merged manifest. Check `manifest.json` directly to confirm total.
- **Subset run scope**: `python pipeline.py 460_100` processes that one tile. The global `web/data/candidates.json` is updated by stripping that tile's old entries and inserting the new ones — so `risk_points.geojson` always reflects all tiles as long as a full run has been done at least once.

## Pipeline outputs (per tile)
- `web/data/tiles/<name>/susceptibility.png` — composite flood risk (RdYlBu_r)
- `web/data/tiles/<name>/ndvi.png` — forest health (RdYlGn, percentile-stretched)
- `web/data/tiles/<name>/classification.png` — land cover classes
- `web/data/candidates.json` — global ranked list of top-500 risk candidates (raw susc scores), used for subset-run safety and future UI features
- `web/data/manifest.json` — tile registry consumed by web app
- `web/data/risk_points.geojson` — top-20 globally ranked flood risk points

## Susceptibility model weights
- TWI (topographic wetness index): 40%
- 3D canopy interception: 25%
- NDVI health: 15%
- Plan curvature: 15%
- Terrain roughness: 5%

## Global normalisation (calibration.json)
Each factor is normalised against a FIXED dataset-wide [lo, hi] range (p2–p98),
not re-curved per tile — so risk scores are comparable across tiles. The ranges
live in `calibration.json` (committed), derived once by `python pipeline.py --calibrate`.
`calibration.json` also stores a dataset fingerprint (tile name + file size map).
Normal pipeline runs compare the current `data/` against it and print a loud
warning if tiles were added, removed, or re-downloaded — prompting a recalibration.
If `calibration.json` is missing, the pipeline falls back to DEFAULT_CONSTANTS
(placeholders) and warns. See DECISIONS.md D15.

## Critical NDVI fix (applied)
The CLSS sensor NIR channel is radiometrically compressed — vegetation NDVI median ~0.09
(not the 0.4–0.8 expected from satellite data). Fixed by:
- Display: percentile-stretch (p5–p95 of veg cells per tile) instead of fixed 0–0.85
- Risk model: `1 - norm01(mn_ndvi)` instead of `1 - clip(mn_ndvi, 0, 1)`

## CDN regions (16 total)
Region names discovered from S3 bucket listing at `https://assets.flycom.si/clss/`:
`01-koper`, `02-nova-gorica`, `03-postojna`, `04-jesenice`, `05-ljubljana`,
`06-kocevje`, `07-novomesto`, `08-kamnik`, `09-celje`, `10-murskasobota`,
`11-maribor`, `12-velenje`, `13-ljubljana-aneks`, `16-kamnik-aneks`,
`17-novagorica-aneks`, `18-jesenice-aneks`

Region cache stored in `.tile_region_cache.json` (committed).

## Marker fix (applied)
MapLibre DOM markers — CSS `transition: transform` caused 120ms pan lag.
Fixed: removed transform transition, used CSS `scale` property for hover instead.

## Web app behaviour
- `app.js` fetches `data/manifest.json` and `data/risk_points.geojson` on load
- `fitBounds` uses `manifest.union_bounds`
- Each tile gets its own MapLibre image source + 3 raster layers
- Layer toggles in the side panel fan out to all tiles simultaneously
