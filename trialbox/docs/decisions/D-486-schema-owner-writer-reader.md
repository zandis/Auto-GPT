# D-486 Owner, writer and reader roles per schema, the EDC schema first: no service role owns a trail table, and migrations of such a schema run as an install step

- **Card:** T-718 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-718-schema-owner-writer-reader`); built on T-712's branch (PR #308): it shows its
  commits until it merges
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-378 (one database role per service), D-461 (the EDC schema is the orchestrator's alone), D-481
  (a service holds its own role's password only)
- **Closes:** finding F4 of `docs/reviews/2026-11-12-architecture/trust.md` for the schema `edc`, and proposal TR-6
  for that schema (see "Not done" for the others)

## The problem

Every service role that reads or writes a schema is a member of the group that owns it (`tbs_<schema>`, D-378), and
`tb_common.db` sets the role to that group on connect. So every writer is an owner: the triggers that make the EDC
trail tables append-only are made at service start by the orchestrator's own role, and the same role can drop
them, disable them, alter the table or truncate it. The stores are append-only against their own code, not
against their writers.

## The decision

One schema at a time, as the card says. This decision sets the mechanism and applies it to `edc`.

1. **Three roles for an owned schema.** `deploy/docker/db-init/30-service-roles.sh` has a second list, `owned`
   (now `edc`). For a schema on it the script makes `tbo_<schema>` (owns the schema, every table, sequence and
   function in it; its one member is `trialbox`, and any other member is removed on each run), `tbw_<schema>`
   (USAGE on the schema; SELECT, INSERT, UPDATE, DELETE on its tables; its sequences) and `tbr_<schema>` (USAGE,
   SELECT). Default privileges give the same to tables the owner makes later. A service with the schema on its
   list becomes a member of `tbw_<schema>` and leaves the D-378 group `tbs_<schema>`; what that group owned on an
   older volume moves to the owner role. No service is a member of any `tbo_*`.
2. **A service does not migrate an owned schema.** `tb_common.db.Database.migrate`, on a schema whose owner is a
   `tbo_` role the caller is not a member of, applies nothing: it checks that the applied versions are the ones
   this release carries (by checksum) and refuses a schema that is behind, naming the command to run. A member
   (the box's admin) takes the owner's role on connect, as it took the group's since D-378, so what it makes is
   the owner's.
3. **The install step.** `python -m orchestrator.migrate` makes every owned schema as the admin: it first gives
   back to the owner role what a restore left under the admin's name and grants the writer and reader again
   (`Database.adopt`; this is the left-over of D-378 "restore" for these schemas), then applies the versions, then
   the store's own part. For `edc` (`edc.store.install`): the append-only triggers on the eight trail tables, and
   the writer loses UPDATE, DELETE and TRUNCATE on them and every write on the version table. `deploy/install.sh`
   runs the step after the role script and before the services start; `trialbox update` runs it before it starts
   the new containers; `python3 -m tools.trialbox migrate` runs it by hand. The admin's URL is passed in the
   environment of a one-off orchestrator container, never on a command line.
4. **The orchestrator checks, it does not make.** `EdcStore` on a schema it does not own verifies that every
   trail trigger exists and is enabled, and does not start without one.

Where the roles are not set (DEV, TEST, the in-process demo, the Kubernetes platform, whose services still sign in as `trialbox`) nothing changes: the caller owns the schema
or is a member of its owner, and migrates it at start as before.

## What a service role can no longer do in `edc`

`DROP TRIGGER`, `ALTER TABLE ... DISABLE TRIGGER`, `ALTER TABLE`, `DROP TABLE`, `TRUNCATE`, `UPDATE` or `DELETE` on
a trail table, replace or drop the trigger's function, create a table, drop the schema, or take the owner's role.
`tests/unit/test_db_roles.py` runs each as `tb_orchestrator` on a real cluster made by the real script.

## What the adversarial review changed (2026-11-12)

- **`trialbox update` runs the role script before the migrate step** (`ComposeBox.set_roles`), as `install.sh`
  does. Before, a box updated in place kept `edc` under the old group with the orchestrator as its owner, and
  nothing said so.
- **The script ends the sessions of a service it takes out of the old group of an owned schema.** Such a session
  still works as that group (`SET ROLE`), which has lost the schema; without this every EDC statement of a
  running orchestrator failed until someone restarted it. It happens once, at the change-over.
- **A rerun of the script does not widen the writer's rights.** A table with an append-only trigger takes INSERT
  only and the version table no write, at every run; before, each run gave back what the migrate step had taken.
- **A service does not make a missing owned schema.** When `tbo_<schema>` exists in the cluster and the session
  is not a member, a missing schema is an error that names `trialbox migrate`; before, the service made the
  schema and so owned its tables and triggers (reachable when a restore died between its drop and its load).

## Not done

- **`app` and `pidmap`**, the other two schemas the card names first, and every other schema: they stay with
  their D-378 group. `app` (the flags) needs a reader for six services and a writer for the console, so the
  script's list needs a way to say "reader"; `pidmap` waits for the identifiers door to be its own role (D-487,
  stage c). The mechanism here takes a schema by adding it to `owned`, giving its store an install function in
  `orchestrator.migrate.OWNED` and, for a reader, that notation.
- **`dataops.batch_step`**, `breakglass`, `team`, `optout`, the sponsor layouts, the recall ledger (F4's other
  stores).
- **The orchestrator's membership of `breakglass` and `team`** (D-484 gave it the groups to read a grant and the
  delegation log): it should be a reader of both. Needs the reader notation above.
- **`profile` and `tuned` on no console role.** The console cannot read the twins on per-service roles: the
  `profile` schema is on the orchestrator's list only and `tuned` on none. This card does not change it; it
  belongs with the reader notation (the console as a reader of `profile` and `tuned`), or the console should
  ask the orchestrator over HTTP as it does for the EDC. Listed as a finding for the integrator.
- **One password file per role** (the rest of T-712): unchanged here.
- **The Kubernetes platform**: its services still sign in as `trialbox`, so they are owners of everything; the
  roles are made there but protect nothing until the platform has per-service roles.
- `GRANT CREATE ON DATABASE` to the service roles (a re-run's scratch schema) stays.
- **The admin's URL is in a one-off container of the orchestrator's image** while the migrate step runs
  (`docker compose run -e TB_DB_URL`): that container is on the orchestrator's networks and mounts its volumes.
  D-481's rule (no service container holds the admin's password) holds for the running services; the step is the
  one exception, for its length. A tool container on `trialbox-net` only, as the backup uses, would close it.
- **Two migrate steps at once, or one with the role script**, can fail with "tuple concurrently updated" and
  exit 1; a rerun succeeds and nothing is left half-done. The step takes no lock of its own.
- **Erasure.** No code deletes EDC rows today. `edc.draft` is owed to erasure (T-206b) and is no trail table: the
  writer keeps DELETE on it. The trail tables are kept under OD-8.

