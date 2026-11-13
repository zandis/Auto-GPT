# D-547 The console's signing key is a pre-start step of its own

- **Task:** T-717b (the integrator's follow-up to T-717, #332, with lane D's UPDATE-PRESTART, #392)
- **PR:** this branch (`agent/T-717b-actor-key-prestart-step`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-485 (the console's signing key in a file of its own), lane D's pre-start command
  (`tools/trialbox/prestart.py`: a release's host-side steps are run by the new release's tree)

## The problem

T-717 made the signing key inside the updater's model-key step (`ComposeBox.ensure_model_key`). It ran from the
new tree, because the pre-start command calls that method, but it was no step: the log read "model key: in
place, or not a GPU box" on a box where a signing key had just been made, and the rule of the pre-start command
(a release that adds a step adds it to `STEPS`) was not kept.

## The decision

1. `ComposeBox.ensure_actor_key()` makes the key and the orchestrator's keys file on a box with per-service
   tokens; it answers made now, in place, or "no per-service tokens on this box". The model-key step no longer
   makes it.
2. `prestart.STEPS` has a third step, `actor signing key`, after the two every release ran. Its line is in the
   operator's log. A fresh install runs the same command (`deploy/install.sh`).
3. The updater's fallback for a host tree without the command runs it too, in its own process.
4. The step keeps the contract: safe to run again, works with the stack down, fails by `UpdateFailed` with its
   reason (a key that cannot be written), and what it leaves is harmless to the release before, which makes the
   same two files. A release from before T-717 reads the orchestrator's keys file with the token-derived key in
   it; a rollback to such a release is excluded by `min_installed_version`.

## What it does not do

- The role scripts of D-486 (#337) and of the FHIR store's role (#390) need the database up; they wait for the
  second hook "after the database is up", which is lane D's with this lane.
- The first release with the pre-start command cannot be helped by it (lane D's record): D-485's sentence about
  the update that brings the key stays true for a box updated from a release before the command.

## What the adversarial review changed

One review by a fresh reviewer. Verdict: merge; no HIGH or MED. No path that made the key lost it (the step, the
fallback, `install.sh`'s `secrets init`); ownership and mode are as before. From its LOW points: a key that
cannot be written was a traceback in the operator's log and is now `UpdateFailed` with the reason (test first);
point 4 above said the release before reads neither file, which was wrong, and is corrected; one more test holds
the step to the call.

## Reuse check

Lane D's pre-start command covers it: this card adds one step to it.

## Dropped (D-311)

No sign-off step.
