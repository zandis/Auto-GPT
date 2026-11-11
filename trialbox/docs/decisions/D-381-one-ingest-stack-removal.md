# D-381 One ingest stack, the removal: dataplat is gone, its controls are in the adapter

- **Task:** T-659b (wave of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-659b-one-ingest`)
- **Date:** 2026-11-11
- **Status:** accepted (carries out D-370; D-311: no gate)
- **Closes:** DATA-002 (`docs/reviews/2026-11-10-deep-review/06-data-flow-governance.md`), with D-370

## Context

D-370 chose `services/adapter` as the one ingest stack and named this card to delete `services/dataplat`. What
dataplat had must live in the adapter first: contracts, row quarantine, one gate record per night, the patient index
as an append-only `pid_alias` table, and lineage. The pseudonym rule stays `pid = HMAC(site key, chart number)`.

## Decision

1. **The tree.** `services/dataplat/` is deleted, with its tests (`test_dataplat_gate.py`,
   `test_dataplat_landing.py`, `test_dataplat_thin_path.py`), its package entry in `pyproject.toml`, its coverage
   baseline row and its store pin (`mpi`, kept in the frozen D-204 baseline and listed as retired in
   `tests/unit/test_migrations.py`). No compose file named it; none does now.
2. **Contracts.** The YAML contracts move to `services/adapter/contracts/` (`demo_his`, `mimic_fhir`).
   `adapter/governance.py` loads them and checks each mapped table's rows before the mapping. They are on when
   `AdapterConfig.contracts_dir` is set (`TB_DATA_CONTRACTS`: a built-in set's name or a folder). A mapped table
   without a contract, a missing contract column, or a blocking row check holds the night. A new column is a warning.
3. **Row quarantine.** A row that fails a check (null patient key, duplicate key, null required column, type,
   enumeration) is set aside and never mapped. It is counted by reason. Its values are not copied: the night keeps
   only counts and keyed hashes of the primary key (`contract_report.json`). A table whose quarantined share passes
   its contract maximum holds the night.
4. **Control totals.** When the export ships `control_totals.json`, each table's `count(*)` and
   `count(distinct patient)` must equal what was read. Without the file the condition is `not_evaluated`.
5. **One gate record per night.** Every night writes one `PublishGateRecord` as `gate.json` beside its report and
   as `<lake>/gates/<night>.json` (a re-run replaces its night's). Six conditions: contracts, control totals, file
   quarantine (T-615b), completeness (T-611), validation, any other step. The audit event carries its outcome and
   reasons. `trialbox doctor` reads it (`--lake-dir` or `TB_LAKE_DIR`).
6. **Patient index.** Schema `pidmap` version 3 adds `pid_alias` (old pid, surviving pid, reason, ticket, time),
   append-only. `adapter pid-merge --from A --into B` adds a row; the same merge again adds none; moving a merged pid
   elsewhere, or a cycle, is refused. The ingest writes a merged patient's records under the surviving pid. Nothing
   stored is re-keyed.
7. **Lineage.** Each night writes `lineage.json` next to `completeness.json`: input file names, sizes and sha256,
   the mapping file and its sha256, the snapshot folder and files, the gate's outcome. OpenLineage events are gone.
8. **Callers.** `tools/ingest_local.py` runs one night through the adapter in process (contracts on, a local lake).
   `tools/cascade_e2e.py`, `tools/trialbox/eval.py ingest_fhir_demo`, the test bench (`/ingest` replaces
   `/dataplat`) and `tools/bench.py` use it. The synthetic truth of the cascade run is keyed by the adapter's pid.

## Not carried over

The L0 landing zone, signed snapshot manifests and the L5 serving pointer (the lake's `CURRENT` serves), steward
notice rendering, OpenLineage events, the L2 to L4 internal equations, and the MPI's random `mpi_id` and `K_pid`.
The planted-defect suite of `test_dataplat_gate.py` is carried over as `tests/unit/test_adapter_governance.py`.

## Consequences

- `ReasonCode.FEED_INCOMPLETE` is added to `tb_contracts.landing` for the completeness condition.
- Readers of a pid outside the ingest (opt-out, marks, candidates, the data core) do not yet resolve through
  `pid_alias`; that is follow-up work.
- The MIMIC contracts load but are not applied to the `fhir_bulk` path.
