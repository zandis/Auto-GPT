# D-543 Every store's schema is on the role list of the service that opens it, and a test enumerates them

- **Task:** NEW-ARCH-18 (`docs/plan/33-plan-v7.md` section 5, wave 0, lane C; TB-PLAN-07)
- **PR:** this branch (`agent/NEW-ARCH-18-schemas-on-role-lists`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Measures:** closes ARCH-021 (High) of `docs/reviews/2026-11-12-deep-review/02-architecture.md`
- **Builds on:** D-378 (one database role per service, each reaching only the schemas on its list)

## Context

A service signs in to the trial database as its own role. A store opened by a service whose role is not on that
schema's list works in every test (one role there) and fails on a box with "no schema has been selected to create
in". The review ran two: the console opening the patient twin (`profile`), and `tuned` on no list at all. `tuned`
was put on the orchestrator's and the console's lists with T-712 (#308). `profile` was still missing for the
console, and nothing stopped the next store from being forgotten.

## The decision

1. **The list.** `profile` is on the console's list (both copies of `30-service-roles.sh`): the console reads the
   twin for `GET /api/v1/studies/{rs}/patients/{pid}/twin`.
2. **The test** (`tests/unit/test_db_schemas_enumerated.py`) reads the code:
   - every `Database.connect(url, <schema>)` in `services/` and `libs/`, and every call of the console's
     `open_db`: each schema is on some role's list, and each schema on a list is opened by some code. The one
     schema listed and opened by nothing (`mpi`, retired with D-381) and the helpers that take the schema as a
     parameter are named in the test with their reasons; a new one fails until it is named.
   - for the console and the orchestrator, every module their process can import (they host the shared stores):
     each schema those modules open is on that service's own list. For the other services, their own folder.
   - on a cluster with the real role script: the console's and the orchestrator's roles open the twin store and
     the not-matched store (the finding as it was run).

## What it does not do

- The console gets the group's full rights on `profile` (read and write), as on its other schemas. Read-only
  roles per schema are T-718's (wave 6), and the console leaving the orchestrator's stores is NEW-ARCH-3 (wave 2).
- **An installed box gets the new membership only when the role script runs.** `trialbox update` does not run
  it (only `deploy/install.sh` does); the changelog line gives the command. The update running the script is the
  update tool's card (lane D), not this one.
- For a service other than the console and the orchestrator the test follows its own package's imports wherever
  they stand, and in another package only the imports at module level: an import inside a function of another
  package runs only if the service calls that function, which the text cannot tell. One pair the rule still
  reaches and the service never opens is named with its reason (`LOADED_NOT_OPENED`: the lake loads the
  matching cascade's module for type names, and with it `derived`, `optout` and `pidmap`).
- `mpi` stays on three lists; taking a retired schema off an installed volume is not done here.

## What the adversarial review changed

One review by a fresh reviewer; verdict: merge with two small fixes; no HIGH.

- **M1, the test checked almost nothing for five of the seven roles** (own folder only: taking `vec` or `omop`
  off the lake's list passed). Now every service's import closure is read, with the rule above, the console
  and the orchestrator included (on the train the console's every-import closure reached the orchestrator's
  own stores through `orchestrator.candidates`, as T-721's table test found).
- **M2, the changelog gave no command** and an updated box stays at 500 until the script runs. The command is
  in the line; the limit is stated above.
- **M3, shapes of a store the scan missed** (a call at module level or in an `async` function, the schema as a
  keyword, `open_db` with a schema that is not a literal, `storedb.open_db`, `x.Database.connect`): all read
  now; a schema the scan cannot read is a `?` entry that must be named. A test plants each shape.
- **LOW-1, `recall` was checked against the union of the lists only:** the role whose process loads the ledger
  must have it.
- Not changed: `wf`, `recall`, `study` and `library` stay on the console's list though nothing in its closure
  opens them (NEW-ARCH-3's); `PostgresBackend(url, "<schema>")` and `importlib` are not read (none exists; the
  ledger's schema is pinned by name).

## Dropped (D-311)

No sign-off or owner review step.
