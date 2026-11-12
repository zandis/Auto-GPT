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

0. **A missing anchor is not an empty chain.** With day files in the audit folder, or an earlier signed head in
   any anchor folder, a head anchor that is missing or says zero events is a failure of the night, never "no event
   yet". On a site box the host checks that the audit folder, the secrets folder and each anchor folder exist
   before the signer starts: Docker would make a missing folder, and an unmounted share would take the head on the
   box's own disk.
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
3. **The key is made where the site keys are sealed.** `deploy/hardening/seal_keys.sh` makes the audit key once,
   after the KEK exists, in both install forms (`install.sh`, and the box's apply step of `box-install.sh`); a key
   that is there is kept. A key that cannot be made is a message, not a stop: the installer must reach the wizard
   (OPS-003). When an anchor folder is already set, `install.sh` runs the night's command once, so the box has its
   first head at install; a failure there is a line of the install's report.
4. **`doctor` checks it.** A new check `audit_heads`: FAIL in VALIDATION and PRODUCTION (WARN in DEV and TEST) when
   no anchor folder is set, when an anchor folder is on the audit volume, when the audit key is missing, when the
   last night was refused or failed (the night leaves its result in the host's log folder), when a file in a
   folder's `heads/` is not signed by this box's key, or when the newest head this box signed in any folder is older
   than `TB_AUDIT_HEAD_MAX_AGE_H`. A folder with no head yet is a WARN while the audit key is younger than that
   limit (the first night has not run), a FAIL after. `check_host.sh` shows the in-image `doctor` the secrets volume
   and the anchor folders read-only. On a platform the check is a WARN: nothing signs heads there yet.
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
- The console's audit page already verifies with `TB_AUDIT_ANCHOR_TARGETS` (D-355), and the console mounts no such
  folder: with the name set, "Verify" called an intact chain broken. The compose file now clears the name for the
  console, so the page verifies against the head anchor until the console mounts the anchor folders (lane C).
- A box updated in place gets the cron line and the key when the installer or `seal_keys.sh` runs again; until
  then `doctor` FAILs `audit_heads` with the command.

## Not done here

- Shipping the signed heads with the backup, and the restore's check against them. After a restore to an earlier
  backup the chain is shorter than the newest signed head, and every night refuses until a person rules: the
  procedure belongs to the restore drill (T-213b).
- An audit event for a refused night (the result file and `doctor` carry it today), and a comparison of the anchor
  folder with the chain's own `audit.head_signed` events (a person who can delete files in the anchor folder and
  write the audit volume is not caught; the folder must be one the box's root cannot prune).
- Signed heads on a platform.
- The audit page's use of the signed heads (`services/console`).
