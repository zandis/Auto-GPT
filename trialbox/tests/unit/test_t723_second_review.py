"""T-723 (D-489), the second adversarial review (2026-11-12): what the first review's new design left open.

* H1: a night the lake serves is never reported as "nothing served" (it could be rejected while served);
* H2: a served night whose pid-map step did not end keeps its staged chart numbers, and the next run finishes it;
* H3: the FHIR store's put-back loads every resource again (a changed resource went back to nothing);
* H4: an accept the adapter refuses at once leaves an ordinary held night (it could be neither accepted nor rejected);
* M1: a reject that read the row before an accept was recorded is refused under the row's lock;
* M3, M4: what a killed re-run leaves on disk (the lake still building; between the two renames);
* L1, L3: the accept's window before its publish starts; a built night that is not served is not a "good" night.

A real lake and PostgreSQL, synthetic rows. Each state is reached by running the code to that point (a step that
fails, a copy of the disk at the kill), then resumed from what is on disk and in the database."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pidmap import PidMap
from adapter.pipeline import AdapterConfig, prune_snapshots, run_ingest
from datacore.dataops import ACCEPTING, HELD, PUBLISHED, REJECTED, DataOps, DataOpsError
from tb_common.audit import AuditLog

from tests.unit.test_dataflow_lake_p0 import _Bad, _cfg, _Lakes, _row
from tests.unit.test_t723_publish_night import (
    N1,
    N2,
    N3,
    Fhir,
    _adapter,
    _conditions,
    _fhir_cfg,
    _held_night,
    _night,
    _record,
    _resolves,
    _staged,
    _two_step,
)

AT = "2026-10-02T09:00:00+08:00"


def _promoter(http: Any, lost: list[bool] | None = None) -> Any:
    """The orchestrator's promoter over the adapter's app (NEW-ARCH-3, D-761; ``lost``: the answer to the start never
    reaches the orchestrator)."""
    from orchestrator.dataops_api import promoter
    from tb_common.http import ServiceError
    from tb_common.jobpoll import Poll

    class Adapter:
        def post_raw(self, path: str, body: Any) -> Any:
            r = http.post(path, json=body)
            if lost and lost[0]:
                raise ServiceError("adapter", 502, "bad gateway")
            if r.status_code >= 400:
                raise ServiceError("adapter", r.status_code, r.text)
            return r

        def get_json(self, path: str) -> Any:
            return http.get(path).json()

        def publish(self, body: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = self.post_raw("/publish", body).json()
            return out

        def publish_state(self, rid: str) -> dict[str, Any]:
            out: dict[str, Any] = self.get_json(f"/publish/{rid}")
            return out

    return promoter(Adapter(), Poll(interval=0.01, lost_after=1.0, sleep=lambda _s: None))


def _accept(ops: DataOps, tmp_path: Path, bid: int, promote: Any) -> Any:
    return ops.decide(AuditLog(tmp_path / "audit"), bid, "accept", by="steward:a", at=AT, reason="checked",
                      promote=promote)  # fmt: skip


def _reject(ops: DataOps, tmp_path: Path, bid: int) -> Any:
    return ops.decide(AuditLog(tmp_path / "audit"), bid, "reject", by="steward:a", at=AT, reason="no")


def _no_commit(monkeypatch: pytest.MonkeyPatch) -> Any:
    def down(self: PidMap, snap: str) -> int:
        raise ConnectionError("the pid map's database did not answer")

    real = PidMap.commit
    monkeypatch.setattr(PidMap, "commit", down)
    return real


# ------------------------------------------------------------------------------------------- H1
def test_a_served_night_whose_pid_map_step_failed_cannot_be_rejected_and_a_second_accept_ends_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    fhir = Fhir(monkeypatch)
    row = _held_night(tmp_path, cfg)
    http = _adapter(cfg, monkeypatch)
    promote = _promoter(http)
    real = _no_commit(monkeypatch)
    ops = DataOps()
    try:
        with pytest.raises(RuntimeError):
            _accept(ops, tmp_path, row.id, promote)
        assert lakes.lake.current() == N2 and fhir.holds == N2  # the night is served
        st = http.post("/publish", json={"snapshot": N2}).json()
        assert st["state"] == "failed" and st["promoted"] is True  # the adapter says what the lake serves
        got = ops.batch(row.id)
        assert got is not None and got.state == HELD and got.detail["step"] == ACCEPTING
        with pytest.raises(DataOpsError, match="can no longer be rejected"):
            _reject(ops, tmp_path, row.id)
        monkeypatch.setattr(PidMap, "commit", real)
        assert _accept(ops, tmp_path, row.id, promote).state == PUBLISHED
        assert _resolves(cfg, "10000002") and _staged(cfg) == {}
    finally:
        ops.close()


def test_a_promotion_whose_answer_is_lost_is_read_from_what_the_lake_serves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    fhir = Fhir(monkeypatch)
    row = _held_night(tmp_path, cfg)

    def answer_lost(snap: str) -> bool:
        lakes.lake.promote_built(snap)
        raise ConnectionError("the lake's answer did not arrive")

    cfg.promote = answer_lost
    ops = DataOps()
    try:
        done = _accept(ops, tmp_path, row.id, _promoter(_adapter(cfg, monkeypatch)))
        assert done.state == PUBLISHED and lakes.lake.current() == N2 and fhir.holds == N2
        assert _resolves(cfg, "10000002") and (snapshot_dir(cfg.lake_dir, N2) / "passed.json").exists()
    finally:
        ops.close()


# ------------------------------------------------------------------------------------------- H2
def test_a_served_nights_chart_numbers_survive_the_next_night_and_are_written_by_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The nightly run promotes N2 and its pid-map step fails (or the process is killed between the two: the same
    state on disk and in the database). The next night must not drop N2's staged numbers: it writes them."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    first = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", first, snapshot=N1, validate=False, load_fhir=False).passed
    real = _no_commit(monkeypatch)
    night2 = _night(tmp_path, "n2", [_row("D1", "2026-09-01"), _row("D2", "2026-10-01")], ["10000001", "10000002"])
    rep = run_ingest(cfg, "csv", night2, snapshot=N2, validate=False, load_fhir=False)
    assert not rep.passed and lakes.lake.current() == N2 and _staged(cfg) == {N2: 2}
    folder = snapshot_dir(cfg.lake_dir, N2)
    assert _record(folder)["lake"] == "done" and _record(folder)["pidmap"] == "failed"
    monkeypatch.setattr(PidMap, "commit", real)
    night3 = _night(tmp_path, "n3", [_row("D1", "2026-09-01"), _row("D3", "2026-10-02")], ["10000001", "10000003"])
    held = run_ingest(cfg, "csv", night3, snapshot=N3, load_fhir=False, validator=_Bad())  # type: ignore[arg-type]
    assert held.held and lakes.lake.current() == N2
    assert _resolves(cfg, "10000002")  # the served night's new patient can be found
    assert _staged(cfg) == {N3: 2} and not _resolves(cfg, "10000003")  # the held night's still wait
    assert _record(folder)["pidmap"] == "done" and (folder / "passed.json").exists()


# ------------------------------------------------------------------------------------------- H3
class Store:
    """A FHIR store stand-in under the real ``sync_snapshot``: what it holds by type and id; a night it refuses
    fails after everything asked for was written (a load that broke at its last resource)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from adapter import load_fhir, publish

        self.holds: dict[str, dict[str, str]] = {}
        self.bad: set[str] = set()
        monkeypatch.setattr(load_fhir, "load_snapshot", self.load)
        monkeypatch.setattr(load_fhir, "delete_refs", self.delete)
        if hasattr(publish, "verify_fhir"):  # P-03: the store's check against a night, from what it holds
            monkeypatch.setattr(publish, "verify_fhir", self.verify)

    def verify(self, cfg: Any, folder: Path, *, ids: bool = False, also: Any = ()) -> dict[str, int]:
        from adapter.load_fhir import snapshot_ids

        want = snapshot_ids(folder)
        held = {t: set(r) for t, r in self.holds.items() if r}
        if held != {t: i for t, i in want.items() if i}:
            from adapter.publish import FhirMismatch

            raise FhirMismatch(f"the store holds {sorted(held)}, the night {sorted(want)}")
        return {t: len(i) for t, i in held.items()}

    def load(self, base: str, directory: Path, workers: int = 4, only: dict[str, set[str]] | None = None) -> int:
        from adapter.load_fhir import snapshot_hashes

        n = 0
        for rtype, rows in snapshot_hashes(directory).items():
            for rid, h in rows.items():
                if only is None or rid in only.get(rtype, set()):
                    self.holds.setdefault(rtype, {})[rid] = h
                    n += 1
        if directory.name in self.bad:
            raise ValueError("the FHIR store refused a resource")
        return n

    def delete(self, base: str, refs: list[str], timeout: float = 600) -> int:
        for ref in refs:
            rtype, rid = ref.split("/", 1)
            self.holds.get(rtype, {}).pop(rid, None)
        return len(refs)

    def now(self) -> dict[str, dict[str, str]]:
        return {t: dict(r) for t, r in self.holds.items() if r}


def test_the_put_back_after_a_broken_load_restores_a_changed_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.load_fhir import snapshot_hashes

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    store = Store(monkeypatch)
    first = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", first, snapshot=N1, validate=False).passed
    served = snapshot_hashes(snapshot_dir(cfg.lake_dir, N1))
    assert store.now() == served
    # N2 changes D1 (the same id, another onset) and adds D2; the store breaks after it took both
    night2 = _night(tmp_path, "n2", [_row("D1", "2026-09-15"), _row("D2", "2026-10-01")], ["10000001"])
    store.bad = {N2}
    rep = run_ingest(cfg, "csv", night2, snapshot=N2, validate=False)
    changed = snapshot_hashes(snapshot_dir(cfg.lake_dir, N2))
    assert changed["Condition"].keys() > served["Condition"].keys()
    assert [h for i, h in changed["Condition"].items() if i in served["Condition"]] != list(
        served["Condition"].values()
    )  # the test's premise: D1 is the same resource with other content
    assert not rep.passed and lakes.lake.current() == N1
    assert store.now() == served  # every resource is the served night's again, the changed one too


# ------------------------------------------------------------------------------------------- H4
def test_an_accept_the_adapter_refuses_at_once_leaves_an_ordinary_held_night(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter import app as adapter_app

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    Fhir(monkeypatch)
    row = _held_night(tmp_path, cfg)
    again = _night(tmp_path, "n2b", [_row("D1", "2026-09-01"), _row("D8", "2026-10-01")], ["10000001", "10000002"])
    assert run_ingest(cfg, "csv", again, snapshot=N2, validator=_Bad()).held  # type: ignore[arg-type]
    promote = _promoter(_adapter(cfg, monkeypatch))
    ops = DataOps()
    try:
        older, newer = sorted((b for b in ops.held() if b.snapshot == N2), key=lambda b: b.attempt)
        assert older.id == row.id
        with pytest.raises(RuntimeError):  # 409: not the newest attempt of its night
            _accept(ops, tmp_path, older.id, promote)
        got = ops.batch(older.id)
        assert got is not None and got.state == HELD and got.detail.get("step") != ACCEPTING
        assert adapter_app._running.acquire(blocking=False)  # an ingest runs: 409, nothing started
        try:
            with pytest.raises(RuntimeError):
                _accept(ops, tmp_path, newer.id, promote)
        finally:
            adapter_app._running.release()
        got = ops.batch(newer.id)
        assert got is not None and got.state == HELD and got.detail.get("step") != ACCEPTING
        assert lakes.lake.current() == N1
        assert _reject(ops, tmp_path, older.id).state == REJECTED  # both can be decided
        assert _accept(ops, tmp_path, newer.id, promote).state == PUBLISHED and lakes.lake.current() == N2
    finally:
        ops.close()


def test_a_refused_second_accept_does_not_forget_an_accept_whose_end_is_not_known(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first accept published the night and its answer was lost (the row says ``accept:publishing``). A second
    accept that the adapter refuses at once (an ingest is running) started nothing and knows nothing new: the row
    keeps the accept, and the served night still cannot be rejected."""
    from adapter import app as adapter_app

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    Fhir(monkeypatch)
    row = _held_night(tmp_path, cfg)
    lost = [True]
    promote = _promoter(_adapter(cfg, monkeypatch), lost)
    ops = DataOps()
    try:
        with pytest.raises(RuntimeError):
            _accept(ops, tmp_path, row.id, promote)
        assert lakes.lake.current() == N2
        lost[0] = False
        assert adapter_app._running.acquire(blocking=False)
        try:
            with pytest.raises(RuntimeError):
                _accept(ops, tmp_path, row.id, promote)
        finally:
            adapter_app._running.release()
        got = ops.batch(row.id)
        assert got is not None and got.detail["step"] == ACCEPTING
        with pytest.raises(DataOpsError, match="can no longer be rejected"):
            _reject(ops, tmp_path, row.id)
        assert _accept(ops, tmp_path, row.id, promote).state == PUBLISHED
    finally:
        ops.close()


# ------------------------------------------------------------------------------------------- M1
def test_a_reject_that_read_the_row_before_the_accept_was_recorded_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    Fhir(monkeypatch)
    row = _held_night(tmp_path, cfg)
    ops = DataOps()
    try:
        stale = ops.batch(row.id)  # what the reject read
        assert stale is not None and stale.detail.get("step") != ACCEPTING

        def unknown(_b: Any) -> None:
            raise RuntimeError("the publish runs; its end is not known")

        with pytest.raises(RuntimeError):
            _accept(ops, tmp_path, row.id, unknown)
        monkeypatch.setattr(ops, "batch", lambda _id: stale)
        with pytest.raises(DataOpsError, match="can no longer be rejected"):
            _reject(ops, tmp_path, row.id)
        monkeypatch.undo()
        got = ops.batch(row.id)
        assert got is not None and got.state == HELD
    finally:
        ops.close()


# ------------------------------------------------------------------------------------------- M3, M4
def _killed_rerun(tmp_path: Path, cfg: AdapterConfig, lakes: _Lakes) -> Path:
    """N1 is served; a re-run of N1 is killed inside its lake step. Returns the served folder; the lake folder is
    the disk as the kill left it (the re-run in the served folder's place, the served one aside)."""
    assert run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False
    ).passed
    killed_at = tmp_path / "disk-at-the-kill"

    def killed_here(snap: str, nd: Path) -> Any:
        shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)
        raise RuntimeError("the test goes on from the copy")

    cfg.rebuild = killed_here
    rerun = _night(tmp_path, "n1b", [_row("D1", "2026-09-01"), _row("D2", "2026-09-02")])
    run_ingest(cfg, "csv", rerun, snapshot=N1, validate=False)
    shutil.rmtree(cfg.lake_dir)
    killed_at.rename(cfg.lake_dir)
    cfg.rebuild = lakes
    return snapshot_dir(cfg.lake_dir, N1)


def test_a_rerun_killed_while_the_lake_still_builds_is_left_alone_until_the_build_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The adapter was killed; the lake service goes on building from the folder the re-run was moved into. The
    folder must not be taken from under the build: recovery waits (the publish says "lake busy")."""
    from adapter.publish import publish_night, recover_all
    from lake.store import SnapshotBuilding, building

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    served = _killed_rerun(tmp_path, cfg, lakes)
    aside = cfg.lake_dir / "ndjson-rerun" / f"{N1}.replaced"
    fhir.calls = []
    with building(cfg.lake_dir, N1):  # the lake's build of N1 is still running
        with pytest.raises(SnapshotBuilding):
            recover_all(cfg)
        out = publish_night(cfg, N1, served)
        assert out.lake_busy and not out.ok
        assert len(_conditions(served)) == 2 and aside.is_dir() and fhir.calls == []  # nothing was moved or loaded
    assert recover_all(cfg) == [N1] and len(_conditions(served)) == 1 and not aside.exists()


def test_a_rerun_killed_between_the_two_renames_puts_the_fhir_store_back_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The served folder was moved aside and the process was killed before the re-run took its place: no served
    folder on disk, the FHIR store already loaded with the re-run (its record says so)."""
    from adapter.publish import fingerprint, read_intent, recover_all

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    served = _killed_rerun(tmp_path, cfg, lakes)
    rerun_dir = cfg.lake_dir / "ndjson-rerun" / N1
    served.rename(rerun_dir)  # the second rename had not happened
    assert _record(rerun_dir)["fhir"] == "done" and not served.exists()
    fhir.holds, fhir.calls, fhir.full, fhir.back = N1 + " (the re-run)", [], [], []
    assert recover_all(cfg) == [N1]
    assert len(_conditions(served)) == 1 and len(_conditions(rerun_dir)) == 2
    assert fhir.calls == [served.name] and fhir.full == [True] and fhir.holds == served.name
    assert fhir.back == [True]  # asked as a put-back: the ledger lets it over the load that did not end
    # the re-run's publish loads the FHIR store again: the intent names the served folder's NDJSON, not the re-run's
    # (converted, P03-DESIGN-2: whether a load is owed is read from the intent; the records' flip to "pending" is gone)
    st = read_intent(cfg) or {}
    assert st.get("verified") is True and st.get("want") == N1 and st.get("fingerprint") != fingerprint(rerun_dir)


# ------------------------------------------------------------------------------------------- L1, L3
def test_a_nightly_run_that_arrives_while_an_accept_is_being_checked_waits_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter import app as adapter_app
    from fastapi.testclient import TestClient

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    Fhir(monkeypatch)
    _held_night(tmp_path, cfg)
    spawned: list[Any] = []
    monkeypatch.setattr(adapter_app, "_spawn", spawned.append)
    http = TestClient(adapter_app.app)
    seen: list[int] = []

    def config() -> Any:
        if not seen:  # the accept reads its configuration: the night's run arrives now
            seen.append(0)
            seen.append(http.post("/run", json={"source": "csv"}).status_code)
        return cfg, "csv", str(tmp_path / "none")

    monkeypatch.setattr(adapter_app, "build_config", config)
    assert http.post("/publish", json={"snapshot": N2}).status_code == 202
    assert seen == [0, 202] and len(spawned) == 2  # the run was taken; it waits behind the publish
    spawned[1]()  # the publish
    assert lakes.lake.current() == N2 and not adapter_app._accepting.is_set()
    spawned[0]()  # then the run
    assert adapter_app._running.acquire(blocking=False)
    adapter_app._running.release()
    # an accept that is refused at once ends the wait as well
    assert http.post("/publish", json={"snapshot": "2026-10-09"}).status_code == 404
    assert not adapter_app._accepting.is_set()


def test_a_built_night_that_was_not_promoted_does_not_take_a_good_nights_place_in_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    cfg.keep_nightly, cfg.keep_month_end_months = 2, 0
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False,
                      load_fhir=False).passed  # fmt: skip
    promote = cfg.promote

    def no_answer(snap: str) -> bool:
        raise RuntimeError("the lake did not promote")

    cfg.promote = no_answer
    night2 = _night(tmp_path, "n2", [_row("D1", "2026-09-01"), _row("D2", "2026-10-01")])
    rep = run_ingest(cfg, "csv", night2, snapshot=N2, validate=False, load_fhir=False)
    assert not rep.passed and lakes.lake.current() == N1 and lakes.lake.db_path(N2).exists()
    cfg.promote = promote
    night3 = _night(tmp_path, "n3", [_row("D1", "2026-09-01"), _row("D3", "2026-10-02")])
    assert run_ingest(cfg, "csv", night3, snapshot=N3, validate=False, load_fhir=False).passed
    assert lakes.lake.current() == N3
    # two good nights are kept: N3 and N1 (before: N3 and the never served N2, and N1 was deleted). N2 is newer than
    # the oldest good night kept, so it stays for whoever resumes it (T-611), without counting
    assert snapshot_dir(cfg.lake_dir, N1).is_dir() and lakes.lake.db_path(N1).exists()
    assert prune_snapshots(cfg, date.fromisoformat(N3)) == [] and lakes.lake.db_path(N2).exists()
    assert json.loads((snapshot_dir(cfg.lake_dir, N3) / "passed.json").read_text())["snapshot"] == N3
