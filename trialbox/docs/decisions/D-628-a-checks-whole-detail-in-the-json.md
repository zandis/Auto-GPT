# D-628 The end-to-end tools keep a check's whole detail in their JSON

- **Task:** E2E-DETAIL (asked by lane G after GPU run C, through the integrator, 2026-11-13)
- **PR:** this branch (`agent/E2E-DETAIL-whole-detail-in-the-json`)
- **Date:** 2026-11-13
- **Status:** accepted

## Context

`tools/e2e_simple.py` and `tools/public_e2e.py` record each check as (what, ok, detail). `Stage.check` cut the
detail at 300 characters when it was recorded, so the JSON written with `--json` (and the parts
`tools/complete_run.py` collects on the GPU) held the cut text too. A failed check on the GPU run lost the part
of its detail that said why, and the run cannot be repeated cheaply.

## Decision

The detail is recorded whole. The cut to 300 characters is made where a failed check is printed (`report`), and
a cut line ends with a mark saying how many characters the JSON holds. The JSON is the record; the printed
report is the summary.

## Consequences

- A run's JSON grows when a check fails with a long detail; a passing run is as before in print.
- The details are what the tools already recorded: synthetic or public data, no new field.
