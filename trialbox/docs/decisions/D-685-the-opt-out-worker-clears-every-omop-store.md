# D-685 The opt-out worker clears every OMOP store the database holds, and names one it cannot open

- **Task:** owed by D-683 (the adversarial review, by reading); ordered by the integrator on 2026-11-13 as an
  erasure gap
- **PR:** this branch (`agent/DC-optout-every-omop-store`), cut from #543's head (D-683: the worker's new shape)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-441 (the opt-out worker), D-683 (each store is asked itself; a store that cannot be opened is
  named), D-465 (the erasure registry), D-378 (roles), D-151 (the OMOP store; `schema_for`: one store per lake)

## Context

A lake that is not the box's own (`TB_LAKE_DIR`) has an OMOP store of its own, `omop_<10 hex of its path>`
(`omop.schema.schema_for`; made by `lake/source.py` and `adapter/dual_write.py`). The worker cleared the store
named `omop` only. A patient who opted out stayed live in every other OMOP store, and the tick reported nothing
failed. Shown by a test with two stores before the change.

## Decision

1. **The worker finds every OMOP store** (`omop_store_names`): each schema of the database named `omop` or
   `omop_<10 hex>` that holds `tb_record`, asked of the catalog on a connection of its own (D-683). A schema that
   only looks alike, or has the name and no store in it, is not one.
2. **One tick withholds the patient in each store that opens**, the box's own first; the counts are summed and
   `stores` says how many. The read-back is per store (`<schema>.<table>`): a row left in any of them fails the
   tick by that store's name.
3. **A store that is there and cannot be opened fails the clear** after the others were cleared: `failed:
   ["omop"]`, and the tick's result and audit event name it (`not_opened: ["omop_<hex>"]`, a schema's name). It is
   never "skipped" and never counted as cleared. If the catalog itself cannot be asked, no store is called absent.
4. **A new kind of OMOP store fails a test until the worker knows it**: every name `schema_for` gives matches the
   worker's pattern, and every caller that opens an OMOP store is listed with the name it opens.

## Under roles, and whether a box can hold such a store

Found by running the real role script: under roles a per-lake store belongs to the service that first opened it
(made as `tb_lake`: owner `tb_lake`; there is no group for it), and no other service can open it.

Whether a box as shipped holds one (lanes D and B2, by reading, through the integrator): **only with the flag
`lake.source = omop` and a site set-up space other than the main one**. The site set-up builds that space's lake
in the orchestrator's own process (`sitesetup/service.py`), so the store is made and loaded as `tb_orchestrator`;
such a space takes uploads, so it can hold a site's real rows. The lake service and the adapter's dual write only
ever take `TB_LAKE_DIR` in the deploy; tests, the goldens and the parity tool make such stores as the admin.

So, for the store a box can really hold, **the worker is its owner and clears it** (held by a test under the role
script: a store made as `tb_orchestrator`, a patient opted out, one tick). For a store another service made, the
worker finds it, cannot open it, **and says so every tick** (`failed`, `not_opened`, health line red): the
fail-closed half. The other half is lane D's D-721 (a service refuses to make an OMOP store that is not its own
to make); lane C2 makes Reset drop a space's store and names it in the erasure registry. Neither is in this card.

## Evidence

`tests/unit/test_optout_worker.py` (five cases, each failed before): the names found; a patient out of two stores
in one tick; one store that cannot be opened is named and the other is cleared; a row left in the second store is
reported by its name; the enumerating test. `tests/unit/test_optout_every_omop_store_roles.py`: the same under the
real role script, with a store of the orchestrator's own (cleared) and one of another service's (named).
