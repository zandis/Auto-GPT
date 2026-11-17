# D-1134 The GPU driver names the qualification record's code by the installed release's commit

- **Task:** lane H, card H-19 (the integrator's ruling on H-15 finding F1: "evidence gates keep the git sha")
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-994 (`commit` beside `dirty` in `deploy/updates/installed.json`), D-881 (the code a record names
  on the driver's route), D-734 (the code identity)

## Context

The three evidence gates of `trialbox eval qualify` (`n12`, `public_e2e` and `goldens`, all `step_evidence` in
`tools/qualify.py`) compare the git commit an evidence file names with the record's own code (`git_head()`). The GPU
driver (`deploy/gcp/box-install-run.sh`, `d_qualify`) runs qualify in the box's python image. The box was installed
from a bundle, so there is no git. The driver mounts no release tree. The record's code was therefore
`image:<the image's id>` (`tools/code_identity.py`, D-881), and the evidence files' commit could never equal it. No
full qualify through the driver could pass (H-15, F1). The integrator ruled that the gates keep the git sha. Lane D's
installer now records the release's commit in `installed.json` (D-994).

## Decision

1. **The driver reads the installed commit.** Before qualify starts, `code_commit` in `box-install-run.sh` calls the
   VM helper `box_vm.py installed-commit $BOXROOT/deploy/updates/installed.json`. The helper prints the commit only
   when it is 40 lowercase hex and `dirty` is exactly `false`. Otherwise it exits 1 and names the reason:
   - the file is missing or unreadable, or is not a JSON object;
   - `dirty: true` (a bundle built with `--allow-dirty`, as every rehearsal bundle is). This is named first;
   - `commit: missing` (a box installed before D-994: update it);
   - `commit: null` (the release names no commit);
   - `commit: malformed` (anything else, an image id among them);
   - `dirty` missing or not a boolean.
2. **Qualify names the code by it.** The driver passes `-e TB_CODE_COMMIT=<commit>` to the qualify container beside
   `TB_CODE_IMAGE`. `tools/code_identity.head` takes it after a git checkout and a signed release tree, and before
   the image id. A 40-hex value names the code as a checkout's commit does (`dirty` false). Any other non-empty value
   gives `unknown` and dirty, which serving_record refuses. The serving record keeps the image id beside the commit
   (`steps.serving_record.detail.code_image`). The part notes `code_commit`.
3. **When a refusal stops the step.** In production mode, or whenever `--qualify-evidence` is given, the record can
   be the product's record. A refusal there is the step's STOP: `TB-CODE-COMMIT-REFUSED: ... <reason>`. A validation
   run without evidence, and G-10's qualify, are measurements, and their records cannot pass the evidence gates
   anyway. They run on with the code named by the image as before, and the part notes `code_commit_refused` with the
   reason.
4. **The gates are unchanged.** `step_evidence`, `git_head`, `code_problems` and the record format are not changed.
   The image-id route of D-881 behaves as before when `TB_CODE_COMMIT` is not set.

## Proof

- `tests/unit/test_h19_installed_commit_driver.py`:
  - the helper on a clean record, and its refusal by name of each bad case (dirty true; commit null, missing,
    uppercase, 39 and 41 characters, a trailing space, an image id, a number, a list; dirty missing or a string; not
    an object; not JSON; no file);
  - the driver's own `code_commit`, run in bash with the real helper. It hands over `TB_CODE_COMMIT` and stops a
    record run on each refusal. A measurement runs on and the refusal is noted;
  - the wiring in `d_qualify`, `step_qualify` and `step_g10_qualify`;
  - `code_identity` takes only a 40-hex commit;
  - serving_record names the commit, with the image id beside it;
  - **a record made on the driver's route passes the three evidence gates unchanged.** The route is `installed.json`,
    then the driver's function, then qualify's environment in an `/app` with no git. The n12 evidence is written by
    `tools.n12_screen` on that commit. Named by the image alone, the same route fails all three gates.
- The rehearsal `tests/rehearsal/box-run`: the stand-in installer writes `installed.json` from the bundle's
  `release.json`, as `Updater._record` does. The stand-in qualify names its code as `code_identity` does. `check.py`
  holds, for every full start, that `08-qualify` notes the run's commit and that the record names it.

## Not here

Nothing ran on a real VM and no model was called. Lane D's installer (D-994) and the gates are untouched. A box
installed before D-994 needs an update before its driver run can make a record.
