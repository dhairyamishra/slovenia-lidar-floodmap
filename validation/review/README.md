# Upper Savinja / Ljubno ob Savinji August-2023 manual review contract

This directory contains the versioned schema for human review decisions. It is
deliberately separate from `validation/data/`: raw imagery, Copernicus source
products, and generated review queues remain ignored; approved reviewer
decisions can later be committed with provenance.

## Generate the candidate queue

```powershell
.venv\Scripts\python.exe extract_emsr680_observed_events.py
.venv\Scripts\python.exe observed_event_labels.py queue
```

The queue contains **candidates**, not labels. It comes from Copernicus EMSR680
and marks every item `pending`.

## Record decisions

Copy `upper_savinja_2023_label_schema.json` to a dated decision file and replace its
empty `decisions` array with only reviewed items. Every `flooded` or
`not_flooded` decision must name the evidence source/sheet and rationale. Use
`uncertain` if the imagery is ambiguous. Never infer dry land merely because a
source has no polygon.

Validate before any later data preparation:

```powershell
.venv\Scripts\python.exe observed_event_labels.py validate --decisions validation/review/upper_savinja_2023_reviewed_labels.json
```

No decision file is included yet because a geographically matching, supported
post-event imagery source has not been acquired. A reviewer must use approved
Upper Savinja imagery before creating labels.
