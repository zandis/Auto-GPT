# D-721 A service makes no OMOP store of its own

- **Task:** OMOP-STORE (lane E's finding by running the role script, through the integrator, 2026-11-13)
- **PR:** this branch (`agent/OMOP-STORE-a-service-makes-no-store-of-its-own`), stacked on #545 (D-720) and #543 (D-683)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-378 (one role per service, a group per store), D-486 (a schema with an owner is made by the install step), D-720

## Context

`omop.schema.schema_for(lake_dir)` names the store of a lake that is not the box's (`TB_LAKE_DIR`) `omop_<10 hex>`.
Under the role script such a store has no group: the service that first opens it makes it and owns it, and no
other service can open it (confirmed by lane E by running: made as `tb_lake`, then `tb_adapter`,
`tb_orchestrator` and `tb_console` fail). The opt-out worker could not erase from it.

Does a box run such a store? By reading: no service path of an installed box makes one. The lake service and the
adapter's dual write both take the box's own folder (`TB_LAKE_DIR`, which compose sets for exactly those two), and
the orchestrator and the console open `omop` by its name. Tests, `tools/goldens.py`, `tools/omop_parity.py` and the
in-process boxes make them, as the admin or on a database without the role script. One trap: `lake/app.py` falls
back to `/data/lake` when `TB_LAKE_DIR` is not set, and `schema_for` then sees no box lake and names the store
`omop_<hex>`: a lake service started without the setting would have made a store of its own.

## Decision

The role model says: a schema a service makes is that service's own, and a store several services share is a
listed store with a group, made before any service opens it. A second lake's store is shared and on no list, so
under roles a service must not make it.

1. **A service refuses** (`omop.schema.connect`, lane E's file, one function and one keyword): under the role
   script (the group `tbs_omop` exists), asked by a role that is neither a superuser nor a member of the
   database's owner (the host tools' admin), for a store other than `omop` that does not exist: `OmopError` with
   one sentence: the store's name, the lake's folder, what `TB_LAKE_DIR` is (or that it is not set), and the
   admin's command. Nothing is made. The two services that name a store by its lake pass the folder for the
   sentence (`lake/source.py`, `adapter/dual_write.py`: one argument each).
2. **The admin's step makes it** (`python3 -m tools.trialbox omop-store --lake <folder>`,
   `tools/trialbox/omop_store.py`): `CREATE SCHEMA ... AUTHORIZATION tbs_omop`, then the store's own migration
   and seed, as the group. A second run changes nothing.
3. **A connection works as the group that owns its schema** (`tb_common.db`, shared code, one fallback): besides
   `tbs_<schema>` by name (D-378), a schema owned by any NOLOGIN `tbs_` group the user is a member of is used as
   that group. So every service with `omop` on its list works in the second lake's store as `tbs_omop`, and what
   a load makes there is the group's. A service off the list is not a member: it can neither read nor make
   anything there.
4. **Not option (a)** (a SECURITY DEFINER function that makes schemas for a group): new machinery with a wide
   right for a case no box runs. **Not option (b)** (the role script adopts every `omop_<hex>` on each run): a
   store made between two runs is the service's own until the next one.
5. **Without the role script nothing changes**: no group, no refusal; whoever opens a store makes it. Goldens
   (both lake sources: identical), the parity tool, the in-process boxes and the tests are that case.
6. **The drill** (`tools/role_paths.py`, D-720) gains the line: a second lake's store is refused to `tb_lake`,
   made by the admin's step, loaded as `tb_adapter`, read as `tb_lake`, `tb_orchestrator` and `tb_console`.

## Not in this card

- The opt-out tick clearing a second lake's store: lane E's next card (the worker enumerates every OMOP store);
  the drill's line gets "cleared by the tick" when that lands.
- A store that already exists and is a service's own (made before this card on a box with roles): opened by its
  maker only, as before; the drill would show it. No box path makes one, so none is expected.
- The platform copy of the role script is the same file content; not run here.

## Consequences

- The unset-`TB_LAKE_DIR` trap is a stop with a sentence, not a silent store nobody else reads.
- A practice site's second lake on a box needs one admin command before its first load.
