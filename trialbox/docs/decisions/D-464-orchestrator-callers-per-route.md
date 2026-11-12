# D-464 The orchestrator admits each calling service to its own routes only; internal principals never come over HTTP

- **Task:** T-713 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, wave T)
- **PR:** this branch (`agent/T-713-orchestrator-callers-per-route`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Closes:** review 2026-11-12 trust F7, F12 (for the orchestrator), the "which service" half of F2; proposed card TR-2
  (its route part; the `/setup/pseudonym` and registry-by-`mrn` part is T-719)
- **Builds on:** D-114 / D-128 / D-138 (one token per service, `tb_common.service_auth`, `request.state.tb_caller`),
  D-130 (reads behind the token), D-437 (the gateway binds the caller claim to the verified token), D-146 (a console
  job is authorised by the signed role, a mailed job by the mailbox rules)

## Decision

1. **One declared table.** `services/orchestrator/route_callers.yaml` names every route of the orchestrator app
   (`METHOD /template`) in exactly one route group, and which verified calling service may reach which groups: the
   console (every group it calls), the mail gateway (`POST /jobs` and `GET /jobs/{job_id}` only), the operator's
   host token (job and model reads), and explicit empty rows for the adapter, the lake, the criteria compiler and the
   doc-parser (`CALLERS` refuses them before this table is read). The scheduler has a row that is in-process only: it
   reaches no route, and it holds the internal principal names (`scheduler`, `system`).
2. **Enforced in one place.** `make_app` takes a `route_gate`, called by the token middleware right after the token
   is verified, before routing. The orchestrator's gate (`orchestrator.callers`) resolves the request to its route
   template in FastAPI's own order and refuses a route outside the caller's groups: HTTP 403 with a named reason
   (`route_not_allowed`, `caller_unverified`) and one audit event `service.route_refused` carrying the verified
   service, the method, the route template and the reason.
3. **The mail gateway's jobs.** It may start only the mail commands (`job_types` in its row, the commands of
   `tb_common.subject.COMMANDS`), and read only a job that came in by mail (one with a `message_id`); anything else is
   `route_not_allowed` with the same audit event.
4. **Internal principals never come over HTTP.** `POST /jobs` with `requested_by` naming an internal principal
   (`scheduler`, `system`) is refused 403 (`internal_principal`) and audited, from every caller and in every
   environment; the scheduler creates its jobs in process. The console's "retry a failed job" names the
   administrator's mailbox for a scheduler job, so the retry is authorised by the administrator's role.
5. **No identity, no route, outside DEV and TEST.** The old shared token (`legacy`, with a registry or the
   shared-token rule without one) reaches the orchestrator only where `TB_ENV` is DEV or TEST, as D-437 did for the
   gateway; elsewhere it is `caller_unverified`. A call with no token at all passes the gate only where the token
   layer runs open (DEV, TEST).
6. **The walk.** A test walks every route of the app (`app.routes`, included routers flattened) with every
   service's token in registry mode: a route outside a service's row refuses; a route in no row fails the test.

## Consequences

- The in-process demo box (`tools.role_demo.orch_client`, used by the demo image, `cgmh_demo`, `feas_demo`,
  `public_e2e`, `scenarios`) runs with no `TB_ENV` in the image (PRODUCTION by the one rule), so it now writes a token
  registry naming its token as the console's, and the console's actor key, as `trialbox secrets init` does on a box.

- A new orchestrator route is unreachable from every service until it has a line in the table, and the walk test
  fails until it does.
- A box without per-service tokens outside DEV and TEST loses the orchestrator as it already lost the gateway (D-437):
  run `trialbox secrets init` / `rotate`.
- The table says which service may call a route; it does not say which person. The 40 routes that take the person
  from the body (`by`) are unchanged: T-715 (actor assertion v3).

## Open

- The person on the body routes: T-715. The chart-number routes that need no person (`/setup/pseudonym`, registry
  by `mrn`): T-719.
- "Its own jobs" means "came in by mail" (a `message_id`): the job row does not record the creating service.
