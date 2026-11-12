"""T-723 (D-489; lifecycle review F-2, F-3, F-12, proposal G-2): ``publish(night)`` is one resumable function.

The row's three acceptance tests: a FHIR-store failure does not promote; a re-run under a held snapshot is refused;
accept works. And what the row names beside them: the pid map is written after the gate, the data-operations row is
opened at the start and a run that dies does not leave it open. Each state change is interrupted once (a step that
fails, a process that dies in the lake step, a second call). A real lake and PostgreSQL, synthetic rows."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import AdapterConfig, run_ingest
from datacore.dataops import FAILED, HELD, LANDED, LINE, PUBLISHED, REJECTED, DataOps
from tb_common.audit import AuditLog
from tb_common.crypto import pid_for_mrn

from tests.unit.test_dataflow_lake_p0 import KEY, _Bad, _cfg, _csv, _Lakes, _row

N1, N2 = "2026-10-01", "2026-10-02"
PAT = ["mrn", "name", "id_no", "birth_date", "sex", "death_date", "phone"]
FHIR = "http://hapi/fhir"


def _patients(path: Path, mrns: list[str]) -> None:
    with (path / "patient.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=PAT)
        w.writeheader()
        for m in mrns:
            w.writerow({"mrn": m, "name": f"Synthetic {m}", "id_no": "", "birth_date": "1960-01-01", "sex": "F"})


def _night(tmp_path: Path, name: str, rows: list[dict[str, str]], mrns: list[str] | None = None) -> str:
    _csv(tmp_path / name, rows)
    if mrns:
        _patients(tmp_path / name, mrns)
    return str(tmp_path / name)


def _conditions(folder: Path) -> list[str]:
    return sorted(r["id"] for r in read_type(folder, "Condition"))


def _record(folder: Path) -> dict[str, str]:
    steps: dict[str, str] = json.loads((folder / "publish.json").read_text())["steps"]
    return steps


class Fhir:
    """The FHIR store's loader stand-in: counts its calls and fails while ``down``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        try:
            from adapter import publish as home
        except ImportError:  # the code before T-723: the pipeline called the loader itself
            from adapter import pipeline as home  # type: ignore[no-redef]

        self.calls: list[str] = []
        self.down = False
        monkeypatch.setattr(home, "sync_snapshot", self)

    def __call__(self, base: str, folder: Path, ledger: Path, previous: Path | None = None) -> tuple[int, int]:
        self.calls.append(folder.name)
        if self.down:
            raise ConnectionError("the FHIR store did not answer")
        return 3, 0


def _fhir_cfg(tmp_path: Path, lakes: _Lakes) -> AdapterConfig:
    cfg = _cfg(tmp_path, lakes)
    cfg.fhir_base_url = FHIR
    return cfg


# ------------------------------------------------------------------------------------------- acceptance 1 (F-2)
def test_a_fhir_store_failure_does_not_promote_and_the_next_call_resumes_at_that_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.publish import publish_night

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    assert run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False
    ).passed
    fhir.down = True
    night2 = _night(tmp_path, "n2", [_row("D1", "2026-09-01"), _row("D2", "2026-10-01")], ["10000001"])
    rep = run_ingest(cfg, "csv", night2, snapshot=N2, validate=False)
    folder = snapshot_dir(cfg.lake_dir, N2)
    assert not rep.passed and not rep.held and any(e.startswith("fhir-store load failed") for e in rep.errors or [])
    # nothing after the failed step ran: the lake was not built, CURRENT did not move, the night did not pass
    assert lakes.calls == [N1] and lakes.lake.current() == N1 and rep.lake is None
    assert not (folder / "passed.json").exists()
    assert _record(folder) == {"pidmap": "done", "omop": "skipped", "fhir": "failed", "lake": "pending"}
    ops = DataOps()
    try:
        row = ops.batches(source="csv")[-1]
        assert (row.snapshot, row.state) == (N2, FAILED) and row.detail["publish"]["fhir"] == "failed"
    finally:
        ops.close()
    # the second call on the same folder starts at the step that failed: the pid map and OMOP are not done again
    fhir.down = False
    seen: list[str] = []
    out = publish_night(cfg, N2, folder, last_good=N1, on_step=lambda step, _steps: seen.append(step))
    assert out.ok and out.promoted and lakes.lake.current() == N2
    assert "pidmap" not in seen and "omop" not in seen and seen[0] == "fhir"
    assert fhir.calls == [N1, N2, N2] and lakes.calls == [N1, N2]
    assert (folder / "passed.json").exists() and set(_record(folder).values()) <= {"done", "skipped"}
    # a third call does nothing at all
    again = publish_night(cfg, N2, folder, last_good=N1)
    assert again.ok and fhir.calls == [N1, N2, N2] and lakes.calls == [N1, N2]


def test_the_same_night_run_again_resumes_and_a_changed_night_starts_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The night is run again from the source (the administrator's retry). The same content keeps the steps that
    were done; other content is another night's worth of work and starts at the first step."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    committed: list[str] = []
    from adapter.pidmap import PidMap

    real = PidMap.commit

    def counted(self: PidMap, snap: str) -> int:
        committed.append(snap)
        return real(self, snap)

    monkeypatch.setattr(PidMap, "commit", counted)
    fhir.down = True
    night = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert not run_ingest(cfg, "csv", night, snapshot=N1, validate=False).passed
    assert committed == [N1]
    fhir.down = False
    assert run_ingest(cfg, "csv", night, snapshot=N1, validate=False).passed
    assert committed == [N1] and lakes.lake.current() == N1  # the pid-map step was done: not run a second time
    ops = DataOps()
    try:
        assert [(b.attempt, b.state) for b in ops.batches(source="csv")] == [(1, FAILED), (2, PUBLISHED)]
    finally:
        ops.close()
    fhir.down = True
    changed = _night(tmp_path, "n1b", [_row("D1", "2026-09-01"), _row("D2", "2026-09-02")], ["10000001"])
    assert not run_ingest(cfg, "csv", changed, snapshot=N2, validate=False).passed
    fhir.down = False
    more = _night(tmp_path, "n1c", [_row("D1", "2026-09-01"), _row("D3", "2026-09-03")], ["10000001"])
    assert run_ingest(cfg, "csv", more, snapshot=N2, validate=False).passed
    assert committed == [N1, N2, N2]  # other content: every step again


# ------------------------------------------------------------------------------------------- acceptance 2 (F-3)
def test_a_rerun_under_a_held_snapshot_is_refused_and_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    assert run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False
    ).passed
    served = snapshot_dir(cfg.lake_dir, N1)
    before = (_conditions(served), (served / "passed.json").read_bytes(), lakes.lake.db_path(N1).stat().st_mtime_ns)
    lakes.lake.hold(N1, "01SCREENJOB")  # a job reads the served night
    rerun = _night(tmp_path, "n1b", [_row("D1", "2026-09-01"), _row("D2", "2026-09-02")])
    rep = run_ingest(cfg, "csv", rerun, snapshot=N1, validate=False)
    assert not rep.passed and not rep.held and any(e.startswith("lake busy") for e in rep.errors or [])
    # nothing a job reads was touched, and nothing was loaded anywhere
    after = (_conditions(served), (served / "passed.json").read_bytes(), lakes.lake.db_path(N1).stat().st_mtime_ns)
    assert after == before and not (served / "held.json").exists()
    assert lakes.calls == [N1] and fhir.calls == [N1]
    aside = cfg.lake_dir / "ndjson-rerun" / N1
    assert len(_conditions(aside)) == 2 and _record(aside)["lake"] == "busy"
    ops = DataOps()
    try:
        assert [(b.attempt, b.state) for b in ops.batches(source="csv")] == [(1, PUBLISHED), (2, FAILED)]
        assert ops.held() == []  # busy is not a judgement on the data: nothing for the steward (D-462)
    finally:
        ops.close()
    # the job ends: the same re-run is published
    lakes.lake.release("01SCREENJOB")
    rep = run_ingest(cfg, "csv", rerun, snapshot=N1, validate=False)
    assert rep.passed and len(_conditions(served)) == 2 and lakes.calls == [N1, N1] and not aside.exists()


def test_a_rerun_whose_lake_step_does_not_end_well_puts_the_served_folder_back(tmp_path: Path) -> None:
    """The hold is taken after the publish's own check (the lake refuses at its swap), the lake refuses the data,
    or the process dies in the lake step: each time the served folder holds what the served file was built from."""
    from lake.store import SnapshotHeld

    class Killed(BaseException):
        pass

    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False,
                      load_fhir=False).passed  # fmt: skip
    served = snapshot_dir(cfg.lake_dir, N1)
    rerun = _night(tmp_path, "n1b", [_row("D1", "2026-09-01"), _row("D2", "2026-09-02")])
    seen_inside: list[int] = []

    def failing(exc: BaseException) -> Any:
        def rebuild(snap: str, nd: Path) -> Any:
            seen_inside.append(len(_conditions(nd)))  # the build reads the re-run's records
            raise exc

        return rebuild

    for exc, held in ((SnapshotHeld("held at the swap"), False), (RuntimeError("disk full"), False)):
        cfg.rebuild = failing(exc)
        rep = run_ingest(cfg, "csv", rerun, snapshot=N1, validate=False, load_fhir=False)
        assert not rep.passed and rep.held is held
        assert _conditions(served) == _conditions(served)[:1] and len(_conditions(served)) == 1
        assert (served / "passed.json").exists() and not (served / "held.json").exists()
    cfg.rebuild = failing(Killed())
    with pytest.raises(Killed):
        run_ingest(cfg, "csv", rerun, snapshot=N1, validate=False, load_fhir=False)
    assert len(_conditions(served)) == 1 and (served / "passed.json").exists()
    assert seen_inside == [2, 2, 2]
    cfg.rebuild = lakes  # the lake is well again: the re-run takes the served folder's place
    assert run_ingest(cfg, "csv", rerun, snapshot=N1, validate=False, load_fhir=False).passed
    assert len(_conditions(served)) == 2 and not (cfg.lake_dir / "ndjson-rerun" / f"{N1}.replaced").exists()


# ------------------------------------------------------------------------------------------- the pid map (F-12)
def _resolves(cfg: AdapterConfig, mrn: str) -> bool:
    pm = cfg.pidmap()
    try:
        return pm.resolve(pid_for_mrn(KEY, mrn)) is not None
    finally:
        pm.close()


def _staged(cfg: AdapterConfig) -> dict[str, int]:
    pm = cfg.pidmap()
    try:
        return pm.staged()
    finally:
        pm.close()


def test_the_pid_map_is_written_after_the_gate_and_a_rejected_nights_numbers_are_dropped(tmp_path: Path) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    good = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", good, snapshot=N1, validate=False, load_fhir=False).passed
    assert _resolves(cfg, "10000001") and _staged(cfg) == {}
    held = _night(tmp_path, "n2", [_row("D1", "2026-09-01"), _row("D9", "2026-10-01")], ["10000001", "10000002"])
    rep = run_ingest(cfg, "csv", held, snapshot=N2, load_fhir=False, validator=_Bad())  # type: ignore[arg-type]
    assert rep.held
    assert not _resolves(cfg, "10000002")  # the reverse map does not know a held night's chart numbers
    assert _staged(cfg) == {N2: 2}
    # the steward rejects the night; the next run drops what it staged
    ops = DataOps()
    try:
        (row,) = ops.held()
        ops.decide(AuditLog(tmp_path / "audit"), row.id, "reject", by="steward:a", at="2026-10-02T09:00:00+08:00",
                   reason="the wrong extract")  # fmt: skip
        assert ops.batch(row.id).state == REJECTED  # type: ignore[union-attr]
    finally:
        ops.close()
    night3 = _night(tmp_path, "n3", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", night3, snapshot="2026-10-03", validate=False, load_fhir=False).passed
    assert _staged(cfg) == {} and not _resolves(cfg, "10000002")


def test_an_opt_out_takes_the_patient_out_of_the_staging(tmp_path: Path) -> None:
    """The staging is a store like any other (D-465): the opt-out worker's clear deletes the opted-out patient's
    staged chart number and identity, and its verify reads the store back."""
    from types import SimpleNamespace

    from datacore.optout_worker import clear_pending, verify_pending
    from tb_common.optout import OptOutRegister

    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    held = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001", "10000002"])
    assert run_ingest(cfg, "csv", held, snapshot=N1, load_fhir=False, validator=_Bad()).held  # type: ignore[arg-type]
    assert _staged(cfg) == {N1: 2}
    reg = OptOutRegister()
    try:
        env: Any = SimpleNamespace(register=reg)
        out = frozenset({pid_for_mrn(KEY, "10000002")})
        assert verify_pending(out, env) == {"pidmap.pending": 1}
        assert clear_pending(out, env) == {"staged": 1}
        assert verify_pending(out, env) == {"pidmap.pending": 0} and _staged(cfg) == {N1: 1}
        assert clear_pending(out, env) == {"staged": 0}  # idempotent
    finally:
        reg.close()


# ------------------------------------------------------------------------------------------- acceptance 3: accept
def _held_night(tmp_path: Path, cfg: AdapterConfig) -> Any:
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"]), snapshot=N1,
                      validate=False).passed  # fmt: skip
    held = _night(tmp_path, "n2", [_row("D1", "2026-09-01"), _row("D9", "2026-10-01")], ["10000001", "10000002"])
    rep = run_ingest(cfg, "csv", held, snapshot=N2, validator=_Bad())  # type: ignore[arg-type]
    assert rep.held
    ops = DataOps()
    try:
        (row,) = ops.held()
    finally:
        ops.close()
    return row


def test_accept_publishes_the_held_night_with_the_same_function(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.publish import NothingToPublish, publish_held

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    _held_night(tmp_path, cfg)
    folder = snapshot_dir(cfg.lake_dir, N2)
    assert (folder / "held.json").exists() and lakes.lake.current() == N1 and fhir.calls == [N1]
    out = publish_held(cfg, N2)
    assert out.ok and out.promoted and lakes.lake.current() == N2 and fhir.calls == [N1, N2]
    assert (folder / "passed.json").exists() and not (folder / "held.json").exists()
    assert _resolves(cfg, "10000002") and _staged(cfg) == {}  # the accepted night's chart numbers are in the map
    with pytest.raises(NothingToPublish):
        publish_held(cfg, N2)  # no longer a held night
    with pytest.raises(NothingToPublish):
        publish_held(cfg, "2026-10-09")


def test_the_stewards_accept_goes_through_the_adapter_and_a_failed_publish_keeps_the_night_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The console's promoter (``adapter_promoter``) over the adapter's ``/publish`` job, inside
    ``DataOps.decide``: a publish that fails leaves the night held with the step in ``publish.json``; a second
    accept resumes there and the night is PUBLISHED."""
    from adapter import app as adapter_app
    from console.dataops_page import adapter_promoter
    from fastapi.testclient import TestClient
    from tb_common.http import ServiceError
    from tb_common.jobpoll import Poll

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    row = _held_night(tmp_path, cfg)
    monkeypatch.setattr(adapter_app, "build_config", lambda: (cfg, "csv", ""))
    monkeypatch.setattr(adapter_app, "_spawn", lambda run: run())  # the job runs in the request (a test)
    http = TestClient(adapter_app.app)

    class Adapter:
        def post_raw(self, path: str, body: Any) -> Any:
            r = http.post(path, json=body)
            if r.status_code >= 400:
                raise ServiceError("adapter", r.status_code, r.text)
            return r

        def get_json(self, path: str) -> Any:
            return http.get(path).json()

    class Bk:
        adapter = Adapter()

    promote = adapter_promoter(Bk(), Poll(interval=0.01, lost_after=1.0, sleep=lambda _s: None))
    audit = AuditLog(tmp_path / "audit")
    ops = DataOps()
    try:
        fhir.down = True
        with pytest.raises(RuntimeError, match="failed"):
            ops.decide(audit, row.id, "accept", by="steward:a", at="2026-10-02T09:00:00+08:00", reason="checked",
                       promote=promote)  # fmt: skip
        assert ops.batch(row.id).state == HELD and lakes.lake.current() == N1  # type: ignore[union-attr]
        assert _record(snapshot_dir(cfg.lake_dir, N2))["fhir"] == "failed"
        fhir.down = False
        done = ops.decide(audit, row.id, "accept", by="steward:a", at="2026-10-02T09:05:00+08:00", reason="checked",
                          promote=promote)  # fmt: skip
        assert done.state == PUBLISHED and lakes.lake.current() == N2
        assert [s["new"] for s in ops.steps(row.id)] == [LANDED, HELD, PUBLISHED]
    finally:
        ops.close()
    # refused at once, nothing touched: no held night, and an attempt that is not the newest of its night
    assert http.post("/publish", json={"snapshot": "2026-10-09"}).status_code == 404
    rep = run_ingest(cfg, "csv", _night(tmp_path, "n3", [_row("D1", "2026-09-01")]), snapshot="2026-10-03",
                     validator=_Bad())  # type: ignore[arg-type]  # fmt: skip
    assert rep.held
    r = http.post("/publish", json={"snapshot": "2026-10-03", "source": "csv", "attempt": 7})
    assert r.status_code == 409 and "not the newest" in r.json()["detail"]


# ------------------------------------------------------------------------------------------- the row from the start
def test_the_row_is_opened_at_the_start_and_a_run_that_died_does_not_stay_open(tmp_path: Path) -> None:
    class Killed(BaseException):
        pass

    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    seen: list[tuple[str, int, Any, Any]] = []

    def dies(snap: str, nd: Path) -> Any:
        ops = DataOps()
        try:
            (row,) = ops.batches(source="csv")
            seen.append((row.state, row.attempt, row.detail.get("step"), row.detail.get("publish")))
        finally:
            ops.close()
        raise Killed

    cfg.rebuild = dies
    night = _night(tmp_path, "n1", [_row("D1", "2026-09-01")])
    with pytest.raises(Killed):
        run_ingest(cfg, "csv", night, snapshot=N1, validate=False, load_fhir=False)
    # while the night ran its row was there, with the step it was in
    assert seen == [(LANDED, 1, "publish:lake", {"pidmap": "done", "omop": "skipped", "fhir": "skipped",
                                                "lake": "pending"})]  # fmt: skip
    cfg.rebuild = lakes
    assert run_ingest(cfg, "csv", night, snapshot=N1, validate=False, load_fhir=False).passed
    ops = DataOps()
    try:
        first, second = ops.batches(source="csv")
        assert (first.attempt, first.state, second.attempt, second.state) == (1, FAILED, 2, PUBLISHED)
        assert [(s["new"], s["reason"].split(":")[0]) for s in ops.steps(first.id)] == [(LANDED, ""),
                                                                                        (FAILED, "interrupted")]  # fmt: skip
        assert [s["new"] for s in ops.steps(second.id)] == list(LINE)
        assert ops.held() == []
    finally:
        ops.close()
