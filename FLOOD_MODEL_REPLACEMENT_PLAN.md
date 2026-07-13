# Flood Terrain Model Replacement Plan

**Status:** Approved and in progress. Phases 1–4 complete (D24–D27); Phase 5 benchmark implemented but no candidate selected. D30 completes the real categorical Q100 comparison required by A3.

**Prepared:** 2026-07-12

**Progress:**

- [x] Phase 1 — communication repair, DRSV validity/depth, Q100 comparison.
- [x] Phase 2 — validation rasters, locked spatial splits, negative controls.
- [x] Phase 3 — Savinja mosaic hydrology.
- [x] Phase 4 — Ljubljana mosaic hydrology.
- [ ] Phase 5+ — model benchmark, sparse production output, scenario evidence.

**Phase-5 gate update (D28):** B0/B1/B2/M1/M2, spatial folds, TWI/slope additions, negative controls, and distance applicability were implemented. No candidate met all approved development thresholds, so the locked test remains closed and no replacement is selected or published.

**Comparison update (D30):** A3 no longer relies on semitransparent source-layer stacking. A committed 2 m derived product now classifies official-only, D19-only, both, neither, missing D19 data, and outside-validity cells; the app adds exact regional area shares and click interpretation.

**Problem:** The frozen `D19-baseline-v1` overlay renders most low, flat land as strongly red. It is visually alarming, strongly associated with elevation, and performs worse than HAND-only against the official DRSV Q100 reference. The replacement must reduce false positives through drainage connectivity and scenario evidence, not cosmetic weight or color changes.

## 1. Evidence and proposed decision

| Diagnostic | D19 result | Interpretation |
|---|---:|---|
| Median warm display area | 98.79% | Continuous display is saturated |
| Median strongly-red area | 92.19% | Visual implies widespread danger |
| Score/elevation Pearson | -0.4742 | Strong altitude shortcut |
| Ljubljana score/elevation Pearson | -0.8181 | Basin floor is treated as broadly susceptible |
| DRSV Q100 ROC-AUC | 0.5972 | Weak separation inside official validity |
| DRSV Q100 average precision | 0.4109 | Weak positive-class ranking |
| HAND-only ROC-AUC | 0.6908 | Simpler drainage-relative baseline is better |
| HAND-only average precision | 0.4985 | Minimum replacement benchmark |

Proposed decisions for approval:

1. Freeze D19 permanently as an experimental comparison baseline.
2. Do not retune D19 from visual inspection.
3. Separate immediate risk-communication repair from model-quality work.
4. Build continuous mosaic hydrology before fitting a replacement.
5. Treat HAND-only as the minimum performance baseline.
6. Use DRSV products as scenario references only inside their validity domain.
7. Do not call a learned score “flood probability” without independent event calibration.

## 2. Product semantics

| Product | Question answered | Allowed claim |
|---|---|---|
| Official DRSV Q10/Q100/Q500 | What does the published hydraulic study map? | Official scenario hazard extent within validity |
| Static terrain screening | Where does terrain have drainage-relative susceptibility? | Validated screening class/score, not annual probability |
| Scenario inundation | Where is water estimated to reach for a defined stage/discharge? | Estimated extent/depth under stated assumptions |
| Observed event extent | What was actually observed to be wet? | Observation with source limitations |
| Hydroclimate trigger | When is the catchment primed? | Antecedent/event indicator, not inundation |

The first cycle improves the first two products. Scenario inundation requires stage/discharge work later.

## 3. Non-goals

- Do not make the map look safer by changing only the palette or choosing an arbitrary cutoff.
- Do not fit and evaluate new weights on the same full Q100 sample.
- Do not treat locations outside DRSV validity as confirmed dry negatives.
- Do not merge Koper coastal SLR exposure into the riverine model.
- Do not use random pixel splits.
- Do not introduce deep-learning or “world model” claims without multiple independent events.
- Do not delete D19 outputs; retain them for reproducible comparison.

## 4. Workstream A — immediate communication repair

This changes how current evidence is presented, not its scientific accuracy. It can ship before the replacement model.

### A1. Rename and demote D19

- Rename the control to **Experimental D19 Terrain Baseline**.
- Keep it and its review points off by default.
- Make the official DRSV reference visually/textually primary.
- State that D19 failed the current selection gate and is retained for comparison.
- Replace “lower/higher risk” with “lower/higher experimental score.”

### A2. Replace the alarming continuous display

- Use a color-safe non-hazard palette such as transparent lavender → purple.
- Add two display modes:
  - **Review mask:** only the upper screening band is visible.
  - **Full diagnostic surface:** continuous values for technical review.
- Version the review-mask rule and expose it in provenance.
- Until validation selects a threshold, label it a **display percentile**, not a hazard threshold.
- Retain the original raw score raster for auditing.

### A3. Add official validity and agreement context

- Add the DRSV hydraulic-study validity domain as an outline/fill.
- Add a comparison display inside validity only: official Q100 only, D19 only, and overlap.
- Never classify absence outside validity as a model false positive.
- Add Q100 depth classes from the already acquired DRSV IKG layers.

### A4. Acceptance gate

- D19 and review points remain off on initial load.
- Users can distinguish official extent, validity, experimental signal, and overlap without repository documentation.
- No D19 legend uses “probability,” “danger,” “safe,” or modeled depth.
- Browser checks pass at desktop and narrow widths.

**Rollback:** Revert web assets/controls; D19 analytical outputs remain unchanged.

## 5. Workstream B — lock validation before fitting

The existing whole-dataset Q100 evaluation rejects D19, but cannot be the model-selection test once development uses it.

### B1. Versioned evaluation rasters

- Rasterize validity, Q10/Q100/Q500, Q100 depth, and hazard classes to a common grid.
- Preserve 2 m analysis, but evaluate at 10 m and 20 m for boundary/geolocation sensitivity.
- Create boundary-buffer variants for ambiguous polygon edges.
- Record source, CRS, acquisition digest, rasterization parameters, and output digest.

### B2. Spatial development and locked-test blocks

- Assign contiguous blocks before fitting and commit their membership.
- Use Savinja as the hydrology engineering pilot, not the only final test.
- Reserve contiguous Ljubljana blocks for locked urban/basin evaluation.
- Keep Koper riverine assessment separate from coastal SLR.
- Never reassign blocks after viewing test results without a new experiment version.

### B3. Negative controls

Inside official validity, include:

- low flat urban land outside Q100;
- terraces above nearby channels;
- flat hilltops;
- disconnected depressions;
- protected/embanked land where mapped;
- cells similar in absolute elevation but different in channel-relative position.

### B4. Acceptance gate

- Every cell is positive, negative, ambiguous, or outside applicability.
- Development/test blocks remain separated after a spatial buffer.
- Baselines reproduce D19 and per-tile HAND results.
- Reports include ROC-AUC, PR-AUC, IoU/F1, recall, false-positive rate, bias ratio, and negative-control false-positive rate.
- Locked test data is not used for feature, threshold, or hyperparameter selection.

## 6. Workstream C — continuous mosaic hydrology

### C1. Savinja 5 × 5 pilot

- Assemble 25 DTMs into one EPSG:3794 mosaic.
- Retain ground-coverage and tile-provenance masks.
- Quantify raw seam differences before conditioning.
- Use overlap/halo data where available and document conflict resolution.
- Store large intermediates in ignored `output/`.

### C2. Terrain conditioning

- Add priority-flood depression filling plus a breaching sensitivity option.
- Separate real depressions from data artifacts where possible.
- Align the official flow network and inspect CRS/offset errors.
- Test gentle stream enforcement separately; never silently carve the final DEM.
- Preserve the raw DTM and conditioning delta.

### C3. Mosaic features

- D8 receiver and accumulation across the complete mosaic.
- One multiple-flow-direction sensitivity run.
- Stream mask/order under several contributing-area thresholds.
- Mosaic HAND and horizontal channel distance.
- Valley-relative elevation/local relief.
- Connectivity and outlet identifiers.
- Optional embankment/barrier candidates for later review.

### C4. Cut back to web tiles

- Split mosaic features into existing tile bounds only after routing completes.
- Never recompute hydrology per tile.
- Add feature provenance and mosaic digest to manifests.
- Keep per-tile hydrology behind an explicit baseline flag.

### C5. Ljubljana extension

- Apply the same code path to the 10 × 10 Ljubljana mosaic.
- Measure memory/runtime; add chunked or memory-mapped storage if required.
- Explicitly document urban drainage and barrier limitations.
- Do not assume LiDAR captures underground stormwater drainage.

### C6. Acceptance gate

- Flow, accumulation, stream order, HAND, and channel distance are continuous across every interior seam.
- No cell receives low HAND solely because it is a tile-edge outlet.
- Conditioning changes are summarized and reviewable.
- Derived channels align with official flow lines under a documented tolerance.
- Mosaic HAND beats or matches per-tile HAND on development blocks.
- Results are stable under reasonable stream-threshold and D8/MFD sensitivities.

**Rollback:** Select hydrology/model version explicitly; retain D19 reproduction.

## 7. Workstream D — benchmark replacement models

Implement candidates in increasing complexity:

1. **Frozen references:** D19 and per-tile HAND-only.
2. **Mosaic HAND-only:** optional maximum channel-distance applicability; no absolute elevation.
3. **Drainage rules:** HAND + channel distance + valley-relative elevation + stream order/contributing area + connectivity.
4. **Constrained statistical model:** regularized logistic/additive model, drainage-relative inputs first.
5. **Tree challenger:** constrained inspectable tree model only after interpretable baselines exist.

Add slope, TWI, land cover, canopy, or imperviousness one at a time. Retain a feature only when it improves spatially held-out performance without worsening negative controls.

### D1. Model-selection gate

The selected model must:

- beat mosaic HAND-only on locked blocks, not merely D19;
- improve both ROC-AUC and average precision under a predeclared rule;
- materially reduce false positives on low/flat controls;
- avoid a strong residual absolute-elevation shortcut;
- remain stable by region, elevation, channel distance, and urban/non-urban class;
- provide an applicability mask, model card, and reproducible digests.

Proposed practical thresholds to approve before fitting:

- at least +0.03 held-out ROC-AUC and +0.03 held-out average precision over mosaic HAND-only;
- at least 30% relative reduction in negative-control false-positive rate at the chosen operating point;
- no more than 5 percentage points of recall loss unless justified by the screening use;
- no absolute-elevation term unless its held-out contribution is positive and shortcut audits pass.

These are proposal thresholds, not established scientific standards.

## 8. Workstream E — sparse reporting thresholds

### E1. Threshold selection

- Select thresholds on development blocks only.
- Tie them to an intended use: maximum false-positive rate or minimum recall.
- Report confusion matrix and affected land area for each candidate.
- Test threshold stability across spatial folds.

### E2. Output semantics

- transparent: below threshold or outside applicability;
- elevated screening signal;
- high screening signal;
- blue reserved for official/observed/modeled water;
- ambiguity shown with hatching, outline, or desaturation.

These are screening classes, not Q10/Q100 probabilities.

### E3. Acceptance gate

- Default output is sparse enough for inspection without implying universal flooding.
- Every class has held-out metrics or an explicit non-statistical display definition.
- UI shows applicability and uncertainty.
- Popups expose model version, class meaning, HAND/channel context, and DRSV validity status.

## 9. Workstream F — scenario estimates

This is required for our own defensible inundation extent/depth.

### F1. Evidence and forcing

- Acquire ARSO gauge metadata, discharge, stage, and precipitation.
- Obtain an official or vetted Sentinel-1 August 2023 Savinja extent.
- Add at least one dry period and preferably more independent flood events.

### F2. Rapid stage/HAND baseline

- Associate channels with reaches.
- Add stage/discharge for a named event or return-period scenario.
- Build or ingest reach rating relationships.
- Convert water-surface elevation to connected extent and approximate depth.
- Compare against official Q scenarios and observed events.

### F3. Hydraulic-model decision

- If rapid HAND/stage mapping misses the accuracy target, integrate 1D/2D hydraulics.
- Include channel geometry, roughness, structures, barriers, and boundary conditions where available.
- Keep terrain screening as triage, not an engineering substitute.

### F4. Probability gate

Do not show cell-level probability unless the target is defined, multiple independent events/basins exist, calibration passes held-out-event testing, and uncertainty/domain limits are visible. Until then use “screening score,” “estimated scenario extent,” or “approximate depth” as appropriate.

## 10. Implementation order

| Phase | Scope | Deliverable | Exit condition |
|---|---|---|---|
| 1 | Communication repair | Honest D19/DRSV comparison UI | **Complete — D24** |
| 2 | Validation lock | Rasters, spatial blocks, controls | **Complete — D25** |
| 3 | Savinja mosaic | Continuous conditioned hydrology | **Complete — D26** |
| 4 | Ljubljana mosaic | Continuous basin features | **Complete — D27** |
| 5 | Model benchmark | Candidate comparison/model card | **Implemented; selection gate failed — D28** |
| 6 | Sparse production output | Validated classes/applicability | E3 |
| 7 | Event/scenario evidence | Savinja hindcast and stage/HAND | F2 evaluated |
| 8 | Hydraulic/probability decision | Evidence-based scope decision | F3/F4 recorded |

## 11. Expected repository changes

| Area | Expected work |
|---|---|
| `web/index.html`, `web/style.css`, `web/app.js` | D19 demotion, validity/agreement, sparse classes, provenance |
| `pipeline.py` | Preserve D19; consume mosaic features for new versions |
| `kernels.py` | Mosaic-safe routing/HAND kernels or adapters and seam tests |
| `mosaic_hydrology.py` | Mosaic assembly, conditioning, routing, feature export |
| `validation/` | Raster spec, spatial splits, controls, provenance |
| `evaluate_validation.py` | Spatial folds, buffered metrics, thresholds, controls |
| `model_diagnostics.py` | Shortcut, ablation, applicability, uncertainty reports |
| `web/data/validation/` | Compact validity/depth/agreement assets |
| Tests | Seam, conditioning, model, metric, and web-contract tests |
| `DECISIONS.md` | Accepted architecture/model decisions |
| `HANDOFF.md` | Phase-by-phase restart state |

Large rasters and fitted artifacts remain under ignored `output/` unless a compact reproducible web asset must be committed.

## 12. Verification checklist

- Unit tests for numerical and data-contract behavior.
- Deterministic digests for fixed inputs.
- Python/JavaScript syntax checks and `git diff --check`.
- Before/after diagnostic report, including unfavorable results.
- Desktop and narrow-width browser verification for UI changes.
- No silent mosaic-to-per-tile fallback.
- No probability/depth wording without the relevant model.
- Append decisions and experiments; never overwrite prior failures.

## 13. Review decisions requested

Please approve or change:

1. Rename D19 to “Experimental D19 Terrain Baseline,” use a neutral sparse display, and add validity/agreement context.
2. Keep all analytical layers off, or show official Q100 by default.
3. Use Savinja as the smaller mosaic pilot, followed immediately by Ljubljana.
4. Keep HAND-only as the minimum baseline; D19 cannot return without beating it on held-out data.
5. Use the proposed +0.03 AUC/AP and 30% negative-control improvement gate.
6. Keep the next release at “validated screening”; delay extent/depth claims until stage/discharge or hydraulics exist.

## 14. First implementation slice after approval — complete

Workstream A only:

1. Add official validity geometry and Q100 depth assets.
2. Rename and visually demote D19.
3. Add sparse review/full diagnostic modes.
4. Add Q100 comparison/overlap inside validity.
5. Update explanations/provenance.
6. Add web-contract tests and browser verification.
7. Record the semantics decision in `DECISIONS.md`.
8. Commit and push as one reversible change.

No D19 weights or susceptibility PNGs change in this first slice.
