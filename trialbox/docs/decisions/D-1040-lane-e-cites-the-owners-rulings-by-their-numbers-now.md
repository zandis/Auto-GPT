# D-1040 Lane E cites the owner's rulings of 2026-11-16 by their numbers now

- **Task:** E-RENUM (the integrator's correction of its own numbering, on PR #897 and to lane E)
- **PR:** this branch (`agent/E-RENUM-owner-ruling-numbers`)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** `docs/decisions/OWNER-RULINGS-2026-11-16.md` (the mapping), D-1021, D-1024, D-1027, D-1028, D-1029

## Decision

The owner's rulings were relayed to the lanes as D-520 to D-537, but those numbers already belong to decisions on
master. The integrator renumbered the rulings D-1020 to D-1037, keeping the last two digits. Lane E's records, code
comments and tests had cited them under the relayed numbers. Each such citation now carries the ruling's number:

- D-521 → D-1021 (REDCap downloaded for testing, in lane E's private container): D-847 to D-853, the RC13 tests,
  `services/rc_bridge/client.py`, `tools/redcap_instance.py`.
- D-524 → D-1024 (REDCap 13.7 is supported): D-852, its REGISTRY row and its test.
- D-527 → D-1027 (the build dates removed, the freeze lifted): D-853 to D-857.
- D-528 → D-1028 and D-529 → D-1029 (terminology loaded at install; public-domain code data may ship): D-858, its
  REGISTRY row, `criteria_compiler/terminology` (`installed.py`, `mapper.py`), `tools/terminology_install.py`,
  `tools/trialbox/doctor.py`'s terminology check, the TERM-1 test and `TB_TERMINOLOGY_DIR`'s note in
  `libs/tb_common/config.py`.

The integrator's list covered master at `9d5853f3`. The citations in D-856 to D-858 and their files came later, with
EDC-011, EDC-019 and TERM-1. A bare D-520 to D-537 that means the decision holding that number stays as it is, for
example `doctor.py`'s NEW-B-3 (D-522). Only text changes: no behaviour, no test expectation.
