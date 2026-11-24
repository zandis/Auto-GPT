# H124: the update's code comes from the signed new bundle

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders.

- **Card:** H-124, the integrator's ruling 7128338428, after H-121's finding H121-06. Before this, the update's checks
  and applying code always came from the installed tree, so a fault in them could be mended only by a reinstall.
- **Date:** 2026-11-24
- **Findings:** [`update-code-from-the-bundle-h124-2026-11-24/findings.json`](update-code-from-the-bundle-h124-2026-11-24/findings.json)
- **Files:** `tools/apply_update.sh` (the hand-off and the one constant), `tools/host_tree.py` (`stage_code`, the
  `stage-code` command), the new test `tests/unit/test_update_code_from_the_bundle_h124.py`, one row each for its
  two new lines in the H-94 page's `tools/apply_update.sh` table.

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

**A bundle without a host tree** (an older bundle format) runs the installed code, and says so on stdout and
stderr. That is not one of the five stops of D-1091. On PRODUCTION the integrator rules between warn and refuse
(#639). Until then the one constant `H124_NO_HOST_TREE_PRODUCTION=warn` in `tools/apply_update.sh` decides; set to
`refuse`, it stops PRODUCTION only, before anything runs.

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

## 3. The four recurring finding types

- **Ctrl-C or SIGTERM:** tested above. Bash runs the trap that removes the stage only after the foreground update
  exits.
- **Files written whole:** the stage's code is unpacked to `.code.partial` and renamed (`host_tree._unpack`).
  `_unpack` does not fsync; that is a separate commit (H124-03).
- **Value sets and date windows:** not in this code.
