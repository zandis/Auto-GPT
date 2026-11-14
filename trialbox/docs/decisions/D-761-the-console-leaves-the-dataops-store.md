# D-761 The console leaves the orchestrator's stores: slice 1, the night's data operations

- **Task:** NEW-ARCH-3 (plan v7, wave 2, lane C: "the console leaves the orchestrator's stores"; the deep review's
  ARCH-005), slice 1 of 3
- **PR:** this branch (`agent/NEW-ARCH-3-the-console-leaves-the-orchestrators-stores`), stacked on NEW-SEC-4 (D-760)
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-760 (the publish of a held night checks the steward), T-723 (D-489), T-112b (D-443, the data
  operations page), D-543 (every store's schema on its service's role list), T-715 (D-483)

## The problem

The deep review (ARCH-005): process boundaries are not data boundaries. The console opened the orchestrator's stores
itself, so a compromised or broken console owned their tables, and T-718 (owner is not writer) and T-715 (the person
verified at the callee) could not be finished. The data operations page opened `datacore.dataops.DataOps` (schema
`dataops`) and ran the steward's accept, and the publish of the night, inside the console.

## The decision (slice 1)

- **The orchestrator serves the night's data operations** (`orchestrator.dataops_api`): `GET /dataops/sources`,
  `/held`, `/counts`, `/history`, `/batches/{bid}`, `/batches/{bid}/steps`, `/can-publish` (rows of counts and step
  names, never a patient's row), and `POST /dataops/batches/{bid}/decide`, signed (`require_actor("dataops.decide")`):
  the steward's accept or reject under the verified person, with the publish of an accepted night run there, next to
  the store, through the adapter's `POST /publish` (the orchestrator's alone, D-760). A refusal of the store answers
  409 with its `why`; a publish that did not end "done" 502 with its marks (nothing served, not started), so the
  console's page says what it said before.
- **The console's page reads and decides through those routes** (`console.dataops_page.OrchOps`, the method names
  of `DataOps`), posting the decision with the client that never retries (D-760's review). It imports no module of the
  store (its own row type and refusal), holds no promoter, and offers Accept when the orchestrator says it can publish.
- D-760's single-step `POST /dataops/publish` gives way to the decision route: the steward's accept is one request.
- **The console's database role leaves the schema `dataops`** (both role scripts), and its audit role the family
  `dataops` (the orchestrator writes `dataops.decide` now).
- **An import lint** (`tests/unit/test_the_console_opens_no_domain_store.py`) reads every console module for the
  names that open another service's store; what is left is listed with the slice that takes it out, and the list only
  shrinks: the OMOP conflicts page (slice 2) and the instruments page's set-up store (slice 3).

## What it does not do

- Slices 2 and 3 (the OMOP conflicts, the set-up store's switches), and the other schemas the review lists for the
  console's role (`datacore, omop, sitesetup, orch, recall, study, mpi, pidmap`), are later slices of this card.
- The decision still runs in the request that asks it, as it did in the console (the publish is followed to its end,
  never timed, D-472).

## Review

See "What the adversarial review changed" when the review is in.

## Reuse check

`datacore.dataops.DataOps` (unchanged), `orchestrator.actor.require_actor`, `console.actor.assert_for`, the
publish promoter of T-723 (moved from the console to `orchestrator.dataops_api.promoter`), `AdapterHttp.publish` and
`publish_state` (D-760), the D-543 schema test. Added: the router, the console's client and row type, the import lint,
the console tests' shim of the routes (`tests/console/dataops_orch.py`).

## Dropped (D-311)

No sign-off step.
