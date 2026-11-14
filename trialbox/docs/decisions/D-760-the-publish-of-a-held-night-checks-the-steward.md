# D-760 The publish of a held night checks the steward who accepted it

- **Task:** NEW-SEC-4 (plan v7, wave 1, lane C: "the adapter's `POST /publish` checks the signed person and right",
  found in T-723's review)
- **PR:** this branch (`agent/NEW-SEC-4-the-publish-of-a-held-night-checks-the-steward`), from master after train 14
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** T-723 (D-489, the steward's accept publishes a held night), T-715 (D-483, the acting person of a
  route; actor assertion v3), D-464 (which service may call which route), D-138 (the token registry)

## The problem

The steward's accept (`dataops.decide`) published a held night through the adapter's `POST /publish`, which took any
caller's service token and no person. The console's token alone published a night the gate had held, and the
adapter recorded nobody. **Confirmed by a run**: with a token registry, the console's token reached the publish
handler.

## The decision

- **The check is the orchestrator's, as for every changing route.** The console asks `POST /dataops/publish`, signed
  as the steward who accepts (`console.actor.assert_for`, `dataops.decide`, no study). The orchestrator's one
  dependency (`require_actor`) verifies the person, the action, this request and this body, and asks the matrix
  again. It then starts the adapter's publish with its own token, gives the adapter's answer back (202 and a run id;
  404 and 409 as the adapter said them) and records `dataops.publish_started` under the verified person. Its state is
  read at `GET /dataops/publish/{rid}` (a night's state, no patient's row).
- **The adapter takes `POST /publish` from the orchestrator only** (its route gate): another service's token is
  refused (403, nothing touched). An open DEV/TEST box and the old shared token (DEV and TEST only) pass as
  everywhere.
- **The actor key stays with the orchestrator alone.** Verifying at the adapter would have meant a second holder of
  the key that `service_auth` says no other service holds; the orchestrator already verifies every changing route.
  This is the plan's line ("the adapter's publish checks the signed person and right") met by the route that starts
  it.
- Route tables: a group `dataops` (the console's), stage `refuse`.

## What it does not do

- The adapter's other changing routes (`POST /run`, the night's ingest) are the orchestrator's job calls and keep
  `make_app`'s token rule; this card is the steward's accept.
- `DataOps.decide` and the page's two-step accept are unchanged; the promoter is handed the accepting person's
  signer.

## Review

See "What the adversarial review changed" when the review is in.

## Reuse check

`orchestrator.actor.require_actor`, `console.actor.assert_for`, `make_app`'s `route_gate` (T-713), the adapter's
publish job and its poll (T-723, D-472), the route tables. Added: two orchestrator routes, `AdapterHttp.publish` and
`publish_state`, the adapter's `_publish_gate`.

## Dropped (D-311)

No sign-off step.
