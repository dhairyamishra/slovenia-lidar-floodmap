# Handoff - Slovenia CLSS LiDAR Flood & Coastal Demo

**Status:** The app is a 146-tile, 3-region static MapLibre demo with D19 riverine susceptibility and D20 Koper coastal sea-level-rise overlays implemented. The active thread is now validation and credibility: compare against ARSO / Aug-2023 flood evidence, then improve per-tile approximations with mosaic-level routing.

**Goal:** A polished, honest screening tool for Aleks / sledilnik.org that shows where detailed flood/coastal investigation should start. It is not a hydraulic model.

> Authoritative context: `AGENTS.md`, `CLAUDE.md`, `DECISIONS.md`, and `PLAN.md`. This handoff is the current snapshot plus the latest implementation notes.

## Context

This repository builds an interactive web map from Slovenia's CLSS airborne LiDAR data. `pipeline.py` reads local `data/GKOT_*.laz` files, computes terrain/vegetation factors, exports PNG overlays under `web/data/tiles/<tile>/`, and writes `web/data/manifest.json`, `web/data/candidates.json`, and `web/data/risk_points.geojson` for the static web app.

The project started as a Ljubljana flood/forest demo. Aleks then provided two validation/extension sites: the Savinja valley flood area from Aug 2023 and Koper for sea-level-rise exposure. The dataset now covers all three.

Live site: https://dhairyamishra.github.io/slovenia-lidar-floodmap/

## Current State

Latest known commits before this handoff:

- `770a7b5` - docs: update README
- `1bccc73` - Add HAND flood factor (D19) - research-weighted model
- `f9281d7` - Add Koper coastal baseline (21 tiles) + D18 no-data mask
- `c6ea058` - Record D17: model redesign + per-region calibration
- `3c5ec01` - Update calibration and risk assessment data

Current uncommitted work in this session:

- D20 coastal bathtub sea-level-rise mode added to `pipeline.py`.
- Coastal UI controls added to `web/app.js`, `web/index.html`, and `web/style.css`.
- Koper tiles regenerated; `web/data/manifest.json` now has 21 coastal-enabled tiles and 63 coastal scenario PNGs.
- `DECISIONS.md` now records D20.
- `PLAN.md` checklist updated so completed D16-D20 work is not shown as pending.
- `HANDOFF.md` replaced with this current handoff.
- Existing pre-session local changes remain: `README.md` was already modified and `AGENTS.md` was untracked before this session. Do not assume those are ours.

Verified facts:

- `web/data/manifest.json` still has `tile_count: 146`.
- `.tile_region_cache.json` splits the data as 100 Ljubljana (`05-ljubljana`), 25 Savinja/Kamnik (`08-kamnik`), and 21 Koper (`01-koper`).
- Coastal export count: 21 Koper tiles x 3 scenarios = 63 `coastal_slr_*.png` files.
- `400_46` coastal visible pixels grow with scenario: about 58,895 at +0.5 m, 71,463 at +1.0 m, 127,669 at +2.0 m.
- `400_48` is all sea/no-data and remains fully transparent for coastal scenarios.
- Static checks passed: `py_compile` for `pipeline.py` / `kernels.py`, and `node --check web/app.js`.
- Local browser smoke test confirmed the new "Coastal Inundation" control and scenario selector are present.

## Method

Current riverine model (D19):

- HAND: 25%, inverted - low height above drainage is high risk.
- TWI: 20%.
- Elevation: 15%, inverted.
- Slope: 15%, inverted.
- Plan curvature: 10%.
- Canopy interception: 7.5%, inverted.
- NDVI: 7.5%, inverted.
- Roughness: computed but weight 0.

Each factor is normalised by CDN region, not globally. `calibration.json` is `model_version: 2` and has one region block each for Ljubljana, Kamnik/Savinja, and Koper.

Risk points:

- Global candidate pool is capped at 500.
- Final top-20 is deduplicated at 50 m.
- `REGION_CAP = 7` prevents one per-region-normalised region from monopolising the list. Current split is balanced by design, not because cross-region scores are absolute probabilities.

Coastal D20 model:

- Applies only to CDN region `01-koper`.
- Outputs three scenario masks per Koper tile:
  - `coastal_slr_0_5m.png`
  - `coastal_slr_1_0m.png`
  - `coastal_slr_2_0m.png`
- A land cell is shaded when its DTM elevation is below the scenario and it connects, within that tile, to sea/no-data cells.
- Sea/no-data remains transparent. The overlay only shades exposed land.

Why D20 is separate:

Koper sea-level rise is a coastal exposure mechanism. The riverine susceptibility factors can identify low-flat terrain, but they cannot honestly answer "which land is below +1 m sea level?" Keeping this as a separate overlay makes the limitation obvious and demo-friendly.

## Active Thread

The main open work is validation and model credibility.

1. ARSO / official flood-hazard validation is still pending.
   The model is literature-informed but not calibrated against observed flood footprints. This is the biggest credibility step for sledilnik-style technical stakeholders.

2. Savinja Aug-2023 validation is pending.
   The D17/D19 redesign was motivated by Aleks's Savinja location. The model now highlights the valley floor, but it still needs comparison against a documented footprint or hazard layer.

3. Per-tile HAND is still approximate.
   D19 computes HAND inside each 1 km tile. Drainage paths that should cross tile boundaries terminate at tile edges, so channels are local. Whole-region / mosaic routing is the real upgrade.

4. D20 coastal connectivity is also per-tile.
   Coastal inundation only propagates from sea/no-data cells within the same tile. That avoids false filling of isolated inland depressions, but it misses cross-tile connectivity. A stitched Koper DEM is the upgrade.

5. ERA5-Land hydroclimate is proposed, not implemented.
   Aleks shared a Copernicus article about linking landslide activity and ERA5 hydroclimatic models. Useful direction: combine static LiDAR susceptibility ("where") with ERA5-Land soil moisture / rolling water-input anomalies ("when"). Start with an Aug-2023 Savinja hindcast.

Recommended entry point:

Start with validation. Specifically, find or ingest ARSO flood-hazard zones / Aug-2023 Savinja footprint and compare against the current D19 risk layer. That gives the project credibility and tells whether mosaic HAND or ERA5 should be the next engineering investment.

## Gotchas

- `HANDOFF.md` and `PLAN.md` were stale before this session. Use `DECISIONS.md` as the decision source of truth.
- Raw `.laz` files in `data/` are gitignored and large, about 50 GB total.
- If you delete LAZ/PNG tiles manually, also purge them from `web/data/manifest.json`; subset runs merge and will keep old entries.
- Pipeline subset runs update global candidates by removing stale entries for reprocessed tiles and merging fresh candidates.
- `manifest.json - N tile(s)` in pipeline output reports total merged manifest count, while earlier docs warned about processed-run count; inspect the JSON directly if in doubt.
- Long pipeline/calibration runs have previously died when the machine slept. Keep the machine awake.
- Browser preview may not fully verify MapLibre if external basemap/sprite requests fail. DOM/static checks are still useful.
- In this session, the desktop shell had no system `python`; the bundled runtime lacked SciPy/laspy/numba. Missing packages were installed into `C:\tmp\slovenia_pydeps` and the pipeline was run with `PYTHONPATH=C:\tmp\slovenia_pydeps` under escalation.
- New Matplotlib removed `matplotlib.cm.get_cmap`; `pipeline.py` now uses `matplotlib.colormaps[...]` with a fallback.

## File Map

| Path | Purpose |
|---|---|
| `pipeline.py` | Canonical LiDAR pipeline; D19 riverine model; D20 coastal export. |
| `kernels.py` | Numba kernels for DTM min-grid, D8 accumulation, HAND. |
| `download_tiles.py` | CLSS CDN downloader and tile-region cache helper. |
| `calibration.json` | Per-region p2-p98 factor/display calibration. |
| `.tile_region_cache.json` | Tile ID to CDN region mapping. |
| `web/app.js` | MapLibre app, raster layers, risk markers, coastal scenario UI. |
| `web/index.html` | Static app shell and layer panel. |
| `web/style.css` | App styling. |
| `web/data/manifest.json` | Tile registry consumed by the app. |
| `web/data/tiles/<tile>/coastal_slr_*.png` | D20 Koper coastal scenario overlays. |
| `web/data/risk_points.geojson` | Top-20 balanced risk markers. |
| `DECISIONS.md` | Chronological decision log; append here for significant changes. |
| `PLAN.md` | Multi-region execution plan and current open checklist. |

## How To Run

Local web app:

```powershell
python -m http.server 8765 --directory web
```

If `python` is unavailable in this desktop environment, use the bundled runtime:

```powershell
C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m http.server 8765 --directory web
```

Process all tiles:

```powershell
python pipeline.py
```

Process only Koper tiles with the temporary dependency target used in this session:

```powershell
$env:PYTHONPATH='C:\tmp\slovenia_pydeps'
C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe pipeline.py 398_44 398_45 398_46 399_44 399_45 399_46 400_44 400_45 400_46 400_47 400_48 401_44 401_45 401_46 401_47 401_48 402_44 402_45 402_46 402_47 402_48 --workers 3
```

Calibrate:

```powershell
python pipeline.py --calibrate
python pipeline.py --calibrate --region 01-koper
```

## References

- Live demo: https://dhairyamishra.github.io/slovenia-lidar-floodmap/
- CLSS / source CDN pattern: `https://assets.flycom.si/clss/raw/<region>/zls/gkot/GKOT_E_N.laz`
- Copernicus article from Aleks: https://climate.copernicus.eu/linking-landslide-activity-and-era-5-hydroclimatic-models-pro-active-infrastructure-management
