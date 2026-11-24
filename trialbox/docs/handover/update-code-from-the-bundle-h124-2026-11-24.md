# H124: the update's code comes from the signed new bundle

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders.

- **Card:** H-124, the integrator's ruling 7128338428, after H-121's finding H121-06. Before this, the update's checks
  and applying code always came from the installed tree, so a fault in them could be mended only by a reinstall.
- **Date:** 2026-11-24
- **Findings:** [`update-code-from-the-bundle-h124-2026-11-24/findings.json`](update-code-from-the-bundle-h124-2026-11-24/findings.json)
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
- **One exception, built here, for the integrator to confirm:** a signed model pack (H-95, `pack.kind: model`)
  carries images and weights and no code by design, so it runs the installed code on every box and says so.
  Refusing it would refuse every model-pack update on PRODUCTION.
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
  the runbook commands test file, `test_update_safety.py`.
- **Not changed:** `deploy/gcp/demo-vm-update.sh` exports `TB_PY_IMAGE` and `TB_VERIFY_IN_DOCKER`. The demo VM needs
  both in its `deploy/.env`. `deploy/install.sh` still reads `TB_VENDOR_PUBKEY` for its own first check (line 406).

## 4. The four recurring finding types

- **Ctrl-C or SIGTERM:** tested above. Bash runs the trap that removes the stage only after the foreground update
  exits.
- **Files written whole:** the stage's code is unpacked to `.code.partial` and renamed (`host_tree._unpack`).
  A separate commit (H124-03) fsyncs each file and each folder before the rename, and the parent after it.
- **Value sets and date windows:** not in this code.
