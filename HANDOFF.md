# Handoff - Slovenia CLSS LiDAR Flood, Coastal & Hydroclimate Demo

**Status:** Phases 1–4 of `FLOOD_MODEL_REPLACEMENT_PLAN.md` are complete (D24–D27). Phase 5 candidates are implemented, but the D28 development selection gate failed. D29 removes the synthetic hydroclimate grid and triggered-candidate visualizations from the public app while retaining their calculations. D30 replaces the former Q100/D19 transparency blend with calculated, clickable comparison categories and exact area shares. D31 expands public LiDAR/reference coverage from 146 to 391 tiles while preserving the frozen evaluation contract. No replacement is approved.

**Goal:** A polished, honest screening tool for Aleks / sledilnik.org that shows where detailed flood/coastal investigation should start. It is not a hydraulic, coastal, or probabilistic forecast model.

> Authoritative context: `AGENTS.md`, `CLAUDE.md`, `DECISIONS.md`, and `PLAN.md`. This handoff is the current snapshot plus the latest implementation notes.
> The active review/implementation tracker is `ALEKS_REVIEW_AND_ALGORITHM_PLAN.md`.
> The focused red-map/model-replacement tracker is `FLOOD_MODEL_REPLACEMENT_PLAN.md`.
> The active observed-event enhancement tracker is
> `UPPER_SAVINJA_OBSERVED_EVENT_ENHANCEMENT_PLAN.md`.

## D44 Three-choice public sidebar (2026-07-22)

- Replaced the research-heavy sidebar with exactly three switches: **Compare
  with official Q100 flood map**, **Show land and buildings**, and **Show
  places to review**.
- The comparison switch now handles the derived Q100 categories and official
  comparison boundary together. The separate D19, official scenario,
  validity, depth, connectivity, NDVI, coastal, scenario, and opacity controls
  are no longer shown publicly; their calculations and files remain intact.
- The only guided action is **Start with the Ljubljana comparison**, which
  moves to Ljubljana and enables the comparison. Labels, legends, About copy,
  and both map popups now use short plain-English explanations.
- Cache versions: `style.css?v=13`, `app.js?v=24`.

## D43 Mobile low-memory map mode (2026-07-21)

- Desktop retains D40's complete active-overlay behavior with all available
  tiles rendered for every enabled layer.
- Mobile/coarse-pointer browsers load at most 12 analytical raster tiles near
  the current padded viewport and rebuild that bounded set after navigation.
  Only one heavy analytical toggle is active at a time; off-screen image
  sources and inactive official GeoJSON are removed instead of merely hidden.
- Mobile MapLibre uses a 1.5 pixel-ratio cap, 24-tile basemap cache, and one
  cache zoom level. Connectivity and Q100 click-index canvases use three-entry
  LRU-style caches. The UI explains that panning or zooming reveals the full
  available coverage.
- Cache versions: `style.css?v=12`, `app.js?v=23`.

## D42 Spatially distributed D19 review points (2026-07-21)

- Split local candidate spacing (`CANDIDATE_SEP_M = 50`) from public marker
  spacing (`REVIEW_POINT_SEP_M = 750`). The final selector remains score-first
  and region-capped, but skips candidates representing the same local hotspot.
- Regenerated `web/data/risk_points.geojson` from the retained 500 candidates:
  20 points now cover 19 tiles, with an actual minimum spacing of 823 m. Only
  one point remains in the previously clustered Koper port patch.
- D19 scores and model outputs are unchanged. These remain experimental review
  locations—not probabilities, forecasts, or independently confirmed critical
  risks.

## D41 Mobile bottom-sheet controls (2026-07-21)

- Mobile and coarse-pointer browsers now open with the map unobstructed and a
  44 px Layers button. It opens the existing controls in an 82dvh bottom sheet
  with a sticky header, backdrop, safe-area padding, and contained scrolling.
- Done, backdrop click, Escape, and the top-bar action close the sheet. Hidden
  controls are inert and focus returns to Layers. Guided presets also close the
  sheet after changing the view.
- Mobile form controls and D19 review markers have larger touch targets, and
  16 px select text avoids iOS focus zoom. Secondary reading steps are hidden
  only on mobile to put guided presets and layers closer to the top.
- Desktop CSS and behavior remain unchanged: browser verification measured the
  original panel at 304 px wide, 12 px left, and 58 px top, with the mobile
  header, backdrop, and top-bar toggle hidden.
- Verification: `node --check web/app.js`, all 90 `.venv` unit tests, live
  390x844 responsive checks (zero horizontal overflow, focus/Escape behavior,
  44 px targets), and a reset 1280x720 desktop check.

## D40 Complete active overlay coverage (2026-07-21)

- Reversed D37's viewport-based raster culling. When a raster toggle is active,
  every available tile for that layer is registered and visible across the
  complete dataset; panning no longer removes distant overlay sources.
- Inactive overlays remain unloaded, and official GeoJSON remains on-demand.
  Connectivity already used full-domain activation and required no change.

## D39 Stable D19 review-point hover (2026-07-21)

- MapLibre now positions an inert `.risk-marker-anchor`; hover/focus scaling is
  applied only to its nested button. This prevents CSS transform composition
  from moving a review point away from its geographic coordinate.
- Review points are keyboard-focusable and have rank-specific accessible names.

## D38 Optional Slovenia aerial basemap (2026-07-21)

- Added an off-by-default Dark map / Aerial imagery selector using the official
  GURS DOF025 orthophoto WMS. The source is bounded to Slovenia, requires no API
  key, and carries the required GURS CC BY 4.0 attribution.
- The WMS raster layer is inserted below map labels and all analytical layers.
  MapLibre requests only visible 256 px tiles after the user selects aerial
  imagery; the default dark view makes no orthophoto requests.
- The app does not copy or publish orthophoto files, so the bounded GitHub Pages
  artifact size is unchanged. GURS service availability remains an external
  dependency; consider a policy-compliant cache only if real traffic warrants it.

## D36-D37 Geography correction and delivery improvements (2026-07-21)

- Corrected a material D33 geography error. The E486–491 km / N132–137 km
  block transforms to about 14.818–14.883 E / 46.328–46.373 N and is centred
  around Ljubno ob Savinji in the Upper Savinja Valley. `08-kamnik` is the
  Flycom CDN region slug, not the study-area name.
- The Kamniška Bistrica/Pšata post-event archives in `validation/sources.json`
  are now `excluded_wrong_geography`; `prepare_event_evidence.py` will not
  inventory or download them. The EMSR680 intersection workflow, queue IDs,
  schema, plan, and current app labels now use Upper Savinja naming. Existing
  ignored legacy context files remain readable only to ease migration.
- The app now loads official GeoJSON only when its control is selected and
  keeps raster overlays to bounded viewport sets, removing distant sources on
  movement. Guided Ljubljana, Upper Savinja, and Koper views make the primary
  comparisons discoverable.
- Mobile controls are a collapsible bottom drawer; form controls have explicit
  labels, visible keyboard focus, and a generated favicon. Layer controls are
  capability-driven when an asset family is absent.
- GitHub Pages now publishes a bounded `_site/` artifact rather than the full
  1.26 GiB research directory. The build omits local-only NDVI and saturated
  D19 diagnostic rasters, rewrites the manifest accordingly, and is currently
  about 144 MB. CI runs all Python tests and `node --check` before deploy.

**Next entry point:** acquire geographically matching Upper Savinja imagery
and gauge forcing before reviewing event labels. Keep the excluded
Kamniška Bistrica/Pšata sources out of this study.

## D34-D35 Connectivity-first physical stage model (2026-07-15)

- Added a separate `connectivity-stage-v1` calculation; D19 remains frozen.
  It reports minimum channel-stage rise through a basin-constrained minimax
  path and emits depth/classes only for an explicit versioned stage scenario.
- Flatness, absolute elevation, inverted slope, NDVI, and canopy cannot flag a
  cell directly. A definitive scenario result requires a drainage source, an
  applicable connected path, and water above original terrain.
- Added 391-tile component inventory (345 central / 25 Upper Savinja / 21 Koper), a
  16 m bounded local-gap contract, explicit missing-tile and edge states,
  optional chunked Zarr storage, exact physical-value web indices, and a frozen
  observed-event scientific gate.
- The 25-tile Upper Savinja minimum-stage diagnostic is now exported into the public
  manifest and web tiles. Its control is enabled only for those tiles. Lower
  required rise is dark blue; values above 3 m are deliberately faint slate so
  inaccessible uplands do not dominate the map. It remains research-only and
  is not a probability, hazard, forecast, or approved model replacement.
- Scenario export still refuses research-only forcing by default. The scenario
  control remains disabled, so no unreviewed August 2023 depth or dry/wet
  classification is visible.
- Zarr/Dask are installed in `.venv` and the chunked writer is round-trip
  tested. GRASS is not installed; complete central contextual terrain and the
  zero-decision observed-event review queue remain genuine external gates.
- The real 25-tile Upper Savinja run is verified: about 38 seconds from cached DTM,
  zero internal sinks, 14,340 seam-crossing receivers, exact 25-tile/22-array
  cut-back, and a roughly 145 MB Zarr store. Deterministic reach IDs drive
  reach-specific stage/discharge forcing and exact popup lookup.
- `input_digests.py` hashed all 391 LAZ files with restartable checkpoints;
  dataset SHA-256 is `16f587afa00b0201f983512bbfe3601863ef0c0bf945eebf8592a607c1101d2b`.
  Repeated unchanged Upper Savinja runs produced identical analytical manifest digest
  `21388fed7903e469b809c2f745127e864e996cef4e1a24f7cb95d0c3fff56615`;
  volatile timing is isolated in `run_report.json`.
- `build_analysis_store.py` is the restartable whole-domain LAZ-to-Zarr
  ingestion boundary at 2 m or 10 m. It writes direct DTM/DSM/canopy,
  point/ground density, coverage, and provenance and never fills absent tiles;
  a real 10 m Upper Savinja tile smoke test passed.

**Recommended next entry point:** acquire/review supported event evidence and
gauge forcing, then run
the frozen gate. Do not publish a scenario or weaken the gate to create one.

## D33 Kamnik/Kamniška Bistrica area correction (2026-07-13; superseded by D36)

- This entry recorded an incorrect inference from the transformed coordinates.
  D36 reverses it: those coordinates are around Ljubno ob Savinji in the Upper
  Savinja Valley, and the DRSV Kamniška Bistrica/Pšata archives are unrelated.
- Renamed all **new** observed-event workflow files, source IDs, generated
  evidence names, review IDs, documentation, and public DRSV asset URLs to
  Kamnik/Kamniška Bistrica. The now-correct DRSV RGB/CIR/sheet-index URLs are
  recorded, though the publisher continues to return HTTP 403 for direct
  retrieval.
- The existing `mosaic_hydrology.py --region savinja` selector and ignored
  `output/mosaic/savinja/` directory intentionally remain legacy identifiers:
  they reproduce the already evaluated D26/D28 experiment. Do not silently
  relabel or regenerate those historical assets. Any future migration needs a
  manifest alias plus an exact-output regression check.

**Why:** Using a Savinja source name for Kamniška Bistrica could lead to the
wrong imagery, gauge, and review coverage. Preserving the legacy selector
separately prevents breaking reproducibility while making future evidence work
geographically correct.

## D32 Kamnik/Kamniška Bistrica observed-event evidence inventory (2026-07-13, uncommitted)

- Added `KAMNIK_OBSERVED_EVENT_ENHANCEMENT_PLAN.md`, which narrows the next
  model work to a Kamnik/Kamniška Bistrica August-2023 hindcast. It prohibits cosmetic
  D19 retuning, full-area red risk displays, and public promotion before
  independent observed-event evaluation.
- Added `prepare_event_evidence.py`, `test_prepare_event_evidence.py`, and
  `validation/sources.json` event-source records. The inventory captures URL,
  licence, capture date, intended use, explicit limitations, HTTP metadata,
  final URL, and checksums before a source can enter model work. Large imagery
  downloads are blocked above 500 MiB unless deliberately overridden; this
  prevents a blind 9.5 GB RGB download before selecting image sheets.
- Verified and downloaded the public CC-BY Copernicus EMSR680 archive:
  `validation/data/event_evidence/emsr680_products.zip`, 91,222,927 bytes,
  SHA-256 recorded in its ignored acquisition manifest. It contains AOI03
  flood-event/delineation products with GeoJSON `observedEvent` layers.
- Added `extract_emsr680_observed_events.py` and three tests. It extracts all
  1,498 EMSR680 flood features and conservatively intersects them with the
  current EPSG:3794 Savinja 5×5 LiDAR mosaic. The ignored catalogue reports
  156 intersecting unreviewed features: 155 from AOI07 and one from AOI03;
  155 are marked `Photo-interpretation`, 82 `Flooded area`, and 74 `Flood
  trace`. This is useful independent context, not a final footprint or a
  source of negative/dry labels.
- Added `observed_event_labels.py`, three tests, and
  `validation/review/` documentation/schema. Its deterministic review queue
  has 156 candidates and its validator requires `flooded`, `not_flooded`, or
  `uncertain` plus reviewer/time/evidence; pending and uncertain candidates
  cannot enter later fitting. Current validation reports zero decisions and
  156 pending because no approved imagery review has occurred.
- The DRSV Kamniška Bistrica/Pšata orthophoto sheet-index endpoint returned HTTP 403 when
  fetched directly, and the official hydrography ZIP endpoint presents a TLS
  hostname mismatch to this runtime. These are source-access limitations, not
  absence of data. Do not disable TLS checks or scrape around the publisher;
  retain the official URLs/provenance and use the Copernicus package as
  independent context while seeking a supported official access route.

**Why:** D28 rejected all static replacement candidates because they still
overflagged low, flat terrain. A real-event evidence package is new information
that can test connectivity-first features rather than making D19 look better.
EMSR680 is explicitly *not* final truth: its remote-sensing delineation can
miss transient/obscured water and must be marked unreviewed until imagery/manual
review validates it.

**Verification:** `test_prepare_event_evidence.py` passes 4/4 under the bundled
Python runtime; `prepare_event_evidence.py --help` and `git diff --check` pass.

**Next entry point:** Build the conservative review-label package around the
extracted EMSR680 context. It needs post-event imagery or an approved official
review source before any human can affirm flooded/not-flooded/uncertain cells.
Do not fit a model or inspect the existing locked static-Q100 test.

## D31 Hydraulic-validity coverage expansion (2026-07-13)

- Downloaded and header-verified 245 new GKOT LAZ tiles in ten bounded 5x5
  chunks selected by overlap with official IKPN hydraulic-study validity. The
  complete public dataset is now 391 tiles: Ljubljana 295, Kamnik/Savinja 75,
  Koper 21; raw GKOT storage is 91.74 GB decimal.
- Recalibrated Ljubljana and Kamnik/Savinja, then reprocessed all 391 tiles with
  three workers in 1,296 seconds. All expected tile products, 500 candidates,
  20 region-capped review points, and the manifest were regenerated.
- Refreshed official validity (46 features) and Q100 (3,833 polygons), rebuilt
  compact official web layers, and generated schema-v2 comparison display and
  click-index images for every current tile directly from raw official geometry.
- Expanded comparable area: Ljubljana 160.414 km2 at 99.71% D19 coverage of
  validity; Kamnik/Savinja 29.790 km2 at 99.86%. Ljubljana shares are 31.79%
  official-only, 11.59% D19-only, 7.53% both, 49.09% neither.
- Preserved `validation/evaluation_contract.json`, its packed grids, and spatial
  assignments unchanged. The post-expansion frozen baseline remains rejected:
  D19 AUC/AP 0.5690/0.3791 versus HAND-only 0.7049/0.5123.
- Added atomic concurrent tile downloads, exact batch tests, bounded official
  ArcGIS query cells, and lazy registration of hidden tile rasters in the app.
- Made the canonical pipeline write D19 display metadata directly. This avoids
  running the legacy palette-recovery migration after a LAZ rerun; categorical
  shares above use the direct unquantized regional display score before final
  PNG palette compression.

**Why:** The old map had isolated LiDAR blocks over a much larger official-study
network. This expansion makes the categorical comparison available over material
central-validity corridors without claiming those corridors flood. Public
coverage may expand; the locked scientific benchmark must not silently move.

**Known limitation:** The DRSV service repeatedly disconnected while paging the
ancillary IKRPN low-risk class. Critical validity/Q100 data and their acquisition
records are current, so this does not affect the user-facing comparison. Retry
ancillary layers separately if they become product requirements.

**Exact selection and regeneration record:** `VALIDITY_TILE_EXPANSION.md` and
`validation/validity_expansion_2026_07.json`.

## D30 Real categorical Q100 comparison (2026-07-12)

- Added `prepare_q100_comparison.py`, which combines committed 2 m DRSV validity/Q100 grids with the frozen D19 review-display mask for all 146 tiles.
- Added map and click-index assets per tile: `q100_d19_comparison.png` and `q100_d19_comparison_index.png`.
- Replaced source-layer transparency mixing with four visible analytical classes: cyan official-only, orange D19-only, white both, and transparent neither. Sparse gray hatching marks missing D19 data; outside the dashed validity boundary is comparison unavailable.
- Comparison mode disables the independent D19 and official controls, displays only the derived class layer, and forces the official validity boundary on.
- Clicking reports official Q100 yes/no, D19 review signal yes/no/no-data, validity inside/outside, tile, and a plain-language interpretation.
- The sidebar reports exact region shares over the denominator “inside official validity with D19 data.” Ljubljana: 35.44% official-only, 5.05% D19-only, 4.30% both, 55.21% neither; comparable coverage is 99.54% (50.544 km²).
- Added `test_q100_comparison.py` for classification, denominators, complete asset registration, and frontend semantics.

**Why:** The D24 mode only stacked semitransparent layers, so mixed colors looked like categories without being calculated categories. Black also conflated neither, unavailable, and outside-validity space. D30 makes the comparison reproducible and explicit while retaining the honest limits: D19's 0.925 cutoff is a display rule, Q100 is a static planning reference, and neither is not proof of safety.

**Regeneration:** Run `.venv\Scripts\python.exe prepare_q100_comparison.py` after changing D19 review assets, official 2 m validation rasters, or the web manifest. Commit both generated PNG types and the manifest update.

## D29 Remove synthetic hydroclimate visualizations (2026-07-12)

- Removed **Hydroclimate Trigger** and **Terrain Candidates Under Trigger** from the sidebar.
- Removed hydroclimate manifest/data fetching, MapLibre grid registration, popups, dynamic markers, date switching, and related CSS from the public frontend.
- Retained `hydroclimate.py`, its fixture/real-data derivation paths, formulas, generated `web/data/hydroclimate/` artifacts, and README regeneration commands.
- The static app no longer requests or displays the retained hydroclimate assets.

**Why:** The current dataset is a deterministic coarse fixture, not ERA5 evidence. Rendering it as large colored squares implies spatial resolution and operational meaning that the calculation does not support. Keeping the calculations preserves future research work without presenting a low-value visualization to users.

**Re-entry gate:** A hydroclimate visualization may return only after real ERA5-Land/ARSO ingestion, correct accumulation handling, meaningful catchment aggregation, multiple-date validation, and a display design whose resolution matches the evidence.

## D28 Phase-5 development benchmark — gate failed (2026-07-12)

- Added `benchmark_replacement.py`, `test_benchmark_replacement.py`, and the explicit scikit-learn dependency.
- Implemented B0 mosaic HAND with channel-distance applicability, B1 fixed drainage rules, frozen B2 D19/per-tile HAND references, nonnegative-coefficient monotonic logistic M1, and monotonic histogram-gradient-boosting M2.
- Features: mosaic HAND, channel distance, 250 m valley position, 250 m relief, accumulation, order; TWI and slope were tested individually and together. Absolute elevation is not an input.
- Used 10 spatial leave-one-easting-column-out development folds; adjacent columns in the same region are excluded from training. Dataset: 84,358 eligible samples, 27,541 Q100-positive.
- Tested 250/500/1000/2000 m channel-distance applicability. Best B0 is 500 m: AUC/AP 0.7447/0.5049.
- Best challenger is `m2_plus_twi_slope_d500m`: AUC/AP 0.7647/0.5819, top-10% precision/recall 0.6536/0.2002, low-flat negative flagged fraction 0.0598 versus B0 0.0753.
- Gate result: **fail**. AUC gain is +0.0200 (required +0.03) and low-flat reduction is 20.58% (required 30%); AP gain +0.0770 and recall change +0.0369 pass their parts.
- Shortcut audit also remains concerning: best-challenger score/elevation Pearson is −0.6002 in Ljubljana and −0.3800 in Savinja despite excluding absolute elevation. Drainage-relative geometry can still correlate with basin elevation.
- M2 out-of-fold permutation AUC drops are led by valley position 0.0675, mosaic HAND 0.0444, flatness 0.0337, and local relief 0.0217. TWI, accumulation, and stream order add little.
- `output/replacement_model/development_report.json` and `MODEL_CARD.md` are reproducible ignored artifacts. `finalize` refuses to open the locked test while `selected_candidate` is null.

**Why:** The approved gate exists to prevent publishing a more complex model merely because one metric improves. The challenger clearly improves ranking precision, but it does not reduce the broad low-flat/altitude shortcut enough to justify replacing mosaic HAND.

**Next entry point:** Do not weaken the gate or open the locked test. Add genuinely new information: vetted observed August-2023 extent, mapped levee/embankment and imperviousness/drainage features, or independent basin/event labels. Re-run `python benchmark_replacement.py develop`; only implement the one-time `finalize` path after a candidate passes all development gates.

## D27 Phase-4 Ljubljana mosaic hydrology (2026-07-12)

- Generalized `mosaic_hydrology.py` so `--region savinja` and `--region ljubljana` use one code path and separate fingerprinted caches. The Ljubljana 10×10 run decoded 1,321,210,775 ground returns into a 5000×5000 grid; initial full runtime was 240 s and the expanded cached run was 137 s.
- Added memory-mapped cache reads and downsampled QA rendering for the 25-million-cell basin. Fixed a Windows lock found when a memory-mapped feature already backed its destination file.
- Geometric official-line alignment made Ljubljana's gentle burn eligible (median/p90 line offset 0.100/0.698 m), but development Q100 showed it was harmful: burned 100k m² HAND AUC/AP 0.6991/0.4654. Selection therefore keeps the unburned priority-flood surface.
- Development-only configuration selection chose the unburned 100,000 m² stream threshold: mosaic HAND AUC/AP 0.7358/0.5150 versus per-tile 0.7111/0.4949. Guard and locked test remained untouched.
- Verified zero internal sinks, 63,263 receiver links across former tile seams, conditioned-DTM/HAND seam ratios 0.9976/0.9988, and exact cut-back of 13 features into all 100 tiles.
- Added exact global receiver indices, terminal outlet IDs, first downstream stream IDs, connectivity, 250 m valley-relative elevation, and 250 m local relief. Ljubljana stream connectivity covers 96.47% of cells.
- Conditioned terrain is now retained as float64 and the exact receiver graph is exported. Reconstructing receivers from the saved terrain produces zero mismatches; the former float32 export could lose tiny priority-fill gradients.
- Savinja was rerun through the expanded 13-feature contract while retaining its frozen D26 unburned 50k m² selection and identical benchmark metrics.
- Verification: 33/33 repository tests, Python/JavaScript syntax, diff check, exact tile exports, and real-tile legacy kernel faithfulness all pass.

**Why:** Ljubljana is a broad, urbanized basin rather than an alpine valley. The first automatic burn looked geometrically plausible but made the reference benchmark worse. Requiring development evidence in addition to line alignment prevented an apparently sophisticated conditioning step from degrading the feature.

**Caveats:** Ljubljana priority fill changes 16.51% of cells (median +0.117 m among changed cells; p99 +4.455 m; maximum +19.10 m), so conditioning deltas require review before hydraulic use. Selected D8 channels recover only 23.13% of official line cells within 20 m (precision 56.88%; F1 0.3289); the official layer contains dense field/urban drainage not fully represented by surface D8. D8/MFD selected-stream Jaccard is 0.3983. Underground stormwater, culverts, pumps, barriers, and engineered flow directions remain absent. These are screening features, not hydraulics.

**Next entry point:** Phase 5—implement frozen D19/per-tile HAND, mosaic HAND, drainage-rule, and constrained statistical candidates. Use spatial development folds and negative controls; open the locked test only once at the final selection gate.

## D26 Phase-3 Savinja mosaic hydrology (2026-07-12)

- Added `mosaic_hydrology.py` and mosaic-safe Numba kernels for priority-flood conditioning, continuous receivers/accumulation, HAND, channel distance, Strahler order, and Freeman MFD sensitivity.
- Assembled all 25 Savinja tiles into one 2 m, 2500×2500 EPSG:3794 grid from 346,901,854 ground returns. Large arrays, per-tile feature bundles, the manifest, and QA overview remain reproducible under ignored `output/mosaic/savinja/`.
- Tested official flow-line alignment before terrain enforcement. The gentle burn failed its predeclared alignment acceptance test, so the selected terrain is the unburned priority-flood surface; the raw DTM and conditioning delta remain available.
- Selected the 50,000 m² D8 stream threshold by development-only official-line alignment (precision 0.7687, recall 0.6706, F1 0.7163). The 10k and 100k thresholds and MFD routing remain recorded sensitivities.
- Verified zero internal sinks, 14,340 receiver links crossing former tile seams, conditioned-DTM seam ratio 0.9968, HAND seam ratio 0.9742, and 75.84% of official seam cells within 20 m of a derived stream.
- Cut seven feature grids back into all 25 exact tile windows after routing. Automated verification reports `all_exact: true`; no tile-local hydrology fallback occurs.
- Development-only static Q100 benchmark: per-tile HAND AUC/AP 0.7387/0.1523; mosaic HAND 0.7894/0.1973. Guard and locked-test tiles were not evaluated (`locked_test_accessed: false`).
- Added six mosaic tests; full repository suite is 30/30 passing. The legacy real-tile kernel benchmark remains bit-identical (DTM 206×, D8 76× on `488_134`).

**Why:** D19's per-tile HAND terminates drainage at every 1 km edge. Routing the 5×5 terrain once removes artificial tile outlets and improves drainage-relative discrimination without reintroducing absolute elevation.

**Caveats:** Source LAZ tiles provide no overlap halo; the outer mosaic boundary is intentionally open. Priority fill is implemented, while least-cost breaching is not; the rejected gentle burn is the bounded carve sensitivity. D8 and MFD have similar official-alignment F1 but only 0.4046 stream-cell Jaccard, so exact channel paths remain uncertain. The comparison uses a static planning Q100 reference, not the August 2023 observed event.

**Next entry point:** Phase 4—parameterize the same mosaic pipeline for Ljubljana's 10×10 block, use memory-mapped/chunk-aware storage as needed, repeat seam/conditioning checks, and document underground urban-drainage limitations. Do not inspect replacement performance on the locked test during feature engineering.

## D25 Phase-2 validation lock (2026-07-12)

- Added committed `validation/evaluation_contract.json`: label layers, 2/10/20 m grids, 10/20 m boundary buffers, split rules, controls, and selection policy.
- Added `validation_grid.py` and `prepare_validation_contract.py`.
- Generated nine committed packed grids plus `validation/evaluation_manifest.json`; total size 1.82 MB with SHA-256 digests and positive-cell counts.
- Frozen split: Ljubljana E455–461 development / E462 guard / E463–464 locked; Savinja E486–488 development / E489 guard / E490 locked; Koper evaluation-only.
- Updated `evaluate_validation.py` to exclude the 10 m Q100 ambiguity band, report split metrics, and apply development top-10% thresholds to four negative-control cohorts.
- Eligible diagnostic samples: 128,737 after excluding 22,698 ambiguous boundary samples.
- Frozen locked-test result: D19 AUC/AP 0.6100/0.3737; HAND-only 0.7764/0.5548.
- Low-flat Q100-negative flagged fraction: D19 0.1334 vs HAND-only 0.0904 using development-selected thresholds.
- Added raster/split/control tests. Full repository verification is recorded with the Phase-2 commit.

**Why:** This prevents random-pixel leakage and post-hoc reshaping of the test. It also makes “outside official extent” meaningful only inside validity and away from ambiguous boundaries.

**Important discipline:** Do not inspect locked-test replacement results during Phase 3/4 feature engineering. Use development blocks and seam/physics tests. Open the locked test only at the final model-selection gate.

**Next entry point:** Phase 3—build conditioned, continuous Savinja mosaic routing/HAND/channel-distance features, prove seam continuity, and compare only on development blocks until the final gate.

## D24 Phase-1 communication repair (2026-07-12)

- Renamed the public control to **Experimental D19 Terrain Baseline** and kept it/review points off by default.
- Preserved every original `susceptibility.png`; diagnostic mode deliberately reuses that frozen red artifact.
- Added a purple sparse review asset at display score ≥0.925. This is an unvalidated display rule, not a probability/hazard threshold or area percentile.
- Added `prepare_d19_web.py` for one-time legacy asset migration and native future export in `pipeline.py`.
- Generated 146 palette-quantized review PNGs totaling 4.6 MB. Representative Ljubljana tile `460_100` is 11.8% visible in review mode.
- Extended `prepare_validation_web.py` to schema v2 with official validity and all three Q100 depth classes.
- Added validity, Q100 depth, and Q100 comparison controls. Comparison mode activates Q100 + validity + sparse D19; it is explicitly a visual overlay, not a combined score.
- Added `test_phase1_web.py`; all 14 repository tests pass. JavaScript syntax and diff checks pass.
- Browser verification: comparison state correct, no console errors, and no horizontal overflow at 390 × 844.

**Why:** D19 underperforms HAND-only and the full red map is misleading. Phase 1 fixes claim and display semantics without pretending to improve predictive skill or erasing the failed baseline.

**Next entry point:** Phase 2—create versioned evaluation rasters, fixed spatial development/test blocks, boundary uncertainty variants, and negative controls before fitting or choosing thresholds.

## D22 Phase-0 implementation (2026-07-11)

- Added `analyze_model.py`, `model_diagnostics.py`, `test_model_diagnostics.py`, and `requirements.txt`.
- Pipeline writes model/calibration/dataset provenance plus deterministic score-stratified samples under ignored `output/diagnostics/samples/`.
- Full 146-tile rerun succeeded in 516 s with 3 workers; 145 land-bearing tiles emitted 360,790 samples (`400_48` is all sea).
- Baseline audit fails as intended: median warm fraction 0.9879, strongly red 0.9219, full-grid score/elevation Pearson −0.4742 and Spearman −0.5057.
- Per-region Pearson: Koper −0.7675, Ljubljana −0.8181, Kamnik/Savinja −0.6239.
- UI now defaults D19 and review markers off, removes probability-like percentages, labels D19 as unvalidated and D21 as synthetic, and shows a screening-only notice.
- Verification: four unit tests pass, JS syntax passes, and the rendered local app was browser-checked. Only upstream basemap missing-sprite warnings appeared.

Next entry point: acquire/rasterize official Slovenian hazard maps and an observed August 2023 Savinja extent, then build mosaic-level Savinja hydrology before selecting new weights.

## D23 official-validation implementation (2026-07-11)

- Added `validation/sources.json`, `validation/README.md`, `download_validation.py`, `prepare_validation_web.py`, `evaluate_validation.py`, and validation tests.
- Official DRSV downloads are scoped to three separate EPSG:3794 study envelopes, paginated, deduplicated, checksummed, and kept under gitignored `validation/data/`.
- Acquired IKPN validity + Q10/Q100/Q500, all three IKG Q100 depth classes, four IKRPN classes, and official flow lines.
- Added optional blue official Q10/Q100/Q500 reference controls to the app; Q100 is selected but the layer is off by default.
- Static Q100 benchmark inside official validity: 151,435 samples, 55,309 positives. D19 AUC/AP = 0.5972/0.4109; HAND-only = 0.6908/0.4985. HAND-only is now the minimum baseline.
- Per-region D19 AUC: Koper 0.5368, Ljubljana 0.6117, Kamnik 0.6648. Median tile AUC across 91 two-class tiles: 0.6239 (IQR 0.5285–0.7415).
- Ten unit tests and JS/Python syntax checks pass; official selector and default-off semantics were browser-verified.

Updated next entry point: obtain a vetted August 2023 Savinja observed footprint and ARSO event forcing; meanwhile implement mosaic-level Savinja routing/HAND and evaluate it against the frozen HAND-only and D19 baselines. Do not tune D19 weights on the Q100 reference.

## Context

This repository builds an interactive web map from Slovenia's CLSS airborne LiDAR data. `pipeline.py` reads local `data/GKOT_*.laz` files, computes terrain/vegetation factors, exports PNG overlays under `web/data/tiles/<tile>/`, and writes `web/data/manifest.json`, `web/data/candidates.json`, and `web/data/risk_points.geojson` for the static web app.

Aleks provided two validation/extension directions: the Savinja valley flood area from Aug 2023 and Koper for sea-level-rise exposure. D20 handled Koper coastal exposure. D21 implemented the Copernicus/BGC hydroclimate calculation contract; D29 keeps those calculations but removes their synthetic fixture from the public map.

Live site: https://dhairyamishra.github.io/slovenia-lidar-floodmap/

## Historical D21 snapshot (superseded by D29)

The bullets in this subsection record the original D21 implementation session. They are not current working-tree status; D29 removes the frontend visualization while retaining the calculation assets.

Recent implementation commits before this working tree:

- `83def46` - Update README and handoff for D20
- `47a1320` - Add Koper coastal SLR overlays
- `770a7b5` - docs: update README
- `1bccc73` - Add HAND flood factor (D19) - research-weighted model
- `f9281d7` - Add Koper coastal baseline (21 tiles) + D18 no-data mask

Done but not yet committed in the current working tree:

- D21 `hydroclimate.py` added.
- `web/data/hydroclimate/manifest.json` generated with one available date: `2023-08-04`.
- `web/data/hydroclimate/hydro_2023-08-04.geojson` generated as a deterministic fixture grid.
- `web/data/hydroclimate/dynamic_risk_2023-08-04.geojson` generated from existing `web/data/candidates.json`.
- `web/app.js`, `web/index.html`, and `web/style.css` updated for optional Hydroclimate Trigger controls and hydro-primed risk markers.
- `DECISIONS.md` D21 and `README.md` updated.

Current local note:

- `AGENTS.md` is untracked local context from before the D20 commit.

Verified facts from this implementation:

- Fixture/export commands completed:
  - `C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe hydroclimate.py derive-fixture`
  - `C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe hydroclimate.py export`
- Generated hydroclimate web assets total about 209 KB.
- The fixture dynamic ranking puts Savinja tile `488_132` at rank #1 for `2023-08-04` with `event_score: 0.777`, `static_risk_score: 0.953`, and `hydro_index: 0.816`.
- At the time of the historical D21 fixture implementation,
  `web/data/manifest.json` had `tile_count: 146`; D31 supersedes this with 391.

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
- The retained candidate pool is locally spaced at 50 m; the final top-20 uses
  750 m public-marker spacing so adjacent cells in one hotspot do not dominate.
- `REGION_CAP = 7` prevents one per-region-normalised region from monopolising the list. Current split is balanced by design, not because cross-region scores are absolute probabilities.

Coastal D20 model:

- Applies only to CDN region `01-koper`.
- Outputs three scenario masks per Koper tile:
  - `coastal_slr_0_5m.png`
  - `coastal_slr_1_0m.png`
  - `coastal_slr_2_0m.png`
- A land cell is shaded when its DTM elevation is below the scenario and it connects, within that tile, to sea/no-data cells.
- Sea/no-data remains transparent. The overlay only shades exposed land.

Hydroclimate D21 model:

- Implemented in `hydroclimate.py`.
- Since D29, the app does not read `web/data/hydroclimate/manifest.json`; the calculation manifest remains available for offline validation and future evidence-backed visualization.
- Formula: `hydro_score = soil_moisture_norm + water90_norm + 0.5 * wetting_trend_norm`.
- Normalized UI index: `hydro_index = hydro_score / 2.5`.
- Hydro-primed risk points use `event_score = static_susceptibility * hydro_index`.
- V1 fixture intentionally elevates Savinja/Kamnik for the `2023-08-04` hindcast. It is not real ERA5 evidence.
- Real NetCDF path expects ERA5-Land variables `swvl4`, `tp`, and `smlt` under `data/era5/` and requires xarray/NetCDF support.

## Active Thread

The current open work is validation and credibility.

1. D21 is implemented as a UI/data-contract feature, not a validated climate product.
   The deterministic fixture is useful for stakeholder review and front-end testing, but analytical claims require real ERA5-Land data from CDS. Do not present the fixture as evidence.

2. Real ERA5-Land ingestion is only partially proven.
   `hydroclimate.py derive` has a narrow xarray path for local NetCDF files, but no CDS download automation has been added and no real NetCDF file was available in this session. The next agent should test it against actual ERA5-Land data for Slovenia before expanding the UI.

3. ARSO / official flood-hazard validation is still pending.
   The D19 terrain model is literature-informed but not calibrated against observed flood footprints. This remains the biggest credibility step for sledilnik-style technical stakeholders.

4. Savinja Aug-2023 validation is pending.
   The model highlights the valley floor, while the retained D21 calculations still require comparison against documented event extent and forcing before any temporal layer returns.

5. Per-tile HAND and coastal connectivity are still approximate.
   HAND computes inside each 1 km tile, so drainage paths terminate locally. Coastal connectivity is also per-tile. Whole-region / mosaic routing remains the real model-quality upgrade.

Recommended entry point:

Validate D21 offline with real ERA5-Land over the current app bbox for `2023-08-04`, then compare the derived Savinja signal against ARSO or observed Aug-2023 flood evidence. Only after that comparison is credible should a redesigned visualization be considered.

## Gotchas

- `python` is not on PATH in this desktop shell. Use the bundled runtime:
  `C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`
- Real ERA5 derive needs xarray/NetCDF support; fixture/export does not.
- Raw `.laz` files and future ERA5 NetCDF files in `data/` are gitignored and large.
- If you delete LAZ/PNG tiles manually, also purge them from `web/data/manifest.json`; subset runs merge and will keep old entries.
- Pipeline subset runs update global candidates by removing stale entries for reprocessed tiles and merging fresh candidates.
- Long pipeline/calibration runs have previously died when the machine slept. Keep the machine awake.
- Browser preview may not fully verify MapLibre if external basemap/sprite requests fail. DOM/static checks are still useful.

## File Map

| Path | Purpose |
|---|---|
| `pipeline.py` | Canonical LiDAR pipeline; D19 riverine model; D20 coastal export. |
| `hydroclimate.py` | D21 hydroclimate trigger pipeline; fixture generation, real NetCDF derive path, web export. |
| `kernels.py` | Numba kernels for DTM min-grid, D8 accumulation, HAND. |
| `download_tiles.py` | CLSS CDN downloader and tile-region cache helper. |
| `calibration.json` | Per-region p2-p98 factor/display calibration. |
| `.tile_region_cache.json` | Tile ID to CDN region mapping. |
| `web/app.js` | MapLibre app, raster layers, risk markers, coastal scenario UI, hydroclimate UI. |
| `web/index.html` | Static app shell and layer panel. |
| `web/style.css` | App styling. |
| `web/data/manifest.json` | Tile registry consumed by the app. |
| `web/data/hydroclimate/` | D21 trigger grid, dynamic risk points, and manifest. |
| `web/data/tiles/<tile>/coastal_slr_*.png` | D20 Koper coastal scenario overlays. |
| `web/data/risk_points.geojson` | Top-20 balanced static risk markers. |
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

Regenerate the D21 fixture and web hydroclimate assets:

```powershell
C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe hydroclimate.py derive-fixture
C:\Users\dhair\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe hydroclimate.py export
```

Attempt real ERA5-Land derive after placing NetCDF files under `data/era5/` and installing xarray/NetCDF support:

```powershell
python hydroclimate.py derive --date 2023-08-04
python hydroclimate.py export --date 2023-08-04
```

Process all LiDAR tiles:

```powershell
python pipeline.py
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
- ERA5-Land dataset: https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land
