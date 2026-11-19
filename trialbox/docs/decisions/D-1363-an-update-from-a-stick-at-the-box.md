# D-1363 An update from a stick at the box: verify, the quiet hour, the release note; going back stays at the box

- **Task:** lane K, plan 10 row 10K-7 (review 18 SO-7: "Update from a stick inserted at the box: verify, schedule,
  'return to the previous release'; a Japanese release note and change-impact sheet in each bundle")
- **Date:** 2026-11-19
- **Status:** proposed
- **Builds on:** D-178 (the Operations page writes requests, the host's runner runs them), D-210 (the signed bundle,
  the older-release path `--allow-downgrade REASON`), D-731 (an update asked for the quiet hour), D-344 (the change
  classes CC1 to CC6)

## Context

The command line already verifies, applies, waits for the quiet hour and rolls back. A hospital IT person still had
to copy the bundle into `deploy/updates/incoming` as root, nothing told them in Japanese what a release changes, the
console had no "apply in the quiet hour" button (D-731 left it to the console), and going back after a good update
is "apply the previous release's bundle" with `--allow-downgrade REASON` at the terminal.

## Decision

1. **The note and the sheet in each bundle.** `tools/release_note.py` builds `RELEASE-NOTE.ja.md` and
   `CHANGE-IMPACT.json` (`trialbox-change-impact/1`) from one source per release,
   `docs/releases/next-release.ja.yaml`: a Japanese title and summary, every change class CC1 to CC6 stated changed
   or not (with what changed, in Japanese, when changed), and the impact (minutes down, migration, rulesets to approve
   again, IT's actions). `tools/make_bundle.sh` runs it before any image is exported and refuses the bundle when the
   source does not read or leaves a class unstated (`--release-note FILE` names another source). Both files are
   payloads of kind `other`, so the signed manifest holds their sha256.
2. **The verifier warns, it does not refuse.** `tools/verify_update.py` reports them in the summary's
   `release_note` (present or not, the changed classes, warnings) and prints a `WARNING` line when one is missing or
   the sheet does not list the classes. It refuses only for integrity and safety (D-210); the note decides nothing,
   and refusing would break the bundles a site must still take: one built before this card, the previous release a
   site returns to, a key rotation, an OS patch. The bundle maker is where the note is required.
3. **The stick.** The runner lists the bundles directly on the stick's mount (`TB_UPDATE_STICK`, default
   `/media/trialbox-update`; regular files of a bundle's name, never a link) in the status. The console's "Verify
   and copy to the box" (`update_stick_check`) is the runner's `update_check` with `from: stick`: it copies the file
   into the incoming folder (a temporary name, renamed when whole; a different bundle of that name already there is
   refused; the stick is only read), runs the same `apply_update.sh --dry-run`, removes its copy when the verifier
   refuses it, and keeps the verified bundle's note and sheet in `<ops>/notes/` for the page (shown only while the
   file is the one verified, by size and time).
4. **The quiet hour from the console.** "Apply in the quiet hour" (`update_quiet`) is the runner's `update_apply`
   with `when: quiet` (D-731). The confirmation says the time, that it runs without anyone at the box, the backup and
   automatic rollback, and the 26-hour limit; the waiting updates are listed with why; the status says the quiet hour
   and a setting that does not read.
5. **The same rights.** `update_stick_check` sits under `ops.update_check` and `update_quiet` under
   `ops.update_apply`, the administrator's rows of `libs/tb_common/authz_matrix.yaml`; no row is added or widened.
   Each is a `console.ops` audit event with its arguments, as the other operations are; the source (`from`) and the
   time (`when`) are set by the route, never read from the form.
6. **"Return to the previous release" is shown, not offered.** The update tab names the release before the current
   one (from the update history) and whether its bundle is on the box. Applying it is an older release
   (`--allow-downgrade REASON`, audited `update.downgrade`), which no role can do from the console today; offering it
   would widen what the console can do (lane K rule 11). It stays the RUNBOOK §5 path at the box until the owner
   decides (below).

## Consequences

- The drill `python -m tools.update_drill stick` (no database; `tests/unit/test_update_from_a_stick.py`) shows the
  card: insert, verify (the note shown, the sheet listing CC1 to CC6, a tampered bundle refused and not kept, a link
  not followed), apply in the quiet hour on a frozen clock (waits at 15:00, runs at 05:30), and return to release 1
  through the older-release path, with `update.applied`, `update.applied`, `update.downgrade`, `update.applied`.
- Each release's pull request that sets the version rewrites `docs/releases/next-release.ja.yaml`, as it moves
  `CHANGELOG.md`'s lines.

## For the owner

- **Return to the previous release from the console** needs a yes: either `update_apply` with a downgrade reason
  under `ops.update_apply`, or a new row (for example `ops.update_downgrade`, administrator only). The host runner
  would pass `--allow-downgrade REASON`; nothing of it is built.

## Not covered

- The host's mount unit for the stick (read-only, by label) and the hospital's media procedure (review 18 §9,
  question 3): the runner reads whatever is mounted at `TB_UPDATE_STICK`.
- A rollback point kept after a good update (the update path deletes it, D-210); going back is the previous bundle.
