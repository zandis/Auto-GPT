# D-1357 the unit shards run on every pull request

- **Task:** H-120, lane H; the owner's process change, the integrator's comment 7125828711 item 1 on #639
  (2026-11-24): "the CI workflow never skips the unit shards on a PR, whatever paths it touches"
- **PR:** this branch (`claude/lane-h-120-unit-shards-on-every-pr`)
- **Date:** 2026-11-24
- **Status:** accepted (the card is the ruling; the changed test assertions go to the integrator by id)
- **Amends:** D-564 (a draft runs the fast tier), D-969 (a docs-only card runs the fast tier), D-970 (a card on no
  full-tier path runs the fast tier): for the jobs `unit-shard` and `unit` only. Every other job keeps its tier.

## Context

Since D-970 most card pull requests ran the fast tier, so the unit tests ran only on the card's train. Four reds on
trains on 2026-11-24 came from pull requests whose shards had been skipped. A pull request skipped the shards in five
ways: the tier (a card on no full-tier path, unless labelled `ci:full`), a draft, a docs-only diff (D-969, whose list
of documents that code reads was found incomplete the same day, L-CI-1), a diff with nothing under `trialbox/` (the
`trialbox` output), and a `changes` job that failed: its outputs were empty, both unit jobs were skipped, and a
skipped required check counts as passed.

## Decision

1. **The answer is the tier code's.** `tools/ci_tier.py` prints a third output, `unit`: `true` on every pull request,
   whatever its draft state, labels, `CARD_TIER`, branch name or paths; on a push and a run by hand the same as
   `full` (so a master push at a tree a green train proved, D-578, still skips them). The log's line says which.
2. **The workflow reads only that answer.** `unit-shard` and `unit` run on
   `${{ !cancelled() && needs.changes.outputs.unit != 'false' }}`. "Not false" rather than "true": a `changes` job
   that failed or printed nothing runs them. The `trialbox` gate is gone from these two jobs. `unit` still fails
   when any shard did not pass, so on a pull request it is never skipped and never a pass without its shards.
3. **A documents-only pull request runs them too.** Nothing proves that a document cannot change a test's result:
   tests read the runbook, the licence register and the plans, and `ci_docs_only.CODE_READS` was found incomplete.
   When in doubt the shards run. The `cross-card` job still runs the tests that read the changed documents first.
4. **The policy test.** `tests/unit/test_h120_unit_shards_every_pr.py` runs `tools/ci_tier.py` over a table of path
   sets, draft states, labels, `CARD_TIER` values and branch names, then evaluates the two jobs' real conditions
   with its outputs. A small evaluator of GitHub's expression syntax does this, and it refuses any context other
   than `needs.changes.outputs.unit`. The test also checks the triggers (no path, branch or type filter), `needs`,
   the matrix, the steps up to pytest and `continue-on-error`.
5. **Nothing else about the tiers changes.** `property`, `goldens`, `e2e-simple`, `demo-boot`, `security`,
   `standards` and `images` keep `full` (and `scenarios`). `ci:full` still asks for them.

## Consequences

- The cost is the shards' minutes on every pull request run that was fast tier before. From 18 green runs with all
  eight shards (2026-11-24, from the public Actions API), the median is 159 runner-minutes per run (the shards'
  sum, plus `unit` at under a minute) and 30 minutes of wall time to `unit`. The fast tier's own jobs are unchanged.
  A new push still cancels the older run of the same pull request.
- Check names do not change: `unit-shard (1/8)` to `unit-shard (8/8)` and `unit`. On a pull request they now always
  report, expanded. Before, a skipped matrix reported under the unexpanded expression, D-725. Branch protection
  needs no edit. `unit` is never left pending: it runs, or the run was cancelled and the next push runs it.
- A head commit whose message holds a skip-CI marker starts no workflow at all. No condition in the workflow can
  close that. The required `unit` then stays expected and blocks the merge (not verified: branch protection is
  not readable here).
