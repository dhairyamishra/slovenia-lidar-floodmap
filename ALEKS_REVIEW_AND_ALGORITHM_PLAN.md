# Aleks Review: Flood Algorithm, Validation, Differentiation, and Map Redesign

> Focused implementation tracker for the red-map remediation and D19 replacement: [`FLOOD_MODEL_REPLACEMENT_PLAN.md`](FLOOD_MODEL_REPLACEMENT_PLAN.md). Review and approve that plan before beginning the next implementation slice.

**Created:** 2026-07-11
**Status:** Active execution plan
**Owner:** Project team
**Scope:** Riverine susceptibility, flood-area analysis, hydroclimate trigger, coastal screen, validation, and public communication

> This file is the restart point if work is interrupted. Update the checkboxes, the experiment log, and the decision gates as work proceeds. Significant accepted decisions must also be appended to `DECISIONS.md`.

## 1. Executive conclusion

Aleks's critique is correct and should be treated as a model-quality review, not a request for cosmetic tuning.

The current app has useful ingredients—2 m LiDAR terrain, HAND, TWI, a separate Koper coastal screen, and a separate hydroclimate concept—but the riverine output is not yet validated flood danger or inundation. It is a hand-weighted, region-relative susceptibility surface. Three current design choices make it look more certain than it is:

1. **The score is structurally altitude/flatness-sensitive.** Absolute elevation and slope contribute 30% directly, while HAND and TWI are derived from unconditioned 1 km tile DEMs. Low ground can score highly without adequate river connectivity or event forcing.
2. **The display saturates almost everywhere.** A quick diagnostic of all 146 committed susceptibility PNGs found a median of approximately 98.4% warm pixels and 90.1% strongly red pixels among valid cells. Red therefore means little to a viewer.
3. **There is no validation loop yet.** We do not have official hazard polygons or observed 2023 inundation footprints in the pipeline, no held-out spatial evaluation, no ablation report, and no uncertainty map.

The immediate goal is therefore **not to tune weights until the map looks right**. It is to turn the project into a benchmarked screening system with an honest visual vocabulary.

The recommended product definition is:

- **Static terrain susceptibility:** where water could plausibly collect or spread, conditional on a river flood.
- **Event trigger:** whether the catchment was hydroclimatically primed, based on real and correctly decoded ERA5-Land/ARSO data.
- **Observed/event extent:** what satellite or official evidence says actually flooded.
- **Official hazard reference:** how the screening output compares with Slovenian Q10/Q100/Q500 depth/extent products.
- **Coastal exposure:** a separate connected low-land screen, never merged into the riverine score.

Do not call the current implementation a “world model.” There is no learned world model in the repository. If that term is strategically important, it must be earned by implementing and benchmarking a model that predicts a future or hidden spatial state from multimodal observations. Otherwise, describe this as a **LiDAR-first, multimodal flood screening and hindcast system**.

## 2. Aleks's points translated into acceptance criteria

### A. “What is different from others, and what does a world model add?”

Acceptance criteria:

- [ ] A short literature/product survey compares this project with official hydraulic maps, global flood models, HAND screening, satellite event mapping, and learned geospatial models.
- [ ] The README contains a one-paragraph differentiation claim that is supported by implemented evidence.
- [ ] “World model” is either removed from public claims or defined with an explicit prediction task, training data, baseline, and evaluation metric.
- [ ] At least two simple baselines are implemented and beaten on held-out geography or events.

### B. “Everything is doomed; there is too much red.”

Acceptance criteria:

- [ ] Default map view does not paint the full study area with an alarm color.
- [ ] Color classes have quantitative meanings tied to validation or explicit percentiles; the legend states which.
- [ ] High/very-high classes occupy a controlled, reported share of valid land and remain spatially coherent.
- [ ] The UI distinguishes “relative terrain susceptibility,” “modeled inundation,” “observed flood,” and “uncertainty.”
- [ ] Scores are not rendered as percentages unless they are calibrated probabilities.

### C. “Danger is highly correlated with altitude, but flooding does not work that way.”

Acceptance criteria:

- [ ] Full-grid Pearson and Spearman correlations between score and elevation are reported per region and landform, not inferred from top candidates.
- [ ] Partial dependence or SHAP/feature attribution is reported for every fitted model.
- [ ] Leave-one-factor-out ablations quantify the contribution of elevation, slope, HAND, and TWI.
- [ ] A no-elevation baseline and a drainage-relative model are evaluated against official/observed flood labels.
- [ ] The chosen model improves spatially blocked validation metrics without relying on absolute elevation as a shortcut.

## 3. Evidence from the repository audit

### 3.1 Current riverine formula

`pipeline.py` computes a weighted sum of per-region p2–p98-normalized factors:

| Factor | Weight | Risk direction | Key concern |
|---|---:|---|---|
| HAND | 25% | lower is higher | Computed independently in each 1 km tile; unconditioned pits/outlets can receive HAND = 0. |
| TWI | 20% | higher is higher | D8 flow on a gap-filled but hydrologically unconditioned DEM; tile edges truncate contributing area. |
| Absolute elevation | 15% | lower is higher | A regional rank/relative-altitude shortcut, not a causal flood mechanism by itself. |
| Slope | 15% | flatter is higher | Flat roads, roofs, fields, terraces, and port surfaces can all become broadly “high.” |
| Plan curvature | 10% | configured higher is higher | Sensitive to noise and smoothing; sign/meaning should be verified against labeled floods. |
| Canopy interception | 7.5% | lower is higher | LiDAR structure is not event-scale interception capacity. |
| NDVI | 7.5% | lower is higher | Weakly connected to river inundation and sensor NDVI is radiometrically compressed. |

The current weights are literature-informed judgments, not learned or calibrated coefficients. The code comment says the factors are comparable across tiles, but calibration is actually **per region**, and D19 correctly acknowledges that scores are not comparable across regions.

### 3.2 Altitude-bias evidence and limitations

The top-500 candidate file contains:

- 152 candidates below 50 m,
- 329 candidates from 50–350 m,
- 19 candidates above 350 m.

Several tiles contribute the maximum 60 candidates. Pearson correlation between score and elevation within this already-selected candidate pool is modestly negative in Koper and Savinja, but this is **not a valid bias test**: the file contains only the extreme tail and omits factor values for every other grid cell. The current outputs cannot answer Aleks's question rigorously.

Required correction: export diagnostic samples from the entire valid grid, including raw/normalized factors, score, region, tile, land cover, distance to mapped river, and validation label.

### 3.3 HAND and drainage defects to test first

The current HAND implementation has four high-risk assumptions:

1. **Tile truncation:** each 1 km tile routes independently. Major rivers do not carry upstream area across tile boundaries.
2. **No depression conditioning:** the DTM is smoothed but not breached/filled for hydrologic routing. Artificial pits can terminate flow.
3. **Pit/outlet fallback:** `_hand_core` assigns an interior pit or tile-edge outlet its own elevation, yielding HAND = 0. This makes unresolved drainage endpoints maximally susceptible after inversion.
4. **Local channel threshold:** `STREAM_AREA_M2 = 10,000` was tuned for edge-truncated tiles and cannot be transferred unchanged to a regional mosaic.

Visual inspection of `web/data/tiles/488_132/susceptibility.png` shows broad red slopes/hills with narrow blue drainage traces in substantial areas. That is incompatible with the intended claim that the map highlights the valley/drainage corridor and must be treated as a release-blocking diagnostic.

### 3.4 Display and semantics defects

- The susceptibility PNG uses `RdYlBu_r`, then displays a region-specific p2–p98 stretch. The result is an almost universally warm map.
- Red is used for **relative score**, not probability, expected depth, return period, or observed extent.
- Popups label `risk_score * 100` as a percentage, which strongly implies probability even though no probability calibration exists.
- “High-Risk Locations” overstates the output. These are high-scoring susceptibility candidates, capped by region for presentation balance.
- The region cap makes the demo geographically balanced but is not an analytical ranking rule.
- There is no uncertainty or model applicability layer.

### 3.5 Hydroclimate defects

The deterministic 2023 fixture is suitable only for UI development. It intentionally raises Savinja and therefore cannot validate a hindcast.

The real-data path also needs correction before use:

- ERA5-Land precipitation and snowmelt are accumulated forecast fields; naive hourly resampling can double-count cumulative values unless values are de-accumulated correctly.
- Min-max normalization over the downloaded time interval is unstable and leaks future extremes into a historical score.
- `swvl4` represents deep soil moisture. Flood priming should test layer choices and aggregated/root-zone measures rather than assume layer 4 is best.
- A 365-step difference is not necessarily the intended “wetting trend.” It compares with one year earlier, not recent wetting rate.
- A 90-day water total may describe seasonal wetness but can miss the 6–12 hour extreme rainfall that drove the August 2023 event.
- The product needs catchment aggregation and antecedent/event windows, not nearest coarse ERA5 cell multiplication at each LiDAR candidate.

### 3.6 Coastal defects

Keeping coastal exposure separate is correct. Remaining limitations:

- connectivity is per tile rather than across a stitched coastal DEM;
- vertical datum compatibility between DTM heights and sea-level scenarios is not documented;
- no tide, surge, wave setup, groundwater, drainage, defenses, or DEM uncertainty;
- the output should be named “connected low-land exposure,” not “inundation,” until water levels and defenses are modeled.

## 4. State of the art and defensible differentiation

### 4.1 Relevant method families

| Method family | What it answers | Strength | Limitation relative to this project |
|---|---|---|---|
| Official 1D/2D hydraulic modeling | Extent/depth for specified discharge or return period | Physically interpretable; planning standard | Expensive inputs/calibration; limited scenario coverage |
| Global/regional HAND + streamflow | Rapid inundation guidance | Scalable and terrain-aware | Boundary accuracy degrades with biased flow, low relief, roughness assumptions |
| Statistical/ML susceptibility | Relative likelihood from conditioning factors | Learns nonlinear relationships | Requires trustworthy flood inventories and spatial validation; can learn elevation shortcuts |
| SAR/optical flood segmentation | Observed event extent | Direct event evidence; scalable | Clouds affect optical; SAR has urban/vegetation ambiguities; not a forecast by itself |
| Hydroclimate trigger models | When a basin is primed | Adds temporal state | Coarse reanalysis does not produce 2 m inundation; needs event validation |
| Coastal bathtub/connectivity screens | Low-land exposure at a water level | Transparent and fast | Not surge/hydrodynamics; sensitive to datum and defenses |

### 4.2 What can genuinely be different here

The strongest credible differentiation is not a novel weighted formula. It is the **combination and resolution of evidence**:

1. Slovenia-wide repeatable CLSS LiDAR processing at 2 m.
2. Hydrologically conditioned, mosaic-level drainage-relative features.
3. Real ERA5-Land/ARSO event context at catchment scale.
4. Sentinel-1/Planet-style observed flood extent for event validation.
5. Direct comparison with Slovenian official hazard maps.
6. An interactive explanation/ablation interface showing why a location is flagged and how confident the system is.

A defensible one-sentence claim, after validation, would be:

> “A LiDAR-first flood screening and hindcast tool that links 2 m Slovenian terrain structure with catchment-scale hydroclimate and event observations, and reports performance against official hazard maps rather than presenting an unvalidated heatmap.”

### 4.3 What a world model would have to add

There are three possible interpretations. Pick one; do not blur them.

**Option 1 — no world-model claim (recommended now).**
Ship an interpretable terrain + forcing + observation system. This is the shortest route to credibility.

**Option 2 — learned flood-state model.**
Input: pre-event Sentinel-1/2, LiDAR terrain, river network, antecedent ERA5/ARSO, and event rainfall/discharge. Output: next/event flood mask or depth. Train across multiple events and hold out entire basins/events. Compare with hydraulic/HAND and tree-model baselines. This earns “predictive geospatial model,” though “world model” may still be unnecessarily broad.

**Option 3 — multimodal latent world model.**
Learn representations of terrain, land cover, weather, and evolving water state; forecast future spatial states and quantify uncertainty. This is a research program, not the next app iteration. It requires multiple time steps/events, far more labeled data, and strong baselines.

Recommendation: pursue Option 1 through the validation milestone. Revisit Option 2 only if partners such as Planet can provide imagery/labels or mentorship.

## 5. Target analytical architecture

```text
CLSS LiDAR -> stitched DTM -> depression conditioning -> regional flow routing
                                                  |-> HAND / distance-to-channel
                                                  |-> relative elevation / valley geometry
                                                  |-> slope / curvature / roughness

Official river network + catchments --------------+-> drainage-connected terrain features
Land cover / imperviousness / soils --------------+-> exposure-conditioning features

ERA5-Land + ARSO rainfall/discharge -> catchment event features -> temporal trigger

Official hazard maps + observed event footprints -> labels and independent validation

Terrain model + trigger -> susceptibility/event score -> probability calibration (only if justified)
                                                    -> uncertainty/applicability
                                                    -> sparse map classes and explanations
```

### 5.1 Static model candidates to benchmark

Implement all of these before selecting a winner:

1. **B0: HAND-only baseline.** Low HAND within a maximum channel distance.
2. **B1: drainage rules baseline.** HAND + distance to mapped channel + local/valley-relative elevation; no absolute elevation.
3. **B2: current D19 weighted overlay.** Frozen for comparison.
4. **M1: constrained interpretable model.** Logistic regression/GAM with monotonic constraints where appropriate.
5. **M2: tree model.** LightGBM/XGBoost or histogram gradient boosting, with class weights and SHAP diagnostics.

Do not start with a deep model. With only a few study blocks and likely correlated labels, a deep network will overfit and obscure failure modes.

### 5.2 Replace absolute elevation with drainage-relative geometry

Candidate features:

- mosaic HAND;
- vertical distance to nearest mapped channel;
- horizontal distance to channel;
- elevation above local valley floor;
- multi-scale topographic position index;
- valley-bottom flatness or geomorphon class;
- contributing area and stream order;
- slope perpendicular to channel;
- connected depression storage;
- distance/height relative to levees or road embankments where data exists.

Absolute elevation may remain as a diagnostic/context feature, but it should not be given a fixed inverted weight. Let validation demonstrate whether it adds generalizable information after drainage-relative features are present.

### 5.3 Mosaic-level hydrology

Per region:

1. Stitch the 2 m DTMs with overlap/halo handling.
2. Reconcile seam elevations and retain a provenance/no-data mask.
3. Hydrologically condition with priority-flood filling and/or breaching.
4. Burn or gently enforce an official river network only after CRS/alignment review.
5. Compute D8 and at least one multi-flow-direction sensitivity run.
6. Derive accumulation, stream order, HAND, distance to channel, and outlets on the whole mosaic.
7. Cut results back into web tiles only after analysis.

Keep the current per-tile path behind a flag until the mosaic implementation passes seam and benchmark tests.

## 6. Validation design

### 6.1 Ground truth hierarchy

Use multiple references because they answer different questions:

1. **Official Slovenian hazard maps:** Q10/Q100/Q500 extent and depth classes. Primary static benchmark.
2. **August 2023 observed extent:** Sentinel-1 change/flood mapping, official event mapping, or vetted partner products. Primary hindcast benchmark.
3. **ARSO event data:** precipitation, discharge, stage, and event reports. Temporal trigger benchmark.
4. **High-resolution partner imagery:** PlanetScope/SkySat where licensing and cloud cover permit. Independent visual/event validation.
5. **Negative controls:** elevated terraces, flat hilltops, protected/embanked land, inland Koper depressions, and dry dates/events.

### 6.2 Sampling and splits

- Rasterize labels to a common evaluation grid; preserve a 2 m product but also evaluate at 10 m and 20 m to reflect label/geolocation uncertainty.
- Create basin/tile groups and use **spatial block cross-validation**. Random pixel splits are prohibited because adjacent cells leak nearly identical terrain into train and test.
- Hold out at least one whole basin or contiguous block.
- For event models, hold out an entire event in addition to spatial holds.
- Buffer ambiguous hazard/extent boundaries and report metrics both with and without the uncertainty buffer.
- Sample negatives by landform and distance-to-river so the model cannot win by predicting “low elevation everywhere.”

### 6.3 Metrics

Report at minimum:

- ROC-AUC and precision-recall AUC;
- IoU/Jaccard and F1 at selected thresholds;
- recall of observed/official flooded cells;
- false-positive rate on negative controls;
- critical success index and bias ratio for event extent;
- boundary distance or buffered IoU;
- calibration curve/Brier score only if producing probabilities;
- performance by elevation band, slope band, distance-to-channel band, region, urban/non-urban, and stream order.

### 6.4 Altitude shortcut audit

Every experiment must produce:

- Pearson and Spearman score-vs-elevation correlations by region;
- flooded/non-flooded label rates by elevation band;
- score distributions for flooded and dry cells within the same elevation bands;
- permutation importance and SHAP/partial dependence;
- ablations: no elevation, no slope, no HAND, no TWI, terrain-only, forcing-only;
- a counterfactual test: similar low/flat cells at different channel-relative positions should receive meaningfully different scores.

Decision rule: reject a model if removing absolute elevation materially improves held-out precision with no unacceptable recall loss, or if the model flags low flat negative controls at a high rate.

## 7. Map and risk-communication redesign

### 7.1 Default visual hierarchy

Recommended default:

- basemap visible;
- susceptibility off or shown as a sparse, low-opacity mask;
- official/observed flood extent available as a blue reference layer;
- only validated “high” and “very high” terrain classes emphasized;
- uncertainty/applicability shown with hatching, desaturation, or separate toggle;
- coastal and hydroclimate layers off by default unless viewing the relevant region/date.

### 7.2 Color semantics

Replace the full blue-to-red continuous rainbow with one of these:

**Before probability calibration:**

- transparent: below reporting threshold;
- pale amber: elevated relative susceptibility;
- orange: high relative susceptibility;
- dark magenta: very high relative susceptibility;
- blue/cyan reserved for observed or modeled water/inundation.

**After probability calibration:**

- use a sequential, color-vision-safe scale with explicit probability bins and an uncertainty qualifier.

Do not use red as the default background state. Reserve the strongest color for a small, decision-relevant class.

### 7.3 Threshold policy

Do not choose classes only to make the map pretty. Select thresholds on validation folds:

- “High”: threshold that meets a predeclared recall target while controlling false positives.
- “Very high”: higher-precision operational/review threshold.
- If validation is insufficient, label classes as percentiles, e.g. “top 5% within Savinja study area,” and state that this is not probability.

Report the land-area share in every class. Suggested visual guardrail before validation: the default emphasized classes should cover no more than approximately 10–20% of valid land, subject to observed performance.

### 7.4 UI wording corrections

Change:

- “Flood & Forest Risk Analysis” -> “Flood Susceptibility & Terrain Screening”
- “High-Risk Locations” -> “High-Susceptibility Review Points”
- “Risk score 95.3%” -> “Relative susceptibility 0.953” or a validated class label
- “Coastal Inundation” -> “Connected Coastal Low-Land Exposure” until hydraulics/datum checks exist
- “Hydro-Primed Risk Points” -> “Terrain candidates under selected hydroclimate state”

Add a persistent disclaimer: **screening output, not a forecast, evacuation map, insurance map, or hydraulic depth estimate.**

### 7.5 Explanation panel

On click, show:

- model/version and study region;
- susceptibility class and whether it is relative or probabilistic;
- HAND, distance to channel, valley-relative elevation, slope, and trigger values;
- top positive/negative feature contributions;
- nearest official/observed validation status;
- uncertainty/applicability warnings;
- data date and source.

## 8. Hydroclimate redesign

### 8.1 Data correctness first

- [ ] Download a reproducible ERA5-Land window covering at least 2020–2024 and the three regions.
- [ ] Decode accumulated `tp` and `smlt` according to ECMWF conventions; add unit tests with synthetic cumulative steps.
- [ ] Convert water-equivalent metres to millimetres explicitly.
- [ ] Compare daily totals with an independent extraction or ARSO station/catchment totals.
- [ ] Store provenance: dataset ID, request, variables, time zone, units, and processing version.

### 8.2 Feature experiments

Test, do not assume:

- 1/3/7/30/90-day precipitation and precipitation + snowmelt;
- standardized anomalies against a fixed climatological baseline, using day-of-year seasonality;
- soil moisture layers 1–4 and root-zone aggregates;
- recent wetting slope over 3/7/14/30 days;
- runoff and snow water/snowmelt where relevant;
- ARSO precipitation/discharge where accessible;
- catchment mean, upper quantile, and upstream-area-weighted aggregation.

For the August 2023 hindcast, the ARSO report says already wet catchments received roughly 150–200 mm in 6–12 hours over the affected mountain region. A useful trigger must represent both antecedent wetness and the short-duration extreme, not only a 90-day total.

### 8.3 Event score

Do not multiply two arbitrary 0–1 indices and display the result as a probability.

Benchmark:

1. terrain-only model;
2. trigger-only model;
3. additive terrain + trigger model;
4. interaction model in which forcing matters more in susceptible terrain;
5. if enough events exist, a calibrated classifier with explicit uncertainty.

The 2023 fixture must be visibly watermarked “synthetic demo” or removed from the public deployment once real data is available.

## 9. Coastal workstream

- [ ] Confirm LiDAR vertical datum and convert sea-level scenarios to that datum.
- [ ] Build one stitched Koper DEM and run whole-mosaic sea connectivity.
- [ ] Add DEM vertical uncertainty sensitivity, e.g. scenario ± stated DTM error.
- [ ] Obtain/document mean sea level, extreme sea levels, tides, and available defenses.
- [ ] Keep pure SLR, storm-tide, and drainage/groundwater scenarios separate.
- [ ] Report exposed area/buildings/roads by scenario, not only pixels.
- [ ] Validate shoreline/connectivity against orthophoto and observed coastal water.

## 10. Prioritized implementation phases

### Phase 0 — Freeze claims and add diagnostics (1–2 focused sessions)

- [x] Tag/freeze D19/D21 outputs as baseline artifacts (`D19-baseline-v1`).
- [x] Add `model_version`, model-definition digest, calibration digest, and dataset digest to generated outputs.
- [x] Export deterministic full-grid stratified diagnostic samples with raw and normalized factor values.
- [x] Implement `analyze_model.py` for correlations, candidate concentration, per-tile saturation, and descriptive ablations.
- [x] Add automated failure thresholds for red/warm coverage, candidate concentration, and altitude correlation.
- [x] Correct UI percentage/risk wording and fixture labeling; default the unvalidated D19 raster and review markers off.

**Exit gate: PASSED 2026-07-11.** `python analyze_model.py` produces JSON and Markdown reports; the local app was browser-verified with all analytical layers off by default, explicit screening warnings, and no probability-like percentages for D19/fixture indices.

### Phase 1 — Acquire validation data (can run in parallel conceptually; complete before fitting)

- [x] Inventory/download official Slovenian hazard extent/depth data for all three study areas (DRSV IKPN/IKG/IKRPN plus validity and flow lines; ignored local artifacts with checksums).
- [ ] Obtain August 2023 Savinja observed flood extent from official or Sentinel-1 sources.
- [ ] Acquire ARSO precipitation/discharge/stage series for relevant gauges/catchments.
- [x] Record source URLs, OPSI license statement, CRS, acquisition timestamp, feature counts, regional envelopes, and content digests in the validation contract/manifest.
- [ ] Build versioned validation rasters and negative-control polygons.

**Exit gate:** validation labels render in the app and can be sampled by the analysis pipeline.

### Phase 2 — Fix hydrology (highest algorithm priority)

- [ ] Mosaic Savinja first with overlap/halo and seam checks.
- [ ] Add depression filling/breaching and official river-network alignment.
- [ ] Compute mosaic accumulation, stream order, HAND, and distance-to-channel.
- [ ] Compare D8 vs MFD sensitivity and threshold sensitivity.
- [ ] Demonstrate continuity across every tile seam.
- [ ] Cut features back into tiles without recomputing routing locally.

**Exit gate:** Savinja HAND/channel features are continuous across the 5×5 block and outperform per-tile HAND against validation.

### Phase 3 — Benchmark and select static model

- [ ] Implement B0, B1, B2, M1, and M2.
- [ ] Run spatially blocked cross-validation and altitude shortcut audit.
- [ ] Select thresholds using validation targets.
- [ ] Calibrate probability only if enough independent labels/events exist.
- [ ] Produce model card with known failure modes.

**Exit gate:** selected model beats HAND-only and current D19 on held-out data and passes negative controls.

### Phase 4 — Replace hydro fixture with real evidence

- [ ] Correctly ingest/de-accumulate ERA5-Land.
- [ ] Add catchment aggregation and fixed-climatology anomalies.
- [ ] Evaluate multiple antecedent/event windows.
- [ ] Validate August 2023 and at least one dry/negative period.
- [ ] Remove or watermark fixture in production.

**Exit gate:** trigger claims are based on real data, with hindcast metrics and provenance.

### Phase 5 — Redesign map and explanations

- [ ] Add region/validation navigation.
- [ ] Implement sparse validated classes and color-safe palette.
- [ ] Add official/observed/reference and uncertainty layers.
- [ ] Add factor attribution popup and model/data provenance.
- [ ] Add area/building/road exposure summaries.
- [ ] Test with technical and nontechnical users.

**Exit gate:** users can distinguish susceptibility, trigger, observed extent, official hazard, and coastal exposure without reading repository docs.

### Phase 6 — Partner/world-model decision

- [ ] Prepare a concise technical note and demo for Aleks/Planet contacts.
- [ ] Ask specifically for event imagery, validated extents, and evaluation feedback—not generic endorsement.
- [ ] Decide whether the available event/time-series corpus supports a learned predictive model.
- [ ] If yes, write a separate research plan with event-held-out benchmarks; if no, retain the interpretable screening architecture.

## 11. Experiment log

Append each experiment; never overwrite an unfavorable result.

| ID | Date | Code/model version | Data/labels | Split | Change | Primary metrics | Altitude audit | Decision |
|---|---|---|---|---|---|---|---|---|
| E000 | 2026-07-11 | Pre-provenance D19 outputs | 146 PNGs, top-500 candidates | Diagnostic only | Initial visual/candidate audit | Median warm ≈98.4%; median strongly red ≈90.1% | Candidate-tail analysis inconclusive; full-grid export missing | Reject current display; build diagnostics |
| E001 | 2026-07-11 | `D19-baseline-v1`, digest `11560dd7d57b0e51` | 360,790 samples from 145 land-bearing tiles; 146 PNGs | Equal quota by score decile per tile; descriptive only | Full Phase-0 baseline audit + altitude ablations | Median warm 0.9879; strongly red 0.9219; candidate max-tile share 0.12 | Overall Pearson −0.4742 / Spearman −0.5057; per-region Pearson: Koper −0.7675, Ljubljana −0.8181, Kamnik −0.6239; removing elevation+slope still −0.3825 | Freeze D19 as non-default baseline; acquire labels and build mosaic hydrology before selecting weights |
| E002 | 2026-07-11 | `D19-baseline-v1` | Official DRSV IKPN Q100 + validity; 151,435 eligible samples, 55,309 Q100-positive | Descriptive held reference; per-tile stability, no fitting | Compare D19 with HAND/TWI/no-elevation-slope baselines | D19 ROC-AUC 0.5972 / AP 0.4109; HAND-only ROC-AUC 0.6908 / AP 0.4985; median tile AUC 0.6239 (IQR 0.5285–0.7415) | D19 region AUC: Koper 0.5368, Ljubljana 0.6117, Kamnik 0.6648 | Reject D19 as selected model; use HAND-only as minimum baseline and build mosaic HAND before fitting |

## 12. Decision gates

### Gate A — Can this be called flood risk?

No, not currently. “Risk” requires hazard plus exposure/vulnerability and usually probability/consequence. Use “susceptibility” until those components exist.

### Gate B — Can scores be percentages?

No, not currently. Only use percentages for calibrated probabilities or clearly labeled percentiles/area shares.

### Gate C — Can D19 remain the default public layer?

Not in its current full-heatmap form. It may remain as a labeled baseline toggle while the validated model is developed.

### Gate D — Is a world model the next step?

No. Validation data, mosaic hydrology, and honest baselines have much higher expected value. Revisit after a multi-event dataset exists.

## 13. Immediate next actions

Do these in order:

1. Create the diagnostic export and `analyze_model.py` baseline report.
2. Correct public labels and default color behavior.
3. Acquire/rasterize official hazard and August 2023 observed data.
4. Build mosaic-level Savinja hydrology.
5. Run baselines/ablations with spatial block validation.
6. Only then select/reweight/refit the model.

## 14. Reference starting set

Primary/official sources reviewed for this plan:

- Slovenian government flood hazard/risk maps (Q10/Q100/Q500 extent and depth): https://www.gov.si/teme/karte-poplavne-nevarnosti-in-karte-poplavne-ogrozenosti-za-obmocja-pomembnega-vpliva-poplav/
- ARSO report on the 4–8 August 2023 floods: https://www.arso.gov.si/vode/poro%C4%8Dila%20in%20publikacije/Porocilo_visoke_vode_in_poplave_avg2023.pdf
- NWM–HAND evaluation against remotely sensed inundation: https://nhess.copernicus.org/articles/19/2405/2019/
- USGS discussion of uncertainty sources in inundation maps: https://www.usgs.gov/publications/sources-uncertainty-flood-inundation-maps
- ERA5-Land data/accumulation documentation: https://confluence.ecmwf.int/pages/viewpage.action?pageId=505384848
- Sen1Floods11 event-mapping benchmark: https://openaccess.thecvf.com/content_CVPRW_2020/html/w11/Bonafilia_Sen1Floods11_A_Georeferenced_Dataset_to_Train_and_Test_Deep_Learning_CVPRW_2020_paper.html
- Prithvi flood-mapping assessment (foundation-model comparison): https://arxiv.org/abs/2309.14500

## 15. Restart instructions

If resuming cold:

1. Read `AGENTS.md`, `DECISIONS.md`, this file, and `HANDOFF.md`.
2. Run `git status --short`; preserve unrelated user changes.
3. Find the first unchecked item in the active phase.
4. Record experiment inputs and outputs in Section 11.
5. Add accepted architectural/model decisions to `DECISIONS.md`.
6. Before publishing, rerun the validation report and inspect Savinja, Ljubljana, Koper, tile seams, and negative controls.
