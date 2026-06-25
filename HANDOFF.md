# Handoff — Slovenia CLSS LiDAR Flood & Forest Demo

**Status:** Built, committed, and deployed to GitHub Pages. Multi-tile pipeline working; risk-point ranking corrected and globally normalised. · **Goal:** A polished, static, no-backend web app that overlays flood-susceptibility and forest-NDVI analysis (derived from Slovenia's national CLSS LiDAR) on an interactive dark map, to demo to a stakeholder named Aleks.

> For the authoritative, continuously-maintained context read [`CLAUDE.md`](CLAUDE.md) and the decision log [`DECISIONS.md`](DECISIONS.md). This handoff is a higher-level snapshot.

## Context

This project uses Slovenia's national airborne LiDAR dataset (CLSS — *Ciklično lasersko skeniranje*, run by Geodetska uprava RS) to build flood-risk analytics that map onto a real national priority: post-2023-flood reconstruction. A Python pipeline computes a four-factor flood-susceptibility model and per-cell forest NDVI from LiDAR point clouds, then exports georeferenced raster overlays + ranked risk points for a MapLibre web viewer styled like the national viewer at <https://clss.si>.

## Current state

Verified working:

- **`pipeline.py` processes the full 81-tile dataset** and writes all `web/data/` assets (per-tile PNGs, `manifest.json`, `candidates.json`, `risk_points.geojson`).
- Web app loads in a real browser: dark basemap (OpenFreeMap), susceptibility overlay (blue→red), NDVI overlay (red→green), land classification, side panel with toggles + opacity sliders, geo-registration confirmed.
- **Risk markers** are DOM markers (`maplibregl.Marker`) — numbered pins, attached on map creation. See "Technical notes" for why DOM not GeoJSON.
- **Git repo exists, committed, and auto-deploys** to GitHub Pages on push to `main` (`.github/workflows/deploy-pages.yml`). Live: https://dhairyamishra.github.io/slovenia-lidar-floodmap/

## Dataset

- **81 tiles**, contiguous **9 × 9 km block over Ljubljana** (EPSG:3794 easting 456–464 km × northing 96–104 km). WGS84 ≈ lon 14.431–14.548°, lat 46.002–46.084°.
- All data is **EPSG:3794** (Slovenia 1996 / Slovene National Grid); web overlays reproject to EPSG:4326 via `pyproj`.
- Raw `.laz` (~15 GB) lives in `data/` and is **gitignored**; the small `web/data/` overlays are committed.

## Method

- Flood susceptibility = four factors: **TWI 40 % + 3D canopy interception 25 % + NDVI health 15 % + plan curvature 15 % + terrain roughness 5 %**. DTM is a pseudo-DTM from GKOT ground returns (class 2) at 2 m, with D8 flow accumulation for TWI. Canopy uses a 2 m voxel grid.
- **Global normalisation (D15):** each factor is scaled against a fixed dataset-wide range stored in `calibration.json` (derived by `python pipeline.py --calibrate`), so scores are comparable across tiles rather than re-curved per tile.
- **Risk points:** `risk_points.geojson` holds the **top-20 globally-ranked** cells, selected from `web/data/candidates.json` (top-500 pool, deduplicated to ≥50 m spacing). Scores now vary genuinely across tiles — the earlier all-`1.0` artefact (caused by per-tile renormalisation) is fixed (D13, D15).

## Recommended next steps / ideas

These are candidate improvements discussed for raising the tool's credibility and impact (none committed yet):

1. **Validate against ARSO official flood-hazard zones** (EU Floods Directive) as an overlay — does the model track documented reality?
2. **Add HAND (Height Above Nearest Drainage)** as a factor — physically the strongest simple flood indicator, computable from the existing DTM + flow accumulation.
3. **Urban vs. rural differentiation** using the building classification, to reduce false positives in dense urban areas.
4. **Performance:** multiprocessing across tiles + Numba JIT on the D8 loop would cut a full run from ~27 min to a few minutes.

Framing for Aleks: this is a **terrain + vegetation susceptibility screening tool** (spatial triage — "where to look first"), not a hydraulic flood model. That positioning is honest and defensible.

## Technical notes & gotchas

- **The `preview_*` (Claude Preview) tooling cannot fully verify this app.** The headless preview browser can't reach the OpenFreeMap basemap CDN, so `map.on('load')` never fires and screenshot/promise-based `preview_eval` calls time out. Verify in a **real browser** or via non-blocking DOM checks (`document.querySelectorAll('.risk-marker').length`).
- **Why markers are DOM, not a GeoJSON layer:** the original GeoJSON circle layer relied on MapLibre's vector-tile worker, which wasn't reliably indexing the inline source — circles silently never drew. DOM markers render immediately and don't slip during pan (see D02, D03). Code: `addRiskPoints()` / `setRiskVisible()` in `web/app.js`; `.risk-marker` in `web/style.css`.
- **Manifest merge on subset runs (D06, D12):** subset runs merge into the existing `manifest.json` and global `candidates.json`. Deleting tiles manually requires purging their manifest entry — see "Common pitfalls" in `CLAUDE.md`.
- The export flips rasters vertically (`np.flipud`) because numpy row-0 is south but image row-0 is north. MapLibre `ImageSource` corners are ordered [TL, TR, BR, BL] as `[lon, lat]`.

## File map

| Path | Purpose |
|---|---|
| `pipeline.py` | Canonical multi-tile pipeline (factors → PNGs + manifest + candidates + risk points; `--calibrate`) |
| `download_tiles.py` | CDN downloader with region auto-discovery + cache |
| `calibration.json` | Global normalisation constants + dataset fingerprint (created by `--calibrate`) |
| `web/index.html` | App shell — MapLibre CDN, topbar, side panel |
| `web/style.css` | Dark theme + `.risk-marker` styles |
| `web/app.js` | MapLibre init, per-tile overlays, DOM risk markers, controls |
| `web/data/` | Deployable assets (committed): per-tile PNGs, `manifest.json`, `candidates.json`, `risk_points.geojson` |
| `data/` | Raw CLSS LiDAR (large — gitignored) |
| `CLAUDE.md` / `DECISIONS.md` | Authoritative context + decision log |
| Legacy scripts | `flood_susceptibility.py`, `export_web_assets.py`, `gkot_ndvi.py`, `flood_risk.py`, `probe_affordances.py`, `inspect_data.py` — early single-tile/exploratory work, superseded by `pipeline.py` |

## How to run locally

```bash
python -m http.server 8765 --directory web
# then open http://localhost:8765
```

To regenerate analysis after changing the model: `python pipeline.py --calibrate` (once per dataset), then `python pipeline.py`. Requires `laspy`, `lazrs`, `numpy`, `scipy`, `pyproj`, `Pillow` (and `rasterio` for `inspect_data.py`).
