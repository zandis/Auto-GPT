# D-725 A plain-named gate for each matrix pair

- **Task:** CI-GATES (the owner's D-501, through the integrator, 2026-11-14: require goldens, e2e-simple, property
  and security)
- **PR:** this branch (`agent/CI-GATES-one-plain-name-per-matrix`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-206 (the CI gate), D-564 and D-578 (tiers)

## Context

`goldens` and `e2e-simple` are matrix pairs (one leg per lake source); each job's name is an expression,
`${{ matrix.lake_source == 'legacy' && 'goldens' || 'goldens (omop)' }}`. When the `changes` job skips them (a
draft, a proved push, a pull request that needs no full tier), GitHub does not expand the expression: the check
runs of #381, #545 and #551 (2026-11-13) report it as `matrix.lake_source == 'legacy' && 'goldens' || 'goldens
(omop)'`. A required check named `goldens` would then never report, and every such pull request would wait for ever.
`property` and `security` are plain jobs: skipped, they report under their own name, and a skipped job satisfies a
required check.

## Decision

One gate job per matrix pair, `goldens-gate` and `e2e-simple-gate`, in `.github/workflows/trialbox-ci.yml`:

- plain name; `needs: [changes, <the pair>]`; `if: always()`; no checkout and no action (seconds of a runner);
- passes when the `changes` job passed and the pair's result is `success` (both legs passed) or `skipped` (the
  `changes` job, which passed, did not ask for it); fails when a leg failed or was cancelled, and when the
  `changes` job did not pass (its dependents are then "skipped", which is not a pass);
- says what it saw.

The owner requires, once this is on master: **`goldens-gate`, `e2e-simple-gate`, `property`, `security`** (the
workflow's header and the runbook, section 3, say so). The gates run in every tier; the tier test knows them.

## Test

`tests/unit/test_ci_required_gates.py`: each of the four is a job whose name is a plain string; each gate needs
its pair and `changes`, runs always, checks nothing out; its script, run with every combination of results, passes
only on success or a rightly skipped pair (before: 19 of 21 failed, the jobs did not exist).

## Not covered

- Not run on GitHub here (actionlint is not on this machine; `checks` runs it). The result values (`success`,
  `failure`, `cancelled`, `skipped`) are GitHub's documented values for `needs.<job>.result`.
- The branch rule is the owner's to edit; this card only makes the names exist.
