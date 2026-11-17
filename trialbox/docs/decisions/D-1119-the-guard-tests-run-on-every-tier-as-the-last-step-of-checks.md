# D-1119 the guard tests run on every tier, as the last step of checks

- **Task:** GUARD STEP, lane H (sub-session 8); the plan approved by the integrator on #639 (2026-11-17 04:48 UTC:
  "go, as planned, items 1 to 5, the collection check included"); lane D, which owns CI, reviews it
- **PR:** this branch (`claude/lane-h-8-guard-tests`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-564 (the tiers), D-578 (`checks` holds the short checks as steps), D-969, D-970 (a card runs the
  fast tier), T-653 (the `nodb` marker, `make test-pure`), D-475 (the shards and `tools.test_shard check`)

## Context

Since D-970 an ordinary card's pull request runs the fast tier, and the unit tests run only on its train. Some unit
tests are not about behaviour at all: they read the source tree for something that must not be there (a site time
zone in code, a direct model call, an undeclared setting, an audit write outside the audit writer, legacy encodings)
and need no database and no service. A card that broke one of them learned it on the train, which cost the train. A
test id that carries the clock or random bytes was found later still: in `tools.test_shard check`, after all six
shards had run.

## Decision

1. **The marker.** `guard` in `pyproject.toml`: "reads the tree for something that must not be there; no database,
   no service". It is put on whole test files, in the module's own `pytestmark`, together with `nodb`:
   `pytestmark = [pytest.mark.guard, pytest.mark.nodb]`. The list lives with the tests, not in the workflow.
2. **The step.** The last steps of the `checks` job of `.github/workflows/trialbox-ci.yml` run
   `pytest -m guard -q -n 2 tests/unit` the way `make test-pure` runs the pure tests (`TB_TEST_DB_URL` unset,
   `TB_PG_BIN=/nonexistent`), so no PostgreSQL can start. `checks` runs on every tier, so the step does. `make guard`
   runs the same locally, and the `train-ready:` line names it (`docs/plan/43-ci-and-train-etiquette.md`).
3. **The budget.** Under three minutes added on a CI runner. Measured on 2026-11-17 here with two workers: 22 files,
   424 passed and 1 skipped, 59 to 79 s (about 15 s of it the collection of `tests/unit`). A file whose run would take
   the step over the budget is not marked.
4. **The first list** (22 files): `test_site_tz`, `test_decision_context_lint`, `test_lake_client_answers`,
   `test_shell_lint_gate`, `test_no_direct_model_calls`, `test_config_declared`, `test_error_text_across_services`,
   `test_error_answers`, `test_no_decision_by_error_text`, `test_limits_lint`,
   `test_audit_events_only_from_the_audit_writer`, `test_encoding_utf8_never_legacy`, `test_env_settings_gate`,
   `test_no_record_of_kind`, and, read from the static readers of `tests/unit` and run with the database refused,
   `test_audit_one_writer`, `test_the_console_opens_no_domain_store`, `test_identifiers_door`,
   `test_patient_lists_are_joins`, `test_cascade_language_explicit`, `test_record_inventory`,
   `test_erasure_registry`, `test_registry_match_egress`.
5. **The collection check.** A second step collects the test files a pull request adds or changes twice, each in a
   fresh process (`tools/collect_stable.py`), and fails naming the ids seen in one collection only. A push or a run by
   hand has no pull request's diff; there the full tier's shards compare every collection (or did, on the train that
   proved the tree).
6. **What holds it.** `tests/unit/test_ci_guard.py`: every collected guard test is `nodb` (by its pytestmark or
   `PURE_MODULES`) and asks for no fixture that reaches the test cluster (`pg_cluster_url`, `db_url`, directly or
   through another fixture); the marker is only in module `pytestmark`s under `tests/unit`; `checks` runs the guard
   step exactly once, as its last steps with the collection check, and no other step runs `-m guard`; the collection
   step's script, run in a repository of its own, names an unstable id and leaves a deleted file out.
   `tests/unit/test_collect_stable.py` tests the tool with a deliberately unstable parametrized id.
7. **The tier rules are unchanged.** `tools/ci_tier.py`'s rule, `FULL_TIER` and `CARD_TIER` are as D-970 left them;
   only its docstring and its log say that every tier runs the guard step. The unit shards still run the marked tests
   on the full tier: nothing is deselected, so `tools.test_shard check` still sees every test in exactly one shard.

## Consequences

- A card learns in its fast tier, in about a minute, that it broke a tree reader, instead of on the train.
- The marked tests run twice on a full-tier run (once here, once in their shard): about a minute of one runner.
- A new tree reader joins by its own `pytestmark` line, with its time measured by `make guard`.
- Not measured on a GitHub runner yet: the first run of this pull request gives the step's real time.
