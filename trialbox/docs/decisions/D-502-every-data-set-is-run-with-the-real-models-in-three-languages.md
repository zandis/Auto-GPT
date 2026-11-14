# D-502 Every data set is run end to end with the real models, in three languages

- **Task:** the run matrix (lane G; the lanes' replies are in issue #579)
- **PR:** lane G's branch that replaces #507 (`lg/batch5`)
- **Date:** 2026-11-14
- **Status:** accepted (the owner's ruling of 2026-11-14; numbered by the integrator)
- **Builds on:** D-150 (the rehearsal before any paid launch), D-468 (spot and on-demand VMs), plan v7 section 13.1
  (G-1 to G-10)

## Context

Until now a data set counted as covered when a stub run passed on it, and the paid GPU runs measured chosen parts
(the 50,000-patient hospital in Japanese and Traditional Chinese, the probes G-3 to G-8). Nothing said which data
sets must be run with the real models, in which languages, who starts the runs, or what "done" means.

## Decision

The owner's ruling, word for word:

> Every data set the project has, public or synthetic, is run end to end with the real models in all three
> languages: English, Japanese, Traditional Chinese. "Done" means a paid GPU run by lane G with results committed
> under docs/plan/measurements/, not a stub run. Lane G owns the runs: it rehearses, brings the owner the cost, and
> starts only on his yes. No other lane starts a VM. Lane replies collect in issue #579; lane G builds the run
> matrix from it. The full matrix is measured after the screening-answer fixes (#567, #570, #572, #573, #576) and
> B14 land. Per lane B2's reply, the 50,000-patient hospital stays ja and zh-TW; English is run at the ci-en size
> (5,000) once NEW-B-42 lands. CGRD is not part of the matrix.

In short:

1. **What is run.** Every data set the project has, public or synthetic, end to end, with the real models, in
   English, Japanese and Traditional Chinese.
2. **What "done" means.** A paid GPU run by lane G whose results are committed under `docs/plan/measurements/`. A
   stub run is not "done".
3. **Who runs.** Lane G only. It rehearses (`make rehearse`, D-150), brings the owner the cost
   (`deploy/gcp/complete-run.sh --estimate`), and starts only on his yes. No other lane starts a VM.
4. **The matrix.** The lanes reply in issue #579; lane G builds the run matrix from the replies.
5. **When.** The full matrix is measured after the screening-answer fixes (#567, #570, #572, #573, #576) and B14
   (`docs/plan/measurements/lane-g-findings-2026-11-13.md`) are on master.
6. **Sizes.** The 50,000-patient hospital stays Japanese and Traditional Chinese (lane B2's reply). English is run
   at the ci-en size, 5,000 patients, once NEW-B-42 is on master.
7. **Not in the matrix.** CGRD.

## What it does not do

- It starts no run and approves no cost: each launch still needs the owner's yes on that launch's estimate.
- It changes no code. The matrix itself, and the parts of `tools/complete_run.py` it needs, come with later pull
  requests of lane G.
