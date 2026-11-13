# D-714 Reset of a site set-up space drops the OMOP store a publish made for it

- **Task:** NEW-SITE-4 (an erasure gap read by lane B2 on the lake's side, placed by the integrator on
  2026-11-13)
- **PR:** this branch (`agent/NEW-SITE-4-reset-drops-the-spaces-omop-store`), from train 14
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-131 / D-132 (site set-up spaces and Reset), D-151 / D-207 (the lake built from the OMOP
  store, behind the flag `lake.source`), D-465 (erasure as an obligation of every store), D-378 (service roles)

## The problem

A set-up space other than the hospital's own (`main`) has a lake of its own, a library lake in the
orchestrator's process. With `lake.source` = `omop`, a publish of that space makes and loads a store of record
`omop_<hash of the space's lake folder>` in the trial database. Any space name may be made, and its sheets and
charts take uploads, so such a store can hold a site's real rows. `SiteSetup.reset` deleted the space's rows and
its folder and left that store; nothing in the box drops an `omop_*` schema; no erasure entry named one.

**Confirmed by a run** (the lake's source set to OMOP, a practice space, an upload, Reset): the space's four
patients were still in `person` of its store after Reset. With `lake.source` = `legacy` (the default) no such
store is made.

## The decision

- **Reset drops the space's store, first.** Before the rows and the folder are deleted, `reset` drops the OMOP
  schema named from this space's own lake folder (`omop.schema.schema_for`), in the database the OMOP stores live
  in (`omop.schema.db_url`: `TB_OMOP_DB_URL`, else the trial database), under the lock a publish takes. If it cannot be dropped the error
  goes on and nothing of the space is deleted: a Reset that left the patients in the database must not say
  "reset".
- **Only this space's.** The name is computed from the space's folder; the hospital's store (`omop`) is refused
  by name as well as by `main` being refused, and another space's store is not touched (by test).
- **Asked first, nothing made.** Whether the schema exists is read from the catalogue; a space that never had a
  store gets none made by the question.
- **Audited.** `setup.reset` carries `omop_store`: `dropped` or `none`.
- **The erasure registry names it**: `outside:sitesetup_space_omop`, an erase obligation that is **owed**: the
  opt-out worker's clear of OMOP rows works on the hospital's store, not on a practice space's. The generated
  page is regenerated. The record inventory's row R-20 names the store too. It is on the erasure card's owed list
  (T-206b), with the other clears not yet built (found by the whole-suite run: that list is kept exact).

## Who may open that store (as it is; not changed here)

By a run under the real role script: the orchestrator's login role (`tb_orchestrator`) makes the schema itself
and owns it; there is no group role for it. So the orchestrator opens it and no other service does (the console,
the adapter and the lake's role have no right on it); the box's admin role (`trialbox`, a member of every service
role, for backups and the host tools) reaches it. Reset runs as the orchestrator and can drop what the
orchestrator made. No grant is added. Whether a service should be able to make a schema of patient rows at all
is lane D's to judge (sent to the integrator with this).

## What it does not do

- **An opt-out does not reach a practice space's store** until its clear is built (the owed entry above). Reset
  removes the whole space; one patient is not removed from it by the register.
- Backups made while the store existed still hold it (the registry's own `outside:backups` entry).
- A store left by a space whose folder was removed by hand, or by a box whose data folder moved (the hash is of
  the path), is not found by Reset: nothing lists `omop_*` schemas without a space. Said; a sweep would be a
  card of its own.
- Nothing changes while `lake.source` is `legacy`.

## What the adversarial review changed

One review by a fresh reviewer, by running (also the whole path under the real role script as the
orchestrator's role). Verdict: fix first, two findings.

- **With `TB_OMOP_DB_URL` set, Reset looked in the wrong database**: the publish makes the store where the OMOP
  stores live, Reset read `TB_DB_URL` only, left the patients and audited "none". Reset asks and drops where the
  publish made it; the question goes over a connection of its own, so it makes no schema there. By test.
- **Reset did not take the lock a publish takes**: a publish of the same space between the drop and the deletion
  of the rows made the store anew with the patients in it, and the audit said "dropped". Reset holds the lock
  from first to last. By test.
- A call that closed the space's library lake did nothing (that lake has no such call); it is gone.
- The fail-first order (a store that cannot be dropped stops the Reset before anything is deleted) has its test.
- Ran and sound: a root through a symlink or given as a relative path finds its store; with `TB_LAKE_DIR` equal
  to the space's lake the hospital's store is refused and nothing is deleted; uploads work after a Reset; the
  erasure entry is true (the opt-out worker opens only `omop`) and the generated page is current.

## Open, for the owner (said, not changed)

- **The drop waits for a lock without a limit.** Another session that holds a table of the store (a backup's
  dump, an open transaction) keeps Reset waiting until it lets go; the call then finishes. A time limit with a
  said error would be a new fixed limit; not added here.
- **Only the practice space has a Reset route.** Any other space name can be made and published, and has no
  Reset in the API or the console: its store (and its rows) stay until someone calls the service. Whether other
  spaces should exist at all, or get a Reset, is the owner's to say.

## Reuse check

`omop.schema.schema_for` names the store, as the publish does; `tb_common.db.Database.connect`; the erasure
registry's own helpers and generator. One method is added (`SiteSetup._drop_space_store`).

## Dropped (D-311)

No sign-off step.
