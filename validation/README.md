# Validation data contract

This directory defines the independent evidence used to evaluate the LiDAR
screening model. Generated/downloaded data lives under `validation/data/` and is
gitignored; `sources.json` and acquisition metadata remain versioned.

## Official static references

The initial machine-readable source is the DRSV ArcGIS REST service in
EPSG:3794. The configured layers include:

- IKPN hydraulic-study validity plus Q10, Q100, and Q500 flood-hazard extents;
- IKG Q100 depth classes: below 0.5 m, 0.5–1.5 m, and at least 1.5 m;
- IKRPN high, medium, low, and residual hazard classes;
- official hydrography flow lines for later alignment/mosaic diagnostics.

The OPSI catalogue describes IKPN as an open CC BY 4.0 dataset. Licensing and
update timestamps must be captured again at acquisition time rather than
assumed forever.

## Acquisition

```powershell
python download_validation.py
python download_validation.py --layer ikpn_q100 --layer official_flow_lines
```

The downloader reads the current study union from `web/data/manifest.json`,
queries each ArcGIS feature layer with that EPSG:3794 envelope, follows result
pagination, and writes:

- `validation/data/<layer>.geojson`;
- `validation/data/acquisition_manifest.json` with source URL, query envelope,
  feature count, timestamp, and SHA-256 digest.

Downloaded polygons are reference labels, not automatically perfect truth.
Hydraulic study coverage, age, boundary uncertainty, and scenario semantics
must remain visible in evaluation.

## Frozen evaluation contract

`evaluation_contract.json` locks the label layers, 2 m / 10 m / 20 m grids,
Q100 boundary-ambiguity buffers, spatial development/guard/locked-test rules,
and deterministic Q100-negative control cohorts before replacement fitting.

```powershell
python prepare_validation_contract.py
python evaluate_validation.py
```

The generator writes nine compact versioned grids under `validation/rasters/`
and an expanded `evaluation_manifest.json` with tile assignments, cell counts,
and digests. Areas outside IKPN validity are unknown. Cells within the primary
10 m Q100 boundary band are ambiguous. Koper is evaluation-only for riverine
selection. The locked test must not guide Phase-3/4 feature engineering.

## Still missing

The static hazard layers do not prove what flooded on 4 August 2023. Phase 1
still requires a vetted Upper Savinja event footprint plus ARSO forcing/gauge data.
Do not train or select model weights using only the static layers and call the
result a 2023 hindcast.

## Upper Savinja / Ljubno ob Savinji August-2023 observed-event evidence

`prepare_event_evidence.py` inventories the public sources needed for a
conservative Upper Savinja event-label workflow. It writes ignored source metadata
and downloads only sources explicitly requested. Start with the small
post-event imagery sheet index and the Copernicus event package; the RGB/CIR
archives are multi-gigabyte and must not be downloaded wholesale before the
sheet index identifies the review subset.

```powershell
python prepare_event_evidence.py --source emsr680_products
python prepare_event_evidence.py --source emsr680_products --download
```

The evidence inventory is not a flood footprint. Phase B will create a
versioned label package only after imagery alignment and human review of
ambiguous candidate patches. `sources.json` records source dates, licences,
use, and limitations for this work; it also records ARSO and deferred ERA5-Land
context without treating either as acquired evidence.

After the EMSR680 archive is acquired, extract its flood polygons as explicitly
unreviewed context:

```powershell
python extract_emsr680_observed_events.py
```

This writes ignored all-Slovenia and current-Upper-Savinja-intersection GeoJSON files,
plus a product catalogue. The output is not an observed flood label, does not
mark unobserved land as dry, and must not be used for model fitting until the
Phase-B image review package exists.

Official starting points:

- DRSV IKPN service: https://geohub.gov.si/ags/rest/services/DRSV/IKPN/MapServer
- DRSV IKG service: https://geohub.gov.si/ags/rest/services/DRSV/IKG/MapServer
- DRSV IKRPN service: https://geohub.gov.si/ags/rest/services/DRSV/IKRPN/MapServer
- OPSI IKPN catalogue: https://podatki.gov.si/dataset/integralna-karta-poplavne-nevarnosti-ikpn
- ARSO August 2023 report: https://www.arso.gov.si/vode/poro%C4%8Dila%20in%20publikacije/Porocilo_visoke_vode_in_poplave_avg2023.pdf
