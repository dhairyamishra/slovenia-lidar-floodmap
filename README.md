# Slovenia CLSS LiDAR — Flood Susceptibility & Forest Health Demo

An interactive web map overlaying flood-susceptibility and forest-NDVI analysis derived from Slovenia's national airborne LiDAR dataset (CLSS — *Ciklično lasersko skeniranje*) onto a dark basemap styled after the national viewer at [clss.si](https://clss.si).

**Live demo →** https://dhairyamishra.github.io/slovenia-lidar-floodmap/

## What it shows

| Layer | Description |
|---|---|
| Flood Susceptibility | Four-factor composite (TWI 40 % + canopy interception 25 % + NDVI health 15 % + plan curvature 15 % + terrain roughness 5 %) — blue (low) → red (high) |
| Forest NDVI | Per-point NDVI from 16-bit NIR/R channels — red (stressed) → green (healthy) |
| Land Classification | Ground, low/med/high vegetation, building returns |
| Risk Markers | Top-20 highest-susceptibility cells, shown as numbered pins |

Data source: tile `GKOT_478_73.laz` — 23.6 M points, Z range 418–847 m, EPSG:3794 (Slovenia 1996 / Slovene National Grid), covering the area around lon 14.723°, lat 45.801°.

## Run locally

```bash
python -m http.server 8765 --directory web
# open http://localhost:8765
```

## Regenerate web assets

```bash
python export_web_assets.py
```

Requires: `laspy`, `lazrs`, `numpy`, `scipy`, `pyproj`, `Pillow`

Raw LiDAR tiles (`data/`) are sourced from Geodetska uprava RS and are not included in this repository due to size.

## Pipeline scripts

| Script | Purpose |
|---|---|
| `flood_susceptibility.py` | Four-factor susceptibility model + voxel cube |
| `export_web_assets.py` | Reproject + export `web/data/` (PNGs, GeoJSON, bounds) |
| `gkot_ndvi.py` | Per-point NDVI from 16-bit colour |
| `flood_risk.py` | Channel-network logjam/overhang risk |
| `probe_affordances.py` | Probes hidden LiDAR data properties |
| `inspect_data.py` | Profiles all data files → `DATA_SAMPLES.md` |

## Data credit

Raw LiDAR data: **Geodetska uprava RS** (CLSS programme), distributed under the Open Government Licence of the Republic of Slovenia.
