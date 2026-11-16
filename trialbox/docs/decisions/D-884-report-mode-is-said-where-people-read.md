# D-884 the release gates' mode is said where people read the release

- **Task:** I-7 (release.json report mode), the integrator's answer on #639: option (a) only
- **PR:** this branch (`agent/I-7d-report-mode-is-said-where-people-read`)
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

release.json already carries `gates.vuln_mode`. The box's installed record (`deploy/updates/installed.json`) keeps
it as `vuln_mode`; `apply_update.sh status`, the install summary ("Release gates:") and `tools.release check` say it,
and every mode other than `block` is followed by "not a green release". The record and the gates are unchanged.

## Test

`tests/unit/test_release_gates_mode_shown.py`: before, 7 failed; after, 8 passed.
