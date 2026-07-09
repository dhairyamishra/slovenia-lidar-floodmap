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
- **Current dataset**: **146 tiles across 3 regions** — 100 Ljubljana (455–464 E × 96–105 N, `05-ljubljana`), 25 Savinja (486–490 E × 132–136 N, `08-kamnik`, alpine riverine), 21 Koper (398–402 E × 44–48 N, `01-koper`, coastal). Each region has its own calibration (D17). Koper now has both the riverine baseline and a separate coastal bathtub SLR overlay (D20).
- **LAZ files**: stored in `data/` (gitignored), ~170–800 MB each (alpine/coastal tiles are denser), ~50 GB total on disk
- **Coastal no-data**: cells with no ground return (sea) render transparent and are excluded from calibration + risk candidates (D18). Tile `400_48` is entirely sea (0 ground points) → fully transparent PNG.
- **Scattered outliers removed**: 10 tiles outside the Ljubljana block were deleted (D09)

## Key scripts
| Script | Purpose |
|---|---|
| `pipeline.py` | Process all `GKOT_*.laz` in `data/`, write PNGs + manifest. Run `python pipeline.py` (all tiles) or `python pipeline.py 460_100 461_100` (subset — merges into existing manifest). `python pipeline.py --calibrate` derives the global normalisation constants (run once per dataset). Tiles run in parallel; `--workers N` overrides the RAM-bound default (works with both modes). |
| `kernels.py` | Numba `@njit(cache=True)` hot loops: `dtm_min_grid`, `d8_accumulate` (bit-identical to the old pure-Python loops, ~70–150× faster, D16) + `hand_grid`/`_d8_receivers`/`_hand_core` (HAND, D19). |
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
- `web/data/tiles/<name>/coastal_slr_0_5m.png`, `coastal_slr_1_0m.png`, `coastal_slr_2_0m.png` — Koper-only coastal bathtub sea-level-rise masks (D20)
- `web/data/candidates.json` — global ranked list of top-500 risk candidates (raw susc scores), used for subset-run safety and future UI features
- `web/data/manifest.json` — tile registry consumed by web app
- `web/data/risk_points.geojson` — top-20 globally ranked flood risk points

## Susceptibility model weights (D19 — HAND added, research-weighted)
- **HAND (height above nearest drainage): 25%** (inverted — near the channel → high risk). The #1 flood-literature factor. Per-tile cut (edge-truncated); whole-mosaic routing is the upgrade.
- TWI (topographic wetness index): 20%
- Elevation: 15% (inverted — low elevation → high risk)
- Slope: 15% (inverted — flat terrain → high risk)
- Plan curvature: 10%
- 3D canopy interception: 7.5% (inverted)
- NDVI health: 7.5% (inverted)
- Terrain roughness: dropped (near-zero signal). Land-cover/imperviousness (~5%): still pending.

Weights + factor wiring live in `SUSC_WEIGHTS` / `FACTOR_KEYS` in `pipeline.py`; HAND in
`kernels.hand_grid` (`STREAM_AREA_M2` threshold). Weights follow the flood-literature
consensus (HANDOFF.md). History: pre-D17 (TWI 40 / canopy 25 / NDVI 15 / curv 15 / rough 5)
inverted alpine heatmaps; D17 added elevation+slope and demoted veg; D19 added HAND and
pulled TWI back from its inflated 30% stand-in. See DECISIONS.md D17, D19.

## Coastal SLR mode (D20)
Koper has a separate coastal "bathtub" overlay for +0.5 m, +1.0 m, and +2.0 m sea-level scenarios. This is distinct from riverine susceptibility: a land cell is shaded only when its DTM elevation is below the scenario and it connects, within the same tile, to mapped sea/no-data cells. Sea/no-data remains transparent. The web app exposes this as the **Coastal Inundation** layer with a scenario selector.

Caveat: this is first-order screening, not coastal hydraulics. It ignores surge, waves, drainage, defenses, groundwater, and cross-tile connectivity. A stitched Koper DEM should replace the per-tile connection test when higher credibility is needed.

## Risk-point selection (D19)
`risk_points.geojson` is the global top-20 by raw `susc`, de-duplicated at `SEP_M` (50 m)
and **capped at `REGION_CAP` (7) per CDN region** — per-region normalisation makes scores
non-cross-comparable, so without the cap one region's largest flat-low patch (Koper port)
monopolised the list. Capped split is balanced (Savinja 6 / Koper 7 / Ljubljana 7), Savinja
flood valley at #1.

## Per-region normalisation (calibration.json, D17)
Each factor is normalised against a FIXED [lo, hi] range (p2–p98) derived **per CDN
region**, not globally — Ljubljana basin (285–417 m), alpine Savinja (402–1269 m), and
coastal Koper (~0 m) have disjoint elevation regimes, so a single ruler is meaningless.
`calibration.json` is `model_version: 2` with a `regions` dict keyed by region slug, each
holding its own `constants` + `display`. Derive with `python pipeline.py --calibrate`
(all regions) or `--calibrate --region 01-koper` (one region, merges + preserves others).
Each tile's region comes from `.tile_region_cache.json`. Calibration samples only
ground-covered, finite cells (D18) so sea / no-data doesn't skew ranges. The file also
stores a dataset fingerprint (tile name + size); normal runs warn if `data/` changed.
Missing/region-less → DEFAULT_CONSTANTS fallback with a warning. See DECISIONS.md D15, D17, D18.

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
