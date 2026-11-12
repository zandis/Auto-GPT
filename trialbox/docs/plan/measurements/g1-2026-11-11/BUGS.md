# Bugs found by the integrator session and G1, 2026-11-10 to 11-12

This is every error the integrator session met while integrating and running G1. Each entry gives:

- **Symptom**: what was seen.
- **Evidence**: where it can be checked.
- **Cause**.
- **Fix**: what should change.
- **Status**.

Severity: Blocker (stops a run or a site), High (wrong or lost results), Medium (cost, time or confusion).

Open items come first. The fixed ones are kept so the same mistake is not made again.

## A. Open: the cloud run driver (`tools/complete_run.py`, `deploy/gcp/complete-run.sh`)

### A1. A results-only collect deletes the finished part results on the VM (High)

- **Symptom.** `complete-run.sh --collect 20261111T183639Z-986d91c9`, run after the spot VM was pre-empted, printed
  `--resume: 3 part result(s) of another run or HEAD removed: hospital-ja install prepare`.
- **Evidence.**
  - The collect log of 2026-11-12, 02:04 UTC.
  - `tools/complete_run.py`, `drop_stale_parts()` (line 859), called from `run_all()` (line 882).
- **Cause.** The "results-only" boot that `--collect` starts on a TERMINATED VM runs `run_all --resume`. That path
  calls `drop_stale_parts(parts, run_id, head)`, which deletes every part file it does not judge to be "the same run".
  The boot passes a run id and HEAD that do not match the parts written by the real run: the shard suffix `-s1`, or the
  results-only HEAD. So it deletes 5 hours of finished, paid-for results.
- **Impact.**
  - A `--shard 1` resume after a pre-emption re-runs hospital-ja from zero: 2.5–5 h, US$7–14.
  - If the local copy had not been collected first, the results would have been lost for good.
- **Fix.**
  1. The results-only boot must never delete anything: skip `drop_stale_parts` when no part runs.
  2. `same_run()` must treat `<run_id>` and `<run_id>-s<N>` as the same run.
  3. Add a unit test: a part file written with id `X-s1` survives `run_all --resume` with run id `X`.
  4. Add a rehearsal case: pre-empt after part 3, collect, resume, and the parts already done are kept.
- **Status.** Open.

### A2. The gcloud credentials expire during a long run (Blocker for unattended runs)

- **Symptom.**
  - The first launch of attempt 2 printed `VM 1 ended with an error` and
    `Request had invalid authentication credentials. Expected OAuth 2 access token`. No VM started and nothing was billed.
  - A `--collect` later hung past 10 minutes (`rc=124` from `timeout 600`) with the same error.
- **Evidence.** The launch log of 2026-11-11 at 18:36 UTC, and the collect log of 2026-11-12 at 02:04 UTC.
- **Cause.** The driver relies on a service-account activation stored in a private `CLOUDSDK_CONFIG`. Its access
  token lapses after hours. The driver neither re-activates nor fails fast: a `gcloud` call without a token waits or
  retries instead of failing.
- **Fix.**
  1. The driver activates the service account itself (from `TB_SA_KEY_FILE`) at the start of every command: launch,
     collect, stop and shard.
  2. Every `gcloud` call gets a short timeout and a clear error ("credentials expired: re-activate").
  3. Add a test: `--collect` with an expired token fails within 60 s with that message.
- **Status.** Fixed in #296.

### A3. A pre-empted part restarts from zero (High; costs money)

- **Symptom.** The spot VM was pre-empted at 00:06 UTC on 11-12, 5.5 h into attempt 2, just after hospital-ja ended. A
  pre-emption 2 hours earlier would have lost the whole hospital part.
- **Evidence.** The compute operation `compute.instances.preempted` at 2026-11-11T16:06:59-08:00.
- **Cause.** Parts are only resumable between parts. A hospital part runs 5 h, and `part_hospital` removes its work
  folder at start, so no stage inside it can resume.
- **Fix, in either order.**
  1. Run the two hospital parts on an on-demand VM (about 3x the price for those hours, no pre-emption), or
  2. Make the hospital part resumable by stage: keep the stage results and the screened job and skip finished stages.
  3. Either way, the cap must be re-computed for a resumed shard (see A4).
- **Status.** Open. This is review finding G1-2 in PR #279.

### A4. The estimate for a hospital part is far too low (Medium; makes the hard cap unsafe)

- **Symptom.**
  - The estimate is 2.14 h per hospital part (`estimate()`: 920 note patients × 6.3 s + 300 s canary + 161 s × 10).
  - Measured: hospital-ja took **17,960 s (5.0 h)**, of which screening took 8,584 s (2.4 h).
- **Evidence.** `hospital-ja.json` in this folder (`wall_seconds`, stage 15 at 8,584 s).
- **Cause.** The estimate counts the screening only. It leaves out prepare at 50k and the other 19 stages.
- **Impact.** The cloud hard cap is `estimate × 1.3`.
  - For the full plan (9.45 h → cap 13 h) the measured parts already need about 2 × 5 h for the hospitals plus the rest.
  - For a resumed or `--only` run (2.64 h → cap 4 h) the cap STOPs the VM in the middle of a hospital part.
- **Fix.** Use the measured 5.0 h per hospital part at 50k, and scale it with the patient count. Re-check the cap with
  the new figure before the next launch.
- **Status.** Open.

### A5. The partial report says FAILED for parts that never ran (Medium; confusing)

- **Symptom.** The partial report says `report FAILED: 6/28 checks` while every part that ran had passed. Parts not yet
  started count as `<part> did not report`.
- **Cause.** The report does not tell "not run yet / not run" apart from "failed".
- **Fix.** Add the states `pending` and `not run (VM stopped)`. FAILED only when a part that ran has a failed check.
- **Status.** Open.

## B. Open: the product

### B1. Stage 12: a confirmed fact does not count as expected (High; correctness)

- **Symptom.** hospital-ja, stage 12 "site set-up and data harmonization", 22/23. The failed check reads "confirmed: it
  counts like coded data and may exclude (the malignancy), or makes a patient ready". It returned 7 outcomes:
  `ready, needs, not_eligible, ready, needs, not_eligible` plus one more.
- **Evidence.** `hospital-ja.json`, stage `12 site set-up and data harmonization`, and the check with `false`.
- **Cause.** Not yet known. The check passed in the 500-patient rehearsals and failed at 50k. Suspects:
  - a confirmed fact is read from a snapshot older than the confirmation (the lake rebuild timing at 50k);
  - the check's expected set assumes the small synthetic site.
- **Fix.** Reproduce with `tools/complete_run.py --only hospital-ja --patients 50000` on the stub model (no GPU
  needed), then fix the cause, not the check. This touches D-149 / T-207 (derived and confirmed facts).
- **Status.** Open.

### B2. Fixed limits tuned for small data break at production scale (Blocker class)

- **Summary.** This is the bug class behind the drain failure. PR #279 (`docs/reviews/2026-11-11-scale-timeouts.md`,
  merged) lists 36 findings (3 Blocker, 9 Critical, 10 High, 14 Medium) with file:line, the arithmetic and the fixes.
  It proposes cards T-687 to T-704.
- **Must fix before go-live:**
  - F-01: site publish times out on the lake rebuild and restarts it every minute.
  - F-02: the nightly backup pauses every service for 30–75 min at 50k.
  - F-05: ingest and rebuild need 16–17 GB against 6–8 GB container caps.
- **Card T-687** is the test that would have caught all of them: a nightly 50k run under the real compose memory caps
  with a slow model stand-in.
- **Status.** Open (two fixed in #279: F-03 and F-06).

### B3. The ruleset compiler writes into the source `rulesets/` folder (Medium)

- **Symptom.** A unit test that compiled rulesets changed files under `trialbox/rulesets/` in the checkout, which
  raced with another test (`test_rc_demo`).
- **Cause.** `rulesets_path` defaults to `REPO_ROOT/rulesets` and the compiler rewrites it in place. The test was
  fixed with `TB_RULESETS_DIR` in a temp folder (#88); the default is unchanged. A stray `rulesets/.git` was also left
  in a checkout.
- **Fix.** Default to a copy under `TB_DATA_DIR`, and never write to the source tree. Add a test that the checkout
  is unchanged after a compile.
- **Status.** Open.

## C. Fixed: keep them fixed

| # | What broke | Cause | Fix |
| --- | --- | --- | --- |
| C1 | G1 hospital-ja crashed after 2.6 h with `TimeoutError('queue not drained')` | `Orchestrator.drain()` failed every finished job longer than a 600 s window. One 50k screening job runs for hours | #258: no window; only the optional `total` cap. Test: two 9,500 s jobs drain |
| C2 | The first G1 launch was refused: "RTX PRO 6000 GPUs quota not readable" | Compute Engine lists no regional RTX PRO 6000 metric | #90: `GPUS_ALL_REGIONS` is the bound |
| C3 | The short run's hospital-ja: "queue not drained" at 600 s in all | A fixed budget for the whole queue | #88 (then C1) |
| C4 | Judge model down: the verifier answered as the judge and confirmed itself (LLM-002) | Gateway fallback across aliases on the `patient` route | #101 (D-276): no fallback for patient or consent routes; the two builds are compared |
| C5 | Master `docs` red: a D-271 entry was added to a frozen `DECISIONS.md` | #97's CI ran before T-002 froze the log, and it merged after | #102: decision file |
| C6 | Master `unit` red: `test_notice.py` | #80 added catalogue folders after #99's NOTICE check listed them | #111 |
| C7 | #89: `test_no_applied_ddl_string_changed` failed | The site store's version 3 (#66) was missing from the D-204 baseline, so a box that ran it would refuse to start | Fixed in #89 |
| C8 | #89: the offline box media would lack the database image | Box media kept only two `trialbox-*` images | Fixed in #89 (and the pin test) |
| C9 | A `make test` piped into `tail` hid a failure, and a red commit was pushed | `&&` after a pipe takes the pipe's status | Practice: never pipe a test command into `tail` in an `&&` chain |

## D. Process errors (no code; they cost time or money)

- **D1. Merging a PR whose CI ran on an old base broke master twice (C5, C6).** Before each merge, merge master into
  the branch or run the base's newest gates (`decisions_index --check`, the unit suite) on the merged tree.
- **D2. A paid run needs a fixed, rehearsed commit.** Master moves every few minutes. Rehearse one commit, push it to a
  `g1/rehearsed-*` branch, and launch from it. This was done for attempt 2.
- **D3. The 2.6 h hospital failure ran on for 3 more hours before it was stopped (about US$9 lost).** A long paid run
  must be checked within one part's length of each risky part, and stopped at once when a part that decides the run
  fails.
