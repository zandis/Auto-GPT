# D-564 Two tiers of CI: a draft pull request runs the fast tier; the full tier runs once it is ready, and on a merge train

- **Task:** CI-TIERS (asked by the owner through the integrator on 2026-11-12: "does every card really need its own
  full CI run"; plan TB-PLAN-07 v7.2 section 5, lane D: `.github/workflows`)
- **PR:** this branch (`agent/CI-TIERS-draft-fast-tier`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-206 (the CI jobs), D-475 (T-747: the unit shards, the aggregate check `unit`, the fast
  `cross-card` job), D-311 (no development gates)

## Why

A push to any pull request started about 28 jobs. With five lanes pushing, the hosted runners backed up: on
2026-11-12 jobs waited 40 minutes and more, and a card that had to take master again paid the whole round again.
Most of those jobs answer a question that only matters at the moment of merging.

## Decision

1. **Fast tier, on every push to a pull request, draft or not:** `changes`, `lint`, `types`, `docs`, `contracts`,
   `data-scan`, `shell`, `trace`, `cross-card` (workflow `trialbox-ci.yml`) and `lock` (`trialbox-supply-chain.yml`).
   Minutes, not a queue.
2. **Full tier, only when the pull request is not a draft, and on any branch named `train/*`:** `unit-shard` and its
   aggregate `unit`, `property`, `goldens`, `e2e-simple`, `demo-boot`, `security`, `standards`, `images`, and the
   image gates of `trialbox-images.yml`. Marking a pull request ready starts it (`ready_for_review`). A push to
   `master` and a run by hand run everything, as before.
3. **`unit` is success only from a real full run.** On a draft the check shows as skipped, never as success. The
   name does not change (branch protection and the lanes' tooling read it).
4. **One run per pull request.** Every workflow that runs on pull requests has a concurrency group per pull request
   with `cancel-in-progress`: a new push cancels the old run of the same pull request.
5. **The merge train.** A lane's own pull request needs the fast tier green on its head, its targeted tests and
   its review. The integrator builds `train/<n>` from `master` by merging the heads of several reviewed pull
   requests (`git merge --no-ff`) and opens it as a pull request: the full tier runs once on it. A green train is
   merged with a merge commit (not squash), so the card pull requests show as merged. A red train names the
   failing tests; the card that owns them is dropped and the train rebuilt.
6. `tests/unit/test_ci_tiers.py` pins which job is in which tier: a new job must be put in one.

## Consequences

- A card's push costs the fast tier. The full tier's cost is paid once per train, not once per card and again at
  every merge of master.
- A defect only the full tier finds is found at the train, not at the card's push; the train says which test, and
  `make test SHARD=i/N` or the test's own command repeats it.
- A draft pull request can no longer be merged on a green `unit` of its own: it has none. Until the first train,
  marking a pull request ready still runs the full tier on it.
