# Handoff — Slovenia CLSS LiDAR Flood & Forest Demo

**Status:** Web demo is built and working; risk markers just fixed (DOM-marker rewrite). Not yet committed to git. · **Goal:** Ship a polished, static, no-backend web app that overlays flood-susceptibility and forest-NDVI analysis (derived from Slovenia's national CLSS LiDAR) on an interactive dark map, deployable to GitHub Pages, to demo to a stakeholder named Aleks.

## Context

This project uses Slovenia's national airborne LiDAR dataset (CLSS — *Ciklično lasersko skeniranje*, run by Geodetska uprava RS) to build flood-risk analytics that map onto a real, active national priority: the €2.3 B post-2023-flood reconstruction programme. A Python pipeline computes a four-factor flood-susceptibility model and per-point forest NDVI from a 23.6 M-point LiDAR tile, then exports georeferenced raster overlays + risk points for a MapLibre web viewer styled like the national viewer at <https://clss.si>.

"Done" for the current phase = the local web app cleanly shows the susceptibility overlay, the NDVI overlay, land classification, and the top-20 high-risk markers, then is committed to git and deployed to GitHub Pages so Aleks can open a public URL.

## Current state / what's been done

Verified working:

- Full Python analysis pipeline runs and produces all `output/` figures and all `web/data/` web assets.
- Web app loads in a real browser: dark basemap (OpenFreeMap), susceptibility overlay (blue→red), NDVI overlay (red→green), land classification, side panel with toggles + opacity sliders, geo-registration confirmed (village labels line up with the tile).
- **Risk markers were broken and are now fixed.** They were a GeoJSON circle layer that silently failed to tile; rewrote them as DOM markers (`maplibregl.Marker`) — 20 numbered white/red pins, attached immediately on map creation (not gated behind the basemap load). Verified via DOM inspection that all 20 markers attach. See "Technical notes & gotchas" for why this was hard to diagnose.

Not done yet:

- No git repository exists (`git init` not run).
- Not deployed.
- No `.gitignore` or `README.md`.

## Key facts & findings

Data (verified from `DATA_SAMPLES.md`):

- Hero tile is `data/GKOT_478_73.laz` — 23,600,610 points, Z range 418–847 m (429 m relief), 57.9% high vegetation (class 5). LAS Point Format 8 → has RGB **and** NIR, colours are 16-bit (uint16, 0–65535).
- All data is in **EPSG:3794** (Slovenia 1996 / Slovene National Grid). Web overlays reproject to EPSG:4326 via `pyproj`.
- Tile `478_73` covers EPSG:3794 [478000–479000, 73000–74000]; WGS84 bbox lon [14.71700, 14.72982], lat [45.79651, 45.80554]; centre lon 14.72341, lat 45.80103.
- The `data/` directory holds many CLSS products (GKOT/DMP/DMR/nDMP/PAS/POF/POFI tiles, .laz + .tif). These are large and should **not** be committed to git.

Method:

- Flood susceptibility = four factors: TWI 40% + 3D canopy interception 25% + NDVI health 15% + plan curvature 15% + terrain roughness 5%. DTM is a pseudo-DTM built from GKOT ground returns (class 2) at 2 m, with D8 flow accumulation for TWI. Voxel grid is 2 m × 2 m × 2 m (501×501×215 for this tile).
- `risk_points.geojson` holds the **top-20 ranked** high-risk cells. Note: every point's `risk_score` is `1.0` (they are all maxed), so ranking is the only differentiator — this is why the markers are now numbered pins rather than a colour ramp. If a varying score is wanted, `export_web_assets.py` must be changed to emit a normalized/continuous score.

Repo name (open decision — see below): leading recommendation is **`voxel-flood-slovenia`**.

## Recommended next step(s)

1. Confirm the repo name with the user (recommended `voxel-flood-slovenia`).
2. `git init` in the project root.
3. Add a `.gitignore` that excludes `data/` (large .laz/.tif), `output/` (regenerable figures), and Python cruft (`__pycache__/`, `*.pyc`, venv). Keep `web/data/` (small, deployable assets) tracked.
4. Write a short `README.md` (what it is, how to run `python -m http.server 8765 --directory web`, how the pipeline regenerates assets, data source/credit to Geodetska uprava RS).
5. Commit everything (Python pipeline + `web/`).
6. Deploy to GitHub Pages. Because the app lives in `web/`, either set Pages to serve from `/web` on the default branch, or move `web/` contents to repo root. URL will be `https://<user>.github.io/<repo>`.

## Open decisions / questions

- **Repo name** — recommended `voxel-flood-slovenia`; alternatives: `clss-flood-risk`, `slovenia-lidar-floodmap`, `terra-voxel`, `floodlens-si`.
- **Commit scope** — whole project (recommended, with `.gitignore` for `data/`) vs. only the deployable `web/` folder.
- **Risk score** — keep all-`1.0` top-20 ranking, or update `export_web_assets.py` to emit a genuinely varying score so the ranking has spread.
- **Deploy target** — GitHub Pages (planned) vs. Vercel (drag-drop `web/` also works).

## Technical notes & gotchas

- **The `preview_*` (Claude Preview) tooling cannot verify this app.** The headless preview browser can't reach the OpenFreeMap basemap CDN (`tiles.openfreemap.org`), so `map.on('load')` never fires there and `preview_screenshot` / promise-based `preview_eval` calls time out (~30 s). This burned a lot of time. Verify in a **real browser** instead, or via non-blocking DOM checks (`document.querySelectorAll('.risk-marker').length`). Do **not** trust `queryRenderedFeatures` / `querySourceFeatures` from the headless instance — load never completes there, so they read 0 regardless of correctness.
- **Why the markers are DOM, not a GeoJSON layer:** the original GeoJSON circle layer relied on MapLibre's vector-tile worker, which wasn't reliably indexing the inline source — circles silently never drew in the real browser. DOM markers (`maplibregl.Marker`) don't depend on the worker and render immediately. For a small fixed point set this is the more robust design. Relevant code: `RISK_POINTS` constant + `addRiskPoints()` + `setRiskVisible()` in `web/app.js`; `.risk-marker` styles in `web/style.css`.
- `web/app.js` exposes the map as `window._map` (added for debugging) — harmless to keep, or remove before final commit.
- The export pipeline flips rasters vertically (`np.flipud`) because numpy row-0 is south but image row-0 is north. MapLibre `ImageSource` corners are ordered [TL, TR, BR, BL] as `[lon, lat]`.

## File map

| Path | Purpose |
|---|---|
| `inspect_data.py` | Profiles all data files → `DATA_SAMPLES.md` |
| `gkot_ndvi.py` | Per-point NDVI pipeline (16-bit colour) → `output/` |
| `probe_affordances.py` | Probes hidden data properties (returns, overlap, shadows) |
| `flood_risk.py` | Channel-network logjam/overhang risk pipeline |
| `flood_susceptibility.py` | Full four-factor susceptibility model + voxel cube |
| `export_web_assets.py` | Reprojects + exports `web/data/` (PNGs, bounds.json, geojson) |
| `web/index.html` | App shell — MapLibre CDN, topbar, side panel |
| `web/style.css` | Dark theme + `.risk-marker` styles |
| `web/app.js` | MapLibre init, overlays, DOM risk markers, controls |
| `web/data/` | Deployable assets (keep in git): 3 PNG overlays, `bounds.json`, `risk_points.geojson` |
| `.claude/launch.json` | Preview config (`python -m http.server 8765 --directory web`) |
| `data/` | Raw CLSS LiDAR (large — exclude from git) |
| `output/` | Generated figures (regenerable — exclude from git) |

## How to run locally

```bash
python -m http.server 8765 --directory web
# then open http://localhost:8765
```

To regenerate web assets after changing the analysis:

```bash
python export_web_assets.py
```

Requires `laspy`, `lazrs`, `numpy`, `scipy`, `pyproj`, `Pillow` (and `rasterio` for `inspect_data.py`).
