# D-363 One record inventory, mapped to every table the code creates

- **Task:** T-643 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-643-record-inventory`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** REG-022

## Context

The deep review of 2026-11-10 (REG-022) found no inventory of the records TrialBox makes or holds: the screening log,
the delegation-log copy, consent checks, the SAE register, EDC drafts, decisions, signatures and the "sent" ledger.
Nobody had written which are essential records, source, copies or working aids, who keeps them and for how long.
`docs/SECURITY.md` §7 left it to legal review. The review asked for a one-page table signed by each site's trial
office; D-311 removed signers.

## Decision

1. **`docs/validation/record-inventory.md` is the inventory.** One row per record: class (essential, source, copy,
   aid, control), system of record, keeper, retention, ISF export and audit events. Stores that are not records have
   their own short table with the reason.
2. **The store map ties it to the code.** Every table a module under `services/` or `libs/` creates has one row in
   the map. `tests/unit/test_record_inventory.py` fails on a missing or stale row; `tools/gen_traceability.py`
   warns under `--check` and fails under `--strict` (D-311 S7). A new table therefore needs a decision on what kind
   of record it is, in the same pull request.
3. **The release record carries it.** `tools/gen_traceability.py --records` prints the records table; the release
   step files it as item 9 of the release record.
4. **The box does not set the trial's retention period.** "Kept" means no job of the box deletes the record; the
   period after the study is archived is the sponsor agreement's and the law's.
5. **No signature.** A site that wants the page signed prints it (D-311).

## Consequences

- Card T-304 (ISF bundle) builds its export from the rows marked "page only".
- A per-study retention setting is not built; it is listed as not done in the inventory.
