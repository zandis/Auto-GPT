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
  schema named from this space's own lake folder (`omop.schema.schema_for`). If it cannot be dropped the error
  goes on and nothing of the space is deleted: a Reset that left the patients in the database must not say
  "reset".
- **Only this space's.** The name is computed from the space's folder; the hospital's store (`omop`) is refused
  by name as well as by `main` being refused, and another space's store is not touched (by test).
- **Asked first, nothing made.** Whether the schema exists is read from the catalogue; a space that never had a
  store gets none made by the question.
- **Audited.** `setup.reset` carries `omop_store`: `dropped` or `none`.
- **The erasure registry names it**: `outside:sitesetup_space_omop`, an erase obligation that is **owed**: the
  opt-out worker's clear of OMOP rows works on the hospital's store, not on a practice space's. The generated
  page is regenerated. The record inventory's row R-20 names the store too.

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

## Review

See "What the adversarial review changed" when the review is in.

## Reuse check

`omop.schema.schema_for` names the store, as the publish does; `tb_common.db.Database.connect`; the erasure
registry's own helpers and generator. One method is added (`SiteSetup._drop_space_store`).

## Dropped (D-311)

No sign-off step.
