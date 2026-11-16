# D-855 The EDC's lake reader is tested on a lake

- **Task:** EDC-020 (deep review 2026-11-12, Medium, E-24; wave 6, unfrozen by D-1027)
- **PR:** this branch (`agent/EDC-020-lakefacts-on-a-lake`)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** D-684 (site facts read from the lake's own answer), D-598 (each row carries its code system)

## Decision

1. `edc.prefill.LakeFacts` (the SQL that feeds every EDC draft) is tested on a lake built by the lake's own rebuild
   from synthetic FHIR files holding the stand-in's patient: the patient, the observations with their system, the
   condition, the note (dated, whole), an unknown source and an unknown patient. A draft built on that lake holds the
   same values as one built on `tests/edc_kit.FakeFacts`.
2. The lake writes a patient's sex as FHIR's word (`male`) where the stand-in writes `M`; the draft reads both as one
   value (prefill's sex map), which the draft comparison pins.
3. A test-only card: no product code changes. Breaking the observation query's date column makes two of the four
   tests fail.
