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

## Decision

(written when the card is built)
