> **SUPERSEDED on 2026-11-14.** This order of work is overtaken by `docs/plan/37-remaining-work-split.md` and by lane
> G's validation reset ([validation-reset-2026-11-14.md](validation-reset-2026-11-14.md)): its paid runs were of lane G's own serving and in-process box, not the shipped
> product. Kept as history; do not follow it.

# Lane G (cloud runs): the order of work to the end of wave 1, and what runs in parallel

Written 2026-11-12, about 14:00 UTC, against plan v7.2 (`docs/plan/33-plan-v7.md`, sections 5 and 7.1) and the GCP
test plan (`docs/plan/32-gcp-test-plan.md`, pull request #316). This is a working note of lane G. It changes no
card, no date and no other lane's folder.

## 1. What limits lane G

Three things are serial, and nothing in this note makes them parallel:

1. **One GPU VM at a time** (quota `GPUS_ALL_REGIONS` = 1). Every paid launch waits for the one before it to be
   collected and read, and for the owner's yes to its estimate.
2. **The merge queue.** #310, #333 and #335 change the same driver files and merge one at a time through a
   saturated CI. A new pull request that edits those files adds a rebase round to each of them.
3. **Lane D.** The product-on-GPU run (plan step 7; tests G-2, G-6, G-9, G-11) needs the embedder image, the
   installer that reaches the wizard, the qualification path and the offline bundle. They are wave 1 cards and
   land by 2026-12-04.

So lane G is faster only in two ways: the GPU is never idle because the next launch's driver work is not ready,
and the hours between "the VM stopped" and "the next launch is approved" are short.

## 2. The order

| # | Work | Who | When | Waits on |
| --- | --- | --- | --- | --- |
| 1 | Launch the combined run from `g1/rehearsed-2026-11-12` (9c09e3fd): L1 parts, G-1, G-3 at 1, 4, 16, 48; 5,000 patients; 2.33 h, US$6.38, cap US$10.96 (approved) | main session | 2026-11-12 | nothing |
| 2 | Merge #310, then #333 (retargeted to `master`), then #335, then #316, each when its `unit` run is green. #316 is documents only and conflicts with none of them: it may go first if it is green first | main session | wave 0 | CI |
| 3 | Collect the run; write the results pull request `claude/g1-results-2026-11-12` with the report, the G-1 verdict, the G-3 table and the defect list for the integrator | main session, with worker B's reader | 2026-11-12 to 11-13 | 1 |
| 4 | NEW-PERF-1 (the wave 1 row of lane G): `complete_run` sets `TB_SCREEN_LLM_CONCURRENCY` from the serving record. #333 is its pull request; the setting it chooses is the one G-3 measured in step 1 | main session | wave 0 to wave 1 | 2, 3 |
| 5 | The small driver additions the next launch needs, as one pull request after #335 merges: X-2 (`--langs`), X-6 (the workers list), X-11 (keep the pair's raw answers), and what is left of X-3's result field and X-5 after #333 | main session | wave 0 | 2 |
| 6 | L2 (50,000 patients; g1, embed, profile; test-plan section 6.1): estimate, rehearse, the owner's yes, launch, collect, results pull request | main session | wave 0 to wave 1 | 3 read, 5, owner |
| 7 | G-3 in full (50,000; ja then zh-TW; 1, 4, 8, 16, 32, 48) and L3 or its 5,000-patient form (decision D-A of the test plan) | main session | wave 1 | 6 collected, owner |
| 8 | The box-install run script and its rehearsal on stand-ins (X-10; the driver side of G-2, G-9, G-10) | worker A | wave 0 | nothing |
| 9 | Swap worker A's stand-ins for lane D's real installer, wizard answers and bundle; `make rehearse` on the fixed commit; estimate to the owner | main session | from 2026-12-04 | 8, lane D |
| 10 | The product-on-GPU run and its report (wave 2; the box order of 2026-12-18 reads it) | main session | by about 2026-12-11 | 9, owner |

### The critical path

`lane D's wave 1 cards (12-04)` → `step 9` → `step 10` → `capacity statement and hardware note` → `the order on
2026-12-18`. Lane G's own part of it is step 8 and step 9: if the box-install script is first written after lane D
lands, step 10 moves into the week of the order. Built and rehearsed now, step 9 is a swap and one rehearsal.

Steps 1 to 7 are not on the path to the order, but they feed it: G-3's chosen setting and calls per second are
the figures the capacity statement starts from, and a defect found at 5,000 patients is cheaper than the same
defect found in step 10.

## 3. What runs in parallel now

The rule for parallel work in this lane: **new files only**, in lane G's folders, branched from `master`. Nothing
that edits `tools/complete_run.py`, `deploy/gcp/complete-run*.sh`, `tests/rehearsal/rehearse.sh` or `check.py`
starts until #310, #333 and #335 are merged; those edits stay with the main session (step 5).

Two worker sessions were started on 2026-11-12, 13:58 UTC. Each opens one draft pull request and stops. Neither
merges, calls GCP or touches product code.

| Worker | Session | Branch | Builds | Acceptance |
| --- | --- | --- | --- | --- |
| A | `session_013CtyYR6Dj1zikbSHp9yVWw` | `claude/lane-g-box-install-run` | `deploy/gcp/box-install-run.sh` (bundle, installer, wizard answers, pin, qualify, promote, serving capture, the restarts and power cycle of G-9, the canary of G-10; watchdog, cap and door as in `complete-run-vm.sh`; resumes after a reboot without repeating a finished step); stand-ins and cases under `tests/rehearsal/box-run/`; `tests/unit/test_g1_box_install_run.py` | the unit test passes with no network; five cases: happy path, a failed step stops with its record, reboot and resume, the cap fires, a bundle hash mismatch is refused |
| B | `session_013CtyYQ8GVRtBkE5Z6PEw22` | `claude/lane-g-results-reader` | `deploy/gcp/results_report.py`: a collected results folder becomes the results pull request's README, G-1 verdict, G-3 table (window computed from patients, studies and night hours, no constant), `capacity_inputs.json` for T-667, T-637 and T-734, and `DEFECTS.md` for the integrator; `tests/unit/test_g1_results_report.py`; `docs/plan/measurements/RESULTS-PR-TEMPLATE.md` | the unit test passes; on `g1-2026-11-11` (a real partial run) missing parts are marked, not dropped and not passed |

Worker B's reader is placed in `deploy/gcp/` because lane G's row names its tools one by one and a new file under
`tools/` would be outside it. If it should live in `tools/`, the integrator adds it to the row first.

What the main session does with them: wire worker A's runner into `make rehearse` (the Makefile is not a worker's
file); use worker B's reader on the run of step 1 if its pull request is up before the collect, by running it from
the worker's branch; nothing waits for it.

## 4. Considered and not started

| Item | Why not now |
| --- | --- |
| Readers for the embedder decision (T-607), the profile cost (T-311a chain) and the embedder refit (G-17) | Their inputs are the `embed`, `profile` and `vec` parts. No run has written those parts on the pair yet, and `vec` does not exist (X-3). A reader written before the data's shape is known would be rewritten after L2. Do it when L2 is collected; `capacity_inputs.json` is the place to extend |
| X-4 (serving settings from metadata, the sweep mode) | It edits `complete-run-vm.sh`, which #310 and #335 change. After the merges; it serves L4, which is wave 2 |
| X-12 (forced pre-emption on the real VM) | It edits the driver and its `--dry-run` check is a GCP call. With step 5, by the main session |
| A third worker | The owner's allowance showed a warning, and nothing else is both independent of the open pull requests and certain |
| T-317 inputs | T-317 is lane D's guides and the acceptance run on the site's box (wave 4 and step 15). Lane G gives it nothing before the product-on-GPU run |

## 5. What would change this plan

- The run of step 1 fails for a product reason: it is not repeated (test-plan stop rule); the finding goes to the
  integrator in the results pull request, and step 6 waits for that card only if the failing part is in L2.
- Lane D's installer interface differs from what worker A assumed: the assumptions are listed in worker A's pull
  request body, one function per step, so the change is local.
- Lane D lands after 2026-12-04: step 10 moves day for day, and plan v7.2 section 4 already says the order is then
  made on the measured Linux figures available.
