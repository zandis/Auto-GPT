"""E2E P-03: a night killed inside its FHIR load leaves no half-published clinical store.

The journey: a night is published; the next night's FHIR load is killed part way (the adapter's memory cap, a power
cut: no Python handler runs), so the FHIR store holds part of that night while the lake's CURRENT never moved. What
the kill leaves on disk is all the next run has: ``<lake>/FHIR_STATE`` says ``loading``, and ``<lake>/fhir.lock`` is
free (the kernel dropped it with the process). The next ingest or publish puts the FHIR store back to the served
night before it touches any store, checks it against the night, and only then calls it ``clean``; the killed night,
run again, is published from its FHIR step. A real lake and PostgreSQL, synthetic rows; where the store's own answers
matter, a FHIR store over HTTP in a process of its own (``tests/fhir_store_stub.py``) under the real loader."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from adapter import load_fhir
from adapter import publish as publish_mod
from adapter.ndjson import snapshot_dir
from adapter.pipeline import run_ingest

from tests.unit.test_dataflow_lake_p0 import _Lakes, _row
from tests.unit.test_t723_publish_night import N1, N2, N3, Fhir, _fhir_cfg, _night, _record, _two_step

ROOT = Path(__file__).resolve().parents[2]


def _state(cfg: Any) -> dict[str, Any]:
    st: dict[str, Any] = json.loads((cfg.lake_dir / "FHIR_STATE").read_text(encoding="utf-8"))
    return st


def _put_state(cfg: Any, st: dict[str, Any]) -> None:
    """``FHIR_STATE`` as an earlier run left it."""
    (cfg.lake_dir / "FHIR_STATE").write_text(json.dumps({"version": 1, **st}), encoding="utf-8")


def _owed(night: str, target: str) -> dict[str, Any]:
    return {"state": "rollback-required", "night": night, "target": target, "reason": "the load did not end",
            "attempts": 0, "since": "2026-10-02T17:00:00+00:00", "last_error_at": "2026-10-02T17:00:00+00:00"}  # fmt: skip


def _child_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}


def _holder(cfg: Any, tmp_path: Path, state: dict[str, Any] | None = None) -> tuple[subprocess.Popen[str], Path]:
    """Another live process that holds ``fhir.lock`` (and wrote ``state`` under it) until ``release`` exists."""
    release = tmp_path / "release"
    script = (
        "import fcntl, json, os, time\nfrom pathlib import Path\n"
        f"fd = os.open({str(cfg.lake_dir / 'fhir.lock')!r}, os.O_RDWR | os.O_CREAT)\nfcntl.flock(fd, fcntl.LOCK_EX)\n"
        + (f"Path({str(cfg.lake_dir / 'FHIR_STATE')!r}).write_text(json.dumps({state!r}))\n" if state else "")
        + f"print('held', flush=True)\nwhile not Path({str(release)!r}).exists():\n    time.sleep(0.01)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    assert child.stdout is not None and child.stdout.readline().strip() == "held"
    return child, release


class Stub:
    """The FHIR store over HTTP (``tests/fhir_store_stub.py``)."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.fhir = f"{root}/fhir"

    def log(self) -> list[str]:
        out: list[str] = httpx.get(f"{self.root}/_log", timeout=30).json()
        return out

    def ids(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = httpx.get(f"{self.root}/_ids", timeout=30).json()
        return out

    def control(self, **ctl: Any) -> None:
        httpx.post(f"{self.root}/_control", json=ctl, timeout=30).raise_for_status()

    def seed(self, resources: list[dict[str, Any]]) -> None:
        httpx.post(f"{self.root}/_seed", json=resources, timeout=30).raise_for_status()


@pytest.fixture
def stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Stub]:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    port = tmp_path / "stub.port"
    proc = subprocess.Popen([sys.executable, str(ROOT / "tests" / "fhir_store_stub.py"), str(port)])
    try:
        for _ in range(1000):
            if port.exists():
                break
            time.sleep(0.01)
        yield Stub(f"http://127.0.0.1:{port.read_text(encoding='utf-8')}")
    finally:
        proc.kill()
        proc.wait()


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
    st = _state(cfg)
    assert st["state"] == "loading" and st["night"] == N2 and st["target"] == N1
    assert st["by"]["pid"] == os.getpid()  # the loader: this process, which a real kill takes away
    with publish_mod.fhir_lock(cfg, wait=False), pytest.raises(publish_mod.RecoveryBusy):
        publish_mod.recover_all(cfg)  # a load that still runs (it holds the lock) is let be
    assert fhir.holds == f"part of {N2}" and _state(cfg)["state"] == "loading"

    fhir.calls, fhir.back, fhir.full = [], [], []
    assert publish_mod.recover_all(cfg) == []  # no re-run was swapped: the FHIR store's state is in FHIR_STATE
    assert fhir.holds == N1 and fhir.calls == [N1] and fhir.back == [True] and fhir.full == [True]
    assert _record(folder)["fhir"] == "pending" and lakes.lake.current() == N1  # one night, in both stores
    assert _state(cfg)["state"] == "clean" and _state(cfg)["night"] == N1
    assert publish_mod.recover_all(cfg) == [] and fhir.calls == [N1]  # nothing left to undo

    # the killed night run again is published, its FHIR load from the start
    assert run_ingest(cfg, "csv", night2, snapshot=N2, validate=False).passed
    assert lakes.lake.current() == N2 and fhir.holds == N2
    assert set(_record(folder).values()) <= {"done", "skipped"}
    assert _state(cfg)["state"] == "clean" and _state(cfg)["night"] == N2


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
    _put_state(cfg, {"state": "loading", "night": N2, "target": N1, "previous": N1, "by": {"pid": 0},
                     "since": "2026-10-02T17:00:00+00:00"})  # fmt: skip
    fhir.holds, fhir.calls = f"part of {N2}", []
    after: list[dict[str, str]] = []  # the record as the put-back left it (the ingest then writes the folder anew)
    real_restore = publish_mod.restore_fhir

    def restore(c: Any) -> None:
        real_restore(c)
        after.append(_record(folder))

    monkeypatch.setattr(publish_mod, "restore_fhir", restore)
    rep = run_ingest(cfg, "csv", _night(tmp_path, "empty", []), snapshot=N2, validate=False)
    assert not rep.passed and lakes.lake.current() == N1
    assert fhir.calls[:1] == [N1] and fhir.holds == N1
    assert _state(cfg)["state"] == "clean" and after[0]["fhir"] == "pending"  # review L1 (T14)


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
    """The box as the kill left it: the disk copied at that moment (the process that wrote it, and with it its hold
    of ``fhir.lock``, gone)."""
    shutil.rmtree(cfg.lake_dir)
    killed_at.rename(cfg.lake_dir)


def _copy_night(cfg: Any, snap: str) -> Path:
    """The served night's NDJSON as an unpublished night ``snap``."""
    folder = snapshot_dir(cfg.lake_dir, N1).parent / snap
    shutil.copytree(snapshot_dir(cfg.lake_dir, N1), folder)
    for name in ("passed.json", "publish.json"):
        (folder / name).unlink(missing_ok=True)
    return folder


def test_a_kill_in_the_publish_s_own_put_back_is_undone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review H2: the night's lake step fails, its put-back of the FHIR store to the served night is killed half way.
    ``FHIR_STATE`` says ``restoring``, so the next run puts the store back and the night's resume loads it again
    instead of promoting over a mixed store."""
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
    assert _state(cfg)["state"] == "restoring" and _state(cfg)["target"] == N1 and _record(folder)["lake"] == "failed"
    fhir.calls = []
    assert publish_mod.recover_all(cfg) == [] and fhir.holds == N1 and fhir.calls == [N1]
    assert _record(folder)["fhir"] == "pending" and _state(cfg)["state"] == "clean"
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
    assert _state(cfg)["state"] == "loading"  # the store is not clean until the night is served and checked
    fhir.calls = []
    assert publish_mod.recover_all(cfg) == [] and fhir.holds == N1 and fhir.calls == [N1]
    assert _record(folder)["fhir"] == "pending" and _state(cfg)["state"] == "clean"
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
    fhir.holds, fhir.calls, fhir.back, fhir.full = f"part of {snap}", [], [], []
    return snapshot_dir(cfg.lake_dir, snap)


def test_a_failed_put_back_serves_nothing_until_it_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review M1 / P03-02: the put-back after a killed load fails (the FHIR store is down for a moment): the marker
    stays and no publish serves a night over the half-loaded store; once the store answers, the next call puts it
    back and the night is published."""
    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    folder = _killed_in_its_load(tmp_path, cfg, fhir, monkeypatch, N2)
    fhir.down = True
    with pytest.raises(publish_mod.FhirRestoreOutstanding):
        publish_mod.recover_all(cfg)
    assert _record(folder)["fhir"] == "loading" and _state(cfg)["state"] == "rollback-required"
    out = publish_mod.publish_night(cfg, N2, folder)
    assert not out.promoted and lakes.lake.current() == N1 and _record(folder)["fhir"] == "loading"
    assert any(f"not back to {N1} after the load of 2026-10-02" in e for e in out.errors), out.errors
    fhir.down = False
    out = publish_mod.publish_night(cfg, N2, folder)
    assert out.promoted and fhir.holds == N2 and lakes.lake.current() == N2


def test_a_served_night_without_its_folder_is_a_failed_put_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review M2 / P03-03: the served night's folder is missing: nothing is put back and the marker keeps saying the
    put-back is owed (never "undone" while the store still holds part of the night)."""
    cfg, _lakes, fhir = _served_n1(tmp_path, monkeypatch)
    folder = _killed_in_its_load(tmp_path, cfg, fhir, monkeypatch, N2)
    shutil.rmtree(snapshot_dir(cfg.lake_dir, N1))
    with pytest.raises(publish_mod.FhirRestoreOutstanding):
        publish_mod.recover_all(cfg)
    assert fhir.calls == [] and _record(folder)["fhir"] == "loading"
    assert _state(cfg)["state"] == "rollback-required" and _state(cfg)["night"] == N2


def test_a_first_night_killed_in_its_load_leaves_an_empty_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review M2 / P03-03: no night is served yet: the FHIR store is put back to nothing (every id the loader
    loaded is deleted), not left holding part of the killed night. The real loader's deletes: T5 and T8."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    folder = _killed_in_its_load(tmp_path, cfg, fhir, monkeypatch, N1)
    assert lakes.lake.current() is None and _record(folder)["fhir"] == "loading"
    assert publish_mod.recover_all(cfg) == []
    assert fhir.calls == ["fhir-nothing-served"] and fhir.full == [True] and fhir.back == [True]
    assert _record(folder)["fhir"] == "pending"
    assert _state(cfg)["state"] == "clean" and _state(cfg)["night"] == ""


def test_the_adapter_service_puts_the_store_back_when_its_ingest_process_is_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Residual 3 of r1p1a: the service waits for the night's process; killed in its FHIR load (SIGKILL: no handler
    runs in it, and the kernel drops its fhir.lock), the service puts the FHIR store back at once, not only when the
    next night runs."""
    from adapter import app as adapter_app

    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    folder = snapshot_dir(cfg.lake_dir, N1).parent / N2
    shutil.copytree(snapshot_dir(cfg.lake_dir, N1), folder)
    (folder / "passed.json").unlink()
    steps = {"build": "skipped", "omop": "skipped", "fhir": "loading", "lake": "pending", "pidmap": "pending"}
    loading = {"version": 1, "state": "loading", "night": N2, "target": N1, "previous": N1, "since": "x"}
    child = (
        "import fcntl, json, os, signal\nfrom pathlib import Path\nfrom adapter import publish as p\n"
        f"fd = os.open({str(cfg.lake_dir / 'fhir.lock')!r}, os.O_RDWR | os.O_CREAT)\nfcntl.flock(fd, fcntl.LOCK_EX)\n"
        f"Path({str(cfg.lake_dir / 'FHIR_STATE')!r}).write_text(json.dumps({{**{loading!r}, 'by': {{'pid': os.getpid()}}}}))\n"
        f"p._write_record(Path({str(folder)!r}), {{'snapshot': {N2!r}, 'fingerprint': '', 'steps': {steps!r}}})\n"
        "os.kill(os.getpid(), signal.SIGKILL)\n"
    )  # fmt: skip
    monkeypatch.setattr(adapter_app, "_run_command", lambda fd, spec: [sys.executable, "-c", child])
    monkeypatch.setattr(adapter_app, "build_config", lambda: (cfg, "csv", ""))
    fhir.holds, fhir.calls = f"part of {N2}", []
    state: dict[str, Any] = {"run": "runpthree", "state": "running", "started": "x", "ended": None, "detail": ""}
    adapter_app._run_in_process(state, cfg.lake_dir, {"source": "csv"})
    assert state["state"] == "failed", json.dumps(state)
    assert _record(folder)["fhir"] == "pending" and fhir.calls == [N1] and fhir.holds == N1
    assert lakes.lake.current() == N1 and _state(cfg)["state"] == "clean" and _state(cfg)["night"] == N1


# ------------------------------------------------------------------------------------------- P03-DESIGN §7, T1-T13
def test_two_recoverers_only_one_restores(tmp_path: Path, stub: Stub) -> None:
    """T1 (reviews R1, N2): two processes find the same owed put-back at the same moment. One takes fhir.lock and
    puts the store back; the other is refused before it sends anything."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    cfg.fhir_base_url = stub.fhir
    assert run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"]), snapshot=N1, validate=False
    ).passed
    held = stub.ids()
    assert held.get("Condition") and _state(cfg)["state"] == "clean"
    _put_state(cfg, _owed(N2, N1))
    stub.control(sleep=0.2)
    before = len(stub.log())
    go = tmp_path / "go"
    script = (
        "import os, time\nfrom pathlib import Path\nfrom adapter import publish as p\n"
        "from adapter.pipeline import AdapterConfig\n"
        f"cfg = AdapterConfig(lake_dir=Path({str(cfg.lake_dir)!r}), secrets_dir=Path({str(cfg.secrets_dir)!r}), "
        f"mapping_path=Path({str(cfg.mapping_path)!r}), site_id='T', fhir_base_url={stub.fhir!r})\n"
        f"Path({str(tmp_path)!r}, 'ready-' + str(os.getpid())).touch()\n"
        f"while not Path({str(go)!r}).exists():\n    time.sleep(0.002)\n"
        "try:\n    p.recover_all(cfg)\n    print('RESTORED')\nexcept p.RecoveryBusy:\n    print('BUSY')\n"
    )
    kids = [
        subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True, env=_child_env())
        for _ in range(2)
    ]
    for _ in range(3000):
        if len(list(tmp_path.glob("ready-*"))) == 2:
            break
        time.sleep(0.01)
    go.touch()
    said = sorted(k.communicate(timeout=300)[0].strip() for k in kids)
    assert said == ["BUSY", "RESTORED"], said
    st = _state(cfg)
    assert st["state"] == "clean" and st["night"] == N1
    sent = stub.log()[before:]
    types = sorted(p.stem for p in snapshot_dir(cfg.lake_dir, N1).glob("*.ndjson"))
    # one put-back: a bundle per type and its check, each once; a second writer would have sent each again
    assert len(sent) == len(set(sent)) and sorted(s for s in sent if s.startswith("POST")) == sorted(
        f"POST {len(load_fhir.snapshot_ids(snapshot_dir(cfg.lake_dir, N1))[t])} PUT {t}" for t in types
    ), sent
    assert stub.ids() == held


def test_a_publish_is_refused_while_a_recovery_holds_the_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T2 (review R1): another live process holds fhir.lock: the publish is refused before it reads or writes
    anything; once the lock is free, the same call promotes."""
    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    folder = _copy_night(cfg, N2)
    holder, release = _holder(cfg, tmp_path)
    fhir.calls = []
    try:
        out = publish_mod.publish_night(cfg, N2, folder, last_good=N1)
        assert out.lake_busy and out.errors == [publish_mod.FHIR_BUSY_ERROR] and not out.promoted
        assert set(out.steps.values()) == {"pending"} and not (folder / "publish.json").exists()
        assert fhir.calls == [] and lakes.lake.current() == N1
    finally:
        release.touch()
        holder.wait()
    out = publish_mod.publish_night(cfg, N2, folder, last_good=N1)
    assert out.promoted and lakes.lake.current() == N2 and fhir.holds == N2 and _state(cfg)["night"] == N2


def test_a_failed_in_process_put_back_keeps_rollback_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T3 (reviews R2, N1): N2's promotion fails and the publish's own put-back to N1 fails too. The marker says the
    put-back is owed (the step may say failed); the next publish of another night is refused by that name before
    the lake builds it or OMOP takes it."""
    from adapter import dual_write

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    _two_step(cfg, lakes)
    fhir = Fhir(monkeypatch)
    assert run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False
    ).passed
    real_promote = cfg.promote
    assert real_promote is not None

    def promote(snap: str, *generation: str) -> bool:
        if snap == N2:
            raise RuntimeError("the promotion failed")
        return bool(real_promote(snap, *generation))

    def put_back_fails(c: Any, folder: Path) -> tuple[int, int]:
        raise ConnectionError("the FHIR store did not answer")

    monkeypatch.setattr(cfg, "promote", promote)
    monkeypatch.setattr(publish_mod, "_fhir_put_back", put_back_fails)
    rep = run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False)
    st = _state(cfg)
    assert st["state"] == "rollback-required" and st["night"] == N2 and st["target"] == N1, st
    assert st["attempts"] == 1 and st["reason"] and fhir.holds == N2  # the store still holds N2, as the marker says
    assert _record(snapshot_dir(cfg.lake_dir, N2))["fhir"] == "failed" and lakes.lake.current() == N1
    assert not rep.passed and any(e.startswith("fhir_restore_outstanding") for e in rep.errors or [])
    built: list[str] = []
    omop: list[str] = []
    real_build = cfg.build
    assert real_build is not None

    def build(snap: str, nd: Path) -> Any:
        built.append(snap)
        return real_build(snap, nd)

    monkeypatch.setattr(cfg, "build", build)
    monkeypatch.setattr(dual_write, "load_night", lambda c, s, nd: omop.append(s))
    out = publish_mod.publish_night(cfg, N3, _copy_night(cfg, N3), last_good=N1)
    assert (
        out.fhir_outstanding.startswith("fhir_restore_outstanding")
        and f"after the load of {N2}" in out.fhir_outstanding
    )
    assert out.errors == [out.fhir_outstanding] and built == [] and omop == [] and not out.promoted
    assert _state(cfg)["state"] == "rollback-required" and _state(cfg)["attempts"] == 2


def test_an_ingest_without_a_fhir_endpoint_keeps_the_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T4 (review R3): an owed put-back and no FHIR endpoint configured: the night goes on and says the put-back is
    still owed; the marker is not touched. With the endpoint back, the next recovery puts the store back."""
    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    _put_state(cfg, _owed(N2, N1))
    before = (cfg.lake_dir / "FHIR_STATE").read_bytes()
    url, cfg.fhir_base_url = cfg.fhir_base_url, None
    fhir.calls = []
    night3 = _night(tmp_path, "n3", [_row("D1", "2026-09-01"), _row("D3", "2026-10-02")])
    rep = run_ingest(cfg, "csv", night3, snapshot=N3, validate=False)
    said = [e for e in rep.errors or [] if e.startswith("fhir_restore_outstanding")]
    assert len(said) == 1 and f"after the load of {N2}" in said[0] and "no FHIR endpoint is configured" in said[0]
    assert (cfg.lake_dir / "FHIR_STATE").read_bytes() == before and fhir.calls == []
    report = json.loads((snapshot_dir(cfg.lake_dir, N3) / "ingest_report.json").read_text(encoding="utf-8"))
    assert said[0] in report["errors"]
    served = lakes.lake.current()
    cfg.fhir_base_url = url
    publish_mod.recover_all(cfg)
    assert fhir.calls == [served] and fhir.holds == served
    assert _state(cfg)["state"] == "clean" and _state(cfg)["night"] == served


def test_first_publish_rollback_empties_the_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub: Stub) -> None:
    """T5 (reviews R4, N4, N6): the first night of a box loads the FHIR store and its promotion fails. The store is
    put back to nothing with the real loader; a file left in the empty folder is not loaded as the "empty" night."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    cfg.fhir_base_url = stub.fhir
    _two_step(cfg, lakes)
    stray = cfg.lake_dir / "tmp" / "fhir-nothing-served" / "Patient.ndjson"
    loaded: dict[str, list[str]] = {}

    def promote(snap: str, *generation: str) -> bool:
        loaded.update(stub.ids())
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_text(json.dumps({"resourceType": "Patient", "id": "stray-1"}) + "\n", encoding="utf-8")
        raise RuntimeError("the promotion failed")

    monkeypatch.setattr(cfg, "promote", promote)
    night = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    rep = run_ingest(cfg, "csv", night, snapshot=N1, validate=False)
    assert not rep.passed and lakes.lake.current() is None
    assert loaded.get("Condition") and loaded.get("Patient")  # the load reached the store
    assert stub.ids() == {} and not stray.exists()  # nothing of the night stays, the stray file was never loaded
    st = _state(cfg)
    assert st["state"] == "clean" and st["night"] == ""
    assert _record(snapshot_dir(cfg.lake_dir, N1))["fhir"] == "pending"


def test_a_missing_served_folder_blocks_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T6 (review R4): the served night's folder is missing: nothing is sent, and the refusal names why."""
    cfg, _lakes, fhir = _served_n1(tmp_path, monkeypatch)
    _killed_in_its_load(tmp_path, cfg, fhir, monkeypatch, N2)
    shutil.rmtree(snapshot_dir(cfg.lake_dir, N1))
    with pytest.raises(publish_mod.FhirRestoreOutstanding, match="folder missing"):
        publish_mod.recover_all(cfg)
    st = _state(cfg)
    assert st["state"] == "rollback-required" and "folder missing" in st["reason"] and fhir.calls == []


def test_a_failed_recovery_blocks_the_next_ingest_before_omop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T7 (review R5): a killed load, and the store down when the next night runs (as the box runs it: its own
    process, ``adapter.run_job``): the run is refused by the owed put-back's name, before OMOP or the lake."""
    import lake.build
    import tb_common.logging
    from adapter import cli, dual_write, run_job, runs

    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    _killed_in_its_load(tmp_path, cfg, fhir, monkeypatch, N2)
    fhir.down = True
    omop: list[str] = []
    monkeypatch.setattr(dual_write, "load_night", lambda c, s, nd: omop.append(s))
    monkeypatch.setattr(cli, "build_config", lambda: (cfg, "csv", ""))
    monkeypatch.setattr(tb_common.logging, "setup_logging", lambda service, level="INFO": None)
    monkeypatch.setattr(lake.build, "prefer_me_when_memory_runs_out", lambda: None)
    lakes.calls.clear()
    lock = runs.RunLock(cfg.lake_dir)
    state = {"run": "pthree7", "state": "running", "started": "2026-10-04T17:00:00+00:00", "ended": None, "detail": ""}
    runs.hold(cfg.lake_dir, "pthree7")
    runs.write(cfg.lake_dir, state)
    fd = os.dup(lock.fileno())
    lock.hand_over()
    night3 = _night(tmp_path, "n3", [_row("D1", "2026-09-01"), _row("D3", "2026-10-02")])
    req = {"source": "csv", "path": night3, "since": None, "snapshot": N3, "load_fhir": True, "rebuild_lake": True,
           "validate": False}  # fmt: skip
    assert run_job.main([str(fd), json.dumps({"state": state, "lake_dir": str(cfg.lake_dir), "request": req})]) == 0
    end = runs.read(cfg.lake_dir, "pthree7")
    assert end is not None and end["state"] == "refused", end
    assert str(end["detail"]).startswith("fhir_restore_outstanding") and f"after the load of {N2}" in end["detail"]
    assert omop == [] and lakes.calls == [] and lakes.lake.current() == N1


def test_empty_baseline_put_back_deletes_every_ledger_id(tmp_path: Path, stub: Stub) -> None:
    """T8 (reviews R6, N4): the real loader's partial load of a first night, then the put-back to nothing: every id
    the ledger knows is deleted from the store (no "empty folder, delete nothing" guard), and the check passes."""
    cfg = _fhir_cfg(tmp_path, _Lakes(tmp_path / "lake"))
    cfg.fhir_base_url = stub.fhir
    run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N1, load_fhir=False, rebuild_lake=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, N1)
    assert publish_mod._current(cfg.lake_dir) is None
    with publish_mod.fhir_lock(cfg, wait=False):
        publish_mod._write_state(cfg, {"state": "loading", "night": N1, "target": "", "previous": None, "by": {},
                                       "since": "2026-10-01T17:00:00+00:00"})  # fmt: skip
        stub.control(fail_after=2)  # the load breaks after two of its bundles are in
        with pytest.raises(RuntimeError, match="transaction failed"):
            publish_mod._sync_fhir(cfg, folder, None)
        partial = stub.ids()
        assert len(partial) == 2, partial
        stub.control(fail_after=None)
        publish_mod.restore_fhir(cfg)
    assert stub.ids() == {}
    every = set(load_fhir.snapshot_ids(folder))
    assert publish_mod.verify_fhir(cfg, publish_mod._empty_night(cfg), also=every) == dict.fromkeys(sorted(every), 0)
    st = _state(cfg)
    assert st["state"] == "clean" and st["night"] == ""


def test_service_recovery_swaps_back_before_the_fhir_put_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T9 (review N3): a re-run of the served night killed in its lake step, after the swap. The service's recovery
    puts the served folder back first, so the FHIR store goes back to the served night's own NDJSON."""
    from adapter import app as adapter_app
    from adapter.pipeline import RERUN_DIR

    cfg, _lakes, fhir = _served_n1(tmp_path, monkeypatch)
    served = snapshot_dir(cfg.lake_dir, N1)
    original = publish_mod.fingerprint(served)
    killed_at = tmp_path / "disk-at-the-kill"
    real_rebuild = cfg.rebuild

    def killed_in_the_lake(snap: str, nd: Path) -> Any:
        if (cfg.lake_dir / RERUN_DIR / f"{N1}.replaced").exists():
            shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)
            raise RuntimeError("the test goes on from the copy")
        return real_rebuild(snap, nd)

    monkeypatch.setattr(cfg, "rebuild", killed_in_the_lake)
    rerun = _night(tmp_path, "n1b", [_row("D1", "2026-09-01"), _row("D9", "2026-09-03")])
    run_ingest(cfg, "csv", rerun, snapshot=N1, validate=False)
    assert killed_at.is_dir()
    _as_the_kill_left_it(cfg, killed_at)
    monkeypatch.setattr(cfg, "rebuild", real_rebuild)
    assert _state(cfg)["state"] == "loading" and (cfg.lake_dir / RERUN_DIR / f"{N1}.replaced").is_dir()
    assert publish_mod.fingerprint(served) != original  # the re-run is in the served folder's place
    order: list[str] = []
    real_recover, real_put_back = publish_mod._recover, publish_mod._fhir_put_back

    def recover(c: Any, snap: str, aside: Path) -> str:
        order.append("swap back")
        return real_recover(c, snap, aside)

    def put_back(c: Any, folder: Path) -> tuple[int, int]:
        order.append(f"put back the {'served' if publish_mod.fingerprint(folder) == original else 're-run'} NDJSON")
        return real_put_back(c, folder)

    monkeypatch.setattr(publish_mod, "_recover", recover)
    monkeypatch.setattr(publish_mod, "_fhir_put_back", put_back)
    monkeypatch.setattr(adapter_app, "build_config", lambda: (cfg, "csv", ""))
    assert adapter_app._undo_killed_load() == ""
    assert order == ["swap back", "put back the served NDJSON"]
    assert fhir.holds == N1 and publish_mod.fingerprint(served) == original and _state(cfg)["state"] == "clean"
    assert _record(cfg.lake_dir / RERUN_DIR / N1)["fhir"] == "pending"


def test_a_live_loader_is_never_taken_for_killed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T10 (review N5): a load that runs in another process holds fhir.lock; ``/proc`` is unreadable here. It is
    never taken for a killed one: liveness is the lock, not a pid."""
    cfg, _lakes, fhir = _served_n1(tmp_path, monkeypatch)
    loading = {"version": 1, "state": "loading", "night": N2, "target": N1, "previous": N1, "by": {"pid": 1},
               "since": "2026-10-02T17:00:00+00:00"}  # fmt: skip
    holder, release = _holder(cfg, tmp_path, loading)
    real_read_text = Path.read_text

    def no_proc(self: Path, *args: Any, **kwargs: Any) -> str:
        if str(self).startswith("/proc/"):
            raise PermissionError(str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", no_proc)
    fhir.calls = []
    try:
        with pytest.raises(publish_mod.RecoveryBusy):
            publish_mod.recover_all(cfg)
        assert _state(cfg)["state"] == "loading" and fhir.calls == []
    finally:
        release.touch()
        holder.wait()


def test_an_upgraded_box_without_a_marker_verifies_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub: Stub
) -> None:
    """T11 (review N5): a box from before FHIR_STATE, whose old version was killed in a load (one more Patient in
    the store, its id in the widened ledger). The first recovery checks the store against the served night, finds
    it is not, puts it back and calls it clean; the next does not check again."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    cfg.fhir_base_url = stub.fhir
    night = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", night, snapshot=N1, validate=False).passed
    n1 = stub.ids()
    assert len(n1["Patient"]) == 1
    (cfg.lake_dir / "FHIR_STATE").unlink()
    stub.seed([{"resourceType": "Patient", "id": "p-killed-load"}])
    with (cfg.lake_dir / "fhir_ledger" / "Patient.txt").open("a", encoding="utf-8") as fh:
        fh.write("p-killed-load\t\n")
    written: list[dict[str, Any]] = []
    real = publish_mod._write_state

    def spy(c: Any, st: dict[str, Any]) -> dict[str, Any]:
        written.append(dict(st))
        return real(c, st)

    monkeypatch.setattr(publish_mod, "_write_state", spy)
    publish_mod.recover_all(cfg)
    assert [w["state"] for w in written] == ["rollback-required", "restoring", "clean"], written
    assert "Patient: store 2, night 1" in written[0]["reason"]
    assert stub.ids() == n1 and _state(cfg)["state"] == "clean" and _state(cfg)["night"] == N1
    written.clear()
    publish_mod.recover_all(cfg)
    assert written == []


def test_a_put_back_whose_verify_fails_keeps_the_marker(tmp_path: Path, stub: Stub) -> None:
    """T12 (design §3): the store answers a DELETE and does not do it. The put-back's check finds the Patient left:
    the marker stays, with the count in its reason."""
    cfg = _fhir_cfg(tmp_path, _Lakes(tmp_path / "lake"))
    cfg.fhir_base_url = stub.fhir
    run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N1, load_fhir=False, rebuild_lake=False, validate=False)
    with publish_mod.fhir_lock(cfg, wait=False):
        publish_mod._write_state(cfg, {"state": "loading", "night": N1, "target": "", "previous": None, "by": {},
                                       "since": "2026-10-01T17:00:00+00:00"})  # fmt: skip
        publish_mod._sync_fhir(cfg, snapshot_dir(cfg.lake_dir, N1), None)  # the whole night in, none served
        (patient,) = stub.ids()["Patient"]
        stub.control(drop=[f"Patient/{patient}"])
        with pytest.raises(publish_mod.FhirRestoreOutstanding, match="Patient: store 1, night 0"):
            publish_mod.restore_fhir(cfg)
    st = _state(cfg)
    assert st["state"] == "rollback-required" and st["reason"] == "Patient: store 1, night 0" and st["attempts"] == 1


def _labs_night(tmp_path: Path, n: int) -> str:
    path = Path(_night2(tmp_path))
    with (path / "lab.csv").open("w", encoding="utf-8", newline="") as fh:
        fh.write("lab_no,mrn,local_code,item_name,result_value,unit,sample_datetime\n")
        for i in range(n):
            fh.write(f"L{i:05d},10000001,CRE,Creatinine,1.{i % 10},mg/dL,2026-09-{1 + i % 28:02d}T08:00:00\n")
    return str(path)


def test_kill_9_mid_observation_load(tmp_path: Path, stub: Stub) -> None:
    """T13 (P-03, RC2 acceptance): N1 is served; N2 is run in a process of its own, which the store SIGKILLs after
    100 of N2's Observations are in. Right after: FHIR_STATE ``loading``, CURRENT N1, fhir.lock free. The next
    recovery leaves the store as it was before the night, CURRENT N1, no N2 report, no hold, the marker clean; N2
    run again is published and the store holds N2."""
    from lake.store import held_snapshots

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    cfg.fhir_base_url = stub.fhir
    night1 = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", night1, snapshot=N1, validate=False).passed
    before = stub.ids()
    night2 = _labs_night(tmp_path, 1000)
    script = (
        "import sys\nfrom pathlib import Path\nfrom adapter import load_fhir\nfrom adapter.pipeline import run_ingest\n"
        "from tests.unit.test_dataflow_lake_p0 import _Lakes\nfrom tests.unit.test_t723_publish_night import _fhir_cfg\n"
        f"tmp = Path({str(tmp_path)!r})\ncfg = _fhir_cfg(tmp, _Lakes(tmp / 'lake'))\ncfg.fhir_base_url = {stub.fhir!r}\n"
        "load_fhir.BATCH = 50  # bundles small enough that the kill falls between two of them\n"
        "print('ready', flush=True)\nsys.stdin.readline()\n"
        f"run_ingest(cfg, 'csv', {night2!r}, snapshot={N2!r}, validate=False)\nprint('ended', flush=True)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                             cwd=ROOT, env=_child_env())  # fmt: skip
    assert child.stdout is not None and child.stdin is not None
    assert child.stdout.readline().strip() == "ready"
    stub.control(kill={"pid": child.pid, "type": "Observation", "after": 100})
    child.stdin.write("\n")
    child.stdin.flush()
    said, _ = child.communicate(timeout=600)
    assert child.returncode == -signal.SIGKILL and "ended" not in said
    assert [s for s in stub.log() if s.startswith("KILL")] == [f"KILL {child.pid}"]
    st = _state(cfg)
    assert st["state"] == "loading" and st["night"] == N2 and st["target"] == N1, st
    assert lakes.lake.current() == N1
    assert 100 <= len(stub.ids().get("Observation", [])) < 1000  # part of the night's Observations are in
    with publish_mod.fhir_lock(cfg, wait=False):
        pass  # the kill took the lock with it
    publish_mod.recover_all(cfg)
    assert stub.ids() == before and lakes.lake.current() == N1
    assert not (snapshot_dir(cfg.lake_dir, N2) / "ingest_report.json").exists()
    assert held_snapshots(cfg.lake_dir) == {}
    assert _state(cfg)["state"] == "clean" and _state(cfg)["night"] == N1
    assert run_ingest(cfg, "csv", night2, snapshot=N2, validate=False).passed
    assert lakes.lake.current() == N2
    want = load_fhir.snapshot_ids(snapshot_dir(cfg.lake_dir, N2))
    assert stub.ids() == {t: sorted(i) for t, i in want.items() if i}
    assert _state(cfg)["state"] == "clean" and _state(cfg)["night"] == N2
