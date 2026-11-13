"""NEW-B-4 (D-525; the owner's ruling of 2026-11-12 on T-725's review, M3): a finished generation of the derived
rows stays readable.

The ledger had one row per artefact. Once the build from a newer generation began, a job pinned to the older one
read every stored score as unknown, for ever: safe, but yesterday's job run again did not read what it had read
(D-442). The derived store keeps its rows as of a batch, so the older generation's batch can still be read: the
ledger now keeps, per finished generation of ``derived``, the batch its build made."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from datacore.generations import Built

NEW, OLD = "2026-10-04", "2026-10-03"


def _orch(db_url: str, st: Any, monkeypatch: pytest.MonkeyPatch, generation: list[str]) -> Any:
    from orchestrator import derive
    from tb_common.derived_store import Report

    monkeypatch.setattr(derive, "store", lambda url=None: st)
    monkeypatch.setattr(derive, "mapping_version_of", lambda lake, snap: "m1")

    def run(store: Any, lake: Any, **kw: Any) -> Report:
        store.finish_batch(store.begin_batch(kw["snapshot"], kw["mapping_version"]), Report(), 0)
        return Report()

    monkeypatch.setattr(derive, "run_batch", run)
    lake = SimpleNamespace(generation=lambda snapshot: generation[0])
    audit = SimpleNamespace(append=lambda event, **kw: {})
    return SimpleNamespace(db=SimpleNamespace(url=db_url), services=SimpleNamespace(lake=lake), audit=audit)


def _job_on(st: Any, db_url: str, night: str, gen: str) -> Any:
    from orchestrator import derive

    job = SimpleNamespace(snapshot_date=date.fromisoformat(night), options={"lake_generation": gen})
    return derive.GenerationReader(st, db_url, SimpleNamespace(job=job))


def test_a_job_pinned_to_an_older_finished_generation_still_reads_its_batch(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orchestrator import derive
    from tb_common.derived_store import DerivedStore

    st = DerivedStore(db_url)
    try:
        generation = [OLD]
        orch = _orch(db_url, st, monkeypatch, generation)
        assert derive.after_ingest(orch, OLD) is not None
        old_batch = st.batch(OLD)
        assert old_batch is not None
        generation[0] = NEW
        assert derive.after_ingest(orch, NEW) is not None  # the next night: the ledger's row names NEW now
        got = _job_on(st, db_url, OLD, OLD).batch(OLD)  # yesterday's job, run again
        assert got is not None and got.run_id == old_batch.run_id and got.finished_at == old_batch.finished_at
        # two generations of one date: each job reads the batch its own generation's build made
        generation[0] = f"{NEW}.g1"
        first_new = st.batch(NEW)
        assert derive.after_ingest(orch, NEW) is not None
        assert first_new is not None
        assert _job_on(st, db_url, NEW, NEW).batch(NEW).run_id == first_new.run_id
        assert _job_on(st, db_url, NEW, f"{NEW}.g1").batch(NEW).run_id > first_new.run_id
        # a generation that was never built to its end is still unknown
        assert _job_on(st, db_url, NEW, f"{NEW}.g7").batch(NEW) is None
    finally:
        st.close()


def test_a_newer_build_that_runs_does_not_take_the_older_generations_answer_away(db_url: str) -> None:
    """Each state change: begin of the newer build (the row says building NEW), its failure (still building), its
    end. A job pinned to OLD reads OLD's batch through all three."""
    with Built(db_url) as b:
        g_old = b.begin("derived", OLD)
        assert b.kept("derived", OLD) is None  # not finished: nothing is kept
        assert b.finish("derived", g_old, "41")
        assert b.kept("derived", OLD) == "41"
        g_new = b.begin("derived", NEW)  # the newer build starts ...
        assert not b.readable("derived", OLD).ok and b.kept("derived", OLD) == "41"
        assert b.kept("derived", NEW) is None  # ... and is not readable itself until it ends
    with Built(db_url) as again:  # the process died in the build; a new one reads the same
        assert again.kept("derived", OLD) == "41" and again.kept("derived", NEW) is None
        assert again.finish("derived", g_new, "42")
        assert again.kept("derived", NEW) == "42" and again.kept("derived", OLD) == "41"
        # the same generation built again: its newest finished build is the one that counts
        again.begin("derived", NEW)
        assert again.kept("derived", NEW) == "42"  # while it runs: the build before it
        assert again.finish("derived", NEW, "43") and again.kept("derived", NEW) == "43"


def test_only_the_derived_rows_keep_their_generations(db_url: str) -> None:
    """The twins, the vectors and the FHIR store hold one state, not a history: an older generation of those is
    gone when a newer one is built, and the ledger does not say otherwise."""
    with Built(db_url) as b:
        for artefact in ("twin", "fhir"):
            assert b.finish(artefact, b.begin(artefact, OLD), "x")
            assert b.kept(artefact, OLD) is None


# ------------------------------------------------------------------------------------------- the review of NEW-B-4
def _kept_reader(db_url: str, st: Any, ref_of_old: str) -> Any:
    """A ledger in which OLD is finished (its build made ``ref_of_old``) and NEW is what the rows are built from."""
    with Built(db_url) as b:
        assert b.finish("derived", b.begin("derived", OLD), ref_of_old)
        assert b.finish("derived", b.begin("derived", NEW), "999999")
    return _job_on(st, db_url, OLD, OLD)


def test_a_rebuild_of_the_jobs_own_generation_that_runs_or_died_reads_as_unknown(db_url: str) -> None:
    """Review HIGH: the rows are being built again from the job's OWN generation (a second passed ingest of the
    same night; its content is new under the same name), or that build died. The batch of the earlier build is
    not what the lake holds now: unknown, as D-491 has it. The kept batch is for another generation's job only."""
    from tb_common.derived_store import DerivedStore, Report

    st = DerivedStore(db_url)
    try:
        first = st.begin_batch(NEW, "m1")
        st.finish_batch(first, Report(), 0)
        with Built(db_url) as b:
            assert b.finish("derived", b.begin("derived", NEW), str(first))
            assert _job_on(st, db_url, NEW, NEW).batch(NEW) is not None  # finished from the job's generation
            b.begin("derived", NEW)  # built again from the same generation; this build never ends
        assert _job_on(st, db_url, NEW, NEW).batch(NEW) is None
    finally:
        st.close()


def test_what_stays_unknown_through_the_reader(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """D-525 point 4, each through the job's reader: a kept batch the store no longer has, a build that did not
    say what it made in the store's terms, a ledger that cannot be read."""
    from tb_common.derived_store import DerivedStore

    st = DerivedStore(db_url)
    try:
        assert _kept_reader(db_url, st, "424242").batch(OLD) is None  # no such batch in the store
        with Built(db_url) as b:
            b._db.execute("UPDATE built_kept SET ref = 'not-a-run-id' WHERE artefact = 'derived'")
        assert _job_on(st, db_url, OLD, OLD).batch(OLD) is None

        def broken(self: Any, artefact: str, generation: Any) -> Any:
            raise RuntimeError("the ledger did not answer")

        monkeypatch.setattr(Built, "kept", broken)
        assert _job_on(st, db_url, OLD, OLD).batch(OLD) is None
    finally:
        st.close()


def test_the_older_job_reads_the_values_as_they_stood_at_its_batch(db_url: str) -> None:
    """A value, not only a batch id: what the older generation's job reads is the batch's ``finished_at``, the
    moment the store's rows are read as of."""
    from tb_common.derived_store import DerivedStore, Report

    st = DerivedStore(db_url)
    try:
        old = st.begin_batch(OLD, "m1")
        st.finish_batch(old, Report(), 0)
        stood = st.batch_by_id(old)
        assert stood is not None
        got = _kept_reader(db_url, st, str(old)).batch(OLD)
        assert got is not None and (got.run_id, got.finished_at) == (stood.run_id, stood.finished_at)
    finally:
        st.close()
