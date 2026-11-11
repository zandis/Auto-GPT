# G1b gate record: the model pair on the owner's B200 (T-114, D-428)

- **Status:** not run. The bundle builder, the owner's script, the record format and the `doctor --platform`
  comparison are in place and tested with stand-ins (`tests/unit/test_b200_qualify.py`); the run waits for the owner
  or the named operator (Q-12) on the B200 (GPU ledger row B2).
- **How:** RUNBOOK §11 "G1b on the owner's B200". The run writes `g1b-record.json` (schema
  `schemas/b200_qualification_record.schema.json`) and this file from it (`python -m tools.b200_qualify record`).
  Replace this file with the generated one and add the record and both layouts' serving records next to it.
- **Host:** the owner's B200, not CGMH's partition (RSK-52). The record carries the host fingerprint of each layout.

## Layouts

| Layout | MIG | Serving record | Qualification | Note-stage s p50 / p95 | Status |
| --- | --- | --- | --- | --- | --- |
| small | judge=2g.45gb,verifier=1g.23gb | not run | not run | not run | not run |
| large | judge=3g.90gb,verifier=3g.90gb | not run | not run | not run | not run |
