# Upper Savinja Observed-Event Enhancement Plan

**Status:** Implementing. Phase A is complete with one documented source-access limitation; no model or public map claim changes until the gates below pass.

**Prepared:** 2026-07-13
**Study area:** Upper Savinja Valley around Ljubno ob Savinji, centred on the August 2023 flood event
**Purpose:** Replace the misleading "low and flat means doomed" behaviour with a tested, event-aware terrain-and-connectivity workflow. This plan does **not** authorize reweighting or cosmetically recolouring D19.

## 1. What problem this solves

The frozen D19 terrain baseline is a hand-weighted screening score. It overflags broad, low, flat land because elevation, slope, TWI, and related terrain signals co-occur there. It lacks sufficient evidence of:

1. a connected path from flood water to the cell;
2. the amount and timing of water supplied by the upstream catchment; and
3. whether water was observed there in a real event.

The public app already handles this honestly: D19 is off by default and demoted to an experimental comparison baseline; the official Q100 reference and categorical comparison remain available. This work must preserve those safeguards until a candidate genuinely passes selection.

## 2. Product question and allowed claim

The first target is deliberately narrow:

> For the August 2023 Upper Savinja event, can drainage-relative terrain features plus public event evidence distinguish observed flood footprint from nearby non-flooded controls better than the current HAND-only baseline?

Allowed result if successful: **an August-2023 Upper Savinja hindcast screening model**, with published uncertainty and event/area limits.

Not allowed without additional independent events and calibration:

- real-time flood forecast;
- flood probability, depth, damage, or evacuation advice;
- nationwide hazard claim;
- replacing the official DRSV Q100 planning reference.

## 3. Evidence package

| Evidence | Role | Initial public source | Status / limitation |
|---|---|---|---|
| CLSS LiDAR | 2 m terrain and surface context | Existing local GKOT data | Available; does not represent pipes, culverts, levees, or live water |
| DRSV hydrography, catchments, water structures | Mapped flow paths, channels, ditches, barriers and upstream context | OPSI / DRSV hydrology services | To acquire and validate geometry/alignment |
| DRSV Q10/Q100/Q500 and validity | Static planning comparator and controls | Existing validation contract | Available; not an August-2023 observed footprint |
| 7–8 Aug 2023 post-flood orthophotos | Primary observed-event interpretation evidence | GeoHub-SI / Atlas voda | To acquire; image date is after the peak and requires review |
| Copernicus EMSR680 products | Independent event map and review aid | Copernicus EMS Rapid Mapping | To acquire; may miss short-lived/rapid water, so never use as sole ground truth |
| ARSO gauge/stage/discharge and rainfall | Event timing and upstream forcing context | ARSO public data/archive | To acquire where station coverage permits |
| ERA5-Land soil moisture/rainfall/snowmelt | Optional catchment-scale antecedent context | Copernicus CDS | Deferred until user can register/accept terms; not a blocker |

## 4. Phased implementation

### Phase A — Data inventory and provenance

**Implementation record (2026-07-13):** Added `prepare_event_evidence.py`,
`validation/sources.json` event-source records, and automated tests. The
script records source URL, licence, date, intended use, limitation, HTTP
availability metadata, final URL, content metadata, and SHA-256 for acquired
files. Copernicus EMSR680 was downloaded and verified (91,222,927 bytes) under
ignored `validation/data/event_evidence/`. The previously recorded Kamniška
Bistrica/Pšata orthophoto archives were later found to cover the wrong river
basin and are now explicitly excluded. A matching Upper Savinja imagery source
still has to be acquired before human review.

**Build**

- Scripted download/inventory for Upper Savinja-relevant DRSV hydrography, catchment, and water-structure layers.
- Scripted acquisition manifest for orthophotos, Copernicus products, ARSO series, CRS, dates, licences, checksums, and coverage.
- Read-only map preview showing source coverage and image dates.

**Checks**

- Every source has a URL, timestamp, licence/use note, checksum, CRS, and known spatial/temporal limitation.
- River geometry is measured against the LiDAR DTM before it is used for conditioning; no automatic channel carving merely because a line exists.
- Explicitly record missing culvert, levee, and drainage-network coverage.

**Exit:** a reproducible data inventory. No new flood overlay yet.

### Phase B — Conservative observed-flood footprint

**Implementation record (2026-07-13, partial):** Extracted 1,498 flood
features from the acquired EMSR680 archive and found 156 that intersect the
current Upper Savinja mosaic (155 AOI07 photo-interpreted features, one AOI03
semi-automatic feature). Added `extract_emsr680_observed_events.py` and
`observed_event_labels.py`. The latter produces a deterministic 156-item
review queue and validates the required flooded/not-flooded/uncertain decision
contract. It reports 156 pending, zero labels; no item enters model fitting.
The missing official orthophoto sheet index prevents defensible human review,
so this phase remains incomplete.

**Build**

- Align pre-event and 7–8 Aug 2023 post-event imagery.
- Generate candidate water masks and a review queue; do not treat the automatic mask as truth.
- Add a compact reviewer interface: **flooded**, **not flooded**, and **uncertain**, with imagery/date/source visible at every patch.
- Produce a versioned observed-event label package containing confirmed positive cells, confirmed controls, uncertain/ignored cells, and a boundary buffer.

**Human review required**

- The user or a Slovenian flood/remote-sensing reviewer approves representative ambiguous patches, especially shadows, mud, trees, bridges, urban areas, and water that had already receded.

**Checks**

- Do not label unobservable areas as dry.
- Keep uncertain cells out of training and scoring.
- Compare against EMSR680 and official/field context only as independent checks, not as a substitute for review.

**Exit:** a conservative observed August-2023 footprint with documented completeness limits.

### Phase C — Connectivity-first features

**Build**

- Reuse the existing continuous 5×5 Upper Savinja mosaic routing, HAND, channel-distance, stream-order, local-relief, and valley-relative-elevation outputs. Its on-disk identifier is `savinja`, matching the geographic basin.
- Add measured distance/connectivity to mapped hydrography and, when trustworthy, mapped structures/embankments.
- Add catchment and gauge linkage; use ARSO time series for event metadata and later forcing features.
- Keep absolute elevation out of candidate scores by default. Treat it only as a diagnostic/control feature.

**Checks**

- Test every feature against altitude correlation and low-flat non-flooded controls.
- Inspect channel alignment and known edge/culvert limitations.
- Maintain a feature/data dictionary explaining physical meaning and failure modes.

**Exit:** a reproducible feature table for only observable, labelled cells.

### Phase D — Event-hindcast benchmark

**Candidates**

1. HAND-only baseline.
2. HAND + channel distance + connected flow path + valley geometry, with no absolute elevation.
3. The same drainage model with mapped structures where coverage supports it.
4. Optional ARSO/ERA5 catchment forcing features only after their time semantics are validated.

**Evaluation discipline**

- Spatially split by whole valley/easting blocks; keep adjacent blocks buffered to prevent near-duplicate terrain leaking across train/test.
- Maintain a final held-out Upper Savinja area that is not examined during feature selection.
- Report precision-recall, ROC-AUC, false-positive rate on nearby low/flat controls, recall, calibration only if justified, and score/elevation correlations.
- Compare against the frozen D19 and existing mosaic HAND-only baselines, but do not tune D19.

**Selection gate**

A candidate may proceed only if it improves on HAND-only on held-out observed-event data, materially reduces low-flat false positives, has no unacceptable altitude shortcut, and remains interpretable. Exact thresholds will be written before fitting, not after seeing results.

**Exit:** either one qualified, limited hindcast model or an explicit rejection report. A failed model is still a useful result and remains off the public map.

### Phase E — Public map only after selection

**If no candidate passes:**

- Keep the current official-reference-first map.
- Keep D19 as the demoted audit baseline and retain the categorical Q100 comparison.
- Publish the event-label/data-coverage limitations, not a new risk layer.

**If a candidate passes:**

- Add a separate layer named **"Upper Savinja Aug-2023 observed-event hindcast (experimental)"**.
- Use restrained, categorical colours: confirmed observed water, model agreement, model-only review signal, observed-only miss, and unavailable/uncertain.
- Require a click popup with data sources, applicability, and an explanation that it is not a live forecast or depth estimate.
- Do not display a red-to-yellow continuous danger surface or uncalibrated percentages.

## 5. Immediate implementation order

1. Implement Phase A data inventory/download clients and source manifest.
2. Acquire the post-flood imagery and EMSR680 source package; create the review-queue design from real coverage.
3. Implement Phase B labelling/review package and wait for manual approval of ambiguous samples.
4. Acquire ARSO event context and complete Phase C feature table.
5. Lock the observed-event split and thresholds, then run Phase D.
6. Update `HANDOFF.md`, the experiment log, and `DECISIONS.md` after every completed phase/accepted technical decision.

## 6. What is not in this enhancement

- No change to the frozen D19 weights or display to manufacture a better-looking result.
- No ERA5-Land dependency before CDS registration succeeds.
- No public model replacement based only on static Q100 labels or imagery-derived labels from one event.
- No automatic claim that black/transparent map areas are safe.

## 7. Success looks like this

Instead of a map saying "most flat land is red," the viewer sees:

1. the official planning reference where available;
2. a clearly dated observed August-2023 footprint where imagery supports it;
3. an experimental hindcast only if it independently performs well; and
4. explicit unknown/uncertain areas.

That makes false positives visible and measurable, rather than hiding them behind a different colour ramp.
