# Slovenia CLSS LiDAR — Flood, Coastal & Forest Risk

An interactive web map overlaying riverine flood susceptibility, Koper coastal sea-level-rise exposure, and forest-NDVI analysis derived from Slovenia's national airborne LiDAR dataset (CLSS — *Ciklično lasersko skeniranje*) onto a dark basemap styled after the national viewer at [clss.si](https://clss.si).

**Live demo →** https://dhairyamishra.github.io/slovenia-lidar-floodmap/

## What it shows

| Layer | Description |
|---|---|
| Flood Susceptibility | Weighted composite (HAND 25 % + TWI 20 % + elevation 15 % + slope 15 % + plan curvature 10 % + canopy interception 7.5 % + NDVI health 7.5 %) — blue (low) → red (high) |
| Coastal Inundation | Koper-only bathtub sea-level-rise screen for +0.5 m / +1.0 m / +2.0 m scenarios; shades connected low-lying land, leaves sea/no-data transparent |
| Forest NDVI | Per-cell NDVI from 16-bit NIR/R channels — red (stressed) → green (healthy) |
| Land Classification | Ground, low/med/high vegetation, building returns |
| Risk Markers | Top-20 highest-susceptibility cells (capped at 7 per CDN region so per-region-normalised scores stay comparable), shown as numbered pins |

## Dataset

- **146 tiles across 3 CDN regions** — 100 over Ljubljana (`05-ljubljana`, basin), 25 over the Savinja valley (`08-kamnik`, alpine riverine), 21 over Koper (`01-koper`, coastal). Tile coords are EPSG:3794 kilometres (e.g. `460_100` = easting 460 km, northing 100 km).
- Each region is calibrated independently (see below) because their elevation regimes are disjoint.
- Koper includes both the riverine baseline and a separate coastal sea-level-rise overlay. The coastal layer is a first-order screening product, not a hydraulic storm-surge model.
- Source: Flycom CLSS S3 CDN — `https://assets.flycom.si/clss/raw/<region>/zls/gkot/GKOT_E_N.laz`.
- Raw `.laz` tiles (~170–800 MB each — alpine/coastal tiles are denser — ~50 GB total) live in `data/` and are **gitignored**. The small derived overlays in `web/data/` are committed and deployed.

## Run locally

```bash
python -m http.server 8765 --directory web
# open http://localhost:8765
```

## Regenerate analysis

The pipeline reads `GKOT_*.laz` from `data/` and writes all `web/data/` assets.

```bash
# 1. Download tiles from the CDN (square grid around a centre, a bbox, or a list)
python download_tiles.py --center 460 100 --radius 4        # 9×9 Ljubljana block

# 2. Calibrate the global normalisation constants — run ONCE per dataset
python pipeline.py --calibrate

# 3. Process every tile → PNGs, manifest, candidates, risk points
python pipeline.py
# or a subset (merges into the existing manifest + global candidates):
python pipeline.py 460_100 461_100
```

Requires: `laspy`, `lazrs`, `numpy`, `scipy`, `pyproj`, `Pillow`, `numba` (the hot DTM/D8/HAND loops in `kernels.py` are Numba-JIT'd). Tiles fan out across processes — `--workers N` overrides the RAM-bound default.

### Why calibration?

Each susceptibility factor is normalised against a **fixed [p2, p98] range derived per CDN region** (not re-curved per tile) so risk scores are comparable within a region. Regions are calibrated separately because Ljubljana basin, alpine Savinja, and coastal Koper have disjoint elevation regimes — a single ruler is meaningless. `pipeline.py --calibrate` derives all regions (or `--calibrate --region 01-koper` for one, merging into the rest) and stores them in `calibration.json` (`model_version: 2`, a `regions` dict) along with a dataset fingerprint. Normal runs warn if `data/` has changed and a recalibration is due. See [`DECISIONS.md`](DECISIONS.md) D15/D17/D18.

## Pipeline outputs

| Path | Description |
|---|---|
| `web/data/tiles/<name>/susceptibility.png` | Composite flood-risk overlay (RdYlBu_r) |
| `web/data/tiles/<name>/coastal_slr_0_5m.png` etc. | Koper-only coastal inundation overlays for +0.5 m, +1.0 m, +2.0 m sea-level scenarios |
| `web/data/tiles/<name>/ndvi.png` | Forest-health NDVI (RdYlGn, percentile-stretched) |
| `web/data/tiles/<name>/classification.png` | Land-cover classes |
| `web/data/manifest.json` | Tile registry (bounds + file paths) consumed by the web app |
| `web/data/candidates.json` | Global ranked list of top-500 risk candidates |
| `web/data/risk_points.geojson` | Top-20 flood-risk points (de-duplicated at 50 m, capped at 7 per CDN region) |
| `calibration.json` | Per-region normalisation constants + dataset fingerprint |

## Scripts

| Script | Purpose |
|---|---|
| `pipeline.py` | **Canonical pipeline.** Processes all `GKOT_*.laz` → riverine PNGs, Koper coastal scenario PNGs, manifest, candidates, and risk points. Supports subset runs and `--calibrate`. |
| `download_tiles.py` | Downloads CLSS GKOT tiles from the CDN with region auto-discovery and a probe cache. `--center/--radius`, `--bbox`, `--tiles`, `--dry-run`, `--pipeline`. |
| `kernels.py` | Numba `@njit(cache=True)` hot loops — DTM grouped-min, D8 accumulation, HAND grid — bit-identical to the original pure-Python loops but ~70–150× faster. |
| `bench_kernels.py` | Correctness + speed gate: asserts the Numba kernels match the originals on a real tile. `python bench_kernels.py [TILE_ID]`. |

<details>
<summary>Legacy / exploratory scripts (early single-tile work, superseded by <code>pipeline.py</code>)</summary>

| Script | Purpose |
|---|---|
| `flood_susceptibility.py` | Original single-tile four-factor model + voxel cube |
| `export_web_assets.py` | Original single-tile web-asset exporter |
| `gkot_ndvi.py` | Per-point NDVI from 16-bit colour |
| `flood_risk.py` | Channel-network logjam/overhang risk |
| `probe_affordances.py` | Probes hidden LiDAR data properties |
| `inspect_data.py` | Profiles data files → `DATA_SAMPLES.md` |

</details>

## Deployment

The `web/` directory is published to GitHub Pages on every push to `main` via `.github/workflows/deploy-pages.yml`. No backend required.

## Project context

- [`CLAUDE.md`](CLAUDE.md) — full technical context (stack, data, pipeline, applied fixes).
- [`DECISIONS.md`](DECISIONS.md) — chronological decision log with rationale and reversal notes.

## Verified Maintenance Notes

Reviewed on 2026-07-09 (verified 146-tile / 3-region dataset, D19 HAND weight model, D20 Koper coastal overlays, and Numba kernels against the code).

This repository is the Git-backed version of the Slovenia LiDAR floodmap work.
It has the canonical multi-tile pipeline (`pipeline.py`), downloader
(`download_tiles.py`), calibration state (`calibration.json`), static web app
(`web/`), and GitHub Pages workflow configuration.

Current top-level implementation files:

| Path | Purpose |
|---|---|
| `pipeline.py` | Main calibrated multi-tile processing pipeline. |
| `kernels.py` | Shared numerical kernels used by the pipeline. |
| `download_tiles.py` | CLSS tile downloader and region probing helper. |
| `bench_kernels.py` | Kernel benchmark script. |
| `web/index.html` | Static app shell. |
| `web/app.js` | MapLibre map, overlays, controls, and risk markers. |
| `web/style.css` | Web app styling. |
| `.github/` | Deployment workflow configuration. |

Raw CLSS source data remains local under `data/` and should stay out of Git.
Derived web assets under `web/data/` are the deployable outputs consumed by the
static app.

## Data credit

Raw LiDAR data: **Geodetska uprava RS** (CLSS programme), distributed under the Open Government Licence of the Republic of Slovenia. Tiles served via the Flycom CLSS CDN.
