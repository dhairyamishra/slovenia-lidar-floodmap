# Hydraulic-Validity LiDAR Expansion

**Batch:** `central-validity-2026-07-13`

**Status:** Complete and verified.

## Purpose

Expand the sparse CLSS coverage visible around Ljubljana using the official DRSV
hydraulic-study validity geometry as the selection signal. This is a data-coverage
expansion, not a claim that every selected tile floods. The official validity
geometry says where absence from an official hazard polygon can be interpreted;
it is not itself a flood extent.

## Selection rule

The committed EPSG:3794 `ikpn_validity` geometry was intersected with aligned
5 km × 5 km GKOT chunks. Chunks were prioritized for:

1. material official-validity overlap;
2. connection to the existing 10 km × 10 km Ljubljana block;
3. west, north, and northeast coverage visible in the supplied map review; and
4. a bounded first batch that fits available disk and processing capacity.

All 250 tile positions were probed against the Flycom CLSS CDN before download.
Five positions in `460_105` already existed, leaving **245 new LAZ files**.
All 245 completed successfully (50.91 GB), all 250 selected LAZ headers open,
and no partial transfer files remain. The complete local inventory is 391 tiles.

## Selected chunks

| Chunk origin | Tile range | Validity overlap | CDN region | New tiles |
|---|---|---:|---|---:|
| `445_90` | E445–449, N90–94 | 18.85 km² | `05-ljubljana` | 25 |
| `450_90` | E450–454, N90–94 | 20.10 km² | `05-ljubljana` | 25 |
| `450_95` | E450–454, N95–99 | 9.95 km² | `05-ljubljana` | 25 |
| `460_105` | E460–464, N105–109 | 8.81 km² | `05-ljubljana` | 20 |
| `460_110` | E460–464, N110–114 | 4.92 km² | `05-ljubljana` | 25 |
| `460_115` | E460–464, N115–119 | 12.57 km² | `08-kamnik` | 25 |
| `460_120` | E460–464, N120–124 | 14.10 km² | `08-kamnik` | 25 |
| `465_105` | E465–469, N105–109 | 19.16 km² | `05-ljubljana` | 25 |
| `465_110` | E465–469, N110–114 | 15.62 km² | `05-ljubljana` | 25 |
| `470_110` | E470–474, N110–114 | 14.66 km² | `05-ljubljana` | 25 |
| **Total** | 250 positions | **138.74 km²** | two regions | **245** |

## Recalculation contract

After download:

1. verify all expected LAZ files and nonzero sizes;
2. rerun per-region calibration for the full expanded dataset;
3. rerun the canonical LiDAR pipeline for all local tiles;
4. reacquire official DRSV layers using the expanded regional envelopes;
5. rebuild official web assets and the categorical Q100/D19 comparison;
6. rerun diagnostics and validation checks; and
7. browser-check the expanded map before committing.

## Completed results

- Recalibrated the full 391-tile dataset by CDN region: 295 Ljubljana, 75
  Kamnik/Savinja, and 21 Koper tiles. The GKOT inventory is 91.74 GB decimal.
- Re-ran the canonical pipeline across all 391 tiles in 1,296 seconds with three
  workers. It rebuilt all terrain/forest/classification images, 500 review
  candidates, 20 region-capped review points, and the manifest.
- Refreshed the critical official source layers for the enlarged envelopes: 46
  IKPN validity features and 3,833 IKPN Q100 polygons.
- Rebuilt schema-v2 categorical comparison images and click indices for every
  tile. Comparable area is 160.414 km2 in Ljubljana (99.71% of validity with D19
  data) and 29.790 km2 in Kamnik/Savinja (99.86%).
- Ljubljana comparison shares are 31.79% official-only, 11.59% D19-only, 7.53%
  both, and 49.09% neither. Kamnik/Savinja shares are 20.20%, 17.64%, 12.99%,
  and 49.18%, respectively. These are area shares, not probabilities.
- Re-ran the frozen evaluation without changing its grids or spatial split.
  D19 remains rejected (ROC-AUC 0.5690; AP 0.3791); HAND-only remains stronger
  (ROC-AUC 0.7049; AP 0.5123).
- Updated the frontend to register hidden per-tile rasters lazily, avoiding an
  initial request fan-out across 391 tiles.

The DRSV service repeatedly disconnected while paging the ancillary IKRPN
low-risk class. This did not affect the refreshed validity/Q100 comparison.
`download_validation.py` now supports bounded spatial query cells to reduce
fragile deep offsets; the critical validity and Q100 acquisition records were
successfully refreshed with that path.

The frozen evaluation rasters and spatial test contract remain unchanged. Public
comparison tiles are regenerated from the current official source geometries,
not by expanding or reshaping the locked evaluation set.

## Limits

- The selected chunks cover land around official study corridors; they do not
  imply hazard, probability, depth, or observed August 2023 flooding.
- This batch does not attempt national coverage or bridge all the way to the
  separate existing Savinja 5 km × 5 km block.
- Mosaic hydrology remains defined only for its existing frozen Ljubljana and
  Savinja research mosaics. New public tiles initially use the canonical
  per-tile D19 baseline until a separately reviewed expanded mosaic is designed.
