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

1. **`orch_box`** (`tests/orch_box.py`, the fixture in `tests/conftest.py`). A fresh box per test:
   - the real orchestrator app (`orchestrator.app.app`: `make_app`, the token middleware, the route gate of D-464,
     every router), serving a real `Orchestrator` over a synthetic site ingested into a lake
     (`tests.inproc_box.make_box`), with its pid map;
   - the production trust configuration: `TB_ENV=PRODUCTION`, a token registry with every service's own token, the
     actor-keys file (`tests.service_tokens`);
   - `backend()`: the console's real `HttpBackend`, its orchestrator client bound to that app with the console's
     own token. The one addition (`BoxBackend`) drains the orchestrator's queue after a job is started, because the
     box has no worker thread; requests, headers and the reading of refusals are `HttpBackend`'s own code;
   - `client(service)`: a client with any service's token (or none), for the calls a console never makes;
   - `screen()`, `listed()`, `mrn`, `events(kind)`: a finished screening job, its listed pseudonyms, the synthetic
     site's chart numbers, and the audit records of the one chain the console and the orchestrator write.
2. **The console on the box** (`tests/console/test_orch_box.py`). The console app is created on that backend and
   driven through its pages: a coordinator reveals a listed patient and gets that patient's own chart number; the
   screening log goes out with real chart numbers; a job is started by the signed role. Each has its refusals from
   the real route (another study, a role without identifier authority, a patient not listed, a patient who opted
   out, another service's token, no token, a forged assertion, a body field `by`, an internal principal).
3. **The acceptance is a test of its own.** `test_a_console_that_drops_the_scope_or_the_role_gets_no_chart_number`
   removes `scope=` (and `role=`) in either place the console could lose it (the call to `backend.reveal` in
   `console.reveal`, the `actor_header` call in `HttpBackend.reveal`): the real route refuses, the page shows no
   chart number, the orchestrator's record has the refusal and its reason.
4. **The fake refuses what the real routes refuse.** `FakeBackend.reveal`, `registry_export` and `create_job` now
   apply the orchestrator's own rule functions (`orchestrator.app.id_authority`, `service_auth.in_scope`,
   `authz.role_allowed`; the job type and state rule of the reveal route), not a copy. The console tests that run
   on the fake (73 files import it) therefore fail too when the console signs the wrong role or scope. One test
   was itself wrong in that way (its spy dropped the role and scope it had been given) and is corrected.
5. **The fake is held against the real thing** (`tests/console/test_backend_contract.py`): for every signed role
   of the matrix (and break-glass, none, an unknown one) with five study scopes, the same reveal and export are
   answered the same by the fake and by the real routes on a box; for every role and nine job types, the same
   start. The table must reach every answer (a value and each refusal), so the agreement is not one on refusals
   only. What the fake does not model is a named table (`NOT_MODELLED`), each line with the test of the real
   behaviour.

## What it does not do

- `FakeBackend` stays, for the pages that need no orchestrator rule (it is the in-memory stand-in of 73 test
  files). Its `study_api`-shaped fakes in the page tests (`test_lifecycle_pages.py`, `test_edc_pages.py`: real
  routers on a bare `FastAPI()`, no token layer) are not changed here: T-715 moves the person on those routes
  from the body to the assertion and is the card that must run them on `orch_box`.
- The fixture costs about 12 seconds a test (an ingest and a screening run). It is function-scoped because every
  test has its own trial database; the three test files here have twelve tests on it.
- `tools/role_demo.InprocBackend` (the demo image's backend) is a second hand-written backend over the real app.
  It is product code of the demo, not a test fake, and is not changed; listed as a finding.

## Consequences

- A console change that loses the role, the studies or the person on a reveal, an export or a job start fails a
  console test, on the fake and on the real box.
- A new orchestrator rule for these three calls must be given to the fake too, or the contract test fails.

## Dropped (D-311)

No review or sign-off step.
