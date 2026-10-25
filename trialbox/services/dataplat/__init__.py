"""TrialBox data platform, stages L0–L5 (spec v4 §5; S1-02, S1-03, S1-04).

Entry point: :func:`dataplat.pipeline.run_pipeline` drives one publish cycle L0 → L5 for a source directory and
returns a :class:`dataplat.pipeline.PipelineResult`.

| Stage | Package | OpenLineage job |
| --- | --- | --- |
| L0 landing | ``dataplat.landing`` | ``tb.l0.land.<source>`` |
| L1 validation | ``dataplat.validate`` (+ ``contracts``, ``reconcile``, ``dq``) | ``tb.l1.validate.<source>.<table>`` |
| L2 standardise | ``dataplat.standardise`` | ``tb.l2.standardise.<source>`` |
| L3 pseudonymise | ``dataplat.pseudonymise`` (+ ``mpi``) | ``tb.l3.pseudonymise`` |
| L4 curated + gate | ``dataplat.curated``, ``dataplat.publish`` | ``tb.l4.publish`` |
| L5 serving | ``dataplat.serving`` | ``tb.l5.serve.duckdb`` |

**Deviation from §20.8 S1-04 and HANDOFF §4 Phase 2 (recorded here on purpose).** The plan says to ``git mv``
``services/adapter/`` and ``services/lake/`` into ``services/dataplat/`` with import shims. That move is deferred:
other work streams import ``adapter.*`` and ``lake.*`` today. Instead the stages *wrap* the v1 code:
``standardise`` calls the v1 mapping engine (``adapter.mapping.engine``), the MIMIC normaliser
(``adapter.mapping.mimic``), ``adapter.pipeline.pseudonymise_bulk`` and the v1 NDJSON writer (``adapter.ndjson``);
``curated`` and ``serving`` call the v1 lake rebuild and reader (``lake.store.Lake``). The move, with shims, is a
follow-up once nothing else depends on the old paths.

Other recorded simplifications: the curated store is the §5.13.1 fallback (immutable per-snapshot NDJSON + Parquet +
DuckDB, the v1 layout) rather than Iceberg; GX-style expectations are implemented in code (``dataplat.dq``) rather
than with the Great Expectations package (not a dependency yet); the MPI is a local SQLite store standing in for
``tb-vault`` (§7.5); gate conditions 3 (terminology coverage) and 6 (OHDSI DQD) are recorded ``not_evaluated``
until ``tb-terminology`` and ``tb-omop`` exist.
"""
