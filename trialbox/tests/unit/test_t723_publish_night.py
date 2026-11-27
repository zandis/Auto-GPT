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

N1, N2, N3 = "2026-10-01", "2026-10-02", "2026-10-03"
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
        self.back: list[bool] = []  # per call: asked as a put-back (the ledger lets it over an unfinished load)
        self.full: list[bool] = []  # per call: every resource is loaded again (a put-back), not only the changed
        self.down = False
        self.bad: set[str] = set()  # nights the store refuses part-way (it is up: a put-back works)
        self.holds: str | None = None  # the night the store holds now
        self.verified: list[str] = []  # the nights the store was checked against (P-03)
        self.home = home
        monkeypatch.setattr(home, "sync_snapshot", self)
        if hasattr(home, "verify_fhir"):  # P-03: the store's check against a night is answered from what it holds
            monkeypatch.setattr(home, "verify_fhir", self.verify)

    def verify(self, cfg: AdapterConfig, folder: Path, *, ids: bool = False, also: Any = ()) -> dict[str, int]:
        self.verified.append(folder.name)
        if self.down:
            raise ConnectionError("the FHIR store did not answer")
        nothing = ("", "fhir-nothing-served")
        holds, night = self.holds or "", folder.name
        if holds != night and not (holds in nothing and night in nothing):
            raise self.home.FhirMismatch(f"the store holds {holds or 'nothing'}, not {night}")
        return {}

    def __call__(
        self, base: str, folder: Path, ledger: Path, previous: Path | None = None, full: bool = False,
        back: bool = False,
    ) -> tuple[int, int]:  # fmt: skip
        self.calls.append(folder.name)
        self.full.append(full)
        self.back.append(back)
        if self.down:
            raise ConnectionError("the FHIR store did not answer")
        if folder.name in self.bad:
            self.holds = f"part of {folder.name}"
            raise ValueError("the FHIR store refused a resource")
        self.holds = folder.name
        return 3, 0


def _two_step(cfg: AdapterConfig, lakes: _Lakes) -> None:
    """The lake in two steps, as the adapter service is wired: build (judged, not served), promote last."""
    from embed_service.embedder import HashEmbedder
    from tb_contracts import RebuildResult

    def build(snap: str, nd: Path) -> RebuildResult:
        lakes.calls.append(snap)
        st = lakes.lake.rebuild(snap, HashEmbedder(), nd, promote=False, check=True)
        return RebuildResult(snapshot=st.snapshot, tables=st.tables, chunks=st.chunks, embedded_new=st.embedded_new,
                             seconds=st.seconds)  # fmt: skip

    cfg.build, cfg.promote = build, lakes.lake.promote_built


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
    assert _record(folder) == {"build": "skipped", "omop": "skipped", "fhir": "failed", "lake": "pending",
                               "pidmap": "pending"}  # fmt: skip
    assert not _resolves(cfg, "10000001")  # a night that is not served has no chart number in the reverse map
    ops = DataOps()
    try:
        row = ops.batches(source="csv")[-1]
        assert (row.snapshot, row.state) == (N2, FAILED) and row.detail["publish"]["fhir"] == "failed"
    finally:
        ops.close()
    # the store was down, so the put-back to the served night failed too, and the report says so
    assert any(e.startswith("fhir-store put-back failed") for e in rep.errors or [])
    assert fhir.calls == [N1, N2, N1]
    # the second call on the same folder starts at the step that failed: OMOP is not done again
    fhir.down = False
    seen: list[str] = []
    out = publish_night(cfg, N2, folder, last_good=N1, on_step=lambda step, _steps: seen.append(step))
    assert out.ok and out.promoted and lakes.lake.current() == N2
    assert "omop" not in seen and seen[0] == "fhir" and seen[-1] == "pidmap"  # the pid map last
    # P-03 (reviews R2, N1): the put-back that failed is owed (FHIR_STATE) and done first, then the night is loaded
    assert fhir.calls == [N1, N2, N1, N1, N2] and lakes.calls == [N1, N2] and fhir.holds == N2
    assert (folder / "passed.json").exists() and set(_record(folder).values()) <= {"done", "skipped"}
    assert _resolves(cfg, "10000001")
    # a third call does nothing at all
    marker, record, checks = (
        (cfg.lake_dir / "FHIR_STATE").read_bytes(),
        (folder / "publish.json").read_bytes(),
        len(fhir.verified),
    )
    again = publish_night(cfg, N2, folder, last_good=N1)
    assert again.ok and fhir.calls == [N1, N2, N1, N1, N2] and lakes.calls == [N1, N2]
    # P-03 (review D7): it asks the store nothing and rewrites neither the marker nor the record
    assert fhir.verified[checks:] == [] and (cfg.lake_dir / "FHIR_STATE").read_bytes() == marker
    assert (folder / "publish.json").read_bytes() == record


def test_the_same_night_run_again_resumes_and_a_changed_night_starts_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The night is run again from the source (the administrator's retry). The same content keeps the steps that
    were done; other content is another night's worth of work and starts at the first step."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
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
    # the lake built the night and did not serve it; the pid map was not written
    assert lakes.calls == [N1] and lakes.lake.current() is None and committed == []
    fhir.down = False
    assert run_ingest(cfg, "csv", night, snapshot=N1, validate=False).passed
    assert lakes.calls == [N1] and lakes.lake.current() == N1  # the build was done: not run a second time
    assert committed == [N1]
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
    assert lakes.calls == [N1, N2, N2] and committed == [N1, N2]  # other content: every step again


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
    """The orchestrator's promoter (``orchestrator.dataops_api.promoter``, NEW-ARCH-3) over the adapter's ``/publish`` job, inside
    ``DataOps.decide``: a publish that fails leaves the night held with the step in ``publish.json``; a second
    accept resumes there and the night is PUBLISHED."""
    from adapter import app as adapter_app
    from fastapi.testclient import TestClient
    from orchestrator.dataops_api import promoter
    from tb_common.http import ServiceError
    from tb_common.jobpoll import Poll

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    row = _held_night(tmp_path, cfg)
    monkeypatch.setattr(adapter_app, "build_config", lambda: (cfg, "csv", ""))
    monkeypatch.setattr(adapter_app, "_spawn", lambda run: run())  # the job runs in the request (a test)
    http = TestClient(adapter_app.app)

    class Orch:  # NEW-SEC-4 (D-760): the orchestrator's route, which starts the adapter's publish
        def post_raw(self, path: str, body: Any, headers: Any = None) -> Any:
            r = http.post(path.replace("/dataops/publish", "/publish"), json=body)
            if r.status_code >= 400:
                raise ServiceError("adapter", r.status_code, r.text)
            return r

        def get_json(self, path: str) -> Any:
            return http.get(path.replace("/dataops/publish", "/publish")).json()

    class AsAdapter:  # NEW-ARCH-3 (D-761): the orchestrator's adapter client; the publish runs at the orchestrator
        def publish(self, body: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = Orch().post_raw("/publish", body).json()
            return out

        def publish_state(self, rid: str) -> dict[str, Any]:
            out: dict[str, Any] = Orch().get_json(f"/publish/{rid}")
            return out

    promote = promoter(AsAdapter(), Poll(interval=0.01, lost_after=1.0, sleep=lambda _s: None))

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
    assert seen == [(LANDED, 1, "publish:lake", {"build": "skipped", "omop": "skipped", "fhir": "skipped",
                                                "lake": "pending", "pidmap": "pending"})]  # fmt: skip
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


# ----------------------------------------------------------------------------- review fixes (integrator, 2026-11-12)
def _adapter(cfg: AdapterConfig, monkeypatch: pytest.MonkeyPatch) -> Any:
    from adapter import app as adapter_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(adapter_app, "build_config", lambda: (cfg, "csv", ""))
    monkeypatch.setattr(adapter_app, "_spawn", lambda run: run())  # the job runs in the request (a test)
    return TestClient(adapter_app.app)


def test_an_older_held_night_is_not_published_once_a_newer_night_is_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HIGH-1: N1 passes, N2 is held, N3 passes and is served, the steward accepts N2. Nothing is loaded anywhere:
    the FHIR store stays on N3 with the lake, the held night's chart numbers stay out of the reverse map, and the
    publish does not say "done"."""
    from adapter.publish import publish_held

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    fhir = Fhir(monkeypatch)
    _held_night(tmp_path, cfg)
    night3 = _night(tmp_path, "n3", [_row("D1", "2026-09-01"), _row("D3", "2026-10-02")], ["10000001"])
    assert run_ingest(cfg, "csv", night3, snapshot=N3, validate=False).passed
    assert lakes.lake.current() == N3 and fhir.holds == N3
    calls, builds = list(fhir.calls), list(lakes.calls)
    folder = snapshot_dir(cfg.lake_dir, N2)
    (folder / "held.json").write_text(json.dumps({"snapshot": N2}))  # still on the steward's list
    out = publish_held(cfg, N2)
    assert not out.ok and out.stale and not out.promoted and "newer night" in out.errors[0]
    assert fhir.calls == calls and lakes.calls == builds and fhir.holds == N3 and lakes.lake.current() == N3
    assert not _resolves(cfg, "10000002") and not (folder / "passed.json").exists()
    http = _adapter(cfg, monkeypatch)
    st = http.post("/publish", json={"snapshot": N2}).json()
    assert st["state"] == "stale" and st["promoted"] is False and "newer night" in st["detail"]


@pytest.mark.parametrize("outcome", ["refused", "busy", "failed", "fhir", "not promoted"])
def test_when_the_night_is_not_promoted_no_store_is_left_on_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    """MED-1: the lake's verdict comes first (build), the promotion last. Whatever stops the publish before the
    promotion, the FHIR store is on the night the lake serves and the reverse map has none of the night's numbers."""
    from adapter.pipeline import RebuildRefused
    from lake.store import SnapshotHeld

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    fhir = Fhir(monkeypatch)
    first = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", first, snapshot=N1, validate=False).passed
    build, promote = cfg.build, cfg.promote
    errors = {"refused": RebuildRefused("the lake refused the night"), "busy": SnapshotHeld("held at the swap"),
              "failed": RuntimeError("disk full")}  # fmt: skip
    if outcome in errors:

        def no_build(snap: str, nd: Path) -> Any:
            raise errors[outcome]

        cfg.build = no_build
    elif outcome == "fhir":
        fhir.bad = {N2}
    else:
        cfg.promote = lambda snap: False  # a newer night came to be served while this one was published
    night2 = _night(tmp_path, "n2", [_row("D1", "2026-09-01"), _row("D2", "2026-10-01")], ["10000001", "10000002"])
    rep = run_ingest(cfg, "csv", night2, snapshot=N2, validate=False)
    assert not rep.passed and rep.held is (outcome == "refused")
    assert lakes.lake.current() == N1 and fhir.holds == N1  # one night, in both stores
    assert not _resolves(cfg, "10000002")  # F-12: the numbers of a night that is not served stay out
    record = _record(snapshot_dir(cfg.lake_dir, N2))
    if outcome in errors:
        assert fhir.calls == [N1] and record["build"] == outcome and record["fhir"] == "pending"
    else:
        assert fhir.calls == [N1, N2, N1] and record["build"] == "done" and record["pidmap"] == "pending"
    # the cause is gone: the same night is published, from the step that had not ended
    cfg.build, cfg.promote, fhir.bad = build, promote, set()
    rep = run_ingest(cfg, "csv", night2, snapshot=N2, validate=False)
    assert rep.passed and lakes.lake.current() == N2 and fhir.holds == N2 and _resolves(cfg, "10000002")


def test_a_rerun_killed_in_its_lake_step_is_put_back_from_what_it_left_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MED-2: the process is killed (SIGKILL, a container stop) inside a re-run's lake step: no Python handler
    runs. What it leaves on disk is the re-run in the served folder's place and the served one aside. The next
    publish or ingest starts from that disk state and puts it back, the FHIR store included."""
    import shutil

    from adapter.publish import recover_all

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    assert run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False
    ).passed
    served = snapshot_dir(cfg.lake_dir, N1)
    built = lakes.lake.db_path(N1).stat().st_mtime_ns
    killed_at = tmp_path / "disk-at-the-kill"

    def killed_here(snap: str, nd: Path) -> Any:
        shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)  # the disk as a kill inside this call leaves it
        raise RuntimeError("the test goes on from the copy")

    cfg.rebuild = killed_here
    rerun = _night(tmp_path, "n1b", [_row("D1", "2026-09-01"), _row("D2", "2026-09-02")])
    run_ingest(cfg, "csv", rerun, snapshot=N1, validate=False)
    shutil.rmtree(cfg.lake_dir)
    killed_at.rename(cfg.lake_dir)  # the box as the kill left it
    assert len(_conditions(served)) == 2 and (cfg.lake_dir / "ndjson-rerun" / f"{N1}.replaced").is_dir()
    fhir.holds, fhir.calls = N1 + " (the re-run)", []
    assert recover_all(cfg) == [N1]
    assert len(_conditions(served)) == 1 and (served / "passed.json").exists()  # what the served file was built from
    assert lakes.lake.db_path(N1).stat().st_mtime_ns == built
    assert fhir.calls == [served.name] and fhir.holds == served.name  # the FHIR store is back on the served night
    aside = cfg.lake_dir / "ndjson-rerun" / N1
    assert len(_conditions(aside)) == 2 and not (cfg.lake_dir / "ndjson-rerun" / f"{N1}.replaced").exists()
    assert recover_all(cfg) == []  # nothing left to do
    cfg.rebuild = lakes  # the re-run is run again and published
    assert run_ingest(cfg, "csv", rerun, snapshot=N1, validate=False).passed and len(_conditions(served)) == 2


def test_a_kill_after_the_build_ended_keeps_the_rerun_as_the_served_night(tmp_path: Path) -> None:
    """MED-2, the other side: the lake had finished the build when the process was killed. The served file is the
    re-run's, so the folder stays the re-run's too (never a served folder that the served file was not built from)."""
    import shutil

    from adapter.publish import recover_all

    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False,
                      load_fhir=False).passed  # fmt: skip
    served = snapshot_dir(cfg.lake_dir, N1)
    killed_at = tmp_path / "disk-at-the-kill"

    def killed_after(snap: str, nd: Path) -> Any:
        out = lakes(snap, nd)
        shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)
        return out

    cfg.rebuild = killed_after
    rerun = _night(tmp_path, "n1b", [_row("D1", "2026-09-01"), _row("D2", "2026-09-02")])
    assert run_ingest(cfg, "csv", rerun, snapshot=N1, validate=False, load_fhir=False).passed
    shutil.rmtree(cfg.lake_dir)
    killed_at.rename(cfg.lake_dir)
    assert (cfg.lake_dir / "ndjson-rerun" / f"{N1}.replaced").is_dir()
    assert recover_all(cfg) == [N1]
    assert len(_conditions(served)) == 2 and not (cfg.lake_dir / "ndjson-rerun" / f"{N1}.replaced").exists()


def test_an_accept_whose_end_the_console_lost_is_recorded_and_can_only_be_accepted_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HIGH-2: the adapter publishes the night but the console never reads the end (the adapter restarted, the
    answer was lost). Before: the row stayed HELD with no trace, a second accept got 404 for ever, and a reject
    was recorded while the night was served. Now the accept is in the audit and in the row before the publish
    starts, a reject is refused, and a second accept is answered "done" and records the night as published."""
    from datacore.dataops import ACCEPTING, DataOpsError
    from orchestrator.dataops_api import promoter
    from tb_common.http import ServiceError
    from tb_common.jobpoll import Poll

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    Fhir(monkeypatch)
    row = _held_night(tmp_path, cfg)
    http = _adapter(cfg, monkeypatch)
    lost = [True]

    class Orch:  # NEW-SEC-4 (D-760): the orchestrator's route, which starts the adapter's publish
        def post_raw(self, path: str, body: Any, headers: Any = None) -> Any:
            r = http.post(path.replace("/dataops/publish", "/publish"), json=body)
            if lost[0]:  # the publish ran; its answer never reached the console
                raise ServiceError("adapter", 502, "bad gateway")
            if r.status_code >= 400:
                raise ServiceError("adapter", r.status_code, r.text)
            return r

        def get_json(self, path: str) -> Any:
            return http.get(path.replace("/dataops/publish", "/publish")).json()

    class AsAdapter:  # NEW-ARCH-3 (D-761): the orchestrator's adapter client; the publish runs at the orchestrator
        def publish(self, body: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = Orch().post_raw("/publish", body).json()
            return out

        def publish_state(self, rid: str) -> dict[str, Any]:
            out: dict[str, Any] = Orch().get_json(f"/publish/{rid}")
            return out

    promote = promoter(AsAdapter(), Poll(interval=0.01, lost_after=1.0, sleep=lambda _s: None))

    audit_dir = tmp_path / "audit"
    audit = AuditLog(audit_dir)
    ops = DataOps()

    def decisions() -> list[dict[str, Any]]:
        rows = [json.loads(ln) for f in sorted(audit_dir.glob("*.jsonl")) for ln in f.read_text().splitlines()]
        return [r["detail"] for r in rows if r.get("event") == "dataops.decide"]

    try:
        with pytest.raises(RuntimeError):
            ops.decide(audit, row.id, "accept", by="steward:a", at="2026-10-02T09:00:00+08:00", reason="checked",
                       promote=promote)  # fmt: skip
        assert lakes.lake.current() == N2  # the night is served
        got = ops.batch(row.id)
        assert got is not None and got.state == HELD and got.detail["step"] == ACCEPTING
        said = decisions()
        assert [(d["decision"], d.get("phase"), d.get("outcome")) for d in said] == [
            ("accept", "started", None), ("accept", "ended", "unknown")]  # fmt: skip
        assert said[0]["shown"]  # the hold reasons the steward was shown (counts and names)
        with pytest.raises(DataOpsError, match="can no longer be rejected"):
            ops.decide(audit, row.id, "reject", by="steward:a", at="2026-10-02T09:01:00+08:00", reason="changed")
        lost[0] = False
        done = ops.decide(audit, row.id, "accept", by="steward:a", at="2026-10-02T09:05:00+08:00", reason="checked",
                          promote=promote)  # fmt: skip
        assert done.state == PUBLISHED
        assert decisions()[-1]["outcome"] == "published" and decisions()[-1]["shown"]
    finally:
        ops.close()


def test_a_publish_that_ended_without_serving_the_night_can_still_be_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orchestrator.dataops_api import promoter
    from tb_common.http import ServiceError
    from tb_common.jobpoll import Poll

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    fhir = Fhir(monkeypatch)
    row = _held_night(tmp_path, cfg)
    http = _adapter(cfg, monkeypatch)

    class Orch:  # NEW-SEC-4 (D-760): the orchestrator's route, which starts the adapter's publish
        def post_raw(self, path: str, body: Any, headers: Any = None) -> Any:
            r = http.post(path.replace("/dataops/publish", "/publish"), json=body)
            if r.status_code >= 400:
                raise ServiceError("adapter", r.status_code, r.text)
            return r

        def get_json(self, path: str) -> Any:
            return http.get(path.replace("/dataops/publish", "/publish")).json()

    class AsAdapter:  # NEW-ARCH-3 (D-761): the orchestrator's adapter client; the publish runs at the orchestrator
        def publish(self, body: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = Orch().post_raw("/publish", body).json()
            return out

        def publish_state(self, rid: str) -> dict[str, Any]:
            out: dict[str, Any] = Orch().get_json(f"/publish/{rid}")
            return out

    promote = promoter(AsAdapter(), Poll(interval=0.01, lost_after=1.0, sleep=lambda _s: None))

    audit = AuditLog(tmp_path / "audit")
    ops = DataOps()
    try:
        fhir.bad = {N2}
        with pytest.raises(RuntimeError, match="failed"):
            ops.decide(audit, row.id, "accept", by="steward:a", at="2026-10-02T09:00:00+08:00", reason="checked",
                       promote=promote)  # fmt: skip
        assert lakes.lake.current() == N1 and fhir.holds == N1
        gone = ops.decide(audit, row.id, "reject", by="steward:a", at="2026-10-02T09:02:00+08:00", reason="no")
        assert gone.state == REJECTED
    finally:
        ops.close()


def test_a_nightly_run_waits_behind_an_accept_and_is_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LOW: while a steward's accept publishes a held night, the night's own run is taken and waits (before: 409,
    which the orchestrator recorded as a failed night). A second ingest while an ingest runs is still 409."""
    from adapter import app as adapter_app
    from fastapi.testclient import TestClient

    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    monkeypatch.setattr(adapter_app, "build_config", lambda: (cfg, "csv", str(tmp_path / "none")))
    spawned: list[Any] = []
    monkeypatch.setattr(adapter_app, "_spawn", spawned.append)
    http = TestClient(adapter_app.app)
    assert adapter_app._running.acquire(blocking=False)  # an accept is publishing
    adapter_app._accepting.set()
    try:
        r = http.post("/run", json={"source": "csv"})
        assert r.status_code == 202 and r.json()["detail"] == "waiting for a publish to end"
        assert "X-TB-Run" not in r.headers
    finally:
        adapter_app._accepting.clear()
        adapter_app._running.release()
    assert len(spawned) == 1  # the run is queued behind the publish, not dropped
    rid = r.json()["run"]
    spawned[0]()  # second review, L2: the publish has ended; the queued run starts and ends (its source is missing)
    ended = http.get(f"/run/{rid}").json()
    assert ended["state"] != "running" and ended["ended"] and "waiting" not in ended["detail"]
    assert adapter_app._running.acquire(blocking=False)  # an ingest runs (no accept)
    adapter_app._runs["busy"] = {"run": "busy", "state": "running"}
    try:
        r = http.post("/run", json={"source": "csv"})
        assert r.status_code == 409
        assert r.headers["X-TB-Run"] == "busy"  # T-690: the 409 names the running ingest (PERF-008 follows it)
    finally:
        adapter_app._runs.pop("busy")
        adapter_app._running.release()


def test_a_key_rotation_keeps_the_staged_numbers_of_a_waiting_night(tmp_path: Path) -> None:
    """LOW: ``PidMap.rekey`` left the staging under the old key, so the accept of a held night published patients
    the reverse map could not resolve."""
    import os as _os

    from adapter.publish import publish_held

    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    held = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001", "10000002"])
    assert run_ingest(cfg, "csv", held, snapshot=N1, load_fhir=False, validator=_Bad()).held  # type: ignore[arg-type]
    assert _staged(cfg) == {N1: 2}
    new_key = _os.urandom(32)
    pm = cfg.pidmap()
    try:
        assert pm.rekey(new_key) == 2
    finally:
        pm.close()
    (cfg.secrets_dir / "pid_map.key").write_bytes(new_key)
    assert _staged(cfg) == {N1: 2}  # the same rows, under the new key
    assert publish_held(cfg, N1).ok
    assert _resolves(cfg, "10000001") and _resolves(cfg, "10000002") and _staged(cfg) == {}
