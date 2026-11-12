# D-461 Version-1 EDC signatures are refused; new rows default to and must be version 2; the review page says "signed" only for a covered value; the console leaves the EDC owner group

- **Card:** T-720 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-720-edc-v1-signatures-frozen`)
- **Date:** 2026-11-12
- **Status:** accepted (merged)
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

1. **Version 1 is refused.** `EdcStore.intact()` returns false for every `sig_version` other than 2 (the keyed
   hash). A version-1 row covers nothing: `sendable()` and `signed()` (REDCap send and ODM export) leave its values
   out, the trail marks it not intact, and its values are simply unsigned and need signing again. This replaces
   D-281's "version 1 rows are checked by their own, unkeyed rule".
2. **Why not a frozen list.** The first build of this card accepted version-1 rows from a list frozen and signed
   with the key at the migration. Its adversarial review broke it: "written once" rested on the database itself. A
   schema owner without the key could forge a version-1 row, drop the list table (a trigger does not stop `DROP`),
   delete the schema-version row of the migration and wait for a restart; the store then re-ran the migration and
   signed a fresh list holding the forged row with the real key. Any fact kept only in the database is one its owner
   can reset. No box holds a version-1 signature (point 4), so there is nothing to keep, and refusing version 1
   outright has no such hole: nothing a migration or a restart does can make a version-1 row count.
3. **New rows are version 2.** EDC schema version 5 (after T-302c's version 4, `copy_tick`) sets
   `sig_version DEFAULT 2` and adds the check `signature_v2_only` (`sig_version = 2`, `NOT VALID`: an existing
   version-1 row stays, covering nothing; every new or changed row must say 2). The check is a guard against mistakes; an owner can drop it, and `intact()` is what
   holds then.
4. **No box loses a real signature.** All data on every box is synthetic and no box holds a real signature; the
   boxes with EDC rows made their signatures after D-281 (version 2). If a site ever needs to keep pre-D-281
   signatures, that is a new card, and the fact "these rows were already there" must live outside the database
   (for example a MAC file beside the signing key), never in a table its writers own.
5. **The review page says "signed" only for a covered value** (a pre-existing defect of the same path, found by the
   same review). `GET /studies/{rs}/edc/drafts` returns `covered` per draft (`EdcStore.covered_ids`, the same
   `_covered` check as send and export) and attaches the signer, role, time and meaning only to a covered draft. The
   console's review page shows the "signed" pill and the signer only when `covered`; a value with a signature id
   that is no longer covered (for example after a plain `UPDATE draft SET final = ...`) shows "not signed: changed
   after signing; sign again" (en, ja, zh-TW).
6. **The console leaves the EDC owner group.** `tb_console` is removed from the `edc` entry of the role list in
   `deploy/docker/db-init/30-service-roles.sh` (and its copy under `deploy/platform/base/db-init/`); the script
   revokes `tbs_edc` from it on its next run (install, upgrade, or by hand after a restore). The console reaches the
   EDC only through the orchestrator's routes. `tb_orchestrator` (which opens the store) and the host admin stay.

## Not in this decision

- The orchestrator is still an owner of schema `edc` and can drop its triggers and the version check; owner, writer
  and reader roles per schema are T-718. The keyed hash is what holds against it today.
- The signing step-up (T-205) and the `reauth-` session marker (F5, TR-3) are unchanged.
- On a DEV or TEST box without a key file the signing key is the fixed test key in the source (D-281); such a box
  holds synthetic data only.

## Evidence

`tests/unit/test_edc_v1_refused.py`: the forgery of the problem with no version and with version 1 (both fail on
master, pass here); the review's reset sequence (forged version-1 row, schema-version rows deleted after 0, 1, 2, 3 or 4,
restart) never brings the forged value back from `sendable()` or `signed()`; the default 2 and the check; a
version-1 row from before the migration covers nothing; the drafts route marks a value changed by a plain update as
not covered. `tests/console/test_edc_pages_d461.py`: the review page shows such a value as not signed.
`tests/unit/test_edc_signing_d281.py::test_an_old_unkeyed_signature_is_checked_by_its_own_rule` now asserts that an
old unkeyed signature covers nothing. `tests/unit/test_db_roles.py`: the console is in no EDC group, and a membership
an earlier release gave is revoked on the next run. `tests/unit/test_migrations.py` pins EDC version 5.
