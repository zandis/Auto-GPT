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

Does a box run such a store? Two readings, both needed:

- **The lake service and the adapter: no.** Both take the box's own folder (`TB_LAKE_DIR`, which compose sets
  for exactly those two) and so write `omop`. One trap: `lake/app.py` falls back to `/data/lake` when
  `TB_LAKE_DIR` is not set, and `schema_for` then sees no box lake and names the store `omop_<hex>`: a lake
  service started without the setting would have made a store of its own that the adapter cannot open.
- **The orchestrator: yes** (found by lane B2 from the lake's side; my first reading missed it).
  `SiteSetup.lake(ws)` for a space other than `main` is a lake under the orchestrator's data folder
  (`sitesetup/<ws>/lake`), rebuilt at publish in the orchestrator's own process, which has no `TB_LAKE_DIR`.
  With the lake source `omop` the rebuild makes `omop_<hash of that folder>` as `tb_orchestrator`. Only the
  orchestrator's process reads a space's lake (the console and the lake service never open one: read, the
  routes go through the orchestrator), so in the role model that store is the orchestrator's own, and right.
- Tests, `tools/goldens.py`, `tools/omop_parity.py` and the in-process boxes make such stores as the admin or on
  a database without the role script.

## Decision

The role model says: a schema a service makes is that service's own, and a store several services share is a
listed store with a group, made before any service opens it. A second lake's store is shared and on no list, so
under roles a service must not make it.

1. **The two services that share a lake refuse to make its store alone** (`omop.schema.connect`, lane E's
   file: one function, one constant, two keywords): under the role script (the group `tbs_omop` exists), asked as
   `tb_lake` or `tb_adapter` (`LAKE_SHARERS`: the adapter loads, the lake builds and exports, one store between
   them), for a store other than `omop` that does not exist: `OmopError` with one sentence: the store's name, the
   lake's folder, what `TB_LAKE_DIR` is (or that it is not set), and the admin's command. Nothing is made. The
   same refusal stops the lake service that was started without `TB_LAKE_DIR`. **The orchestrator is not
   refused**: its site spaces' stores are its own and it goes on making them. The two callers that name a store
   by its lake pass the folder for the sentence (`lake/source.py`, `adapter/dual_write.py`: one argument each).
2. **The admin's step makes it** (`python3 -m tools.trialbox omop-store --lake <folder>`,
   `tools/trialbox/omop_store.py`): `CREATE SCHEMA ... AUTHORIZATION tbs_omop`, then the store's own migration
   and seed, as the group. A second run changes nothing. A schema of that name that is already there and belongs
   to someone else (a host tool that opened it as the admin, a service before this card, a role off the list:
   every service has CREATE on the database) is not called ready and not taken from its owner: the step stops
   with the owner's name (it may be that role's own store, with rows in it).
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
6. **The drill** (`tools/role_paths.py`, D-720) gains two lines: a second lake's store is refused to `tb_lake`,
   made by the admin's step, loaded as `tb_adapter`, read as `tb_lake`, `tb_orchestrator` and `tb_console`; and a
   site space's store as `tb_orchestrator`, through the lake's own `lake_rows` with the OMOP source: made,
   loaded, its rows read back, not readable by `tb_lake`, dropped by the orchestrator.

## Not in this card

- A Reset of a site space does not drop the space's OMOP store today, and no erasure entry names it: lane C2's
  card (the drill shows the orchestrator can drop it). With uploads a space can hold a site's real rows.
- The whole `SiteSetup.publish` of a space is not in the drill (it needs the set-up's inputs and model
  stand-ins); the drill runs the part that touches the database, `lake_rows` with the OMOP source.
- The opt-out tick clearing a second lake's or a space's store: lane E's next card (the worker enumerates every OMOP store);
  the drill's line gets "cleared by the tick" when that lands.
- A store that already exists and is a service's own (made before this card on a box with roles): opened by its
  maker only, as before; the admin's step names its owner and stops.
- With a `tb_prefix` URL (tests and tools: several runs in one database) the refusal never fires and the step
  makes the store as whoever asks: the group it looks for is `tbs_<prefix>omop`, as `tb_common.db` names groups,
  and the role script makes none with a prefix. A box has no prefix.
- The platform copy of the role script is the same file content; not run here.

## Consequences

- The unset-`TB_LAKE_DIR` trap is a stop with a sentence, not a silent store nobody else reads.
- A practice site's second lake on a box needs one admin command before its first load.
