> **SUPERSEDED on 2026-11-14: not evidence of the shipped product.** See `SUPERSEDED.md` and [the validation reset plan](../validation-reset-2026-11-14.md).

# G1, 2026-11-11: partial results (50,000 patients, Japanese hospital part)

One RTX PRO 6000 spot VM (`tb-gpu-sim`, asia-east1-a, g4-standard-48, US$2.74 an hour), synthetic data only.
Code: branch `g1/rehearsed-2026-11-11`, commit `986d91c`. That is `2cc2ad7`, rehearsed 2026-11-10, plus the drain
fix of PR #258. The rehearsal of `986d91c` passed 6/6. Run id: `20261111T183639Z-986d91c9`.

## Attempts

| Attempt | Run | Outcome | VM time | Cost |
| --- | --- | --- | --- | --- |
| 1 | `20261111T114128Z-2cc2ad7` | hospital-ja crashed after 2.6 h with `TimeoutError('queue not drained')`: `Orchestrator.drain()` failed every finished job longer than 600 s. Stopped by hand. | about 6 h | about US$16 |
| 2 | `20261111T183639Z-986d91c9` | install, prepare and hospital-ja completed. The spot VM was **pre-empted** at 00:06 UTC on 11-12, just after hospital-ja finished. | about 5.5 h | about US$15 |

Total spent on G1: **about US$31.5**. Both VMs are TERMINATED, as verified on 2026-11-12 at 02:10 UTC. The remaining parts were
not run: hospital-zh-TW, the 14 scenarios, public-ja/zh-TW, embed and profile.

## What was measured (attempt 2, hospital-ja)

- **The drain fix works.** The 50,000-patient Japanese screen ran its screening stage for 8,584 s (2.4 h) and
  passed.
- **19 of 20 stages passed in full.** These cover data in, feasibility, approval, screening, the lists, mail, REDCap,
  audit, data capture, the trial lifecycle, the Japan data checks, the ClinicalTrials.gov reference data, re-run,
  delegation and EDC prefill.
- **Screening funnel**: S0 30,369, S1 1,193, S3 1,193, S4 623. Listed 623 (33 high, 590 review); excluded 29,746.
  Cohort list for GOUT-COH: 36.
- **The model pair** ran in mode agreement (`both_agree`): 8 disagreements and 3 failures. The pair canary passed,
  so notes may exclude. A note excludes only when both models agree.
- **No false model exclusion.** Every model exclusion matched the generator's note truth (db-csv check).
- **Part wall time** 17,960 s (5.0 h), inside the 480-minute limit.
- **Peak GPU memory** 62,592 MiB of 97,887 MiB (64 %).
- **One failed check, in stage 12** (site set-up and data harmonization), 22/23. The check is "confirmed: it counts
  like coded data and may exclude, or makes a patient ready". The run produced 7 outcomes where the check expected
  another set (see `hospital-ja.json`, stage 12). This needs a look by the owner of D-149 / T-207 (confirmed facts
  counting like coded data).

Files: `hospital-ja.json`, `install.json`, `prepare.json` (part results), `gpu_peak.json`, `plan.json`, `TB_HEAD.json`,
`report-partial.md`. The report says FAILED because it counts the parts that never ran as "did not report".

## Bugs found by G1, for the build session

1. **Drain stall window.** Fixed in #258 (merged).
2. **Resume drops finished parts.** A `--collect` of a pre-empted VM boots it "results-only", and that boot printed
   `--resume: 3 part result(s) of another run or HEAD removed: hospital-ja install prepare`
   (`tools/complete_run.py` `drop_stale_parts`, line 859). A resume would then re-run hospital-ja from zero. The local
   copies were collected before this and are the files here. The fix: the results-only boot must not run the stale
   check, or must pass the run's own id and HEAD.
3. **Credentials expire during a long run.** The service-account activation in the private gcloud config lapsed
   between checks, so one launch failed before start (no cost) and one collect timed out. Re-activate before each
   driver call, or have the driver do it.
4. **Spot pre-emption loses a part in progress.** A part does not resume inside itself (review G1-2, PR #279).
5. **Fixed limits that break at scale**: 36 findings in PR #279 (`docs/reviews/2026-11-11-scale-timeouts.md`).

## To finish G1

The remaining parts are hospital-zh-TW, the scenarios, public-ja/zh-TW, embed and profile: about 7 h, about US$19,
cap US$35.62, and the owner's yes first. Run them after bugs 2 and 3 are fixed and after the Blockers of #279 that touch
the run (G1-1 to G1-4) are fixed. Consider an on-demand VM for the two hospital parts, so that a pre-emption does not
lose a 2.5 h part. Launch only from a rehearsed commit.
