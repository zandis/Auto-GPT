# D-624 A release's steps after the database is up are run by that release

- **Task:** UPDATE-DBUP (asked by lane C2 through the integrator, 2026-11-13; it blocks #390)
- **PR:** this branch (`agent/UPDATE-DBUP-steps-after-the-database`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-620 (an update runs the new release's `pre-start`), D-378 (the services' database roles),
  D-486 (the schemas no service owns are made by the box's admin before the services start)

## Context

D-620 gave a release a place for what its stack needs on the host before it starts. Two more things happen
between that and the start of the services, and both need the database: the role script
(`deploy/docker/db-init/30-service-roles.sh`) and the schemas no service owns (`python -m orchestrator.migrate`).
The updater that runs them is the installed, older release's. The script it runs is the new one (the folder is
part of the host tree), but which commands run, in what order and with what around them is the old release's
knowledge. A release that needs one more command there (a second script, a grant that must follow the migrate
step) cannot have it on an update.

One fault is in today's order, found by reading: the role script takes each service's password from the database
container's environment, and the container is the one started by the previous release. A release that adds a
service role adds its password to `deploy/.env`, but the running container does not have it; the role is made
without a password, the new service cannot sign in, and the update is rolled back.

## Decision

1. `tools/trialbox/prestart.py` holds a second list, `DB_STEPS`, beside `STEPS`. The command
   `python3 -m tools.trialbox db-up --deploy <dir>` runs it. A step has the contract of D-620's steps, with one
   difference: the database is up and no other service of the stack is.
2. The steps of this release, in order: `database` (the `db` service is brought to the new release's settings:
   `up -d --wait db`, which recreates the container when its settings changed and does nothing otherwise),
   `service roles` (the role script), `owned schemas` (the migrate step). A box with no `TB_DB_URL` in
   `deploy/.env` never ran the installer's database step: each step says so and does nothing, as before.
3. The updater's restart runs the new tree's `db-up` as a process of its own after `pre-start` and before the
   stack starts. A tree whose `prestart.py` has no `DB_STEPS` (a downgrade; a box with no host tree) gets the two
   commands every release before this ran, in the updater.
4. `deploy/install.sh` runs the same command after it started the database, so a step is written once. A host
   without `python3` keeps the two shell commands and says that the release's steps were not run.
5. As in D-620, the first release with the command cannot be helped by it; a release that adds a step names a
   release with `db-up` as its `min_installed_version`.

## Consequences

- Lane C2 adds its step as one line in `DB_STEPS`; nothing in the updater changes for it.
- The database container is recreated earlier in an update when its settings changed (it was recreated by the
  final `up` before). The services are stopped at that point in both orders.
- For lane G: on a box, an update to a release that adds a service role ends with that service signed in.
