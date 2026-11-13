# D-711 "Could not be read" is not an answer: the anchor folder the console may not list, and the stores the demo scan may not read

- **Task:** NEW-FR-2 (two findings placed by the integrator on 2026-11-13: lane D's from its anchor-mount card,
  and this lane's own from NEW-FR-1)
- **PR:** this branch (`agent/NEW-FR-2-cannot-tell-is-not-an-answer`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-710 (the same family: the first-run page), D-355 / D-562 (the signed heads and the audit
  page's Verify), D-331 / T-502 (the scan of stored demo input), D-378 (one database role per service)

## The two places

1. **The audit page's Verify.** An anchor folder whose `heads/` the console's user may not list was shown as
   reachable with "no signed head yet": a glob passes over a folder it may not read, without an error. The page
   said the folder was there and empty when it had not been read.
2. **The scan of stored demo input** (`python -m console.demo_guard scan --db`). It finds the text columns to
   read in `information_schema`, which lists only what the asking role has a right on. On a box with service
   roles, run with the console's own role, it read the console's stores, passed over every other service's
   store and said "clean". **Confirmed by a run** under the real role script: as `tb_console` the scan read
   nothing of `edc`, `mail`, `trace` and the rest, and exited 0.

## The decision

- **A folder that cannot be listed is not reachable.** `audit_page._listable`: the target is a folder and its
  `heads/`, when there is one, can be listed. A folder with no `heads/` yet is reachable and has no head, as
  before. The page's line says "not reachable (not mounted, or the console may not read it)" in three languages.
- **The scan names what it could not read and exits 1.** The catalogue (`pg_class`, readable by every role)
  says which stores of the database hold a table the role may not read; the scan prints them, says to run it
  with the box's admin role (`trialbox`, a member of every store's group), writes no baseline and does not say
  "clean". Run as that role it reads everything, by the same test.
- The session checklist (`docs/poc/session-checklist.md`) says which role the scan needs and what exit 1 means.

## What it does not do

- The verification itself is unchanged: with an anchor folder set and no head read, `tb_common.audit.verify`
  reports what it reported before. Only what the page says about the folder changes.
- The folder's `keys/` are read as before; a `keys/` that cannot be listed is not judged here.
- The scan does not take another role by itself: it has the URL it is given. A partial scan was refused rather
  than allowed with a switch (no speculative option); if the PoC needs a scan of the console's stores alone,
  that is the owner's to ask.
- **For the owner / the PoC run:** the checklist step "inside the container" no longer passes with the
  console's own `TB_DB_URL` on a box with roles; it needs the admin role's URL. That is the point of the
  change, and it changes a step a person performs.

## Review

See "What the adversarial review changed" when the review is in.

## Reuse check

`tb_common.audit.read_signed_heads` and `verify` are unchanged; the scan's own `MUST_SCAN` refusal (exit 1 with
what was not scanned) is the form the new refusal takes; the role-script fixture is `tests/unit/test_db_roles`'s.

## Dropped (D-311)

No sign-off step.
