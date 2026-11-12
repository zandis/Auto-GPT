# D-468 G1 hospital parts: an on-demand VM for a shard with a hospital part; a resumed shard's cap re-computed

- **Bug:** G1 A3 (`docs/plan/measurements/g1-2026-11-11/BUGS.md` on branch `claude/g1-results-2026-11`; review
  finding G1-2 of PR #279)
- **PR:** this branch (`fix/g1-A3-hospital-on-demand`). It is built on the branch of G1 A4 (`fix/g1-A4-hospital-estimate`,
  PR #299), which was not merged when this one was cut: the cap of a resumed shard depends on A4's measured hospital
  figure.
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-141 (the fail-safe cloud run, the hard cap), D-148 (shards of whole parts), D-150 (the run's
  resume between parts)

## Problem

The spot VM of G1 attempt 2 was pre-empted at 00:06 UTC on 2026-11-12, 5.5 h into the run, just after hospital-ja
ended. Two hours earlier, the whole hospital part would have been lost. A part resumes only between parts: `part_hospital` removes its work folder at
start, and `e2e_simple` runs its 20 stages in one process on one in-memory box. The part is 17,960 s at 50,000
patients (A4), so a pre-emption inside it costs up to 5 h of card time and the wall time to run it again.

## The two options, read in the code

1. **Resume by stage.** Each stage of `tools/e2e_simple.py` (about 1,900 lines) takes its inputs from the results of
   the stages before it, in memory: the box (orchestrator, databases, lake), the jobs, the list, the pids. To resume
   at stage *n*, the box's stores, the screened job and every value a later stage reads would have to be written to
   disk and read back, and each stage would need a skip check. That is new state in the product's end-to-end
   path, with its own failure modes (a half-written stage, a box restored at another snapshot). It cannot be shown
   safe without many 5 h runs.
2. **An on-demand VM for the hospital parts.** Compute Engine does not pre-empt a STANDARD VM. The change is in
   the driver only: one `--provisioning-model` flag on the `set-scheduling` call it already makes before every start.
   The part, the VM script and the product do not change.

**Choice: option 2, the smaller safe one.**

## Decision

1. **A shard with a hospital part runs on demand; every other shard stays spot.**
   - `complete_run.provisioning(tags)` gives STANDARD for a shard with a `hospital-*` tag and SPOT otherwise.
   - `shard_plan` writes each shard's `provisioning` and `price_per_hour` into the plan.
   - The driver sets the model with the cap, before the start:
     `gcloud compute instances set-scheduling <vm> --max-run-duration=<cap>h --instance-termination-action=STOP
     --provisioning-model=STANDARD|SPOT`.
   - `--stop` puts a VM back to SPOT, so that a VM started by hand later does not pay the on-demand price.
2. **The price.** `ON_DEMAND_PRICE_PER_HOUR` is 3 x `PRICE_PER_HOUR` (US$8.22 against US$2.74), the owner's figure
   ("about 3x the spot price"). It must be checked on the billing page before a launch. The estimate, the plan's
   US$ and the "at most US$" of the cap use it for an on-demand VM.
3. **Quota.** An on-demand VM draws on the regular GPU and CPU quota, not the PREEMPTIBLE one.
   `quota_problems(..., standard=zones)` checks that, and the driver passes the zones of its on-demand shards
   (`--quota-standard`).
4. **A resumed shard re-computes its cap (and its model).** `TB_RUN_ID=<run id> complete-run.sh --shard i`
   after a pre-emption used the launch plan's cap. Now `shard_run` asks `complete_run --shard-now` for what the shard
   has left:
   - A part counts as done when a collected result passed and was made by `<run id>-s<i>` at the archive's HEAD
     (`TB_HEAD.json`), which is exactly what the VM's `--resume` keeps.
   - The results are looked up in both `shard-<i>/parts` and the merged `parts/`.
   - The estimate, the cap (x 1.3, rounded up) and the provisioning model are those of the parts left. A shard whose
     hospital part is done restarts on spot.
   - When nothing is known (no collected results, no HEAD), the whole shard counts: the safe, larger cap.
5. **What stays.**
   - Shards of whole parts, longest first (D-148).
   - The resume between parts (D-150, and A1's fix).
   - The VM's own watchdog and hard cap.
   - The rehearsal: its gcloud stand-in records `set-scheduling` and ignores the model.

## Cost consequence (50,000 patients, from `--estimate`)

On demand costs about 3x the spot price for the hours of a VM that holds a hospital part.

| run | VMs | wall | US$ (spot before) | US$ now | at most (caps) |
| --- | --- | --- | --- | --- | --- |
| full plan, `--parts g1,embed,profile` | 4 | 5.5 h | 45.6 | 105.8 (2 x 45.1 on demand + 2 x 7.8 spot) | 153.4 |
| the same | 1 | 15.2 h | 41.5 | 124.5 (all on demand) | 164.4 |
| finishing G1: the parts not yet run | 2 | 5.5 h | 29.2 | 59.3 (hospital-zh-TW on demand 45.1 + the rest spot 14.2) | 84.9 |
| the same | 1 | 10.2 h | 27.8 | 83.5 (all on demand) | 115.1 |

- With one or two VMs, the VM that holds a hospital part also runs other parts on demand.
- **Recommendation:** run with `--vms 4` for the full plan, or `--vms 2` to finish G1. The two hospital parts then
  sit on their own on-demand VMs, and the other parts stay on spot.
- The extra cost against an all-spot run is about US$60 a full run (2 x 5.49 h x US$5.48). One pre-emption inside
  a hospital part on spot costs up to 5.5 h x US$2.74 = US$15 of card time again, plus 5.5 h of wall time and the
  risk of a second pre-emption. The owner accepted the price for those hours (BUGS.md A3 fix 1).

## Not done

- Resume by stage (option 1) is not built. If the price matters more than the wall time later, it is the way back
  to spot.
- Changing the provisioning model of an existing stopped VM with `set-scheduling` is what the driver does.
  The rehearsal does not check that Compute Engine accepts it: confirm on `tb-gpu-sim` while it is stopped
  (`gcloud compute instances set-scheduling tb-gpu-sim --zone asia-east1-a --provisioning-model=STANDARD`, then back
  to `SPOT`) before the first launch under this decision.
- An on-demand GPU VM can still be stopped by host maintenance (the GPU VMs' `onHostMaintenance=TERMINATE`). That
  is rare and announced. The resume between parts and this decision's re-computed cap cover it as they cover a
  pre-emption.
