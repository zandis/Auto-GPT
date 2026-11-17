# D-997 the provenance index's tables in the role script, and who may do what with them

- **Task:** D-989 step 2c, the role script's part (lane D), handed over by lane A2 through the integrator on #639;
  stacked on lane A2's #999
- **PR:** this branch (`agent/D989-2c-ROLES-the-provenance-index-tables`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-989 (the provenance events and their index), D-394 (the audit journal, owned by `audit_writer`),
  D-378 (one role per service), D-465 (the orchestrator runs the opt-out worker)

## Context

Lane A2's #999 writes the provenance index: `provenance.model_calls` and `provenance.model_uses`, derived from the
audit chain and rebuilt from it. `tb_common.provenance_index.INDEX_SQL` makes them, and "the role script runs this
(lane D, with its grants)". Until the tables exist:

- the drain writes the chain without the index;
- `trialbox doctor` says the index is not installed;
- the opt-out worker's clear of a patient's use rows is listed as owed.

## Decision

1. **Both role scripts run `INDEX_SQL` word for word,** the box's (`deploy/docker/db-init/30-service-roles.sh`) and
   the platform's (the same file), between `-- BEGIN PROVENANCE INDEX (D-989)` and `-- END PROVENANCE INDEX`. The
   block follows the journal's, so `audit_writer` exists by then. A test keeps the block equal to the module's SQL,
   as the journal's block is kept equal to `JOURNAL_SQL`.
2. **`audit_writer` owns the schema and both tables,** like the journal, and PUBLIC has nothing.
3. **The grants:**

   | Role | On `model_calls` | On `model_uses` |
   | --- | --- | --- |
   | `tb_audit_writer` (the drain) | USAGE, SELECT, INSERT | USAGE, SELECT, INSERT |
   | `tb_console` | USAGE, SELECT | USAGE, SELECT |
   | `tb_orchestrator` (the search, and the opt-out worker of D-465) | USAGE, SELECT | USAGE, SELECT, DELETE |

   - **`trialbox`,** which runs the host's `trialbox provenance --rebuild` and `--check`, acts as the owner. It is
     `audit_writer`'s one member, as for the journal, so it needs no grant of its own.
   - **Every other service role** has nothing.
4. **The findings page's database-image row** (`deploy/security/known-image-findings.md`) says 0 findings since D-993.
   The integrator asked for it on #639, and it rides here as lane D's next card.

## Tests

`tests/unit/test_provenance_roles.py` (13 tests):

- **Without a cluster:**
  - both scripts run `INDEX_SQL` word for word, after the journal;
  - the two scripts are the same file.
- **On a throwaway cluster** (`pglocal`), the script applied twice:
  - the owner, and `trialbox` as the owner's one member;
  - every role's privileges on each table, exactly;
  - the drain inserts and cannot delete;
  - the orchestrator clears a patient's use rows with `provenance_index.erase` and cannot insert.

## Remains

Turning the opt-out worker's clear from owed to done is lane A2's (`tb_common/erasure.py`): the grant it waits for is
here.
