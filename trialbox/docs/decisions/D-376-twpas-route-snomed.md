# D-376 The TWPAS route is the IG's SNOMED CT oral code; amends D-342

- **Task:** T-676b, TWPAS route coding (batch E, follow-up of T-676 and D-372)
- **PR:** this branch (`agent/T-676b-twpas-route`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Amends:** D-342 item 4 (the TWPAS route code)

## Context

D-342 changed the TWPAS medication route from SNOMED CT to TW Core `medication-path-tw#PO`, so that the box ships
no SNOMED CT. TWPAS 1.2.5 (the version in settings, D-372) binds `MedicationRequest.dosageInstruction.route.coding`
(1..1) to its value set `medication-path-sct-tw` with strength required. The value set holds SNOMED CT routes and
twelve TW Core codes. `PO` is not one of them, and no code outside SNOMED CT means oral. The pinned validator 6.10.4
gave the synthetic bundle 7 errors, all from the route. The profile allows one coding, so `PO` cannot stay beside a
second coding.

## Decision

1. The bundle builder writes the route as SNOMED CT `26643006` (oral route), the code the IG's value set lists, and
   `route.text` `口服`. It writes no SNOMED CT display or other description.
2. D-342 item 4 is amended for this one code only. The NHI's own IG requires it in the bundle the box sends to the
   NHI. No SNOMED CT data file ships, and the build check that refuses one stays as it is.

## Checked

Validator 6.10.4, offline (`-tx n/a`), cache from `make jvm-deps`, IG `tw.gov.mohw.nhi.pas#1.2.5`, the synthetic
bundle of `tests/unit/test_twpas_unit.py`: 7 errors before, 0 after.

## Open

- **Licence.** The register row `snomed-ct` says no SNOMED CT code ships until an affiliate licence is held, and
  Taiwan is not a SNOMED International member. Whether one code that the NHI's IG mandates needs that licence is
  for the owner to confirm (inquiry TB-LIC-01). If it does, the TWPAS bundle cannot validate against 1.2.5 without
  it.
