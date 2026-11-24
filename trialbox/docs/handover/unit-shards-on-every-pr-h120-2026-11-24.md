# The unit shards run on every pull request (2026-11-24)

**Reader:** the people who build TrialBox: lane H, the integrator and the independent reviewer.

Card H-120 implements the owner's process change (integrator 7125828711, item 1, on #639). The CI workflow never
skips the unit shards (`unit-shard`, eight jobs) or their aggregate `unit` on a pull request. A policy test fails if
any pull request can skip them. Decision: `docs/decisions/D-1324-the-unit-shards-run-on-every-pull-request.md`.
Findings: `unit-shards-on-every-pr-h120-2026-11-24/findings.json` (H120-01 to H120-03).

## The ways a pull request skipped the shards, and how each is closed

| Way | Before | Now |
| --- | --- | --- |
| the tier: a card on no full-tier path, no `ci:full` (D-970) | `full=false` skipped both | the jobs read `unit`, which is true on every pull request |
| a draft (D-564) | `full=false` | the same |
| a docs-only diff (D-969) | `full=false` | the same: the shards run (see below) |
| a label | only `ci:full` added the shards; no label removed them | labels do not matter; a condition reading one is refused by the test |
| nothing under `trialbox/` (`trialbox=false`) | both skipped | the gate is gone from the two unit jobs |
| `changes` failed or printed nothing | empty outputs: both skipped, and a skipped `unit` counts as passed | `!cancelled() && unit != 'false'`: they run |
| a path, branch or type filter on the trigger | none (D-725 note) | the test forbids one; `ready_for_review` must stay |
| `needs` on a job that can be skipped | `changes` only | held: `changes` has no `if` and no `continue-on-error` |
| the matrix emptied or narrowed | literal 1..8 | held: one axis `shard`, a literal 1..N equal to the pins' count, no include or exclude |
| a step's own `if` before pytest, `continue-on-error` | none | held, for the shards' steps up to `make test` and for `unit`'s two gate steps |
| a skip-CI marker in the head commit's message | starts no workflow | cannot be closed in a workflow; branch protection should hold it (H120-02, not verified) |

**A documents-only pull request runs the shards.** The rule says every pull request. Nothing proves that a document
cannot change a test's result: tests read the runbook, the licence register and the plans, and
`ci_docs_only.CODE_READS` was found incomplete (L-CI-1). When in doubt the shards run. The `cross-card` job still runs
the tests that read the changed documents, first and alone.

**Everything else about the tiers is unchanged.** `property`, `goldens`, `e2e-simple`, `demo-boot`, `security`,
`standards` and `images` keep `full` (and `scenarios`). `checks`, `data-scan`, `cross-card`, `powershell` and
`differential` keep `trialbox`. A push and a run by hand get `unit` = `full`, so a master push at a tree a green train
proved (D-578) still skips them, as before.

## The policy test

`tests/unit/test_h120_unit_shards_every_pr.py::test_every_pull_request_runs_the_unit_shards` is one of 126 tests in
the file. The rest:

- `tools/ci_tier.py` is run as the `changes` job runs it, over a table of 13 path sets × draft or not × 4 label states:
  a docs page, a document code reads, a markdown file outside docs, a test file only, a shell script, a tool, a
  service, a full-tier path, this workflow, another workflow, another project's workflow, a file outside `trialbox/`
  and an empty diff. The labels are none, another one, `ci:full`, and unreadable. `trialbox` comes from the diff
  step's own grep pattern and `DOCS_ONLY` from `ci_docs_only`. Four `CARD_TIER` values and three branch names are
  crossed with drafts.
- Each unit job's real `if` is evaluated with those outputs by a small evaluator of GitHub's expression syntax
  (string compare ignoring case, a non-empty string true, an implied `success()` unless a status function is
  named). It refuses any context but `needs.changes.outputs.unit`, and any function or context it does not know,
  so a draft, label, branch or `full` condition fails even when the table would miss it.
- `changes` failed, `unit` after a failed shard, the push case (it does say false there), the triggers, `needs`,
  the matrix and the steps are checked as well.

**Mutants: 22 planted, 22 caught** (each applied alone, the test file run with `-x`, then the file put back):

- In the workflow, 13: the old tier gate on the shards; a `trialbox` gate on `unit`; `== 'true'` in place of
  `!= 'false'`; a draft condition; a label condition; a `paths:` filter; `needs` on `standards`; the matrix emptied;
  an `if` on the pytest step; no `!cancelled()`; the `unit` output not passed on; `continue-on-error`; no
  `ready_for_review`.
- In `tools/ci_tier.py`, 9: false for a draft, for docs-only, always as `full`, the `unit=` line removed, true only
  with `ci:full`, false for an empty diff, false with nothing under `trialbox/`, false under `CARD_TIER=touched`,
  false on an `agent/` branch.

## Cost

From the public Actions API, 18 green runs of 2026-11-24 with all eight shards (pull requests and trains): the median
is **159 runner-minutes per run** (the eight shards' sum, 144 to 176; `unit` under a minute) and about **30 minutes
of wall time** from the first shard's start to `unit`'s end (23 to 40). Each run of a pull request that got the fast
tier before now adds these. Of the 40 latest completed successful runs, 22 had no shards (fast-tier pull requests
and two master pushes). A newer push still cancels the older run of the same pull request.

## Check names

None change. `unit-shard (1/8)` to `unit-shard (8/8)` and `unit` now always report on a pull request, under their
expanded names. Before, a skipped matrix reported under the unexpanded expression (D-725). `unit` stays the required
name, and it is never left pending: it runs, or the run was cancelled by a newer push, which runs it. Branch
protection needs no edit (not verified: its settings are not readable from here).

## Files outside the card

`.github/workflows/trialbox-ci.yml` and `trialbox/tools/ci_tier.py` are shared infrastructure: the card is the ruling
to change them. The tests that pinned the old tier rule (`tests/unit/test_ci_tier.py`, `tests/unit/test_ci_tiers.py`,
`tests/unit/test_test_shard.py`) change only after the integrator's ruling on the listed assertions.
`docs/DEVELOPING.md` gets a row and a sentence. `docs/plan/43-ci-and-train-etiquette.md` is not edited (H120-03).

## Not run, not verified

- The pull request's own CI. Its unit shards must run, although before this card it would have been a fast-tier
  pull request on `.github/` and `tools/`. Strictly, `ci_tier.py` and the workflow are on `FULL_TIER`, so this pull
  request was always full tier. The proof that a fast-tier card now runs them is the next card's run.
- Branch protection's list of required checks.
- The whole unit and integration suites (not asked; `services/` and `libs/` are untouched).
