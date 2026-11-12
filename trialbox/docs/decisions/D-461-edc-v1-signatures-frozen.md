# D-461 Version-1 EDC signatures only from a signed frozen list; new rows default to version 2; the console leaves the EDC owner group

- **Card:** T-720 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-720-edc-v1-signatures-frozen`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-281 (the keyed signature, version 2), D-378 (one database role per service), D-204 (checksummed
  migrations)
- **Closes:** finding F4 (the EDC part: a version-1 row inserted by a database writer verifies) and proposal TR-9 of
  `docs/reviews/2026-11-12-architecture/trust.md`; the console part of T-212c's unmet acceptance (plan v6.1 §4.3)

## The problem

D-281 made every new signature a keyed hash (`sig_version` 2) and kept the old rows checked by their own rule
("version 1: an unkeyed SHA-256 over the value hashes"), so that a signature made before it would still cover its
values. Two facts turned that courtesy into a forgery path:

1. the column `edc.signature.sig_version` defaults to 1, so a row inserted without naming it is a version-1 row;
2. the version-1 rule needs no key: anyone can re-make it from the row's own `drafts` column.

A database writer without the signing key (any member of the schema's owner group: `tb_orchestrator`, `tb_console`
and the host admin) could therefore change a signed value's `final`, recompute its value hash (`draft_sha`, no key),
insert a `signature` row with no `sig_version` and the matching unkeyed `content_sha`, and point the draft at it (the
`draft` table is not append-only). `EdcStore.sendable()` returned the changed value, which went to REDCap and the
ODM export. No trigger is bypassed. The audit worker confirmed it with a throwaway test on 2026-11-11, and the trust
review (F4, TR-9) again on 2026-11-12. The console was in the owner group although it never opens `EdcStore` (only
the orchestrator does, `services/orchestrator/app.py`).

## The decision

1. **A version-1 row is accepted only from a frozen list.** EDC schema version 4 adds the append-only table
   `edc.sig_v1_frozen`. Right after the migration to version 4 runs, `EdcStore` (which holds the signing key) writes
   one row there: the `(id, content_sha)` of every version-1 signature row that existed before that migration, and
   `HMAC-SHA256(signing key, "trialbox edc v1 frozen list" || the list)`. The list is read before the migration
   runs, so a row inserted while the upgrade runs is not on it. It is written once: only by the start that applied
   version 4, and only while the table is empty (two services starting together write one row). A later start never
   writes it, so a writer who empties the table (after dropping its trigger) does not get a new list: the store
   then accepts no version-1 row at all.
2. **`intact()` for version 1** needs both: the unkeyed rule of D-281 holds, **and** the row's id and `content_sha`
   are on the first row of `sig_v1_frozen`, whose MAC verifies with the store's key. A version-1 row not on the
   list, a list whose MAC does not verify (changed, or another box's key) or no list at all: the row covers nothing,
   so `sendable()` and `signed()` (REDCap send and ODM export) leave its values out and the trail page marks it not
   intact. The list is read once when the store opens; it never changes.
3. **On every box today the list is empty.** All data on every box is synthetic and no box holds a real signature;
   the boxes that have EDC rows at all made their signatures after D-281 (version 2). The rule exists so that a box
   which did hold version-1 rows keeps them, and so that the frozen list, not the column's default, is what decides.
4. **New rows default to version 2.** Version 4 sets `sig_version DEFAULT 2`; `EdcStore.sign` still names it. A row
   inserted without a version is then checked by the keyed rule, which a writer without the key cannot satisfy.
5. **The console leaves the EDC owner group.** `tb_console` is removed from the `edc` entry of the role list in
   `deploy/docker/db-init/30-service-roles.sh` (and its copy under `deploy/platform/base/db-init/`); the script
   revokes `tbs_edc` from it on its next run (install, upgrade, or by hand after a restore). The console reaches the
   EDC only through the orchestrator's routes. `tb_orchestrator` (which opens the store) and the host admin stay.

## Not in this decision

- The orchestrator is still an owner of schema `edc` and can drop its triggers; owner, writer and reader roles per
  schema are T-718. After T-718 the orchestrator has INSERT only and cannot touch the list at all.
- The signing step-up (T-205) and the `reauth-` session marker (F5, TR-3) are unchanged.
- Version-1 rows that are on the list are still checked by the unkeyed rule over the value hashes only (the signer,
  name and time are not bound). Re-signing them under version 2 is a person's act, not a migration.

## Evidence

`tests/unit/test_edc_v1_frozen.py`: the forgery sequence of the problem (fails on master, passes here); a version-1
row that existed before the migration is listed and verifies, a changed or unlisted one does not; a list made under
another key, an emptied table and a later start that does not re-freeze; the default 2; the table append-only.
`tests/unit/test_edc_signing_d281.py::test_an_old_unkeyed_signature_is_checked_by_its_own_rule` now builds its old
row before the migration (a row made afterwards is exactly the forgery). `tests/unit/test_db_roles.py`: the console is
in no EDC group, and a membership an earlier release gave is revoked on the next run. `tests/unit/test_migrations.py`
pins EDC version 4.
