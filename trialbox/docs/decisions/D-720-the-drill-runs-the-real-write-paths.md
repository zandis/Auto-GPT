# D-720 The drill's role check runs each service's real write paths

- **Task:** ROLE-PATHS (the nightly of 2026-11-13; lane E's two findings, through the integrator)
- **PR:** this branch (`agent/ROLE-PATHS-the-drill-runs-the-real-write-paths`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-573 (after a restore every service opens its stores as its own role), D-378 (one role per service), D-486 (owned schemas)

## Context

The backup drill's role check (D-573) said "7 service roles, 70 stores opened as their groups" on a box where the
opt-out worker failed at every tick and no role could load the OMOP store. The check opens each store with DDL of
its own; it never ran a line of a service's code under the role script.

## Decision

`tools/role_paths.py`, a line of the backup drill after the D-573 check, on a throwaway cluster with the real
`deploy/docker/db-init/30-service-roles.sh`, each path as the service's own role and through the service's own
code:

| path | as | what it runs |
|---|---|---|
| a temporary table on every store connection | every service role, each store of its list (not the owned ones) | `tb_common.db.Database.connect` (which sets the role to the store's group), then `CREATE TEMP TABLE` in a transaction |
| the OMOP load | `tb_adapter` | `omop.schema.connect`, `omop.load.load_batch` with one synthetic patient |
| the OMOP export as of a time | `tb_lake` (two loads of one record as `tb_adapter` first) | `omop.export.export_rows(as_of=between the two loads)`: the wind-back that makes its temporary table |
| the opt-out tick | `tb_orchestrator`, on a box that has an OMOP store | `datacore.optout_worker.tick` with the orchestrator's handles; what stopped a tick that "never raises" is taken from its log record |

The drill's line names every path that does not run with what it raised; of the temporary tables the first three
and a count.

## What it says on master bf93f570 (before lane E's card)

Run here, 2026-11-13, the role script as it is on master:

```
roles: each service's real write paths run as its own role (D-720) -> FAIL
   72 do not run: a temporary table: tb_adapter on app: InsufficientPrivilege: permission denied to create temporary tables in database "trialbox_wf"
   a temporary table: tb_adapter on dataops: InsufficientPrivilege: permission denied to create temporary tables in database "trialbox_wf"
   a temporary table: tb_adapter on derived: InsufficientPrivilege: permission denied to create temporary tables in database "trialbox_wf"
   a temporary table: 66 more store connections the same
   the OMOP load as tb_adapter: InsufficientPrivilege: permission denied to create temporary tables in database "trialbox_wf"
   the OMOP export as of a time as tb_lake: RuntimeError: its two loads did not run (InsufficientPrivilege: permission denied to create temporary tables in database "trialbox_wf")
   the opt-out tick as tb_orchestrator: RuntimeError: the tick did not run (failed ['tick']): InsufficientPrivilege: permission denied for schema omop
```

That is the drill's own proof of lane E's two findings: after `SET ROLE` to a store's group no service can make a
temporary table (the script gives TEMPORARY to the service roles and takes it from PUBLIC; the group has none), so
the OMOP load does not run as any role; and the opt-out tick stops at its first line on a box with an OMOP store
(`permission denied for schema omop`: the OMOP store is asked about over the opt-out register's connection, which
works as `tbs_optout`).

## What it says with lane E's card (D-683, #543 at 3824b3b1, merged into this branch)

```
roles: each service's real write paths run as its own role (D-720) -> ok
   a temporary table on 69 store connections, and 3 paths: the OMOP load as tb_adapter, the OMOP export as of a time as tb_lake, the opt-out tick as tb_orchestrator
```

With D-683's one grant line taken out of the script again, the line fails by name (a test keeps that): the
temporary tables, the load and the export; not the opt-out tick, whose fault was the worker's own. A second test
watches the statements: the load's `tb_in_tmp` and the export's `tb_asof_tmp` are really made (an export that
winds nothing back makes no temporary table and would pass without asking for the right).

## Judged here: TEMPORARY is never taken back from a group (a finding of lane E's review)

The script grants TEMPORARY to `tbs_<schema>` and never revokes it when the schema later becomes owned (D-486)
or leaves every list. It does not matter, and no revoke is added:

- TEMPORARY gives a session a private `pg_temp` schema and nothing else: no reach into any store.
- A group is NOLOGIN. Only a member can work as it, and every member is a service role that holds TEMPORARY on
  the database itself. The script already takes the services out of a group that left their list, and out of the
  old group of a schema that became owned (and ends their sessions). After that only `trialbox` can become the
  group, and `trialbox` owns the database.
- So the right left on such a group can be used by nobody who does not have it anyway. A revoke would be one more
  statement that every box runs at every install and update, to remove nothing.

## What D-573's check missed, and the rule from here

It proved ownership (a table altered, a function replaced, as the group) and reach (no store off a list is read).
It never ran service code, so it could not see a right the code needs and the group lacks, nor one store asked over
another store's connection. Rule: a service path that is more than a plain statement on its own store's connection
(a temporary object, another store asked, a function) gets a line in `tools/role_paths.py` `PATHS`.

## Not covered

- The vocabulary load (`omop/vocab_load.py`, a temporary table too): it needs an Athena download; the temporary
  table line on every store connection covers its right, not its code.
- Owned schemas (D-486, `edc`): the install step's; D-573's check and `tests/unit/test_db_roles.py` hold them.
- A platform (k8s) box: its services sign in as `trialbox` (D-573 says so); the second copy of the script is not
  run here.
