# D-620 An update runs the new release's own start-up steps

- **Task:** UPDATE-PRESTART (a finding in lane D's folder from lane C's reviews of #332, #337 and #390, passed on by
  the integrator on 2026-11-12)
- **PR:** this branch (`agent/UPDATE-PRESTART-new-tree-steps`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-138, D-210 (the update path), D-367 (the host tree: an update switches `current` to the new
  release's files)

## Context

`tools/apply_update.sh` starts the installed release's `python3 -m tools.trialbox update`. `apply_host` switches
the box to the new tree, and `ComposeBox.restart` then ran its host-side steps (the image pins, the model key) in
the same old process and started the stack with the new compose files. A step a release adds (a secret file a
new service reads, a role script) is not in the old process: it first ran on the update after the one that
brought it, and the update that brought it failed at the start of the stack and rolled back. Three cards of lane
C add such a step. Running `install.sh` with the new bundle is no way round: it loads the bundle through the same
installed updater.

## Decision

1. **`python3 -m tools.trialbox pre-start --deploy <deploy>`** runs a release's host-side steps before its stack
   starts. The steps are a list in `tools/trialbox/prestart.py` (`STEPS`); a release that adds one adds it there.
   A step is safe to run again, works with the stack down, and fails by raising `UpdateFailed`. The first two are
   the ones every release ran in the updater: the image pins and the model key.
2. **The restart of an update runs that command as a process of its own**, in the install folder, where `tools/`
   is the new tree since `apply_host`. A failure stops the update before the stack starts; the rollback follows as
   for any failure. Afterwards the updater reads `deploy/.env` again.
3. **A tree without the command** (a downgrade to a release from before it; a box with no host tree) gets the two
   old steps in the updater's own process, as before.
4. **The first release with the command cannot be helped by it**: the release installed before it restarts the
   old way. So a bundle that adds a start-up step names a release that has the command as its
   `min_installed_version`; the verifier refuses it on an older box before anything changes.

## Consequences

- The release that carries this card must add no start-up step of its own, or boxes installed before it cannot
  take it by update. No box is in the field yet; from the first field release on, the rule of item 4 holds.
- **Proof.** `tests/unit/test_update_prestart.py` runs the restart against a tree whose `tools.trialbox` is a
  stand-in for a later release with a step the installed code never heard of, as a real child process: the step
  runs before `compose up`, its `.env` line is read, a failing step stops the update before the stack starts, and
  a tree without the command gets the old steps. **Not proven:** an update between two real releases with real
  images. `tools/update_drill.py` runs the in-process box, not the compose box; the box rehearsal with a second
  bundle would be that proof and does not exist yet.

## After the adversarial review (2026-11-12)

No HIGH finding. The reviewer built two releases from this tree under a scratch folder, switched from one to the
other with the real host tree, and saw the second release's step run from the first release's updater, and the
first release's command again after switching back.

- **A fresh install did not run the command**, so a step added only to `STEPS` would have been skipped by every
  fresh install. `deploy/install.sh` now runs it before it starts the stack.
- **A relative `--deploy`** named a folder that is not there once the command had changed into the install
  folder; every step found nothing to do and the update went on. The paths are made absolute (not resolved: the
  symlinked layout stays), and the command refuses a deploy folder that does not exist.
- **What a step leaves survives a rollback** (`deploy/.env` and `deploy/secrets` are not in the rollback point):
  the contract of a step now says it must be harmless to the previous release.
- The child's lines are shown to the operator; a failure reads as the step's own reason, not the command line
  around it; `deploy/.env` is read again after a failure too.
- **Open:** no release records "I have the command". `min_installed_version` is a number a person writes; the
  first release number with the command has to be written into the runbook when that release is cut. Not built.
- **Open:** the older tests that reach `restart` have no tree beside their deploy folder and so run the two old
  steps in-process; only `tests/unit/test_update_prestart.py` runs the command.

