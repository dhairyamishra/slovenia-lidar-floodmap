# Slovenia CLSS LiDAR — Flood Susceptibility & Forest Health

An interactive web map overlaying flood-susceptibility and forest-NDVI analysis derived from Slovenia's national airborne LiDAR dataset (CLSS — *Ciklično lasersko skeniranje*) onto a dark basemap styled after the national viewer at [clss.si](https://clss.si).

**Live demo →** https://dhairyamishra.github.io/slovenia-lidar-floodmap/

## What it shows

| Layer | Description |
|---|---|
| Flood Susceptibility | Four-factor composite (TWI 40 % + canopy interception 25 % + NDVI health 15 % + plan curvature 15 % + terrain roughness 5 %) — blue (low) → red (high) |
| Forest NDVI | Per-cell NDVI from 16-bit NIR/R channels — red (stressed) → green (healthy) |
| Land Classification | Ground, low/med/high vegetation, building returns |
| Risk Markers | Top-20 globally-ranked highest-susceptibility cells, shown as numbered pins |

## Dataset

- **81 tiles** forming a contiguous **9 × 9 km block over Ljubljana** (EPSG:3794 easting 456–464 km × northing 96–104 km).
- WGS84 extent ≈ lon 14.431–14.548°, lat 46.002–46.084°.
- Source: Flycom CLSS S3 CDN — `https://assets.flycom.si/clss/raw/<region>/zls/gkot/GKOT_E_N.laz`.
- Raw `.laz` tiles (~170–200 MB each, ~15 GB total) live in `data/` and are **gitignored**. The small derived overlays in `web/data/` are committed and deployed.

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

Requires: `laspy`, `lazrs`, `numpy`, `scipy`, `pyproj`, `Pillow`

### Why calibration?

Each susceptibility factor is normalised against a **fixed dataset-wide range** (not re-curved per tile) so risk scores are comparable across tiles. `pipeline.py --calibrate` derives those ranges from a sample of all tiles and stores them in `calibration.json` along with a dataset fingerprint. Normal runs warn if `data/` has changed (tiles added / removed / re-downloaded) and a recalibration is due. See [`DECISIONS.md`](DECISIONS.md) D15.

## Pipeline outputs

| Path | Description |
|---|---|
| `web/data/tiles/<name>/susceptibility.png` | Composite flood-risk overlay (RdYlBu_r) |
| `web/data/tiles/<name>/ndvi.png` | Forest-health NDVI (RdYlGn, percentile-stretched) |
| `web/data/tiles/<name>/classification.png` | Land-cover classes |
| `web/data/manifest.json` | Tile registry (bounds + file paths) consumed by the web app |
| `web/data/candidates.json` | Global ranked list of top-500 risk candidates |
| `web/data/risk_points.geojson` | Top-20 globally-ranked flood-risk points |
| `calibration.json` | Global normalisation constants + dataset fingerprint |

## Scripts

| Script | Purpose |
|---|---|
| `pipeline.py` | **Canonical pipeline.** Processes all `GKOT_*.laz` → PNGs + manifest + candidates + risk points. Supports subset runs and `--calibrate`. |
| `download_tiles.py` | Downloads CLSS GKOT tiles from the CDN with region auto-discovery and a probe cache. `--center/--radius`, `--bbox`, `--tiles`, `--dry-run`, `--pipeline`. |

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

## Data credit

Raw LiDAR data: **Geodetska uprava RS** (CLSS programme), distributed under the Open Government Licence of the Republic of Slovenia. Tiles served via the Flycom CLSS CDN.
