# D-970 a card runs the fast tier unless it is on the full-tier list

- **Task:** CI THROUGHPUT, lane D; changes D and E of the measurement posted on #639 (2026-11-16), which the
  integrator approved there with the full-tier list and its additions, the label name and the revert line
- **PR:** this branch (`agent/CI-TIER-card-prs-run-the-fast-tier`), stacked on D-969's
- **Date:** 2026-11-16
- **Status:** accepted (a trial; the integrator reverts it as below)
- **Builds on:** D-564 (the tiers), D-578, D-969 (a docs-only card runs the fast tier)

## Context

A card's pull request and its merge train both ran the full tier: about 141 runner-minutes each (median of 682 runs),
with unit-shard about 60 % of it, and the limit was concurrency. The train runs everything anyway.

## Decision

1. `tools/ci_tier.py` (standard library; the `changes` job runs it with the runner's python3) decides the tier and
   prints why. The workflow's `env: CARD_TIER` selects the rule for a card's pull request.
2. **E, the trial (`CARD_TIER: fast`):** a card's pull request runs the fast tier unless
   - a changed file is on `FULL_TIER` (condition iii: decides about a patient, guards patient data, sends patient
     files out, seals keys, the schemas, the gate itself; the integrator's additions: the adapter whole, the lake's
     `sqlguard.py`, `store.py`, `source.py` and `app.py` (the query guard, the tombstones and the query path; not the
     whole lake), datacore whole (its `lifecycle.py` holds the consent and withdrawal state), `mail_gateway`,
     `rc_bridge` and `edc`), or
   - it carries the label `ci:full` (condition iv). The labels are read through the API when the run starts, so a
     re-run sees a label added after the push; labels that cannot be read count as `ci:full`.
3. A merge train (`train/*`), a push to master and a run by hand run everything (condition i), as before. A draft and
   a docs-only card run the fast tier unless labelled.
4. **D, the revert (`CARD_TIER: touched`):** every ready card runs the full tier, except that a card whose every
   change is under `trialbox/deploy/`, `trialbox/tools/` or `.github/` and on no full-tier path skips `goldens`,
   `e2e-simple` and `demo-boot` (a new `changes` output, `scenarios`, gates those three). The integrator reverts the
   trial with that one line if more than one train in five goes red from a single card (condition v).
5. Condition ii (each `train-ready:` line states the lane's own full local run on its merged head) and the
   draft-first rule (C) are written in `docs/plan/43-ci-and-train-etiquette.md`.

`tests/unit/test_ci_tier.py` checks the rule and that every pattern of the list still matches a tracked file (a renamed
folder fails CI instead of leaving the list). `tests/unit/test_ci_tiers.py` runs the workflow's tier step as the runner
does, with a stand-in `gh` for the labels; D-564's cases run under `CARD_TIER=touched`, where its rule still holds.

`tools/trialbox/restic_repo.py` (PERF-010 R2, not on master yet) joins the list in R2's pull request.

## Consequences

- An ordinary card's pull request runs in minutes; its train still runs all of it before master.
- A card that breaks something only the full tier sees is caught on the train, which costs that train. That is the
  trade the trial measures.
