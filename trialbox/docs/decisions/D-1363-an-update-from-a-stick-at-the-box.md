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

**After the independent review** (NOT READY: 3 blocking, 7 to fix; each fixed with its test):
- *The status stays small.* The notes are no longer copied into `status.json`, which the console reads with a
  64 KiB cap (26 staged bundles made the page lose its whole status). The runner keeps one small record per verified
  bundle (`<ops>/verified/<bundle>.json`: the sha256 and the file's size, time and inode), which the status lists,
  and the note apart (`<ops>/notes/<bundle>.json`), which the console reads per bundle with a cap (192 KiB) and shows
  as "too large" above it. `tools/release_note.py` caps the note at 32 KiB and the sheet at 16 KiB, at build and when
  read from a bundle.
- *The check is bound to the bytes.* A bundle's name is matched whole and is ASCII only (`[A-Za-z0-9][A-Za-z0-9_.-]*
  .tar`): `$` matched before a trailing newline, so `x.tar\n` was listed and copied while `apply_update.sh`'s
  `basename` verified the genuine `x.tar`, and `\w` took look-alike letters. The sha256 is taken while the file is
  copied (or before the verify), the file's identity must not change until the note is read, and the record and the
  note carry it. "Verified" on the page is that record of that file; the note is shown only from a note record of the
  same sha256; "Apply" and "Apply in the quiet hour" are offered only then, and send the sha256: the runner refuses
  any other file of that name (and `apply_update.sh` verifies again). A failed check removes an earlier record.
- *The copy is bounded.* The stick's file is looked at before it is opened (a folder, link, device or pipe is refused
  without opening it), exactly the size seen at open is copied, at least 10 GiB must stay free on the disk after the
  copy, and the copy runs in a thread the runner watches: no byte for 2 minutes, over 2 hours, or under 1 MB/s after
  5 minutes stops it, removes the part file and frees the runner's lock. The stick must be mounted
  `ro,nodev,nosuid,noexec` (RUNBOOK §5, "Updates from a stick").
- *An account with `ops.update_check` alone can cause a stick-to-box copy* (today the administrator only): it writes
  only into the incoming folder, never runs anything from the stick, and is bounded by the free-space floor above.
- *A waiting quiet apply can be cancelled* on the page (`update_cancel`, under `ops.update_apply`, no matrix row):
  the runner takes a cancel before the update it withdraws, never one that has started; audited `console.ops`.
- *The listing* finds the bundles among any number of other files (20,000 entries looked at), lists the first 50 by
  name and says when it is cut, and counts the `.tar` files whose names are refused; `make_bundle.sh --release-note`
  without a file says how to give one.

**After the integrator's review of d314d016** (five High, each first reproduced by a test at the real call that
failed on d314d016, then fixed; `tests/unit/test_update_from_a_stick.py`, `tests/console/test_ops_pages.py`):
- *H1, the verifier reads once.* `tools/verify_update.py` no longer opens the bundle a second time for the note and
  the sheet: their bytes are kept while `_check_payloads` hashes every payload from the one open file, and the
  summary's `release_note` is built from those bytes against the manifest whose signature was verified. The verifier
  still imports nothing beyond its own modules (the rehearsal's set). `read_from_bundle` (which checks no signature)
  is now called only on the runner's private copy below, the bytes `apply_update.sh` verified.
- *H3, one descriptor from hash to install.* The runner opens the staged file once (`O_NOFOLLOW`, a regular file,
  looked at before the open and the same file after it), copies its bytes from that descriptor into a fresh folder
  under `deploy/updates/.ops-held` (a real folder, 0700, the runner's own, or refused) while hashing them, hashes the
  copy again, compares the sha256 with the confirmed one, and gives `apply_update.sh` the copy's path; the copy is
  removed when it returns. Chosen because `apply_update.sh` takes a pathname and verifies it before anything else,
  also in its docker fallback, which mounts that path into a container: a `/proc/self/fd/N` path cannot be mounted
  there and stdin is not a file the verifier can seek. The private copy keeps its verify-first order unchanged; it
  costs the bundle's size once more on that disk, under the same floor as the stick copy (10 GiB must stay free).
  The check (`update_check`) uses the same copy: the sha256 recorded, the bytes `--dry-run` verified and the note
  shown are one set of bytes. An apply that names no verified sha256 is refused by the runner.
- *H2, the release shown is the release applied.* The Apply buttons carry the sha256 and the release id of the
  verified bundle the page showed, and so does the confirmation sheet. At each post the console compares them with
  that bundle's verified record now; another file or release id, or no record, is refused (409, "this is not the
  verified bundle you were shown", en/ja/zh-TW) and audited `console.refused`. The queued request carries that
  sha256, never one read later; nothing is queued without one.
- *H4, the drill deletes only its own folder.* `--dir` (both `update_drill` and `update_drill stick`) is a folder that
  does not exist yet (made, with the mark `.tb-update-drill`) or one holding that mark, which is emptied (the folder
  kept, links inside removed, never followed). A folder without the mark, a link (even to a marked folder) or a file is
  refused, exit 2, before anything is removed.
- *H5, a cancel accepted before the installer starts stops the update.* Each waiting update has one decision record
  beside the requests (`requests/<id>.decided`, written once by a hard link, so the first of the two writers wins and
  neither is overwritten). The console accepts a cancel only by writing `cancel` there, and refuses it (409, "this
  update has started", translated, audited `console.refused`) when the runner wrote `start` first. The runner runs a
  cancel that arrived while earlier requests ran (a backup) before it looks at the update, skips an update whose
  record says `cancel`, and writes `start` immediately before `apply_update.sh` starts, after the limit is asked and
  the private copy made; a `cancel` there first stops it (result `cancelled`, nothing changed). The confirmation's
  sentence says so: a cancel is taken until the moment the update starts, even while a backup runs before it. Who may
  start, confirm or cancel is unchanged.

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

- The review of d314d016's other findings (one more High: the stick copy's watchdog and a blocked `close()`; the
  Mediums) are not part of this round.

- The host's mount unit for the stick (read-only, by label) and the hospital's media procedure (review 18 §9,
  question 3): the runner reads whatever is mounted at `TB_UPDATE_STICK`.
- A rollback point kept after a good update (the update path deletes it, D-210); going back is the previous bundle.
