# H124: the update's code comes from the signed new bundle

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders.

- **Card:** H-124, the integrator's ruling 7128338428, after H-121's finding H121-06. Before this, the update's checks
  and applying code always came from the installed tree, so a fault in them could be mended only by a reinstall.
- **Date:** 2026-11-24
- **Findings:** [`h124-update-code-from-the-bundle-2026-11-24/findings.json`](h124-update-code-from-the-bundle-2026-11-24/findings.json)
- **Files:** `tools/apply_update.sh` (the hand-off and the one constant), `tools/host_tree.py` (`stage_code`, the
  `stage-code` command), the new test `tests/unit/test_update_code_from_the_bundle_h124.py`, three rows in the H-94 page's
  `tools/apply_update.sh` table, `tools/trialbox/update.py` (`update_code` in two audit events).

## 1. What runs from where

| Step | Code | Why |
| --- | --- | --- |
| arguments, the unfinished-update refusal, `tools.keys check --for-update` | installed | the box's own state |
| `tools/verify_update.py` with `deploy/updates/trust.json` or `deploy/keys/*.pub` | installed | a bundle never vouches for itself |
| the host tree: its sha256 in the manifest, `HOST-SHA256SUMS`, member rules | checked by the installed verifier, then again by the installed `host_tree.stage_code` | |
| the start guard (`deploy/settings_guard.sh`) | installed | the box's guard, unchanged |
| `tools.trialbox update`: preflight, backup, rollback point, apply, migrate, check, automatic rollback | **the new release's** | the point of the card |
| `apply_update.sh status`, `rollback`, `clean` | whatever `current` names | as before |

The new release's code runs from `$STAGE/code`. That is the signed host tree unpacked into the update's own 0700
stage, which the script removes on exit. Its `deploy` is one link to the box's own `deploy/`, so the new tools,
libs and schemas read the box's own settings, keys, records and configuration, as the installed code does. A tool
finds `deploy/` beside its own folder (`tools/trialbox/launch.py`). `host_tree.install`, inside the update, then
unpacks the same checked tar under `releases/<id>` as before.

**A bundle without a host tree.** This follows the integrator's ruling 7131272906:
- On PRODUCTION it is refused before anything runs, saying why and what to do: "Ask the vendor for the release's
  full bundle, or install it with the bootstrap (RUNBOOK §5)".
- On a PoC box it is warned and listed in `deploy/site/poc-stops.jsonl`, and the installed code runs.
- **A signed model pack** (H-95, `pack.kind: model`; the integrator's ruling 7132081597) runs the installed code on
  every box and says why: it carries images and weights, no code. The installed verifier checks it against the
  installed key and refuses it if it carries a host tree or anything else but images and weights
  (`pack_problems`). It also refuses any weight file that is code, a script or pickle weights
  (`MODEL_PACK_REFUSED_SUFFIXES`, a superset of `tools/pin_model.py`'s refused types).
- The output names the code that ran (`update code: ...`), and so do the audit events `update.applied` and
  `update.rolled_back` (`update_code`: `bundle` or `installed`). The update decides that from where its own file is,
  never from the environment.

The start guard runs before this choice, as before H-124, so its refusals come first.

**The limit.** Only a box whose installed `apply_update.sh` has H-124 gains it. A box on an older release still runs
its own update code once (H124-02).

## 2. The tests (`tests/unit/test_update_code_from_the_bundle_h124.py`)

Each case runs the real installed `tools/apply_update.sh`, of a box made from this repository's own host tree, on
bundles from the real signer, with a stand-in `docker`. A "fault" is a `main_apply` planted in a release's update
code that fails at once.

- **The invariant:** `test_h124_a_fault_in_the_installed_update_code_does_not_stop_an_update_to_a_fixed_release`.
  The installed R1 is broken and the update to a fixed R2 succeeds.
- The control: R1 is sound and R2 broken; R2's code runs, so the update fails and the box is unchanged.
- A host tree changed after signing is refused by the installed verifier; none of it runs.
- A bundle without a host tree runs the installed code and says so. PRODUCTION follows the one constant.
- A caller's `PYTHONPATH`, or the constant's name in the environment, does not choose the code.
- SIGTERM to the update's process group while the new code holds the marker: the box is still on R1 and the stage is
  removed. The installed tree's `apply_update.sh status` names R2, and its `rollback R2` clears the marker.
- The order of the hand-off; and the staged `deploy/` is the box's own.

**Mutants:** two planted, two caught. They are the hand-off back to the installed code (`CODE` left at `$ROOT`), and
the installed `PYTHONPATH` with `cd "$ROOT"`. Each fails the invariant, the control, the environment case and the
SIGTERM case. A mutant that drops `stage_code`'s own `check_tar` is not caught: the installed verifier refuses first.
The second check is defence in depth.

## 3. No caller's environment steers the trust (H124-01, the ruling's point 2)

- The vendor key is the installed key file alone: `deploy/keys/vendor_ed25519.pub`, put there by the bootstrap,
  or `deploy/updates/trust.json` once it exists. It must be a file of its own, not a link, owned by root or by the
  user running the update; otherwise the update is refused (kept stop (1)).
- Whether the verifier runs in the box's Python image, and which image, come from the box's own `deploy/.env`
  (`TB_VERIFY_IN_DOCKER`, `TB_PY_IMAGE`).
- A caller's `TB_VENDOR_PUBKEY`, `TB_VERIFY_IN_DOCKER` and `TB_PY_IMAGE` are unset unread. Each has a test that
  setting it changes nothing.
- **Other files.** Tests that set these variables now set them in their box's `deploy/.env`, or run the script of a
  `checkout_box` that holds its own key file. Their assertions are unchanged: `test_update_signals_h114.py`,
  `test_poc_stops_h94.py`, `test_load_from_the_stick_h95.py` (f7), `test_update_bundle.py`, `test_host_baseline.py`,
  the runbook commands test file, `test_update_safety.py`. The H-95 software packs and whole bundles
  (`test_load_from_the_stick_h95.py`) now carry this checkout's host tree, as `tools/make_bundle.sh` builds them.
- **Not changed:** `deploy/gcp/demo-vm-update.sh` (lane D's) exports `TB_PY_IMAGE` and `TB_VERIFY_IN_DOCKER`; lane D
  writes them into the demo VM's own `deploy/.env`. `deploy/install.sh` still reads `TB_VENDOR_PUBKEY` for its own first check (line 406).

## 4. Space for the update's own code (H124-06, ruled 7132484063)

The staged code is one more unpacked copy of the host tree in the stage. The update's `space_needs` runs after it is
unpacked, when it is already on disk, so it is counted where it can still be refused:
- the installed verifier's space to stage now counts the host tree twice: the staged tar and its unpacked copy, both
  read from the signed manifest, against the free space of the file system that holds TMPDIR, where
  `apply_update.sh` makes the stage, never the install root's (7133378239);
- `tools/packs.py` counts the copy in the load's peak and in `space`, and its bound allows twice the host tree;
- tests: `test_h124_06_a_stage_short_by_exactly_the_update_code_is_refused` (short by exactly that amount: refused;
  one byte short: refused; enough: staged).

**H-95's peak-disk test** (`test_load_from_the_stick_h95.py`). Its software packs and whole bundles now carry their
host tree, as `make_bundle.sh` builds them.
- The old assertion was `peak <= installed * 1.10`.
- The new one is `peak <= installed * 1.10 + 2 * host`, where `host` is the host tree's size that the software
  pack's signed manifest declares. It is read from the bundle, never measured in the run it bounds.
- A new case, `test_peak_disk_a_third_copy_of_the_host_tree_is_over_the_bound`, plants a third copy in the stage for
  the whole load and must be over the bound.
- Measured on the session machine: peak 104,869,888 bytes against installed 79,515,648 bytes.
- The install page of the runbook names the new bound.

## 5. A passphrase-backed box is updated in place (the integrator's ruling 7135119782)

On master, `apply_update.sh` refused the passphrase from the environment (H-97) and had no other way to take it.
After a restart a passphrase box's KEK is not unsealed, so the update's key check refused it, and such a box could
not be updated in place (the walk, 7135110331).
- `apply_update.sh` takes `--kek-passphrase-file FILE` (with `--keep-kek-passphrase-file`) or
  `--kek-passphrase-stdin`, as the bootstrap and the installers do.
- It uses their KEK-INPUT functions, byte for byte (a test holds them to `deploy/hardening/seal_keys.sh`'s): a
  regular file, not a link, owned by root (the user running it), mode 0600, in folders only root can write; never
  from the environment.
- The value goes by a pipe to `tools.keys unseal --passphrase-stdin` before the key check. It is never an argument
  and never printed; the file is removed once used unless kept.
- A wrong passphrase stops the update before anything changes. A passphrase given to a box whose KEK is not
  passphrase-backed is not used, and the script says so.
- Tests update a passphrase box both ways; they also check that the box without its passphrase is refused, that a
  wrong one changes nothing, and that a link, a group-readable file or the environment are refused.
- **For H-123's N-1 rehearsal:** the case is a passphrase-backed box installed from release N-1, restarted (its KEK
  not unsealed), then updated to N with `--kek-passphrase-file`, and again with `--kek-passphrase-stdin`. Until
  H-124 is in the installed release, N-1's own `apply_update.sh` has neither option.

## 6. The lifecycle review's Highs (lane LR, the integrator's 7136231344 item 3)

Each is reproduced at master by a test in `tests/unit/test_lifecycle_lr_h124.py` and fills its cell of the review's
matrix (`docs/reviews/lifecycle-deep-review-2026-11-24.md`).

- **LR-9, no boot guard** (cell: update, any step, N, power cut then boot). The boot unit's start guard,
  `deploy/settings_guard.sh` (its ExecStartPre), refuses while `deploy/updates/IN_PROGRESS.json` stands. It names
  `tools/apply_update.sh status` and `rollback <bundle>` on every box: a box between two releases is not shown whole
  (H-94 depends (1), as `apply_update.sh` refuses an update over it). At master the guard exited 0. The box
  rehearsal's doctor phase plants a marker on its installed box and runs the guard as the unit does: the real path.
- **LR-12, a failed rollback has no way out** (cell: update, prior failed rollback then restore). The new command is
  `tools/apply_update.sh close <bundle> --restored REASON`.
  - It is taken only for a marker whose last step is the rollback, so an update cut short elsewhere is never hidden.
  - It needs the restore's own record: a `backup.restored` event in the box's audit log, newer than the marker's
    start. The log is read where the box keeps it, from the box's `deploy/.env` (`audit_heads.host_dirs`), never
    from the caller's environment.
  - It needs the release back: the host tree `current` names the release its rollback point recorded as before.
    Images and models are not compared; the restore puts back databases and folders only (LR-12).
  - It removes the marker, audits `update.closed_after_restore` with the reason and the restore's time, and writes
    the history.
  - `status` names it, and so does a section appended at the end of the runbook's page 5 (two tests pin that
    page's earlier lines by number).
  - At master no such command existed.
  - Not done here: the restore naming the marker. `tools/trialbox/box_restore.py` is #1470's (H-126) in those lines.
- **LR-17, a loaded, never-started install refuses a corrected release** (cell: install.sh re-run, newer bundle,
  loaded and never started).
  - A first load marks its record (`installed.json`: `loaded_only`).
  - install.sh's load takes the next release on a box with that mark, no update history and no data volumes.
  - A box that has run, a plain update, and a record without the mark (every box installed before H-124) keep the
    refusal word for word.
  - At master it was refused: "installed ... but not running; start it".

## 7. The four recurring finding types

- **Ctrl-C or SIGTERM:** tested above. Bash runs the trap that removes the stage only after the foreground update
  exits.
- **Files written whole:** the stage's code is unpacked to `.code.partial` and renamed (`host_tree._unpack`).
  A separate commit (H124-03) fsyncs each file and each folder before the rename, and the parent after it.
- **Value sets and date windows:** not in this code.
