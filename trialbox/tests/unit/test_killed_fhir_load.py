"""E2E P-03: a night killed inside its FHIR load leaves no half-published clinical store.

The journey: a night is published; the next night's FHIR load is killed part way (the adapter's memory cap, a power
cut: no Python handler runs), so the FHIR store holds part of that night while the lake's CURRENT never moved. What
the kill leaves on disk is all the next run has. The next ingest or publish puts the FHIR store back to the served
night before it reads anything, and the killed night, run again, is published from its FHIR step. A real lake and
PostgreSQL, synthetic rows."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from adapter import publish as publish_mod
from adapter.ndjson import snapshot_dir
from adapter.pipeline import run_ingest

from tests.unit.test_dataflow_lake_p0 import _Lakes, _row
from tests.unit.test_t723_publish_night import N1, N2, Fhir, _fhir_cfg, _night, _record


def _gone() -> int:
    """The pid of a process that has ended."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_a_night_killed_in_its_fhir_load_is_put_back_to_the_served_night(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    assert run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False
    ).passed
    killed_at = tmp_path / "disk-at-the-kill"

    def killed_in_the_load(
        base: str, folder: Path, ledger: Path, previous: Path | None = None, full: bool = False, back: bool = False
    ) -> tuple[int, int]:
        if folder.name == N2 and not back:
            fhir.calls.append(folder.name)
            fhir.holds = f"part of {N2}"  # Patient and Condition in, part of the Observations
            shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)  # the disk as a kill inside the load leaves it
            raise RuntimeError("the test goes on from the copy")
        return fhir(base, folder, ledger, previous, full=full, back=back)

    monkeypatch.setattr(publish_mod, "sync_snapshot", killed_in_the_load)
    night2 = _night(tmp_path, "n2", [_row("D1", "2026-09-01"), _row("D2", "2026-10-01")], ["10000001"])
    run_ingest(cfg, "csv", night2, snapshot=N2, validate=False)
    shutil.rmtree(cfg.lake_dir)
    killed_at.rename(cfg.lake_dir)  # the box as the kill left it
    monkeypatch.setattr(publish_mod, "sync_snapshot", fhir)  # the process that comes next loads as usual
    fhir.holds = f"part of {N2}"
    folder = snapshot_dir(cfg.lake_dir, N2)
    assert lakes.lake.current() == N1 and not (folder / "passed.json").exists()
    assert _record(folder)["fhir"] == "loading"  # the record says the load began and never ended
    rec = publish_mod.read_record(folder)
    assert rec["fhir_loader"]["pid"] == os.getpid()  # the loader: this process, which a real kill takes away
    assert publish_mod.recover_all(cfg) == [] and fhir.holds == f"part of {N2}"  # a load that still runs is let be
    publish_mod._write_record(folder, {**rec, "fhir_loader": {"pid": _gone(), "start": rec["fhir_loader"]["start"]}})

    fhir.calls, fhir.back, fhir.full = [], [], []
    assert publish_mod.recover_all(cfg) == [N2]
    assert fhir.holds == N1 and fhir.calls == [N1] and fhir.back == [True] and fhir.full == [True]
    assert _record(folder)["fhir"] == "pending" and lakes.lake.current() == N1  # one night, in both stores
    assert publish_mod.recover_all(cfg) == []  # nothing left to undo

    # the killed night run again is published, its FHIR load from the start
    assert run_ingest(cfg, "csv", night2, snapshot=N2, validate=False).passed
    assert lakes.lake.current() == N2 and fhir.holds == N2
    assert set(_record(folder).values()) <= {"done", "skipped"}


def test_the_next_ingest_undoes_a_killed_load_before_it_reads_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same disk state, and the next thing that runs is an ingest that is held at the gate: the FHIR store is
    still put back to the served night, it does not wait for a night that publishes."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    assert run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False
    ).passed
    folder = snapshot_dir(cfg.lake_dir, N1).parent / N2
    shutil.copytree(snapshot_dir(cfg.lake_dir, N1), folder)
    (folder / "passed.json").unlink()
    publish_mod._write_record(folder, {"snapshot": N2, "fingerprint": "", "steps": {"build": "skipped",
                              "omop": "skipped", "fhir": "loading", "lake": "pending", "pidmap": "pending"}})  # fmt: skip
    fhir.holds, fhir.calls = f"part of {N2}", []
    rep = run_ingest(cfg, "csv", _night(tmp_path, "empty", []), snapshot=N2, validate=False)
    assert not rep.passed and lakes.lake.current() == N1
    assert fhir.calls[:1] == [N1] and fhir.holds == N1


# ------------------------------------------------------------------------------------------- the fix round's cases
def _served_n1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, _Lakes, Fhir]:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    assert run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False
    ).passed
    return cfg, lakes, fhir


def _night2(tmp_path: Path) -> str:
    return _night(tmp_path, "n2", [_row("D1", "2026-09-01"), _row("D2", "2026-10-01")], ["10000001"])


def _as_the_kill_left_it(cfg: Any, killed_at: Path) -> None:
    """The box as the kill left it: the disk copied at that moment, and the process that wrote it gone."""
    shutil.rmtree(cfg.lake_dir)
    killed_at.rename(cfg.lake_dir)
    gone = _gone()
    for f in snapshot_dir(cfg.lake_dir, N1).parent.iterdir():
        rec = publish_mod.read_record(f)
        if rec.get("fhir_loader"):
            publish_mod._write_record(f, {**rec, "fhir_loader": {**rec["fhir_loader"], "pid": gone}})


def test_a_kill_in_the_publish_s_own_put_back_is_undone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review H2: the night's lake step fails, its put-back of the FHIR store to the served night is killed half way.
    The record says the FHIR step is ``loading`` (not ``done``), so the next run puts the store back and the night's
    resume loads it again instead of promoting over a mixed store."""
    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    killed_at = tmp_path / "disk-at-the-kill"
    real_rebuild = cfg.rebuild

    def lake_fails(snap: str, nd: Path) -> Any:
        if snap == N2:
            raise RuntimeError("the lake build failed")
        return real_rebuild(snap, nd)

    def killed_in_the_put_back(base: str, folder: Path, ledger: Path, previous: Path | None = None,
                               full: bool = False, back: bool = False) -> tuple[int, int]:  # fmt: skip
        if back and folder.name == N1 and fhir.holds == N2:
            fhir.holds = f"part of {N1} over {N2}"
            shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)
            raise RuntimeError("the test goes on from the copy")
        return fhir(base, folder, ledger, previous, full=full, back=back)

    monkeypatch.setattr(cfg, "rebuild", lake_fails)
    monkeypatch.setattr(publish_mod, "sync_snapshot", killed_in_the_put_back)
    run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False)
    _as_the_kill_left_it(cfg, killed_at)
    monkeypatch.setattr(cfg, "rebuild", real_rebuild)
    monkeypatch.setattr(publish_mod, "sync_snapshot", fhir)
    fhir.holds = f"part of {N1} over {N2}"
    folder = snapshot_dir(cfg.lake_dir, N2)
    assert _record(folder)["fhir"] == "loading" and _record(folder)["lake"] == "failed"
    fhir.calls = []
    assert publish_mod.recover_all(cfg) == [N2] and fhir.holds == N1 and fhir.calls == [N1]
    assert _record(folder)["fhir"] == "pending"
    out = publish_mod.publish_night(cfg, N2, folder)  # the resume loads the FHIR store again, then promotes
    assert out.promoted and fhir.holds == N2 and lakes.lake.current() == N2


def test_a_kill_between_the_fhir_load_and_the_lake_is_undone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review M3 / P03-01: the FHIR step is done and the process is killed in the lake step: the FHIR store holds
    the night, CURRENT the one before. The next run puts the store back; the direct resume loads it again."""
    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    killed_at = tmp_path / "disk-at-the-kill"
    real_rebuild = cfg.rebuild

    def killed_in_the_lake(snap: str, nd: Path) -> Any:
        if snap == N2:
            shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)
            raise RuntimeError("the test goes on from the copy")
        return real_rebuild(snap, nd)

    monkeypatch.setattr(cfg, "rebuild", killed_in_the_lake)
    run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False)
    _as_the_kill_left_it(cfg, killed_at)
    monkeypatch.setattr(cfg, "rebuild", real_rebuild)
    fhir.holds = N2
    folder = snapshot_dir(cfg.lake_dir, N2)
    assert _record(folder)["fhir"] == "done" and _record(folder)["lake"] == "pending" and lakes.lake.current() == N1
    fhir.calls = []
    assert publish_mod.recover_all(cfg) == [N2] and fhir.holds == N1 and fhir.calls == [N1]
    assert _record(folder)["fhir"] == "pending"
    out = publish_mod.publish_night(cfg, N2, folder)
    assert out.promoted and fhir.calls == [N1, N2] and fhir.holds == N2 and lakes.lake.current() == N2


def _killed_in_its_load(tmp_path: Path, cfg: Any, fhir: Fhir, mp: pytest.MonkeyPatch, snap: str) -> Path:
    killed_at = tmp_path / "disk-at-the-kill"

    def killed(base: str, folder: Path, ledger: Path, previous: Path | None = None, full: bool = False,
               back: bool = False) -> tuple[int, int]:  # fmt: skip
        if folder.name == snap and not back:
            fhir.holds = f"part of {snap}"
            shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)
            raise RuntimeError("the test goes on from the copy")
        return fhir(base, folder, ledger, previous, full=full, back=back)

    mp.setattr(publish_mod, "sync_snapshot", killed)
    night = _night2(tmp_path) if snap == N2 else _night(tmp_path, "n1", [_row("D1", "2026-09-01")])
    run_ingest(cfg, "csv", night, snapshot=snap, validate=False)
    _as_the_kill_left_it(cfg, killed_at)
    mp.setattr(publish_mod, "sync_snapshot", fhir)
    fhir.holds, fhir.calls = f"part of {snap}", []
    return snapshot_dir(cfg.lake_dir, snap)


def test_a_failed_put_back_serves_nothing_until_it_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review M1 / P03-02: the put-back after a killed load fails (the FHIR store is down for a moment): the record
    stays ``loading`` and no publish serves a night over the half-loaded store; once the store answers, the next
    call puts it back and the night is published."""
    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    folder = _killed_in_its_load(tmp_path, cfg, fhir, monkeypatch, N2)
    fhir.down = True
    assert publish_mod.recover_all(cfg) == [] and _record(folder)["fhir"] == "loading"
    out = publish_mod.publish_night(cfg, N2, folder)
    assert not out.promoted and lakes.lake.current() == N1 and _record(folder)["fhir"] == "loading"
    assert any("not back to the served night after a killed load of 2026-10-02" in e for e in out.errors), out.errors
    fhir.down = False
    out = publish_mod.publish_night(cfg, N2, folder)
    assert out.promoted and fhir.holds == N2 and lakes.lake.current() == N2


def test_a_served_night_without_its_folder_is_a_failed_put_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review M2 / P03-03: the served night's folder is missing: nothing is put back and the record keeps saying the
    load was killed (never "undone" while the store still holds part of the night)."""
    cfg, _lakes, fhir = _served_n1(tmp_path, monkeypatch)
    folder = _killed_in_its_load(tmp_path, cfg, fhir, monkeypatch, N2)
    shutil.rmtree(snapshot_dir(cfg.lake_dir, N1))
    assert publish_mod.recover_all(cfg) == [] and fhir.calls == [] and _record(folder)["fhir"] == "loading"
    assert publish_mod.unrecovered(cfg) == [N2]


def test_a_first_night_killed_in_its_load_leaves_an_empty_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review M2 / P03-03: no night is served yet: the FHIR store is put back to nothing (every id the loader
    loaded is deleted), not left holding part of the killed night."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    folder = _killed_in_its_load(tmp_path, cfg, fhir, monkeypatch, N1)
    assert lakes.lake.current() is None and _record(folder)["fhir"] == "loading"
    assert publish_mod.recover_all(cfg) == [N1]
    assert fhir.calls == ["fhir-nothing-served"] and fhir.full == [True] and fhir.back == [True]
    assert _record(folder)["fhir"] == "pending"


def test_the_adapter_service_puts_the_store_back_when_its_ingest_process_is_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Residual 3 of r1p1a: the service waits for the night's process; killed in its FHIR load (SIGKILL: no handler
    runs in it), the service puts the FHIR store back at once, not only when the next night runs."""
    import json

    from adapter import app as adapter_app

    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    folder = snapshot_dir(cfg.lake_dir, N1).parent / N2
    shutil.copytree(snapshot_dir(cfg.lake_dir, N1), folder)
    (folder / "passed.json").unlink()
    steps = {"build": "skipped", "omop": "skipped", "fhir": "loading", "lake": "pending", "pidmap": "pending"}
    child = (
        "import os, signal\nfrom pathlib import Path\nfrom adapter import publish as p\n"
        f"p._write_record(Path({str(folder)!r}), {{'snapshot': {N2!r}, 'fingerprint': '', 'steps': {steps!r}, "
        "'fhir_loader': {'pid': os.getpid(), 'start': p._started(os.getpid())}})\n"
        "os.kill(os.getpid(), signal.SIGKILL)\n"
    )
    monkeypatch.setattr(adapter_app, "_run_command", lambda fd, spec: [sys.executable, "-c", child])
    monkeypatch.setattr(adapter_app, "build_config", lambda: (cfg, "csv", ""))
    fhir.holds, fhir.calls = f"part of {N2}", []
    state: dict[str, Any] = {"run": "runpthree", "state": "running", "started": "x", "ended": None, "detail": ""}
    adapter_app._run_in_process(state, cfg.lake_dir, {"source": "csv"})
    assert state["state"] == "failed", json.dumps(state)
    assert _record(folder)["fhir"] == "pending" and fhir.calls == [N1] and fhir.holds == N1
    assert lakes.lake.current() == N1
