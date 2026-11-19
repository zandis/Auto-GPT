# D-1049 A test in the no-database tier never asks for the database

- **Task:** E-PURE. It is the red that lane D's nightly report found in the `pure` job (2026-11-18). The integrator gave it to the EDC owner (lane E) on #639.
- **PR:** this branch (`agent/E-PURE-edc-contract-db-tier`)
- **Date:** 2026-11-19
- **Status:** proposed (merges on green CI)
- **Builds on:** ENG-028 and T-653 (the `nodb` mark and `make test-pure`), D-1044 (the EDC door's stores in the trial database)

## The finding

`tests/unit/test_edc_contract.py` is a pure module: it is listed in `PURE_MODULES`, and its `pytestmark` is `nodb`.

E-EDCB-2 (D-1044) moved the EDC door's event ids, held writes and OIDC codes into the trial database. Three of the module's tests then took `db_url`:
- `test_events_are_signed_retried_and_idempotent`;
- `test_tools_stay_off_without_the_module_and_writes_wait`;
- `test_oidc_issues_a_code_and_stays_off_by_default`.

`make test-pure` runs with no PostgreSQL (`TB_PG_BIN=/nonexistent`). The first of them tried to start a cluster, and the run stopped. The nightly named only the first, because the run was interrupted there.

## Decision

1. **The three tests move, unchanged, to a new module that is not pure:** `tests/unit/test_edc_contract_db.py`.
   - A module's `nodb` mark cannot be lifted for one test: the conftest reads the closest `nodb` marker.
   - So a module of its own is the one way, and it needs no change to `tests/conftest.py`.
   - The pure module keeps its five tests and stays in `PURE_MODULES`.
2. **A guard keeps it so:** `tests/unit/test_pure_modules_need_no_database.py` (itself pure).
   - It reads every module of `PURE_MODULES`, and every module whose `pytestmark` is `nodb`.
   - It fails when a test there takes `db_url` or `pg_cluster_url`, naming each such test.
   - It parses the files and starts nothing.
   - It failed on master with these three tests and passes now.
