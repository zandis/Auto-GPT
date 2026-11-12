"""T-725 (D-491; lifecycle review F-4): the builders ask the generation ledger before they write, and the
stored-score reader asks it before it reads. The property over interleavings is in
``tests/property/test_generation_interleavings.py``; here each wired step, with an older night after a newer one."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from datacore.generations import Built, generation_of, guarded
from tb_common.generation import FINISHED, Generation

NEW, OLD = "2026-10-04", "2026-10-03"


def _folder(tmp_path: Path, night: str, ids: list[str]) -> Path:
    d = tmp_path / "ndjson" / night
    d.mkdir(parents=True)
    rows = [{"resourceType": "Patient", "id": i} for i in ids]
    (d / "Patient.ndjson").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return d


def test_the_fhir_store_does_not_go_back_to_an_older_night(tmp_path: Path, db_url: str, monkeypatch: Any) -> None:
    """F-4: a late re-run of an earlier night made the FHIR store hold exactly the older night. Now the load of an
    older night is skipped and the store keeps the newer one."""
    from adapter import load_fhir

    loaded: list[str] = []
    deleted: list[list[str]] = []

    def load(base: str, directory: Path, workers: int = 4, only: Any = None) -> int:
        loaded.append(directory.name)
        return sum(len(v) for v in (only or {}).values())

    monkeypatch.setattr(load_fhir, "load_snapshot", load)

    def delete(base: str, refs: list[str]) -> int:
        deleted.append(list(refs))
        return len(refs)

    monkeypatch.setattr(load_fhir, "delete_refs", delete)
    ledger = tmp_path / "fhir_ledger"
    assert load_fhir.sync_snapshot("http://hapi/fhir", _folder(tmp_path, NEW, ["p1", "p2", "p3"]), ledger) == (3, 0)
    with Built(db_url) as b:
        assert b.state("fhir") == (Generation(NEW), FINISHED)
    before = sorted(p.name for p in tmp_path.rglob("*") if "ledger" in p.name)
    assert load_fhir.sync_snapshot("http://hapi/fhir", _folder(tmp_path, OLD, ["p1"]), ledger) == (0, 0)
    assert loaded == [NEW] and deleted == []  # nothing loaded, and p2 and p3 were not deleted from the store
    assert sorted(p.name for p in tmp_path.rglob("*") if "ledger" in p.name) == before
    with Built(db_url) as b:
        assert b.state("fhir") == (Generation(NEW), FINISHED) and b.readable("fhir", NEW)
    # the same night again is a retry, and a folder that is not a night is loaded as before
    assert load_fhir.sync_snapshot("http://hapi/fhir", tmp_path / "ndjson" / NEW, ledger) == (0, 0)
    other = tmp_path / "bundle"
    other.mkdir()
    (other / "Patient.ndjson").write_text(json.dumps({"resourceType": "Patient", "id": "p1"}) + "\n")
    load_fhir.sync_snapshot("http://hapi/fhir", other, tmp_path / "other_ledger")
    assert loaded == [NEW, NEW, "bundle"]


class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event: str, **fields: Any) -> dict[str, Any]:
        self.events.append((event, dict(fields.get("detail") or {})))
        return {}


def test_the_derive_batch_of_an_older_night_does_not_run(db_url: str, monkeypatch: Any) -> None:
    from orchestrator import derive

    ran: list[str] = []
    rep = SimpleNamespace(inserted=1, unchanged=0, superseded=0, retired=0, conflicts=0, failed=0)
    monkeypatch.setattr(derive, "store", lambda url=None: object())
    monkeypatch.setattr(derive, "mapping_version_of", lambda lake, snap: "m1")

    def run(st: Any, lake: Any, **kw: Any) -> Any:
        ran.append(kw["snapshot"])
        return rep

    monkeypatch.setattr(derive, "run_batch", run)
    audit = _Audit()
    orch = SimpleNamespace(db=SimpleNamespace(url=db_url), services=SimpleNamespace(lake=object()), audit=audit)
    assert derive.after_ingest(orch, NEW) is not None and ran == [NEW]
    assert derive.after_ingest(orch, OLD) is None and ran == [NEW]  # refused: the newer rows stay
    assert audit.events[-1] == ("derive.failed", {"snapshot": OLD, "error": "OlderGeneration"})
    with Built(db_url) as b:
        assert b.readable("derived", NEW) and not b.readable("derived", OLD)


def test_the_twin_build_of_an_older_night_does_not_run(db_url: str, monkeypatch: Any) -> None:
    from orchestrator.scenarios import admin
    from patient_profile import twin

    built: list[str] = []

    # the build's stand-in answers a report, as the build does when it ran (None is "could not run": review H2)
    def ran(db: Any, lake: Any, snap: str, now: str, url: str | None = None) -> Any:
        built.append(snap)
        return twin.BuildReport(snap)

    monkeypatch.setattr(twin, "after_ingest", ran)

    class Lake:  # a lake with generations (T-724) says which one a night is
        def generation(self, snapshot: str) -> str:
            return f"{snapshot}.g2"

    ctx: Any = SimpleNamespace(orch=SimpleNamespace(db=object()), services=SimpleNamespace(lake=Lake()))
    admin.twins_after_ingest(ctx, date.fromisoformat(NEW))
    admin.twins_after_ingest(ctx, date.fromisoformat(OLD))  # F-4: superseded the newer twins before
    assert built == [NEW]
    with Built(db_url) as b:
        assert b.state("twin") == (Generation(NEW, 2), FINISHED)
    assert generation_of(Lake(), NEW) == f"{NEW}.g2" and generation_of(object(), NEW) == NEW


def test_a_job_reads_stored_scores_only_when_they_are_built_from_its_generation(db_url: str) -> None:
    """The reader's gate: for the job's own night the finished batch counts only when the derived rows are
    finished from the generation the job pinned; else every stored score is unknown (``batch`` is None)."""
    from orchestrator.derive import GenerationReader

    class Store:
        mapping = "m1"

        def batch(self, snapshot: str) -> str:
            return f"batch of {snapshot}"

    def job_on(generation: str | None) -> GenerationReader:
        job = SimpleNamespace(snapshot_date=date.fromisoformat(NEW), options={"lake_generation": generation})
        return GenerationReader(Store(), db_url, SimpleNamespace(job=job))  # type: ignore[arg-type]

    assert job_on(f"{NEW}.g1").batch(NEW) is None  # never built: unknown
    guarded("derived", f"{NEW}.g1", lambda: None, db_url)
    on_g1 = job_on(f"{NEW}.g1")
    assert on_g1.batch(NEW) == f"batch of {NEW}" and on_g1.mapping == "m1"
    assert job_on(f"{NEW}.g2").batch(NEW) is None  # the site published since: the rows are of generation 1
    assert job_on(None).batch(NEW) is None  # a job that pinned the bare date: not generation 1 either
    assert job_on(f"{NEW}.g2").batch(OLD) == f"batch of {OLD}"  # another night than the job's: the store's own answer
    with Built(db_url) as b:
        b.begin("derived", f"{NEW}.g2")
    assert job_on(f"{NEW}.g2").batch(NEW) is None  # still building
    assert on_g1.batch(NEW) == f"batch of {NEW}"  # a job keeps the answer it got to its end
    with Built(db_url) as b:
        b.finish("derived", f"{NEW}.g2")
    assert job_on(f"{NEW}.g2").batch(NEW) == f"batch of {NEW}" and job_on(f"{NEW}.g1").batch(NEW) is None
    unpinned = GenerationReader(Store(), db_url, SimpleNamespace(job=SimpleNamespace(snapshot_date=None, options={})))  # type: ignore[arg-type]
    assert unpinned.batch(NEW) == f"batch of {NEW}"  # a job that reads no lake has no night to be wrong about


@pytest.mark.nodb
def test_without_a_trial_database_the_builders_run_as_before(monkeypatch: Any) -> None:
    monkeypatch.delenv("TB_DB_URL", raising=False)
    assert guarded("twin", NEW, lambda: "built") == "built"
