# D-483 Actor assertion v3: the person, the right and the request in one signed claim, minted in one place and checked by one dependency

- **Card:** T-715 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-715-actor-assertion-v3`); it is built on T-714's branch (PR #312, the `orch_box`
  fixture) and shows that card's commits until it merges
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-143 / D-447 (the signed actor, used once), D-146 (the signed role), D-273 (the signed study
  scope), D-425 (the matrix, `permit`), D-464 (callers per route), D-482 (the real-box fixture)
- **Closes:** finding F2 and proposal TR-3 of `docs/reviews/2026-11-12-architecture/trust.md`, in stages (see
  "Stages")

## The problem

About forty changing routes of the orchestrator take the acting person from the request body (`by`) under any
admitted service token: a subject is enrolled, a study setting saved, a serious adverse event acknowledged under a
name that never signed in, and the audit line is the same as a real one. Six route groups take the person from a
signed assertion (v2), which carries a name, a session, a role and a study list, and nothing about what the person
was allowed to do, to what, or with which request body.

## The decision

1. **The claim** (`libs/tb_common/actor_v3.py`). One signed claim per request, in `X-TB-Actor-Assertion`:
   `v3.<base64url(JSON)>.<HMAC-SHA256>`. Its fields: `sub` (the verified account, `console:<username>`, or a
   service principal), `role`, `session`, `study` (exactly one, or none for an action of the whole box),
   `standing` (PI, ticked tasks, whether the log names a PI, a monitor grant: what `permit` reads), `action` (the
   row of `authz_matrix.yaml`), `target` (`METHOD path?query`), `grant` (a break-glass grant, or null),
   `reauth_at` (when the password was typed again, or null), `body` (a hash), `nonce`, `iat`, `exp` (two minutes).
   The claim is the whole message: no second header names the person. It is signed with the console's actor key
   (the key of v2; T-717 gives it a file of its own) and accepted once (`ReplayGuard`, on the nonce).
   - **The body hash is of the JSON value**, in one canonical form (sorted keys, no spaces, ASCII), not of the
     bytes: the minting side hashes the object it is about to send, the checking side the object it received,
     whatever the HTTP client wrote. An added, removed or changed field is another hash.
   - **A retry** (`ServiceClient` sends a call again) carries the same claim minted again with a new nonce
     (`service_auth.resign`), as v2 did.
   - **A box with no token at all** (DEV, TEST) checks no MAC, as v2 there; the claim is still read, and its
     expiry, action, study, request and body are still checked, so tests run the one path.
2. **One minting place** (`services/console/actor.py`). `assert_for(h, sess, action, rid, method, path, body)`
   asks `Helpers.permit` first (the question every page asks, with the account's standing from the delegation
   log) and refuses with 403 and `console.denied` what the matrix refuses: the console cannot sign what it would
   not allow. `call(...)` is the study API with that header. A test fails when `mint(` appears anywhere else in
   `services/`. A console timer has no session: `assert_service` mints for a named principal
   (`service:console-notify`), which the orchestrator admits only on a route that says so and only for the actions
   its row of `route_actors.yaml` lists.
3. **One dependency** (`services/orchestrator/actor.py`). `require_actor(action)` on a route: the assertion
   verifies; it is for this `action`; its study is the route's `{rs}`; its target is this method, path and query;
   its body hash is this body's; and `permit(role, action, standing)` allows it. The handler receives the claim
   and takes the audit actor from it. A refusal is HTTP 403, code `ACTOR`, with the reason (`action`, `study`,
   `request`, `body`, `right`, `principal`, or why the assertion did not verify), and one `actor.refused` event
   with the route template, the action and the calling service.
4. **Stages** (`services/orchestrator/route_actors.yaml`), per route group of D-464's table:
   - `refuse`: **lifecycle and sponsor** (12 changing routes and the enrolment report file). Their request
     models have no `by`; the console signs every call (`lifecycle_pages`, `entry_pages`, `study_setup`,
     `sae_pages`). The sponsor's three changing routes have no console caller yet, so they were open to any
     admitted token with a typed name; they now need a signed coordinator.
   - `report`: **study, data core, site set-up, registry** (32 changing routes). `report_actor` is on the
     router: a changing call without a valid v3 assertion is counted per route and reason
     (`orchestrator.actor.UNSIGNED`) and logged once per route and process, and let through; the person is still
     the body's `by`. The list only shrinks.
   - `v2`: jobs, cancel, retry, reveal, notices, EDC: the handler verifies the older assertion (a name, a
     session, a role, a study list). They move with the cards that change what they check (T-716: the grant
     and the standing read by the orchestrator; the EDC re-authentication as `reauth_at`).
   - `no_person`: the pair canary and the deceased-patients read, each with its reason.
5. **The walk is the service's own.** `orchestrator.actor.route_problems(app, group_of)` flattens the app's
   routes with the dependencies of their `include_router` calls and names: a changing route whose group is in no
   stage; a route of a `refuse` group without `require_actor`; a `refuse` route whose request model or query
   names a person (`by`, `signer`, `approved_by`) or whose action is not a matrix row; a `report` route without
   `report_actor`; a table group with no changing route. `orchestrator.app` calls it at import
   (`assert_staged`): a mis-staged route stops the service, it is not found later.
   `tests/unit/test_actor_routes.py` runs it on the real app and on small apps that have each defect.

## What it does not do (the stages that remain)

- **Stage (b) for study, data core, site set-up and registry**, and then (c) refuse and (d) delete `by`: 32
  changing routes and about 45 console call sites (`data_pages`, `entry_pages`, `study_setup`, `site_pages`,
  `screening_log`, `sdv_page`, `team`, `copy_assist_page`). The review's confirmed case
  (`PUT /studies/RS/settings` with `"by": "dr_tanaka"`) is in this group: it is counted, not refused. Each
  router is one pull request of the shape of this one: actions on the routes, the group moved in the table,
  the console's calls through `actor.call`.
- **The v2 routes** stay on v2 (above).
- **The replay guard stays in the process's memory** (D-447): the move to a table, and the nonce written into
  every audit event of the request so that the console's and the orchestrator's records join, are T-721's
  shared id.
- **The standing is the console's word, signed.** The orchestrator asks the matrix with it and does not read
  the delegation log: T-716.
- **The mail gateway's jobs** have no person by design (D-146, D-464).
- **Operator tools** that call the orchestrator over HTTP do not exist (D-464: `docker compose exec`); the
  demo and the end-to-end tools go through the console's pages and so through `assert_for`.

## Consequences

- A participant's step, the visit schedule, the SAE rule, the contact rule, a deviation call, an SAE
  acknowledgement and the sponsor layout are recorded under a verified person or not at all.
- The audit actor of these routes is `console:<username>` always (a test that wrote `"by": "crc"` now reads
  `console:crc`); the notice timer's refresh is `service:console-notify` (it was `console:notify`).
- A new changing route cannot be added without a stage: the service does not start.
- A call to a report-stage route shows in `UNSIGNED` and the log until its router is converted.

## Dropped (D-311)

No security sign-off or owner review step.
