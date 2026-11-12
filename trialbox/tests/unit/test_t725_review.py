"""T-725 (D-491), the adversarial review of 2026-11-12.

* H1: an older build that is still running cannot finish last and win the content: builds of one artefact are
  serial from their begin to their finish, and a build that was overtaken is a failed build;
* H2: a twin build that did not run, or that failed for a patient, is not ``finished``;
* H3: a job pinned to a generation reads the derive batch of that generation, not the first batch of its date;
* M1: a FHIR load whose ledger cannot be read does not run;
* M2: the same generation built twice at once: the first one's finish does not cover the second one's writes;
* M5: a generation is a date and a number, nothing else;
* a job keeps one reader, and with it one answer, to its end.

The real ledger in PostgreSQL; the builds are stand-ins that record what they wrote and when."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from datacore.generations import Built, guarded
from tb_common.generation import BUILDING, FINISHED, Generation

NEW, OLD = "2026-10-04", "2026-10-03"


def test_an_older_build_that_still_runs_cannot_finish_after_a_newer_one(db_url: str) -> None:
    """Job A (a late re-run of the older night) is inside its build when job B (the newer night) starts. Before:
    B began, built and finished while A went on writing; the content ended on the older night and the ledger said
    "finished from the newer". Now B waits for A's build to end, and then builds over it."""
    content: list[str] = []
    a_inside, a_may_end = threading.Event(), threading.Event()
    b_began = threading.Event()

    def build_a() -> str:
        a_inside.set()
        assert a_may_end.wait(30)
        content.append(OLD)  # A's last write
        return "a"

    def build_b() -> str:
        b_began.set()
        content.append(NEW)
        return "b"

    out: dict[str, Any] = {}
    ta = threading.Thread(target=lambda: out.update(a=guarded("derived", OLD, build_a, db_url)))
    ta.start()
    assert a_inside.wait(30)
    tb = threading.Thread(target=lambda: out.update(b=guarded("derived", NEW, build_b, db_url)))
    tb.start()
    assert not b_began.wait(1.0)  # B does not write while A's build runs
    a_may_end.set()
    ta.join(30)
    tb.join(30)
    assert content == [OLD, NEW] and out == {"a": "a", "b": "b"}  # the newer night's rows are the last written
    with Built(db_url) as b:
        assert b.state("derived") == (Generation(NEW), FINISHED) and b.readable("derived", NEW)


def test_the_same_generation_built_twice_at_once_is_finished_by_the_build_that_ends_last(db_url: str) -> None:
    """An administrator's retry while the first build of the generation still runs: the second waits, and the
    artefact is never ``finished`` while a build of it is writing."""
    seen: list[str] = []
    first_inside, first_may_end = threading.Event(), threading.Event()

    def first() -> None:
        first_inside.set()
        assert first_may_end.wait(30)

    def second() -> None:
        with Built(db_url) as b:
            got = b.state("derived")
        seen.append(got[1] if got else "")

    t1 = threading.Thread(target=lambda: guarded("derived", NEW, first, db_url))
    t1.start()
    assert first_inside.wait(30)
    t2 = threading.Thread(target=lambda: guarded("derived", NEW, second, db_url))
    t2.start()
    t2.join(1.0)
    assert t2.is_alive()  # the retry waits for the build that runs
    first_may_end.set()
    t1.join(30)
    t2.join(30)
    assert seen == [BUILDING]  # inside the second build the artefact is building, not finished by the first
    with Built(db_url) as b:
        assert b.state("derived") == (Generation(NEW), FINISHED)


def test_a_build_that_was_overtaken_is_a_failed_build(db_url: str) -> None:
    """A writer that does not take the build's lock (a tool, a hand repair) records a newer generation while a
    build runs: the build's own finish changes nothing, and the caller is told the build did not count."""

    def overtaken() -> str:
        with Built(db_url) as b:
            b.begin("vec", f"{NEW}.g3")
        return "built"

    with pytest.raises(RuntimeError, match="overtaken"):
        guarded("vec", NEW, overtaken, db_url)
    with Built(db_url) as b:
        assert b.state("vec") == (Generation(NEW, 3), BUILDING)


def test_a_twin_build_that_did_not_run_is_not_finished(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.scenarios import admin
    from patient_profile import twin

    answers: list[Any] = [None, twin.BuildReport(NEW, inserted=1, failed=["p9"]), twin.BuildReport(NEW, inserted=2)]
    monkeypatch.setattr(twin, "after_ingest", lambda db, lake, snap, now, url=None: answers.pop(0))
    ctx: Any = SimpleNamespace(orch=SimpleNamespace(db=object()), services=SimpleNamespace(lake=object()))
    admin.twins_after_ingest(ctx, date.fromisoformat(NEW))  # the build could not run (the store did not open)
    with Built(db_url) as b:
        assert b.state("twin") == (Generation(NEW), BUILDING) and not b.readable("twin", NEW)
    admin.twins_after_ingest(ctx, date.fromisoformat(NEW))  # it ran and failed for a patient
    with Built(db_url) as b:
        assert b.state("twin") == (Generation(NEW), BUILDING)
    admin.twins_after_ingest(ctx, date.fromisoformat(NEW))  # the retry builds every twin
    with Built(db_url) as b:
        assert b.state("twin") == (Generation(NEW), FINISHED)


def test_a_job_reads_the_batch_of_its_generation_not_the_first_batch_of_its_date(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two generations of one date (a site publish after the night): each has its derive batch. A job pinned to
    the second reads the second batch; before, it passed the gate and was handed the first batch of the date."""
    from orchestrator import derive
    from tb_common.derived_store import DerivedStore, Report

    st = DerivedStore(db_url)
    try:
        monkeypatch.setattr(derive, "store", lambda url=None: st)
        monkeypatch.setattr(derive, "mapping_version_of", lambda lake, snap: "m1")

        def run(store: Any, lake: Any, **kw: Any) -> Report:
            store.finish_batch(store.begin_batch(kw["snapshot"], kw["mapping_version"]), Report(), 0)
            return Report()

        monkeypatch.setattr(derive, "run_batch", run)
        generation = [NEW]
        lake = SimpleNamespace(generation=lambda snapshot: generation[0])
        audit = SimpleNamespace(append=lambda event, **kw: {})
        orch = SimpleNamespace(db=SimpleNamespace(url=db_url), services=SimpleNamespace(lake=lake), audit=audit)
        assert derive.after_ingest(orch, NEW) is not None
        first = st.batch(NEW)
        generation[0] = f"{NEW}.g1"
        assert derive.after_ingest(orch, NEW) is not None

        def job_on(gen: str) -> Any:
            job = SimpleNamespace(snapshot_date=date.fromisoformat(NEW), options={"lake_generation": gen})
            return derive.GenerationReader(st, db_url, SimpleNamespace(job=job))

        assert first is not None
        got = job_on(f"{NEW}.g1").batch(NEW)
        assert got is not None and got.run_id > first.run_id  # the batch built from generation 1
        assert job_on(NEW).batch(NEW) is None  # the rows are of generation 1 now
    finally:
        st.close()


def test_a_fhir_load_whose_ledger_cannot_be_read_does_not_run(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ledger says the store holds the newer night; the database does not answer for one call. Before: the
    older night was loaded (and the newer night's resources deleted) while the ledger still said "newer, finished"."""
    import json

    from adapter import load_fhir
    from datacore import generations

    loaded: list[str] = []

    def load(base: str, d: Path, workers: int = 4, only: Any = None) -> int:
        loaded.append(d.name)
        return 1

    def delete(base: str, refs: list[str]) -> int:
        loaded.append("deleted")
        return len(refs)

    monkeypatch.setattr(load_fhir, "load_snapshot", load)
    monkeypatch.setattr(load_fhir, "delete_refs", delete)
    for night in (NEW, OLD):
        (tmp_path / night).mkdir()
        (tmp_path / night / "Patient.ndjson").write_text(json.dumps({"resourceType": "Patient", "id": night}) + "\n")
    load_fhir.sync_snapshot("http://hapi/fhir", tmp_path / NEW, tmp_path / "ledger")
    assert loaded == [NEW]

    class Down:
        def __init__(self, url: str | None = None) -> None:
            raise ConnectionError("the trial database did not answer")

    monkeypatch.setattr(generations, "Built", Down)
    with pytest.raises(RuntimeError, match="generation ledger"):
        load_fhir.sync_snapshot("http://hapi/fhir", tmp_path / OLD, tmp_path / "ledger")
    assert loaded == [NEW]  # nothing loaded, nothing deleted
    monkeypatch.undo()
    with Built(db_url) as b:
        assert b.readable("fhir", NEW)


@pytest.mark.nodb
@pytest.mark.parametrize(
    "name",
    ["latest", "2026-11-9", "2026-13-01", f"{NEW}.g-1", f"{NEW}.g1x", f"{NEW}.G1", f"{NEW}.g１", f"{NEW}.g0",
     f"{NEW}.g01", f"{NEW}.g1.g2", "", "a/b"],
)  # fmt: skip
def test_a_generation_is_a_date_and_a_number_and_nothing_else(name: str) -> None:
    with pytest.raises(ValueError, match="not a generation"):
        Generation.parse(name)


@pytest.mark.nodb
def test_generations_are_ordered_by_date_then_number() -> None:
    order = ["2026-11-09", "2026-11-10", "2026-11-10.g1", "2026-11-10.g9", "2026-11-10.g10", "2026-11-11"]
    assert sorted(order, key=Generation.parse) == order
    assert str(Generation.parse("2026-11-10.g10")) == "2026-11-10.g10"


def test_a_snapshot_that_is_not_a_night_is_built_as_before_and_not_recorded(db_url: str) -> None:
    """A lake snapshot with another name (a tool's, a test's) has no place in the order: its build runs, the
    ledger is not written, and no real night is ever refused because of it."""
    assert guarded("derived", "latest", lambda: "built", db_url) == "built"
    with Built(db_url) as b:
        assert b.state("derived") is None
    assert guarded("derived", NEW, lambda: "built", db_url) == "built"


def test_a_job_keeps_one_reader_and_its_answer_to_its_end(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import derive

    class Store:
        def batch(self, snapshot: str) -> str:
            return f"batch of {snapshot}"

    monkeypatch.setattr(derive, "reader", lambda orch: Store())
    monkeypatch.setattr(derive, "url_of", lambda orch: db_url)
    guarded("derived", NEW, lambda: None, db_url)
    job = SimpleNamespace(snapshot_date=date.fromisoformat(NEW), options={})
    ctx = SimpleNamespace(orch=object(), job=job)
    one = derive.reader_for(ctx)
    assert one.batch(NEW) == f"batch of {NEW}"
    with Built(db_url) as b:
        b.begin("derived", "2026-10-05")  # the next night's batch starts while the job still runs
    again = derive.reader_for(ctx)
    assert again is one and again.batch(NEW) == f"batch of {NEW}"  # the same answer at the job's next read
    other = derive.reader_for(SimpleNamespace(orch=object(), job=job))  # a job started now
    assert other.batch(NEW) is None
