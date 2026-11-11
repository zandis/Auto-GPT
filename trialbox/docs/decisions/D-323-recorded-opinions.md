# D-323 Recorded first and second checks on the demo, each marked with its source

- **Task:** T-515 (wave P of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2)
- **PR:** this branch (`agent/T-515-test-model-labels`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Closes:** UX-007 (the console part; the real-pair opinions follow with the G1 short run)

## Context

The demo runs the test model. It never disagrees with itself, so no patient page in the demo shows the
"First check / Second check" block, and the clinicians in the PoC cannot judge the two-model check (UX-007). The
review asked for opinions recorded from the real model pair in the G1 short run. The owner parked the G1 run, so
those opinions do not exist yet.

## Decision

1. **A fixture shape for recorded opinions.** A JSON file holds agree and disagree cases per study and criterion,
   each with the judge's and the verifier's verdict, quote and date, and a source (`synthetic` or `recorded`, with
   a name). `services/console/recorded_opinions.py` checks the shape and lays the cases over the latest candidate
   list. A case lands only on a listed patient whose criterion already has the verdict the case implies (the shared
   verdict when the checks agree, unknown when they disagree), so a fixture never contradicts a row.
2. **DEV and TEST only.** The console reads fixtures only from `TB_DEMO_OPINIONS` and only with `TB_ENV` DEV or
   TEST. The demo points it at `demo/fixtures/opinions/`. A production box never shows a recorded opinion.
3. **Every opinion says where it came from.** On the patient page, the candidate page and the weekly list each first
   or second check carries "synthetic example", "recorded run" (with the run's name) or "test model" (the box's own
   test model answered). The patient page explains "first check / second check" once and marks a disagreement.
4. **Synthetic until G1.** Until the G1 short run exists the folder holds only `synthetic.json`, hand-made and
   marked: every quote starts with `[synthetic]`, and the loader refuses a synthetic quote without the mark. The G1
   file drops in as `g1-short-run.json` with source `recorded` (the folder's README); no code changes.

## Consequences

- The PoC shows an agreement and a disagreement on the demo list today, honestly labelled as made up.
- When G1 runs, its cases replace or join the synthetic ones by adding one file.
- How the engine forms the two checks and refuses one model asked twice stays with D-276; this decision is display
  only.
