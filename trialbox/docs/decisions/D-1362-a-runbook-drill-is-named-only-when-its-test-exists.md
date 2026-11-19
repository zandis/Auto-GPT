# D-1362 A runbook drill is named only when its test exists

- **Task:** lane K, plan 10 row 10K-9 (SO-9 of review 18: the operations drills the runbook names)
- **Date:** 2026-11-19
- **Status:** proposed
- **Builds on:** D-390 (the operations pages and their drill lines), D-413 (close-out), D-139 and D-311 (doclint)

## Context

Thirteen operations pages of the RUNBOOK each named a "Drill (T-213b)" test. Only one of the 14 names in the
runbook (§19's model hold) was a test under `tests/`; the others were described as Docker drills that were never
written (review 18, §2.3; finding H33-10). Nothing checked that a named drill exists, so a reader could not tell a
rehearsed procedure from an unrehearsed one.

## Decision

1. **The check.** `tools/doclint.py` gets a failing **drill** check: every drill name cited in a living document
   under `docs/` (outside the records; the site tabletops of `docs/plan/sites/` are read too) must be a `def` of that
   name under `tests/`. Decisions, reviews, plan measurements and the findings register are history and are not read.
2. **Built where the procedure runs on master.** Five drills are built in process, running the page's own commands
   on synthetic data: §12 certificate renewal (steps 1 to 3 through `console.cli check-tls`), §20 close-out (step 2's
   four `audit_verify.py` commands, step 3's audit copy, plan and `SHA256SUMS` by the page's own command, step 4 on a
   second folder, both checks failing on a changed copy), §22 moving the box (step 3's `check-tls` on the new name,
   step 4's network sheet stale and written again), §23 the lost-box list (the inventory names every key of the box
   the list names, with the same commands, and the tools take them), §25 leavers (step 1 by **Users** and by
   `console.cli disable`: no sign-in after, the account kept, the disable audited with the name).
3. **Removed where it cannot be honestly built now.** §4 disk full, §4 GPU fault, §4 morning mail, §22 timed restore,
   §22 power cut, §22 replacing hardware and §24 patch window need a compose box, a GPU, a host restart or a second
   machine. Their pages now say "none" and, in words, that no test rehearses the procedure. §21's supervised session
   is left to card 10K-15, which builds the switch and names its drill with its test.
4. **Each drill line says what it does not rehearse.** A built drill's line names the steps that need the running
   box or people and are not tested.
5. **Two runbook corrections the drills found.** §22 moving: `check-tls` reads the variables it is run with, not
   `deploy/.env`, so step 3 says to run it with the new values (the running console still has the old ones). §20
   step 2: the head to write down is the one after the four commands, because `--sign-head` adds one event
   (`audit.head_signed`).

## Consequences

- `tests/unit/test_operations_docs.py` now takes a page whose drill line says "none" and that it is not rehearsed by
  a test; the tabletops list only drills that exist, and say "none (not rehearsed by a test)" for the others.
- No product file changes. The Docker drills of T-213b remain to be written; each removed name comes back with its
  test, and doclint fails a name written before its test.
