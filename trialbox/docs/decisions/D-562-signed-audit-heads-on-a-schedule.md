# D-562 The signed audit heads are made every night on a box, and `doctor` fails when they are not

- **Task:** NEW-STD-2 (findings STD-002 and LIFE-010 of the deep review of 2026-11-12,
  `docs/reviews/2026-11-12-deep-review/11-standards.md` and `09-trial-lifecycle.md`; plan TB-PLAN-07 v7.2, wave 0,
  lane D)
- **PR:** this branch (`agent/NEW-STD-2-signed-audit-heads`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-355 (T-211a: signed heads and off-box anchors; it left "the nightly timer" as deploy work),
  D-394 (only the audit writer writes the audit volume; events go through the journal), D-272 (the head anchor),
  D-347 (the site keys under the KEK), D-138 (the host's nightly `logs daily`)

## Why

D-355 built the control: an Ed25519 key signs where the audit chain stands, and the signed head is kept write-once
in a folder off the audit volume. Nothing on a box ever ran it. The review showed the result by a run: remove the
newest events, recompute the chain, rewrite `HEAD.json`, and `verify` passes; the same attack against a signed head
fails. On a deployed box the audit trail was protected only by an unkeyed chain and an unkeyed anchor on the same
volume.

## Decision

1. **One host command, every night.** `python3 -m tools.trialbox audit-sign` runs from the installer's cron file
   after `logs daily`. It does three things in this order and stops at the first that fails:
   a. **Check first.** It verifies the chain against its own head anchor and against every signed head already in
      every anchor folder. A chain that does not agree with an earlier signed head is never signed again: the
      command prints the reason and exits 1.
   b. **Sign and publish.** It signs where the chain stands and writes the signed head, write-once, to every anchor
      folder of `TB_AUDIT_ANCHOR_TARGETS`.
   c. **Record.** The event `audit.head_signed` goes through the audit journal, as every other event of a box does.
2. **The host never writes the audit volume** (D-394). The host reads the chain under a shared lock on the writer's
   own lock file, opened read-only, and writes nothing there: a file made by the host's root would not be writable
   by the audit writer, and the next event of the box would fail. On an in-process box (file mode, no journal) the
   event is appended directly, as before.
3. **The key is made at install.** `install.sh` runs `audit_verify --init-key` once when the secrets folder has no
   audit key. A key that cannot be made (no KEK yet in PRODUCTION) is a line of the install report, not a stop: the
   installer must reach the wizard (OPS-003).
4. **`doctor` checks it.** A new check `audit_heads`: FAIL in VALIDATION and PRODUCTION (WARN in DEV and TEST) when
   no anchor folder is set, when an anchor folder is on the audit volume, when the audit key is missing, or when the
   newest signed head of any folder is older than `TB_AUDIT_HEAD_MAX_AGE_H`.
5. **The period is a setting.** `TB_AUDIT_HEAD_MAX_AGE_H`, default 36: the job is nightly, and 36 hours is the age
   at which the nightly backup is already called old (D-274), so one missed night is seen the next morning. Events
   written after the newest signed head are protected by the chain and its anchor only, until the next night.
6. **`make audit-verify` uses the signed heads** when `ANCHOR=<folder>` is given.

## Consequences

- A box with an anchor folder has a signed head every night; a removed or rewritten event is found by the next
  night's check, by `make audit-verify ANCHOR=...` and by the daily verify, as long as the anchor folder keeps its
  files. The folder should be on the hospital's share, not on the box.
- A box with no anchor folder set FAILs `doctor` in PRODUCTION. Choosing the folder is the site's step (the wizard
  and T-735 place it); the installer does not stop for it.
- The console's audit page still verifies against the head anchor only. Using the signed heads there is lane C's
  (one line in the pull request).

## Not done here

- Shipping the signed heads with the backup, and the restore's check against them.
- The audit page's use of the signed heads (`services/console`).
