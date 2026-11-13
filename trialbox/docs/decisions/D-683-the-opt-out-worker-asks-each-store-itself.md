# D-683 The opt-out worker asks each store itself; a store's group role may make temporary tables

- **Task:** the integrator's urgent order of 2026-11-13 from the nightly on the compose stack (the worker's tick
  failed every five minutes with `permission denied for schema omop`), and what the fixture for it showed
- **PR:** this branch (`agent/DC-optout-worker-asks-each-store-itself`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-441 (the opt-out worker), D-378 (one role per service; a store's connection works as the
  store's group role), D-465 (the erasure registry's clears), D-573 (what a restore leaves to the roles)

## Context

Both faults were confirmed by running the real `deploy/docker/db-init/30-service-roles.sh` against a throwaway
cluster and then the product's own functions as the service roles.

**1. The tick did nothing on a box with roles.** `tick()` asked "is there an OMOP store" with
`to_regclass('"omop".tb_record')` over the opt-out register's connection. That connection works as `tbs_optout`
(D-378), which may not use the schema `omop`, and PostgreSQL answers `to_regclass` about a schema the role may
not use with an error, not with NULL. The question sat before `run_once` in one `try`: the registry was not
copied, and no store was cleared (pool, candidates, OMOP, vector store, pid-map staging, profile). The tick
reported `failed: ["tick"]` every time (health line red, one `optout.worker_failed` audit event per tick). The
same question for the vector, pid-map and profile stores (`_schema_url`) was asked the same way.

**2. No role could load the OMOP store on a box with roles.** The load, the export "as of" and the Athena load
work in temporary tables. The role script grants `TEMPORARY` on the database to the service roles and revokes it
from PUBLIC; `tb_common.db` then sets the role to the group (`tbs_omop`), which had none: `permission denied to
create temporary tables`, for the admin, the adapter, the lake and the orchestrator alike. Not seen in the nightly:
the lake source defaults to `legacy` and the dual write is off.

## Decision

1. **Whether a store exists is asked of the catalog, on a connection of its own** (`optout_worker.store_has`): as
   the service's login role, with no store's group role, through `pg_class` and `pg_namespace`, which answer every
   role. "No such store" is a clear false. A failure to ask raises; it is never read from an error's text.
2. **The worker opens each store as that store** (`omop.schema.connect`, `Database.connect(url, "<store>")`), never
   through the register's connection.
3. **The tick is not all-or-nothing.** An OMOP store that is there and cannot be opened is named (`failed:
   ["omop"]`) and the registry copy and every other clear run in the same tick. It is never reported as skipped:
   skipped means the box has no such store.
4. **A store's group role may make temporary tables**: `GRANT TEMPORARY ON DATABASE` to every `tbs_<schema>`
   group, inside the loop that makes the groups, in both copies of the role script (lane D's files; lane D read
   the hunk and set its bounds). TEMPORARY only, never CREATE; PUBLIC stays revoked. Not the roles of an owned
   schema (D-486): a service's session on `edc` keeps its login role (shown by a test), which holds the right
   itself, so `tbo_`, `tbw_` and `tbr_` get nothing. A temporary table lives in the session's own `pg_temp` and
   reaches no store. The script runs on every install and upgrade, so a box gets the right with its next update.
5. **An enumerating test** lists every `to_regclass` question in the services and libraries with why it may ask;
   the worker has none, and the list only shrinks.

## What a box with roles did not do while this stood

No site is live. On a box installed with the role script, from the day the worker and the roles were both there:

- the hospital registry's refusals were **not copied** into the opt-out register;
- an opted-out patient's rows stayed in the **candidate pool**, and an open candidate (`candidate`, `contacted`)
  was **not withdrawn**;
- the **vector store's** note chunks, the **profile** and the **pid map's staging** of an opted-out patient were
  **not erased**;
- the **OMOP** store held nothing to erase: no load into it succeeded (fault 2).

What still held: an opt-out typed by the office is in the register at once, and every screening path reads the
register itself (D-147, D-273), so a new run did not list the patient. Each tick's failure was audited and the
health line was red.

## Stated plainly

- **With the install's roles, the OMOP dual write and the OMOP lake source have never loaded a record.** Every
  load ended at its first temporary table. The dual write reports this as the night's `omop` state `failed` and
  never stops the night (by design), and both are off by default, so nothing else showed it.
- **Which tests passed without seeing it, and why.** Every OMOP test (`test_omop_*`, `test_optout_worker.py`,
  the goldens, `test_e2e_simple`) and the dual-write tests (`test_omop_slice2.py`) run on the shared test cluster
  as its one admin, where no role script has run: there is no group role to switch to, and the admin may do
  everything. The tests that do run the role script (`test_db_roles.py`, `test_restore_roles.py`,
  `test_migrate_step.py`, `test_update_dbup.py`, `test_audit_writer.py`, `test_audit_one_writer.py`) put one
  probe table into each store and read it; none ran a store's own code as a service role. The opt-out worker's
  tests gave the worker a register on the same admin connection.
- **What the backup drill's "the OMOP store reads back the same" ran as** (by reading `tools/backup_drill.py`): the
  load and the read-back run on the drill's main cluster as its admin, with no role script. The drill's roles
  round (D-573) is a second, throwaway cluster where each store gets one table and one function; no OMOP load
  runs there. So the drill never loaded OMOP under roles either.
- **The rule this card adds for the next store**: a store's own code is run at least once as a service role on a
  cluster with the real role script (`tests/unit/test_optout_worker_roles.py` does it for the OMOP load, the
  export as of a time, the Athena load, the adapter's dual write and the worker's tick).

## Other lanes (not changed here)

- `services/console/firstrun.py` asks about the pid map over the console's `auth` connection (by reading: on a
  box with roles the question raises, is caught, and the first-run page reads it as "the box holds patients").
  Listed in the enumerating test as the console lane's.

## Evidence

`tests/unit/test_optout_worker_roles.py`: a cluster with the role script, the stores made by the admin, the tick
run as `tb_orchestrator`. Before the worker's change: the tick returned nothing (`failed: ["tick"]`). Before the
script's change: the fixture's own OMOP load was refused. After: the registry is copied, the pool, OMOP and the
pid-map staging are cleared, an OMOP store that cannot be opened is named while the others are cleared, and the
adapter, the lake and the orchestrator each load the OMOP store; the export as of a time runs as the lake; an
Athena bundle loads as the admin; and end to end, the adapter's dual write (as `tb_adapter`) loads a night, the
office opts a patient out, and one tick (as `tb_orchestrator`) takes the patient out of the store. The tests
pass in either order. `tests/unit/test_db_roles.py` holds: every `tbs_` group has TEMPORARY and no CREATE on the
database, the roles of an owned schema neither, PUBLIC no entry.
