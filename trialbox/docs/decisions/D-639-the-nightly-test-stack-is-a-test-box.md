# D-639 The nightly: the test stack is a TEST box in every service that is called

- **Task:** NIGHTLY-GREEN-2 (the scheduled run of 2026-11-13 on master 906889ee, three red jobs)
- **PR:** this branch (`agent/NIGHTLY-GREEN-2-the-test-stack-sends-a-token`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-560 (the test stack's embed service says TEST), D-640 (orchestrator and compiler), D-128/D-138 (service tokens)

## Context

The scheduled run of 2026-11-13 (43491559098, master 906889ee) was red in three jobs. Three of the causes are in
this lane's files and are fixed here; the opt-out worker's "permission denied for schema omop" is lane E's card,
and the scale gate's time is lane B2's.

1. **compose: 13 set-up errors, `503 Service Unavailable` from `POST :8016/run`.** The adapter's log: status 503
   in 0.3 ms, refused before the handler. The only 503 on that path is `tb_common.service_auth.authorize`: a
   service outside DEV and TEST with no token refuses every changing call. In the test stack the adapter, the lake
   and the doc-parser had no `TB_ENV` (unset is PRODUCTION), and `deploy/.env` is a copy of `.env.example`, whose
   `TB_SERVICE_TOKEN=change-me-service-token` is a placeholder and counts as none. The refusal is right; the
   stack was wrong. The lake also protects its reads, so it refused the orchestrator's queries the same way.
2. **random-order 5/6: two failures in `tests/unit/test_db_roles.py`.** Two tests of the one cluster depended on
   the order: one made the role `tbs_edc` without asking whether another test had made it; one dropped the `edc`
   schema and put it back without the cluster's one probe row that a third test reads.
3. **compose: the browser walk stopped at "the MedTxt corpus is not in .cache/medtxt".** Only the public-e2e run
   fetched it.

## Decision

1. The synthetic stack says TEST in every service the harness or a TEST service of the stack calls
   (`deploy/docker-compose.test.yml`: adapter, lake, doc-parser; as D-560 for the embed service and D-640 for the
   orchestrator and the compiler). `tests/unit/test_test_stack_is_a_test_box.py` merges the stack's files with
   `.env.example`, takes the callers from `service_auth.CALLERS`, and asks `authorize` itself: a callee that would
   refuse fails the test. The rule is not loosened: the same test keeps that a PRODUCTION service with the
   placeholder token answers 503.
2. The two role tests leave the cluster as the others expect it (a guarded `CREATE ROLE`; the probe row put back
   after the schema is). No assertion is changed.
3. The compose job fetches the public corpus from the same cache as the public-e2e run, before the images and the
   stack.

## Not established

- **Which train brought the 503.** `authorize` and `.env.example`'s token line did not change between the
  previous nightly's commit (536ab479) and this one. The previous night's compose log has no request to the
  adapter at all: that run stopped before the ingest. So the refusal was most likely there before and hidden
  behind an earlier stop; not proven.
- **That the compose job is green with this.** No docker daemon in this session: the stack was not started. The
  merged files were rendered (`tests/unit/test_compose_db_passwords.py` compares the Python render with
  `docker compose config`), and the refusal was reproduced and removed through `authorize`. The next nightly is
  the proof; the role walk's 15 failed checks ("waitForSelector" on the admin pages) were most likely the missing
  ingest and are read again then.
- The console, the audit writer and the model stand-in of the test stack still have no `TB_ENV`. Nothing in the
  stack calls them with a service token (`CALLERS`), and the console's cookie and sign-in rules differ by
  environment, so they are left as they are until a run says otherwise.

## Consequences

- A new service in the test stack that a TEST service calls and that has no `TB_ENV` fails a unit test, not the
  night.
- `tests/unit/test_db_roles.py` passes in four shuffled orders of its 26 tests (run here).
