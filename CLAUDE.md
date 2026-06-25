# Slovenia LiDAR Floodmap — Project Context

> **Decision log:** All significant technical and data decisions are recorded in [`DECISIONS.md`](DECISIONS.md) with rationale and reversal instructions. Read it before making architectural changes and append to it after making new decisions.

## What this is
A flood & forest risk analysis web app built on Slovenia's national CLSS LiDAR dataset.
Four-factor susceptibility model rendered as MapLibre GL image overlays on a dark basemap.

## Stack
- **Frontend**: MapLibre GL JS v4.7.1, OpenFreeMap dark basemap, vanilla JS
- **Pipeline**: Python (`pipeline.py`) — reads `.laz` files, outputs PNGs + manifest
- **Hosting**: GitHub Pages (`web/` directory), deployed via GitHub Actions on push to main
- **Local dev**: `python -m http.server 8765 --directory web`

## Data
- **Source**: Flycom CLSS S3 CDN — `https://assets.flycom.si/clss/raw/<region>/zls/gkot/GKOT_E_N.laz`
- **CRS**: EPSG:3794 (Slovene national grid), tile coords = km (e.g. `460_100` = easting 460km, northing 100km)
- **Current dataset**: 81 tiles — contiguous 9×9 block covering Ljubljana (456–464 E × 96–104 N)
- **LAZ files**: stored in `data/` (gitignored), ~170–200 MB each
- **Total on disk**: ~15 GB

## Key scripts
| Script | Purpose |
|---|---|
| `pipeline.py` | Process all `GKOT_*.laz` in `data/`, write PNGs + manifest. Run `python pipeline.py` (all) or `python pipeline.py 460_100 461_100` (subset). Subset runs MERGE into existing manifest — does not overwrite. |
| `download_tiles.py` | Download tiles from CDN. `--center E N --radius R` for grid, `--bbox`, or `--tiles`. `--pipeline` flag runs pipeline after download. `--dry-run` checks availability. |

## Pipeline outputs (per tile)
- `web/data/tiles/<name>/susceptibility.png` — composite flood risk (RdYlBu_r)
- `web/data/tiles/<name>/ndvi.png` — forest health (RdYlGn, percentile-stretched)
- `web/data/tiles/<name>/classification.png` — land cover classes
- `web/data/manifest.json` — tile registry consumed by web app
- `web/data/risk_points.geojson` — top-20 globally ranked flood risk points

## Susceptibility model weights
- TWI (topographic wetness index): 40%
- 3D canopy interception: 25%
- NDVI health: 15%
- Plan curvature: 15%
- Terrain roughness: 5%

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
