# D-482 The console is tested against the real orchestrator: the `orch_box` fixture, and a fake that refuses what the real routes refuse

- **Card:** T-714 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2 and §5.3, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-714-orch-box-fixture`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-273 (the orchestrator checks the signed role and study scope), D-464 (callers per route, the
  token registry in every PRODUCTION test), D-143 / D-447 (the signed actor assertion), D-146 (a console job is
  authorised by the signed role)
- **Closes:** proposal TR-7 and question 5 ("fakes") of `docs/reviews/2026-11-12-architecture/trust.md`

## The problem

The console's tests run against `FakeBackend` (`tests/console/test_console_app.py`), written by hand. Its `reveal`
returns a chart number for any role, any study scope and any patient; its `registry_export` and `create_job`
refuse nobody. A console that signs the wrong role, the wrong studies or none passes every console test. The
orchestrator's own tests send hand-made headers, so the two halves of the one contract are never run together.

## The decision

(filled in with the build; see the pull request)
