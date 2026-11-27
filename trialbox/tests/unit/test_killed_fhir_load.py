"""E2E P-03: a night killed inside its FHIR load leaves no half-published clinical store.

The journey: a night is published; the next night's FHIR load is killed part way (the adapter's memory cap, a power
cut: no Python handler runs), so the FHIR store holds part of that night while the lake's CURRENT never moved. What
the kill leaves on disk is all the next run has: ``<lake>/FHIR_STATE`` says ``loading``, and ``<lake>/fhir.lock`` is
free (the kernel dropped it with the process). The next ingest or publish puts the FHIR store back to the served
night before it touches any store, checks it against the night, and only then calls it ``clean``; the killed night,
run again, is published from its FHIR step. A load killed while one of its transactions may still be out is the one
kill the box does not put back by itself (review H4, a known limitation): it is refused by name until the operator's
exit. A real lake and PostgreSQL, synthetic rows; where the store's own answers
matter, a FHIR store over HTTP in a process of its own (``tests/fhir_store_stub.py``) under the real loader."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
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
    (cfg.lake_dir / "FHIR_STATE").write_text(json.dumps({"version": 2, **st}), encoding="utf-8")


def _owed(night: str, target: str) -> dict[str, Any]:
    """A put-back to ``target`` that began after the load of ``night`` and did not end."""
    return {"want": target, "fingerprint": "", "verified": False, "reason": "the load did not end", "attempts": 0,
            "undoing": night}  # fmt: skip


def _loading(night: str) -> dict[str, Any]:
    """What a kill inside the load of ``night`` leaves (W1)."""
    return {"want": night, "fingerprint": "", "verified": False, "reason": "loading", "attempts": 0}


def _clean_at(cfg: Any, night: str) -> bool:
    """The store was checked to hold ``night`` ("" nothing) and the lake serves it (P-03: clean is derived from the
    intent and CURRENT, never stored)."""
    st = _state(cfg)
    return st["verified"] is True and st["want"] == night and publish_mod.derive(cfg).clean


def _loaded(cfg: Any, snap: str, folder: Path) -> bool:
    """The intent says the store holds ``folder`` as the night ``snap``, checked: a resume skips its FHIR load (the
    record's ``fhir`` decides nothing; it replaced the records' flip to ``pending``)."""
    st = publish_mod.read_intent(cfg) or {}
    return (
        st.get("verified") is True
        and st.get("want") == snap
        and st.get("fingerprint") == publish_mod.fingerprint(folder)
    )


def _generation() -> tuple[str, str] | None:
    """The generation ledger's fhir build: ``(night, building | finished)``."""
    from datacore.generations import Built

    with Built() as book:
        st = book.state("fhir")
    return None if st is None else (st[0].snapshot, st[1])


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

    def held(self) -> dict[str, dict[str, str]]:
        """What it holds, resource by resource: ``{type: {id: content hash}}`` (the loader's hash, ``meta`` aside)."""
        got = httpx.get(f"{self.root}/_resources", timeout=30).json()
        return {t: {i: load_fhir.content_hash(r) for i, r in rows.items()} for t, rows in got.items()}

    def faults(self) -> list[str]:
        """The ``fail_at`` faults it injected since its reset, in order (review M2)."""
        out: list[str] = httpx.get(f"{self.root}/_faults", timeout=30).json()
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
        base: str,
        folder: Path,
        ledger: Path,
        previous: Path | None = None,
        full: bool = False,
        back: bool = False,
        finish: bool = True,
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
    assert st["verified"] is False and st["want"] == N2 and st["reason"] == "loading"
    assert publish_mod.derive(cfg).served == N1
    assert st["by"]["pid"] == os.getpid()  # the loader: this process, which a real kill takes away
    with publish_mod.fhir_lock(cfg, wait=False), pytest.raises(publish_mod.RecoveryBusy):
        publish_mod.recover_all(cfg)  # a load that still runs (it holds the lock) is let be
    assert fhir.holds == f"part of {N2}" and _state(cfg) == st

    fhir.calls, fhir.back, fhir.full = [], [], []
    # converted (review H4, a known limitation): a transaction of the killed load may still commit, and nothing
    # fences it, so the box puts nothing back by itself: refused by name until the operator's exit
    with pytest.raises(publish_mod.FhirRestoreOutstanding, match=publish_mod.UNFENCED):
        publish_mod.recover_all(cfg)
    assert fhir.holds == f"part of {N2}" and fhir.calls == [] and _state(cfg)["reason"].startswith(publish_mod.UNFENCED)
    (cfg.lake_dir / "FHIR_STATE").unlink()  # the operator's exit, once the FHIR store was restarted
    assert publish_mod.recover_all(cfg) == []  # no re-run was swapped: the FHIR store's state is in FHIR_STATE
    assert fhir.holds == N1 and fhir.calls == [N1] and fhir.back == [True] and fhir.full == [True]
    assert not _loaded(cfg, N2, folder) and lakes.lake.current() == N1  # one night, in both stores
    assert _clean_at(cfg, N1)
    assert publish_mod.recover_all(cfg) == [] and fhir.calls == [N1]  # nothing left to undo

    # the killed night run again is published, its FHIR load from the start
    assert run_ingest(cfg, "csv", night2, snapshot=N2, validate=False).passed
    assert lakes.lake.current() == N2 and fhir.holds == N2
    assert set(_record(folder).values()) <= {"done", "skipped"}
    assert _clean_at(cfg, N2)


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
    # killed once its load was answered (converted, review H4: a kill while a transaction may be out is refused)
    publish_mod._write_record(folder, {"snapshot": N2, "fingerprint": "", "steps": {"build": "skipped",
                              "omop": "skipped", "fhir": "done", "lake": "pending", "pidmap": "pending"}})  # fmt: skip
    _put_state(cfg, {**_loading(N2), "by": {"pid": 0}})
    fhir.holds, fhir.calls = f"part of {N2}", []
    after: list[bool] = []  # whether N2's load counts as in the store once the put-back ended (the ingest then
    # writes the folder anew)
    real_restore = publish_mod.restore

    def restore(c: Any, reason: str = "") -> None:
        real_restore(c, reason)
        after.append(_loaded(c, N2, folder))

    monkeypatch.setattr(publish_mod, "restore", restore)
    rep = run_ingest(cfg, "csv", _night(tmp_path, "empty", []), snapshot=N2, validate=False)
    assert not rep.passed and lakes.lake.current() == N1
    assert fhir.calls[:1] == [N1] and fhir.holds == N1
    assert _clean_at(cfg, N1) and after[0] is False  # review L1 (T14)


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

    def killed_in_the_put_back(base: str, folder: Path, ledger: Path, previous: Path | None = None, full: bool = False,
                               back: bool = False, finish: bool = True) -> tuple[int, int]:  # fmt: skip
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
    st = _state(cfg)  # the put-back began (W2) and did not end
    assert st["verified"] is False and st["want"] == N1 and st["undoing"] == N2 and _record(folder)["lake"] == "failed"
    fhir.calls = []
    assert publish_mod.recover_all(cfg) == [] and fhir.holds == N1 and fhir.calls == [N1]
    assert not _loaded(cfg, N2, folder) and _clean_at(cfg, N1)
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
    st = _state(cfg)  # the store is not clean until the night is served and checked
    assert st["verified"] is False and st["want"] == N2 and st["reason"] == "loading"
    fhir.calls = []
    assert publish_mod.recover_all(cfg) == [] and fhir.holds == N1 and fhir.calls == [N1]
    assert not _loaded(cfg, N2, folder) and _clean_at(cfg, N1)
    out = publish_mod.publish_night(cfg, N2, folder)
    assert out.promoted and fhir.calls == [N1, N2] and fhir.holds == N2 and lakes.lake.current() == N2


def _killed_in_its_load(tmp_path: Path, cfg: Any, fhir: Fhir, mp: pytest.MonkeyPatch, snap: str) -> Path:
    """The night ``snap`` killed in its FHIR step once every transaction of its load was answered (the record says
    ``done``, the intent is still W1). Converted (review H4): a kill while a transaction may still be out is refused
    by name (``test_a_night_killed_in_its_fhir_load_is_put_back_to_the_served_night``); this is the kill the box
    still puts back by itself, so the tests that use it keep their subject (the put-back)."""
    killed_at = tmp_path / "disk-at-the-kill"
    real = publish_mod._checkpoint

    def killed(name: str) -> None:
        if name == "FHIR store loaded":
            fhir.holds = f"part of {snap}"
            shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)
            raise _Killed(name)
        real(name)

    mp.setattr(publish_mod, "_checkpoint", killed)
    night = _night2(tmp_path) if snap == N2 else _night(tmp_path, "n1", [_row("D1", "2026-09-01")])
    with pytest.raises(_Killed):
        run_ingest(cfg, "csv", night, snapshot=snap, validate=False)
    _as_the_kill_left_it(cfg, killed_at)
    mp.setattr(publish_mod, "_checkpoint", real)
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
    assert _record(folder)["fhir"] == "done" and _state(cfg)["verified"] is False and _state(cfg)["want"] == N1
    out = publish_mod.publish_night(cfg, N2, folder)
    assert not out.promoted and lakes.lake.current() == N1 and _record(folder)["fhir"] == "done"
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
    assert fhir.calls == [] and _record(folder)["fhir"] == "done"
    assert _state(cfg)["verified"] is False and _state(cfg)["undoing"] == N2


def test_a_first_night_killed_in_its_load_leaves_an_empty_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review M2 / P03-03: no night is served yet: the FHIR store is put back to nothing (every id the loader
    loaded is deleted), not left holding part of the killed night. The real loader's deletes: T5 and T8."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    fhir = Fhir(monkeypatch)
    folder = _killed_in_its_load(tmp_path, cfg, fhir, monkeypatch, N1)
    assert lakes.lake.current() is None and _record(folder)["fhir"] == "done"
    assert publish_mod.recover_all(cfg) == []
    assert fhir.calls == ["fhir-nothing-served"] and fhir.full == [True] and fhir.back == [True]
    assert not _loaded(cfg, N1, folder)
    assert _clean_at(cfg, "")


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
    # killed once its load was answered (converted, review H4: a kill while a transaction may be out is refused)
    steps = {"build": "skipped", "omop": "skipped", "fhir": "done", "lake": "pending", "pidmap": "pending"}
    loading = {"version": 2, **_loading(N2)}
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
    assert not _loaded(cfg, N2, folder) and fhir.calls == [N1] and fhir.holds == N1
    assert lakes.lake.current() == N1 and _clean_at(cfg, N1)


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
    assert held.get("Condition") and _clean_at(cfg, N1)
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
    assert _clean_at(cfg, N1)
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
    assert out.promoted and lakes.lake.current() == N2 and fhir.holds == N2 and _clean_at(cfg, N2)


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
    assert st["verified"] is False and st["undoing"] == N2 and st["want"] == N1, st
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
    assert _state(cfg)["verified"] is False and _state(cfg)["attempts"] == 2


def test_an_ingest_without_a_fhir_endpoint_keeps_the_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T4 (review R3, converted by P03-DESIGN-2 R4): an owed put-back and no FHIR endpoint configured: the night is
    refused before any step, by its name; the marker is not touched and the lake does not move. With the endpoint
    back, the next recovery puts the store back."""
    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    _put_state(cfg, _owed(N2, N1))
    before = (cfg.lake_dir / "FHIR_STATE").read_bytes()
    url, cfg.fhir_base_url = cfg.fhir_base_url, None
    fhir.calls = []
    lakes.calls.clear()
    night3 = _night(tmp_path, "n3", [_row("D1", "2026-09-01"), _row("D3", "2026-10-02")])
    with pytest.raises(publish_mod.NightRefused, match=r"together or not at all \(fhir off, lake on; the store holds"):
        run_ingest(cfg, "csv", night3, snapshot=N3, validate=False)
    assert (cfg.lake_dir / "FHIR_STATE").read_bytes() == before and fhir.calls == []
    assert lakes.calls == [] and lakes.lake.current() == N1 and not snapshot_dir(cfg.lake_dir, N3).exists()
    served = lakes.lake.current()
    cfg.fhir_base_url = url
    publish_mod.recover_all(cfg)
    assert fhir.calls == [served] and fhir.holds == served
    assert _clean_at(cfg, N1)


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
    assert _clean_at(cfg, "")
    assert not _loaded(cfg, N1, snapshot_dir(cfg.lake_dir, N1))


def test_a_missing_served_folder_blocks_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T6 (review R4): the served night's folder is missing: nothing is sent, and the refusal names why."""
    cfg, _lakes, fhir = _served_n1(tmp_path, monkeypatch)
    _killed_in_its_load(tmp_path, cfg, fhir, monkeypatch, N2)
    shutil.rmtree(snapshot_dir(cfg.lake_dir, N1))
    with pytest.raises(publish_mod.FhirRestoreOutstanding, match="folder missing"):
        publish_mod.recover_all(cfg)
    st = _state(cfg)
    assert st["verified"] is False and "folder missing" in st["reason"] and fhir.calls == []


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
        publish_mod._write_intent(cfg, _loading(N1))
        stub.control(fail_after=2)  # the load breaks after two of its bundles are in
        with pytest.raises(RuntimeError, match="transaction failed"):
            publish_mod._sync_fhir(cfg, folder, None)
        partial = stub.ids()
        assert len(partial) == 2, partial
        stub.control(fail_after=None)
        publish_mod.restore(cfg)
    assert stub.ids() == {}
    every = set(load_fhir.snapshot_ids(folder))
    assert publish_mod.verify_fhir(cfg, publish_mod._empty_night(cfg), also=every) == dict.fromkeys(sorted(every), 0)
    assert _clean_at(cfg, "")


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
    st = _state(cfg)
    assert st["verified"] is False and st["want"] == N1 and (cfg.lake_dir / RERUN_DIR / f"{N1}.replaced").is_dir()
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
    assert fhir.holds == N1 and publish_mod.fingerprint(served) == original and _clean_at(cfg, N1)
    assert not _loaded(cfg, N1, cfg.lake_dir / RERUN_DIR / N1)  # the re-run's own NDJSON is owed its load again


def test_a_live_loader_is_never_taken_for_killed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T10 (review N5): a load that runs in another process holds fhir.lock; ``/proc`` is unreadable here. It is
    never taken for a killed one: liveness is the lock, not a pid."""
    cfg, _lakes, fhir = _served_n1(tmp_path, monkeypatch)
    loading = {"version": 2, **_loading(N2), "by": {"pid": 1}}
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
        assert _state(cfg) == loading and fhir.calls == []
    finally:
        release.touch()
        holder.wait()


def test_an_upgraded_box_without_a_marker_verifies_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub: Stub
) -> None:
    """T11 (review N5): a box from before FHIR_STATE, whose old version was killed in a load (one more Patient in
    the store, its id in the widened ledger). The first recovery puts the store back to the served night (P03-DESIGN-2:
    no file beside a ledger is owed, "never checked"; the first check of the deleted ``_first_verify`` is gone) and
    calls it clean only once that was checked; the next does not check again."""
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
    real = publish_mod._write_intent

    def spy(c: Any, st: dict[str, Any]) -> dict[str, Any]:
        written.append(dict(st))
        return real(c, st)

    monkeypatch.setattr(publish_mod, "_write_intent", spy)
    publish_mod.recover_all(cfg)
    assert [(w["want"], w["verified"]) for w in written] == [(N1, False), (N1, True)], written
    assert "never checked" in written[0]["reason"]
    assert stub.ids() == n1 and _clean_at(cfg, N1)
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
        publish_mod._write_intent(cfg, _loading(N1))
        publish_mod._sync_fhir(cfg, snapshot_dir(cfg.lake_dir, N1), None)  # the whole night in, none served
        (patient,) = stub.ids()["Patient"]
        stub.control(drop=[f"Patient/{patient}"])
        with pytest.raises(publish_mod.FhirRestoreOutstanding, match="Patient: store 1, night 0"):
            publish_mod.restore(cfg)
    st = _state(cfg)
    assert st["verified"] is False and st["reason"] == "Patient: store 1, night 0" and st["attempts"] == 1


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
    assert st["verified"] is False and st["want"] == N2 and st["reason"] == "loading", st
    assert lakes.lake.current() == N1
    assert 100 <= len(stub.ids().get("Observation", [])) < 1000  # part of the night's Observations are in
    with publish_mod.fhir_lock(cfg, wait=False):
        pass  # the kill took the lock with it
    # converted (review H4, a known limitation): killed while sending, a transaction may still commit; nothing
    # fences it, so the store is refused by name and nothing is sent, until the operator's exit
    left = stub.ids()
    with pytest.raises(publish_mod.FhirRestoreOutstanding, match=publish_mod.UNFENCED):
        publish_mod.recover_all(cfg)
    assert stub.ids() == left and _state(cfg)["reason"].startswith(publish_mod.UNFENCED)
    (cfg.lake_dir / "FHIR_STATE").unlink()  # the operator's exit, once the FHIR store was restarted
    publish_mod.recover_all(cfg)
    assert stub.ids() == before and lakes.lake.current() == N1
    assert not (snapshot_dir(cfg.lake_dir, N2) / "ingest_report.json").exists()
    assert held_snapshots(cfg.lake_dir) == {}
    assert _clean_at(cfg, N1)
    assert run_ingest(cfg, "csv", night2, snapshot=N2, validate=False).passed
    assert lakes.lake.current() == N2
    want = load_fhir.snapshot_ids(snapshot_dir(cfg.lake_dir, N2))
    assert stub.ids() == {t: sorted(i) for t, i in want.items() if i}
    assert _clean_at(cfg, N2)


# ------------------------------------------------------------- the final delta reviews of #1566 (D1-D7, D1-D4)
def _hashes(folder: Path) -> dict[str, dict[str, str]]:
    """A night's NDJSON as the store would hold it, resource by resource (types with none left out)."""
    return {t: rows for t, rows in load_fhir.snapshot_hashes(folder).items() if rows}


def _stub_cfg(tmp_path: Path, stub: Stub) -> tuple[Any, _Lakes]:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    cfg.fhir_base_url = stub.fhir
    return cfg, lakes


def test_the_records_say_pending_before_the_marker_says_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review D1 (and D3 of the second reviewer): N2's FHIR step is done and its process is killed in the lake step.
    Converted (P03-DESIGN-2: the records' flip to ``pending`` is deleted; whether a resume loads is read from the
    intent alone): when the recovery's intent says ``verified``, it names N1, never N2, so no resume skips N2's load
    beside a store that holds N1; and the resume does load it."""
    cfg, _lakes, fhir = _served_n1(tmp_path, monkeypatch)
    killed_at = tmp_path / "disk-at-the-kill"
    real_rebuild = cfg.rebuild

    def killed_in_the_lake(snap: str, nd: Path) -> Any:
        shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)
        raise RuntimeError("the test goes on from the copy")

    monkeypatch.setattr(cfg, "rebuild", killed_in_the_lake)
    run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False)
    _as_the_kill_left_it(cfg, killed_at)
    monkeypatch.setattr(cfg, "rebuild", real_rebuild)
    fhir.holds = N2
    folder = snapshot_dir(cfg.lake_dir, N2)
    assert _record(folder)["fhir"] == "done" and _state(cfg)["verified"] is False and _state(cfg)["want"] == N2
    at_clean: list[str] = []
    real = publish_mod._write_intent

    def spy(c: Any, st: dict[str, Any]) -> dict[str, Any]:
        if st["verified"]:
            at_clean.append(st["want"])
        return real(c, st)

    monkeypatch.setattr(publish_mod, "_write_intent", spy)
    publish_mod.recover_all(cfg)
    assert at_clean == [N1] and _clean_at(cfg, N1) and not _loaded(cfg, N2, folder)
    fhir.calls = []
    assert publish_mod.publish_night(cfg, N2, folder).promoted and fhir.calls == [N2]


def test_an_upgrade_puts_back_a_value_changed_under_a_served_id(tmp_path: Path, stub: Stub) -> None:
    """Review D2: a box from before FHIR_STATE, whose old version was killed in a re-run that had changed one
    resource under an id the served night has. Ids and counts match the served night; the first start still puts
    the store back (ids are not values), so the served value is what the store holds."""
    cfg, _lakes = _stub_cfg(tmp_path, stub)
    night = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", night, snapshot=N1, validate=False).passed
    served = _hashes(snapshot_dir(cfg.lake_dir, N1))
    assert stub.held() == served
    (cfg.lake_dir / "FHIR_STATE").unlink()
    got = httpx.get(f"{stub.root}/_resources", timeout=30).json()
    changed = {**got["Condition"][sorted(got["Condition"])[0]], "recordedDate": "2026-09-30"}
    stub.seed([changed])  # the same id, another value: what the interrupted load left
    assert stub.ids() == {t: sorted(r) for t, r in served.items()} and stub.held() != served
    publish_mod.recover_all(cfg)
    assert stub.held() == served and _clean_at(cfg, N1)


def test_an_upgrade_check_without_an_answer_keeps_the_gate_closed(tmp_path: Path, stub: Stub) -> None:
    """Review D3: the first start of an upgraded box (no FHIR_STATE, a ledger: its loader sent resources) meets a
    store that answers nothing. The marker says the put-back is owed and the next night is refused before its
    lake build; without an endpoint, the missing file is not read as ``clean`` either."""
    cfg, lakes = _stub_cfg(tmp_path, stub)
    night = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", night, snapshot=N1, validate=False).passed
    (cfg.lake_dir / "FHIR_STATE").unlink()
    stub.control(down=True)
    with pytest.raises(publish_mod.FhirRestoreOutstanding):
        publish_mod.recover_all(cfg)
    assert _state(cfg)["verified"] is False
    lakes.calls.clear()
    with pytest.raises(publish_mod.FhirRestoreOutstanding):
        run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False)
    assert lakes.calls == [] and lakes.lake.current() == N1
    (cfg.lake_dir / "FHIR_STATE").unlink()
    cfg.fhir_base_url = None
    assert not publish_mod.derive(cfg).clean


def test_a_delete_the_store_did_not_do_is_sent_again_on_retry(tmp_path: Path, stub: Stub) -> None:
    """Review D4: the store answers a DELETE and does not do it; the put-back's check finds the Patient left (T12).
    The ids it owes a DELETE of were on disk before the first DELETE, so the retry, with the store well again,
    deletes the Patient and only then calls the store clean."""
    cfg = _fhir_cfg(tmp_path, _Lakes(tmp_path / "lake"))
    cfg.fhir_base_url = stub.fhir
    run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N1, load_fhir=False, rebuild_lake=False, validate=False)
    with publish_mod.fhir_lock(cfg, wait=False):
        publish_mod._write_intent(cfg, _loading(N1))
        publish_mod._sync_fhir(cfg, snapshot_dir(cfg.lake_dir, N1), None)
        (patient,) = stub.ids()["Patient"]
        stub.control(drop=[f"Patient/{patient}"])
        with pytest.raises(publish_mod.FhirRestoreOutstanding, match="Patient: store 1, night 0"):
            publish_mod.restore(cfg)
        stub.control(drop=[])
        publish_mod.restore(cfg)
    assert stub.ids() == {} and _clean_at(cfg, "")
    assert not (cfg.lake_dir / "FHIR_OWED").exists()


def test_a_count_without_its_total_is_no_count(tmp_path: Path, stub: Stub) -> None:
    """Review D5 (and D4 of the second reviewer): the store answers the count with no ``total``. That is no proof of
    zero: the check of the empty baseline fails, with the type named."""
    cfg = _fhir_cfg(tmp_path, _Lakes(tmp_path / "lake"))
    cfg.fhir_base_url = stub.fhir
    stub.seed([{"resourceType": "Patient", "id": "p-left"}])
    stub.control(no_total=True)
    with pytest.raises(publish_mod.FhirMismatch, match="Patient: the store gave no count"):
        publish_mod.verify_fhir(cfg, publish_mod._empty_night(cfg), ids=True, also=["Patient"])


def test_a_lock_refusal_says_the_served_night_is_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review D6: N1 is served and asked for again while a recovery holds fhir.lock. The refusal still reads what
    CURRENT names: ``promoted``."""
    cfg, lakes, _fhir = _served_n1(tmp_path, monkeypatch)
    holder, release = _holder(cfg, tmp_path)
    try:
        out = publish_mod.publish_night(cfg, N1, snapshot_dir(cfg.lake_dir, N1))
        assert out.lake_busy and out.errors == [publish_mod.FHIR_BUSY_ERROR] and lakes.lake.current() == N1
        assert out.promoted
    finally:
        release.touch()
        holder.wait()


def test_a_publish_without_its_lake_step_leaves_the_store_owed(tmp_path: Path, stub: Stub) -> None:
    """Review D1 of the second reviewer, converted (P03-DESIGN-2 R4: the store and the lake are published together
    or not at all): a night asked for with its lake step off, a new night or a re-run of the served night, is
    refused before any step. Nothing reaches the store, the intent is not written, the served night stays clean."""
    cfg, lakes = _stub_cfg(tmp_path, stub)
    night1 = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", night1, snapshot=N1, validate=False).passed
    served = _hashes(snapshot_dir(cfg.lake_dir, N1))
    before, sent = (cfg.lake_dir / "FHIR_STATE").read_bytes(), len(stub.log())
    again = _night(tmp_path, "n1b", [_row("D1", "2026-09-03")], ["10000001"])
    for night, snap in ((_night2(tmp_path), N2), (again, N1)):
        with pytest.raises(publish_mod.NightRefused, match=r"together or not at all \(fhir on, lake off"):
            run_ingest(cfg, "csv", night, snapshot=snap, rebuild_lake=False, validate=False)
        out = publish_mod.publish_night(cfg, snap, _copy_night(cfg, snap) if snap == N2 else snapshot_dir(
            cfg.lake_dir, N1), rebuild_lake=False)  # fmt: skip
        assert out.errors[0].startswith("night refused:") and set(out.steps.values()) == {"pending"}
        assert lakes.lake.current() == N1 and stub.held() == served and len(stub.log()) == sent
        assert (cfg.lake_dir / "FHIR_STATE").read_bytes() == before and _clean_at(cfg, N1)


def test_an_ingest_that_meets_a_held_store_is_refused_not_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review D2 of the second reviewer: a CLI ingest (``adapter.run_job``) starts while a publish holds fhir.lock.
    It is refused by that name, not ``failed``, and nothing of it reaches OMOP or the lake."""
    import lake.build
    import tb_common.logging
    from adapter import cli, dual_write, run_job, runs

    cfg, lakes, _fhir = _served_n1(tmp_path, monkeypatch)
    omop: list[str] = []
    monkeypatch.setattr(dual_write, "load_night", lambda c, s, nd: omop.append(s))
    monkeypatch.setattr(cli, "build_config", lambda: (cfg, "csv", ""))
    monkeypatch.setattr(tb_common.logging, "setup_logging", lambda service, level="INFO": None)
    monkeypatch.setattr(lake.build, "prefer_me_when_memory_runs_out", lambda: None)
    lakes.calls.clear()
    lock = runs.RunLock(cfg.lake_dir)
    state = {"run": "pthreeb", "state": "running", "started": "2026-10-04T17:00:00+00:00", "ended": None, "detail": ""}
    runs.hold(cfg.lake_dir, "pthreeb")
    runs.write(cfg.lake_dir, state)
    fd = os.dup(lock.fileno())
    lock.hand_over()
    req = {"source": "csv", "path": _night2(tmp_path), "since": None, "snapshot": N2, "load_fhir": True,
           "rebuild_lake": True, "validate": False}  # fmt: skip
    holder, release = _holder(cfg, tmp_path)
    try:
        assert run_job.main([str(fd), json.dumps({"state": state, "lake_dir": str(cfg.lake_dir), "request": req})]) == 0
    finally:
        release.touch()
        holder.wait()
    end = runs.read(cfg.lake_dir, "pthreeb")
    assert end is not None and end["state"] == "refused", end
    assert end["detail"] == "night refused: the FHIR store is held by another publish or recovery"
    assert omop == [] and lakes.calls == [] and lakes.lake.current() == N1


# ------------------------------------------------------- the last delta reviews of #1566 (F1-F7, E1-E4; P03-DESIGN-2)
def test_a_publish_with_fhir_off_over_a_held_store_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review F1: N1 is served and checked; the FHIR endpoint is gone, and N2 is asked for. Promoting N2 would leave
    the store on N1 under a lake on N2 with nothing owed: the night is refused before any step, the intent is not
    touched. With the endpoint back, the recovery sends nothing (the store holds what is served). The same with the
    endpoint set and ``load_fhir`` off."""
    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    before = (cfg.lake_dir / "FHIR_STATE").read_bytes()
    url, cfg.fhir_base_url = cfg.fhir_base_url, None
    fhir.calls, fhir.verified = [], []
    lakes.calls.clear()
    with pytest.raises(publish_mod.NightRefused, match=rf"\(fhir off, lake on; the store holds {N1}\)"):
        run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False)
    folder = _copy_night(cfg, N2)
    out = publish_mod.publish_night(cfg, N2, folder, last_good=N1)
    assert out.errors[0].startswith("night refused:") and set(out.steps.values()) == {"pending"} and not out.promoted
    assert not (folder / "publish.json").exists() and lakes.calls == [] and lakes.lake.current() == N1
    assert (cfg.lake_dir / "FHIR_STATE").read_bytes() == before and fhir.calls == []
    cfg.fhir_base_url = url
    publish_mod.recover_all(cfg)
    assert fhir.calls == [] and fhir.verified == [] and _clean_at(cfg, N1)
    with pytest.raises(publish_mod.NightRefused, match=r"\(fhir off, lake on"):
        run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, load_fhir=False, validate=False)
    out = publish_mod.publish_night(cfg, N2, folder, last_good=N1, load_fhir=False)
    assert out.errors[0].startswith("night refused:") and lakes.calls == [] and lakes.lake.current() == N1
    assert (cfg.lake_dir / "FHIR_STATE").read_bytes() == before and fhir.calls == []


def test_current_moved_under_a_verified_intent_is_owed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reviews F1, E1: N1 is served and checked, then ``CURRENT`` moves without a publish (a lake restored from a
    backup that serves N2): the store is owed at once (clean is derived from CURRENT, never stored), and the recovery
    puts it to N2. The same date with another served folder (its NDJSON changed, its record as it was: review H3, the
    fingerprint is the data's): owed, put back."""
    cfg, _lakes, fhir = _served_n1(tmp_path, monkeypatch)
    _copy_night(cfg, N2)
    (cfg.lake_dir / "CURRENT").write_text(N2, encoding="utf-8")
    d = publish_mod.derive(cfg)
    assert not d.clean and d.served == N2 and "CURRENT moved" in d.reason
    fhir.calls = []
    publish_mod.recover_all(cfg)
    assert fhir.calls == [N2] and fhir.holds == N2 and _clean_at(cfg, N2)
    served = snapshot_dir(cfg.lake_dir, N2)
    publish_mod._write_record(served, {"snapshot": N2, "fingerprint": publish_mod.fingerprint(served), "steps": {}})
    record = (served / "publish.json").read_bytes()
    _restored_with_another_value(served)
    assert (served / "publish.json").read_bytes() == record and not publish_mod.derive(cfg).clean
    publish_mod.recover_all(cfg)
    assert fhir.calls == [N2, N2] and _clean_at(cfg, N2)
    assert (
        _state(cfg)["fingerprint"] == publish_mod.fingerprint(served) != publish_mod.read_record(served)["fingerprint"]
    )


def test_a_lake_build_that_outlives_its_publisher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review E1: N2's publisher is killed inside the lake's one-call build (the FHIR store holds N2, CURRENT N1),
    and the lake's build goes on without it. While it runs, the recovery does not put the store back under it
    (``SnapshotBuilding``, the intent untouched); the build then promotes N2, and the next recovery puts the store to
    N2, not N1."""
    from lake.store import SnapshotBuilding, building

    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    killed_at = tmp_path / "disk-at-the-kill"
    real_rebuild = cfg.rebuild
    assert real_rebuild is not None

    def killed_in_the_lake(snap: str, nd: Path) -> Any:
        shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)
        raise RuntimeError("the test goes on from the copy")

    monkeypatch.setattr(cfg, "rebuild", killed_in_the_lake)
    run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False)
    _as_the_kill_left_it(cfg, killed_at)
    monkeypatch.setattr(cfg, "rebuild", real_rebuild)
    fhir.holds, fhir.calls = N2, []
    before = (cfg.lake_dir / "FHIR_STATE").read_bytes()
    with building(cfg.lake_dir, N2), pytest.raises(SnapshotBuilding):  # the killed publisher's lake build
        publish_mod.recover_all(cfg)
    assert fhir.calls == [] and (cfg.lake_dir / "FHIR_STATE").read_bytes() == before
    real_rebuild(N2, snapshot_dir(cfg.lake_dir, N2))  # the build ends and promotes, its publisher long gone
    assert lakes.lake.current() == N2 and not publish_mod.derive(cfg).clean
    publish_mod.recover_all(cfg)
    assert fhir.calls == [N2] and fhir.holds == N2 and _clean_at(cfg, N2)


def test_an_upgrade_with_a_finished_newer_generation(tmp_path: Path, stub: Stub) -> None:
    """Reviews F2, H5: a box from before FHIR_STATE whose old loader finished N2 in the generation ledger before the
    lake promoted it, and the promotion failed: CURRENT N1, the store holds N1's ids with N2's value. That "finished"
    is the old loader's (its last resource in, never checked as served), so the recovery of the served night, under
    the locks, takes the ledger back to N1 (``Built.begin(..., upgrade=True)``) and puts the store back: N1's values,
    checked, N1 finished. The next night is then published as on any box. (Converted, review H5: it stayed refused
    for good.)"""
    from datacore.generations import Built

    cfg, _lakes = _stub_cfg(tmp_path, stub)
    night = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", night, snapshot=N1, validate=False).passed
    served = _hashes(snapshot_dir(cfg.lake_dir, N1))
    (cfg.lake_dir / "FHIR_STATE").unlink()
    got = httpx.get(f"{stub.root}/_resources", timeout=30).json()
    stub.seed([{**got["Condition"][sorted(got["Condition"])[0]], "recordedDate": "2026-09-30"}])
    with Built() as book, book.building("fhir"):
        book.finish("fhir", book.begin("fhir", N2))  # the old loader: finished once its last resource was in
    left = stub.held()
    assert left != served and stub.ids() == {t: sorted(r) for t, r in served.items()}
    publish_mod.recover_all(cfg)
    assert stub.held() == served and _clean_at(cfg, N1) and _generation() == (N1, "finished")
    assert run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False).passed
    assert stub.held() == _hashes(snapshot_dir(cfg.lake_dir, N2)) and _clean_at(cfg, N2)
    assert _generation() == (N2, "finished")


def test_a_generation_ledger_that_does_not_answer_keeps_the_store_owed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub: Stub
) -> None:
    """Reviews F3, E2: N2 is loaded, promoted and checked, and the generation ledger does not answer its finish. The
    store is owed by that name, no PASSED; the ledger still says N2 is building. The next recovery settles it (the
    one way to clean, on both paths) and the ledger says finished; the resume writes PASSED."""
    from adapter.pipeline import PASSED

    cfg, lakes = _stub_cfg(tmp_path, stub)
    night = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", night, snapshot=N1, validate=False).passed
    assert _generation() == (N1, "finished")
    real = load_fhir.finish_load

    def no_answer(*args: Any) -> None:
        raise load_fhir.LedgerError("the generation ledger did not answer (OperationalError)")

    monkeypatch.setattr(publish_mod, "finish_load", no_answer)
    rep = run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False)
    folder = snapshot_dir(cfg.lake_dir, N2)
    assert not rep.passed and lakes.lake.current() == N2 and not (folder / PASSED).exists()
    assert any("generation ledger did not answer" in e for e in rep.errors or []), rep.errors
    assert _state(cfg)["verified"] is False and _generation() == (N2, "building")
    monkeypatch.setattr(publish_mod, "finish_load", real)
    publish_mod.recover_all(cfg)
    assert _clean_at(cfg, N2) and _generation() == (N2, "finished")
    out = publish_mod.publish_night(cfg, N2, folder)
    assert out.ok and (folder / PASSED).exists()


def test_a_failed_end_check_writes_no_passed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub: Stub) -> None:
    """Reviews F4, E2(b): N2 is promoted and the store answers its end check 500. The night is served but not
    settled: no ``passed.json``, its hold kept, ``promoted``, the put-back owed; the next recovery settles N2 and
    finishes it in the generation ledger; the resume then writes PASSED and drops the hold."""
    from adapter.pipeline import HELD, PASSED

    cfg, lakes = _stub_cfg(tmp_path, stub)
    night = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    assert run_ingest(cfg, "csv", night, snapshot=N1, validate=False).passed
    folder = _copy_night(cfg, N2)
    (folder / HELD).write_text("{}\n", encoding="utf-8")  # a held night the steward accepted
    real_verify = publish_mod.verify_fhir

    def end_check_500(c: Any, f: Path, *, ids: bool = False, also: Any = ()) -> dict[str, int]:
        stub.control(down=not ids)  # the publish's own end check is the one check without ids
        try:
            return real_verify(c, f, ids=ids, also=also)
        finally:
            stub.control(down=False)

    monkeypatch.setattr(publish_mod, "verify_fhir", end_check_500)
    out = publish_mod.publish_night(cfg, N2, folder, last_good=N1)
    assert out.promoted and lakes.lake.current() == N2 and out.steps["fhir"] == "failed"
    assert out.fhir_outstanding.startswith("fhir_restore_outstanding") and not out.ok
    assert not (folder / PASSED).exists() and (folder / HELD).exists()
    assert out.steps["pidmap"] == "pending" and _generation() == (N2, "building")
    monkeypatch.setattr(publish_mod, "verify_fhir", real_verify)
    publish_mod.recover_all(cfg)
    assert _clean_at(cfg, N2) and _generation() == (N2, "finished")
    assert publish_mod.publish_night(cfg, N2, folder, last_good=N1).ok
    assert (folder / PASSED).exists() and not (folder / HELD).exists()


def test_a_delete_the_forward_load_lost_is_sent_again(tmp_path: Path, stub: Stub) -> None:
    """Review E3: the store answers a DELETE of N2's forward load and does not do it (a Condition only N1 has). The
    end check finds it; the id ledger keeps the id until a check passes, so the next put-back deletes it again and
    only then is the store clean."""
    cfg, lakes = _stub_cfg(tmp_path, stub)
    night1 = _night(tmp_path, "n1", [_row("D1", "2026-09-01"), _row("D9", "2026-09-09")], ["10000001"])
    assert run_ingest(cfg, "csv", night1, snapshot=N1, validate=False).passed
    stub.control(drop=[f"Condition/{i}" for i in stub.ids()["Condition"]])
    rep = run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False)
    want = load_fhir.snapshot_ids(snapshot_dir(cfg.lake_dir, N2))
    left = set(stub.ids()["Condition"]) - want["Condition"]
    assert not rep.passed and lakes.lake.current() == N2 and len(left) == 1
    assert left <= set(load_fhir._read_ledger(cfg.lake_dir / "fhir_ledger")["Condition"])
    assert _state(cfg)["verified"] is False and "Condition: store" in _state(cfg)["reason"]
    stub.control(drop=[])
    publish_mod.recover_all(cfg)
    assert stub.held() == _hashes(snapshot_dir(cfg.lake_dir, N2)) and _clean_at(cfg, N2)
    assert set(load_fhir._read_ledger(cfg.lake_dir / "fhir_ledger")["Condition"]) == want["Condition"]


def test_an_intent_write_error_fails_the_step_not_the_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review E4: the intent cannot be written before the FHIR load (the lake volume is full). ``publish_night``
    returns, it never raises: the FHIR step failed, nothing was sent, nothing promoted, the store is still N1's."""
    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    real = publish_mod._write_intent

    def full(c: Any, st: dict[str, Any]) -> dict[str, Any]:
        if st["want"] == N2:
            raise OSError(28, "No space left on device")
        return real(c, st)

    monkeypatch.setattr(publish_mod, "_write_intent", full)
    fhir.calls = []
    out = publish_mod.publish_night(cfg, N2, _copy_night(cfg, N2), last_good=N1)
    assert out.steps["fhir"] == "failed" and not out.promoted and lakes.lake.current() == N1
    assert any(e.startswith("fhir-store load failed: OSError") for e in out.errors), out.errors
    assert fhir.calls == [] and _clean_at(cfg, N1)


def test_a_busy_lake_at_entry_says_the_served_night_is_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review F6: N1 is served and asked for again while a killed re-run's lake build of N1 still runs. The publish
    says the lake is busy, and still reads what CURRENT names: ``promoted``."""
    from adapter.pipeline import RERUN_DIR
    from lake.store import building

    cfg, lakes, _fhir = _served_n1(tmp_path, monkeypatch)
    (cfg.lake_dir / RERUN_DIR / f"{N1}.replaced").mkdir(parents=True)  # what the killed re-run left
    with building(cfg.lake_dir, N1):
        out = publish_mod.publish_night(cfg, N1, snapshot_dir(cfg.lake_dir, N1))
    assert out.lake_busy and publish_mod.BUSY_ERROR in out.errors and lakes.lake.current() == N1
    assert out.promoted


def test_a_recovery_write_error_reaches_the_run_detail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review F7: the service's recovery after a killed ingest fails on its way (the intent cannot be written; a
    killed re-run's folder cannot be moved back). The store is still owed, and the run's detail says so."""
    from adapter import app as adapter_app
    from adapter.pipeline import RERUN_DIR

    cfg, _lakes, fhir = _served_n1(tmp_path, monkeypatch)
    _killed_in_its_load(tmp_path, cfg, fhir, monkeypatch, N2)
    monkeypatch.setattr(adapter_app, "build_config", lambda: (cfg, "csv", ""))

    def no_room(*args: Any) -> Any:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(publish_mod, "_write_intent", no_room)
    said = adapter_app._undo_killed_load()
    assert said.startswith("fhir_restore_outstanding") and fhir.calls == []
    monkeypatch.setattr(publish_mod, "_recover", no_room)
    (cfg.lake_dir / RERUN_DIR / f"{N2}.replaced").mkdir(parents=True)
    said = adapter_app._undo_killed_load()
    assert said == "fhir_restore_outstanding: recovery failed (OSError); the store is still owed"
    assert not publish_mod.derive(cfg).clean


# ----------------------------------------------------------------- the crash points (integrator's ruling, #1566)
# P03-DESIGN-2 §ii as a test. Every durable write of the publish and of the recovery path ends in
# ``publish._checkpoint`` (FHIR_STATE and each publish.json by construction, the store, the ledgers, the lake and the
# folders by name). Each night below is run once per checkpoint it reaches and killed there (the disk as the kill left
# it: no handler of the process runs after it); from the kills inside the FHIR load and the lake step, the recovery
# that follows is itself killed at each of its own checkpoints. Each night, and the recovery after a kill in its FHIR
# load, is also run once per store request it sends with that request answered 500 (nothing done) or done and
# answered with a body that is not JSON. Right after each: the store is owed (derived), or it holds what CURRENT
# serves and the generation ledger has that night finished. Then the box starts again: the night is served, the store
# holds it resource by resource, with the night's own values, and the intent says so.
class _Killed(BaseException):
    """The process dies here."""


@dataclass
class _Box:
    root: Path
    cfg: Any
    lakes: _Lakes
    n1: str
    n2: str
    night1b: str  # N1 again, another value under the same ids (a re-run of the served night)
    night2: str


def _box(root: Path, stub: Stub, i: int) -> _Box:
    """A box serving its first night (the store holding it); every box its own dates, later than the last one's (the
    generation ledger in the test's database is shared by the boxes of one test)."""
    stub.control(reset=True, fail_at=None, down=False, drop=[], no_total=False)
    day = date(2026, 1, 1) + timedelta(days=3 * i)
    lakes = _Lakes(root / "lake")
    cfg = _fhir_cfg(root, lakes)
    cfg.fhir_base_url = stub.fhir
    _two_step(cfg, lakes)
    box = _Box(root, cfg, lakes, day.isoformat(), (day + timedelta(days=1)).isoformat(),
               _night(root, "n1b", [_row("D1", "2025-12-03")], ["10000001"]),
               _night(root, "n2", [_row("D1", "2025-12-01"), _row("D2", "2025-12-02")], ["10000001"]))  # fmt: skip
    assert run_ingest(cfg, "csv", _night(root, "n1", [_row("D1", "2025-12-01")], ["10000001"]), snapshot=box.n1,
                      validate=False).passed  # fmt: skip
    return box


def _ingest(box: _Box, rerun: bool) -> Any:
    night, snap = (box.night1b, box.n1) if rerun else (box.night2, box.n2)
    return run_ingest(box.cfg, "csv", night, snapshot=snap, validate=False)


def _fails_once(box: _Box, rerun: bool) -> None:
    """The night whose lake step fails (the promotion, or a re-run's build), then the operator's retry."""
    name = "rebuild" if rerun else "promote"
    real = getattr(box.cfg, name)

    def fails(*args: Any) -> Any:
        raise RuntimeError("the lake step failed")

    setattr(box.cfg, name, fails)
    try:
        _ingest(box, rerun)
    finally:
        setattr(box.cfg, name, real)
    _ingest(box, rerun)


def _recovery(box: _Box) -> None:
    """What the box runs first after a kill (the service's ``_undo_killed_load``, or the next ingest's start)."""
    with contextlib.suppress(publish_mod.FhirRestoreOutstanding):
        publish_mod.recover_all(box.cfg)


NIGHTS: dict[str, tuple[Callable[[_Box], Any], bool]] = {
    "a night": (lambda b: _ingest(b, False), False),
    "a night whose promotion fails once": (lambda b: _fails_once(b, False), False),
    "a re-run of the served night": (lambda b: _ingest(b, True), True),
    "a re-run whose lake step fails once": (lambda b: _fails_once(b, True), True),
}
# the publish's kill points from which the recovery is killed at each of its own (§ii: the cost kept down)
RECOVERY_FROM = ("FHIR store loaded", "lake promoted", "re-run swapped in")


def _run(box: _Box, night: Callable[[_Box], Any], *, kill_at: int = 0, hits: list[str] | None = None) -> bool:
    """Run ``night``; with ``kill_at``, die at that checkpoint (1 = the first). True when it was killed."""
    seen = [] if hits is None else hits
    first = len(seen)
    killed_at = box.root / "disk-at-the-kill"

    def checkpoint(name: str) -> None:
        seen.append(name)
        if len(seen) - first == kill_at:
            shutil.copytree(box.cfg.lake_dir, killed_at, symlinks=True)
            raise _Killed(name)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(publish_mod, "_checkpoint", checkpoint)
        try:
            night(box)
        except _Killed:
            _as_the_kill_left_it(box.cfg, killed_at)
            return True
    return False


def _owed_or_one_night(box: _Box, stub: Stub, where: str) -> None:
    """The invariant: the store is owed (derived from the intent and CURRENT), or it holds what CURRENT serves,
    resource by resource, the generation ledger has that night finished (review E2), and every folder the intent
    says the store holds is that one."""
    from adapter.pipeline import RERUN_DIR

    d = publish_mod.derive(box.cfg)
    if not d.clean:
        return
    served = box.lakes.lake.current()
    held = stub.held()
    assert d.served == served and d.intent["want"] == (served or ""), f"{where}: {d}"
    assert held == (_hashes(snapshot_dir(box.cfg.lake_dir, served)) if served else {}), f"{where}: store != CURRENT"
    assert served is None or _generation() == (served, "finished"), f"{where}: generation {_generation()}"
    home = snapshot_dir(box.cfg.lake_dir, "-").parent
    for f in sorted(f for f in [*home.glob("*"), *(box.cfg.lake_dir / RERUN_DIR).glob("*")] if f.is_dir()):
        if _loaded(box.cfg, f.name, f):
            assert _hashes(f) == held, f"{where}: the intent skips {f.name}'s load, which the store does not hold"


def _ndjson(folder: Path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in sorted(folder.glob("*.ndjson")))


def _settled(box: _Box, stub: Stub, rerun: bool, where: str, rep: Any = None) -> None:
    """The night is served, the store holds its folder resource by resource, and both carry the night's own value
    (review F5: a re-run whose folder and store both went back to the original N1 is not settled)."""
    from adapter.pipeline import RERUN_DIR

    night = box.n1 if rerun else box.n2
    assert rep is None or rep.passed, f"{where}: {rep.errors}"
    assert box.lakes.lake.current() == night, where
    assert _clean_at(box.cfg, night), f"{where}: {_state(box.cfg)}"
    folder = snapshot_dir(box.cfg.lake_dir, night)
    assert stub.held() == _hashes(folder), f"{where}: the store is not the night"
    store = json.dumps(httpx.get(f"{stub.root}/_resources", timeout=30).json())
    own, gone = ("2025-12-03", "2025-12-01") if rerun else ("2025-12-02", "")
    assert own in _ndjson(folder) and own in store, f"{where}: the night's own value is not served"
    assert not gone or (gone not in _ndjson(folder) and gone not in store), f"{where}: the original N1 is served"
    assert _generation() == (night, "finished"), f"{where}: generation {_generation()}"
    assert not list((box.cfg.lake_dir / RERUN_DIR).glob("*.replaced")), where


@pytest.mark.parametrize("phase", ["publish", "recovery"])
@pytest.mark.parametrize("name", list(NIGHTS))
def test_a_kill_at_every_checkpoint_leaves_the_store_owed_or_one_night(
    tmp_path: Path, stub: Stub, name: str, phase: str
) -> None:
    """§ii's two tables: ``publish``, a kill at each checkpoint of the night; ``recovery``, from each kill inside the
    FHIR load or the lake step, the recovery killed at each of its own checkpoints (enumerated from a recovery of that
    same kill state that is not killed), then a recovery that is not, then the night's resume."""
    night, rerun = NIGHTS[name]
    hits: list[str] = []
    dry = _box(tmp_path / "dry", stub, 0)
    assert not _run(dry, night, hits=hits)
    _settled(dry, stub, rerun, f"{name}, not killed")
    i = 0
    for k, point in enumerate(hits, start=1):
        if phase == "recovery" and point not in RECOVERY_FROM:
            continue
        where = f"{name}, killed after #{k} ({point})"
        i += 1
        box = _box(tmp_path / f"k{i}", stub, i)
        assert _run(box, night, kill_at=k), where
        _owed_or_one_night(box, stub, where)
        if phase == "recovery":
            back: list[str] = []
            assert not _run(box, _recovery, hits=back), where
            assert back, f"{where}: the recovery wrote nothing"
            for j, step in enumerate(back, start=1):
                again = f"{where}, its recovery killed after #{j} ({step})"
                i += 1
                box = _box(tmp_path / f"k{i}", stub, i)
                assert _run(box, night, kill_at=k), again
                assert _run(box, _recovery, kill_at=j), again
                _owed_or_one_night(box, stub, again)
                publish_mod.recover_all(box.cfg)
                _owed_or_one_night(box, stub, f"{again}, recovered")
                _settled(box, stub, rerun, again, _ingest(box, rerun))
            continue
        _unfenced_then_the_exit(box, stub, rerun, where)
        _settled(box, stub, rerun, where, _ingest(box, rerun))


def _unfenced_then_the_exit(box: _Box, stub: Stub, rerun: bool, where: str) -> None:
    """Review H4 (converted: such a kill was put back by the box itself): a kill that left the night's FHIR step
    ``loading`` (killed while its load may have had a transaction out) is refused by name, the recovery and the
    night's ingest alike, and nothing is sent; then the operator's exit (``FHIR_STATE`` removed)."""
    from adapter.pipeline import RERUN_DIR

    night = box.n1 if rerun else box.n2
    folders = (snapshot_dir(box.cfg.lake_dir, night), box.cfg.lake_dir / RERUN_DIR / night)
    if not any((publish_mod.read_record(f).get("steps") or {}).get("fhir") == "loading" for f in folders):
        return
    sent = len(stub.log())
    with pytest.raises(publish_mod.FhirRestoreOutstanding, match=publish_mod.UNFENCED):
        publish_mod.recover_all(box.cfg)
    with pytest.raises(publish_mod.FhirRestoreOutstanding, match=publish_mod.UNFENCED):
        _ingest(box, rerun)
    assert len(stub.log()) == sent, f"{where}: sent over a transaction that may still commit"
    (box.cfg.lake_dir / publish_mod.FHIR_STATE).unlink()


@pytest.mark.parametrize("kind", ["error", "malformed"])
@pytest.mark.parametrize("phase", ["publish", "recovery"])
@pytest.mark.parametrize("name", list(NIGHTS))
def test_a_store_fault_at_every_request_leaves_the_store_owed_or_one_night(
    tmp_path: Path, stub: Stub, name: str, phase: str, kind: str
) -> None:
    """§ii's store-fault column: ``publish``, each request of the night; ``recovery``, each request of the recovery
    after a kill right after the night's FHIR load."""
    night, rerun = NIGHTS[name]
    dry = _box(tmp_path / "dry", stub, 0)
    hits: list[str] = []
    k = 0
    if phase == "recovery":
        assert not _run(dry, night, hits=hits)
        k = hits.index("FHIR store loaded") + 1
        dry = _box(tmp_path / "dry2", stub, 1)
        assert _run(dry, night, kill_at=k)
    sent = len(stub.log())
    _run(dry, _recovery if phase == "recovery" else night)
    sent = len(stub.log()) - sent
    assert sent
    for j in range(1, sent + 1):
        where = f"{name}, {phase} store request #{j} answered {kind}"
        box = _box(tmp_path / f"r{j}", stub, j + 1)
        if phase == "recovery":
            assert _run(box, night, kill_at=k), where
        stub.control(fail_at={"n": j, "kind": kind})
        _run(box, _recovery if phase == "recovery" else night)
        assert stub.faults() == [kind], f"{where}: the fault was not injected"  # review M2
        _owed_or_one_night(box, stub, where)
        if phase == "recovery":
            publish_mod.recover_all(box.cfg)
        _settled(box, stub, rerun, where, _ingest(box, rerun))


def test_every_checkpoint_is_reached(tmp_path: Path, stub: Stub) -> None:
    """The nights above, and the recoveries after their kills, reach every checkpoint publish.py names (one that
    none reaches fails here): the swap-back of a re-run killed right after its swap included."""
    src = Path(publish_mod.__file__).read_text(encoding="utf-8")
    names = set(re.findall(r'_checkpoint\(f?"([^"]+)"\)', src))
    names |= {publish_mod.FHIR_STATE, publish_mod.RECORD, "passed.json"}
    hits: list[str] = []
    for i, (night, _rerun) in enumerate(NIGHTS.values()):
        _run(_box(tmp_path / f"n{i}", stub, i), night, hits=hits)
    rerun = NIGHTS["a re-run of the served night"][0]
    probe: list[str] = []
    _run(_box(tmp_path / "probe", stub, len(NIGHTS)), rerun, hits=probe)
    box = _box(tmp_path / "swap", stub, len(NIGHTS) + 1)
    assert _run(box, rerun, kill_at=probe.index("re-run swapped in") + 1)
    _run(box, _recovery, hits=hits)
    assert {"served folder renamed aside", "served folder put back", "FHIR store put back"} <= set(hits)
    _run(box, rerun, hits=hits)
    assert names <= set(hits), sorted(names - set(hits))


# --------------------------------------------------------- the last round on #1566 (H1-H5, M1-M3; G1, G2)
def _restored_with_another_value(folder: Path) -> None:
    """The night's Condition NDJSON as a same-date restore leaves it: another value under the same id; CURRENT and
    the folder's ``publish.json`` as they were."""
    f = folder / "Condition.ndjson"
    text = f.read_text(encoding="utf-8")
    assert "2026-09-01" in text
    f.write_text(text.replace("2026-09-01", "2026-09-30"), encoding="utf-8")


def _gate(cfg: Any) -> Any:
    from tools.trialbox import doctor

    return doctor.check_publish_gate(doctor.DoctorInputs(ingest_lake=cfg.lake_dir))


def test_a_retry_of_an_older_published_night_sends_nothing(tmp_path: Path, stub: Stub) -> None:
    """Review H1: N1 and N2 are both published (the same ids, another value). N1 asked for again with its own record
    (every step done) is refused before any step, whatever its record says: a newer night is served. Nothing reaches
    the store, the intent still says N2, checked. A forward load the generation ledger refuses as older is an error,
    never "loaded"."""
    cfg, lakes = _stub_cfg(tmp_path, stub)
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"]), snapshot=N1,
                      validate=False).passed  # fmt: skip
    assert run_ingest(cfg, "csv", _night(tmp_path, "n2", [_row("D1", "2026-09-02")], ["10000001"]), snapshot=N2,
                      validate=False).passed  # fmt: skip
    folder1, served = snapshot_dir(cfg.lake_dir, N1), _hashes(snapshot_dir(cfg.lake_dir, N2))
    assert set(_record(folder1).values()) <= {"done", "skipped"} and stub.held() == served != _hashes(folder1)
    before, sent = (cfg.lake_dir / "FHIR_STATE").read_bytes(), len(stub.log())
    out = publish_mod.publish_night(cfg, N1, folder1)
    assert out.stale and not out.ok and not out.promoted and lakes.lake.current() == N2
    assert len(stub.log()) == sent and stub.held() == served
    assert (cfg.lake_dir / "FHIR_STATE").read_bytes() == before and _clean_at(cfg, N2)
    with pytest.raises(load_fhir.LedgerError, match="older"):
        publish_mod._sync_fhir(cfg, folder1, None)
    assert len(stub.log()) == sent


def test_a_fresh_box_refuses_a_fhir_only_first_night(tmp_path: Path, stub: Stub) -> None:
    """Review H2 (G1 of the second reviewer): a box that never published; a first night asked for with the FHIR store
    on and its lake step off. It is refused before any step, the ingest and the direct publish alike: nothing reaches
    the store, no intent, no PASSED. So no later recovery finds a store loaded with a night the lake never served
    (and puts it back to nothing)."""
    from adapter.pipeline import PASSED

    cfg, lakes = _stub_cfg(tmp_path, stub)
    night = _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"])
    with pytest.raises(publish_mod.NightRefused, match=r"\(fhir on, lake off; the store holds nothing\)"):
        run_ingest(cfg, "csv", night, snapshot=N1, rebuild_lake=False, validate=False)
    assert stub.log() == [] and not (cfg.lake_dir / "FHIR_STATE").exists()
    run_ingest(cfg, "csv", night, snapshot=N1, load_fhir=False, rebuild_lake=False, validate=False)  # both off
    folder = _copy_night(cfg, N2)
    out = publish_mod.publish_night(cfg, N2, folder, rebuild_lake=False)
    assert out.errors[0].startswith("night refused:") and set(out.steps.values()) == {"pending"}
    assert stub.log() == [] and not (cfg.lake_dir / "FHIR_STATE").exists() and not (folder / PASSED).exists()
    assert lakes.lake.current() is None


def test_changed_data_under_a_stale_record_is_owed(tmp_path: Path, stub: Stub) -> None:
    """Review H3: N1 is served and checked; its served NDJSON is then replaced by another value under the same id (a
    same-date restore), ``CURRENT`` and ``publish.json`` as they were. The fingerprint is the data's, never the
    record's: the store is owed, and the recovery puts the new value in."""
    cfg, _lakes = _stub_cfg(tmp_path, stub)
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"]), snapshot=N1,
                      validate=False).passed  # fmt: skip
    served = snapshot_dir(cfg.lake_dir, N1)
    record = (served / "publish.json").read_bytes()
    _restored_with_another_value(served)
    assert (served / "publish.json").read_bytes() == record and stub.held() != _hashes(served)
    assert not publish_mod.derive(cfg).clean
    publish_mod.recover_all(cfg)
    assert stub.held() == _hashes(served) and _clean_at(cfg, N1)
    assert "2026-09-30" in json.dumps(httpx.get(f"{stub.root}/_resources", timeout=30).json())


def test_a_lake_restored_behind_the_generation_ledger_is_refused(tmp_path: Path, stub: Stub) -> None:
    """Review G2 (detect and refuse: a known limitation). N1, then N2, are published and checked; the lake is then
    restored to where it served N1 (``CURRENT`` and ``FHIR_STATE`` as they were then), the trial database is not:
    its generation ledger has the FHIR store finished at N2. The store is owed by that name and nothing is put back;
    every recovery and the next ingest are refused by it; the doctor fails by it. The same with ``FHIR_STATE`` as N2
    left it."""
    cfg, lakes = _stub_cfg(tmp_path, stub)
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"]), snapshot=N1,
                      validate=False).passed  # fmt: skip
    then = (cfg.lake_dir / "FHIR_STATE").read_bytes()
    assert run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False).passed
    now, held = (cfg.lake_dir / "FHIR_STATE").read_bytes(), stub.held()
    for intent in (then, now):
        (cfg.lake_dir / "CURRENT").write_text(N1, encoding="utf-8")  # the lake's restore
        (cfg.lake_dir / "FHIR_STATE").write_bytes(intent)
        sent = len(stub.log())
        for _ in range(2):
            with pytest.raises(publish_mod.FhirRestoreOutstanding, match=publish_mod.LAKE_BEHIND):
                publish_mod.recover_all(cfg)
        st = _state(cfg)
        assert st["verified"] is False and st["reason"].startswith(publish_mod.LAKE_BEHIND) and st["want"] == N1
        assert stub.held() == held and len(stub.log()) == sent and _generation() == (N2, "finished")
        lakes.calls.clear()
        with pytest.raises(publish_mod.FhirRestoreOutstanding, match=publish_mod.LAKE_BEHIND):
            run_ingest(cfg, "csv", _night(tmp_path, "n3", [_row("D3", "2026-09-03")], ["10000001"]), snapshot=N3,
                       validate=False)  # fmt: skip
        assert lakes.calls == [] and lakes.lake.current() == N1 and len(stub.log()) == sent
        gate = _gate(cfg)
        assert gate.status == "FAIL" and publish_mod.LAKE_BEHIND in gate.detail, gate


def _killed_with_a_transaction_out(tmp_path: Path, cfg: Any, mp: pytest.MonkeyPatch) -> None:
    """N2's publisher dies right after the store took one of its transactions, before its answer was read."""
    killed_at = tmp_path / "disk-at-the-kill"
    real = load_fhir.post_batches

    def killed_after_sending(base_url: str, resources: Any, workers: int = 4, timeout: float = 600) -> int:
        real(base_url, resources, workers, timeout)
        shutil.copytree(cfg.lake_dir, killed_at, symlinks=True)
        raise _Killed("the store has the transaction; its publisher is gone")

    mp.setattr(load_fhir, "post_batches", killed_after_sending)
    with pytest.raises(_Killed):
        run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False)
    mp.setattr(load_fhir, "post_batches", real)
    _as_the_kill_left_it(cfg, killed_at)


def test_a_publisher_killed_with_a_transaction_out_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub: Stub
) -> None:
    """Review H4 (detect and refuse: a known limitation). N2's publisher dies while a transaction of its load is out:
    the store may still commit it, and nothing fences it. So the recovery puts nothing back and settles nothing: the
    store is owed by name, every recovery and the next ingest are refused by it, the doctor fails by it. The
    operator's exit (the FHIR store restarted, then ``FHIR_STATE`` removed) puts the store back to the served night,
    once."""
    cfg, lakes = _stub_cfg(tmp_path, stub)
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"]), snapshot=N1,
                      validate=False).passed  # fmt: skip
    served = _hashes(snapshot_dir(cfg.lake_dir, N1))
    _killed_with_a_transaction_out(tmp_path, cfg, monkeypatch)
    left, sent = stub.held(), len(stub.log())
    assert left != served and lakes.lake.current() == N1
    for _ in range(2):
        with pytest.raises(publish_mod.FhirRestoreOutstanding, match=publish_mod.UNFENCED):
            publish_mod.recover_all(cfg)
    st = _state(cfg)
    assert st["verified"] is False and st["reason"].startswith(publish_mod.UNFENCED) and st["want"] == N1
    assert stub.held() == left and len(stub.log()) == sent
    lakes.calls.clear()
    with pytest.raises(publish_mod.FhirRestoreOutstanding, match=publish_mod.UNFENCED):
        run_ingest(cfg, "csv", _night(tmp_path, "n3", [_row("D3", "2026-09-03")], ["10000001"]), snapshot=N3,
                   validate=False)  # fmt: skip
    assert lakes.calls == [] and lakes.lake.current() == N1 and len(stub.log()) == sent
    gate = _gate(cfg)
    assert gate.status == "FAIL" and publish_mod.UNFENCED in gate.detail, gate
    (cfg.lake_dir / "FHIR_STATE").unlink()  # the operator's exit, once the FHIR store was restarted
    publish_mod.recover_all(cfg)
    assert stub.held() == served and _clean_at(cfg, N1) and _gate(cfg).status != "FAIL"


def test_a_store_request_without_an_answer_in_time_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub: Stub
) -> None:
    """Review H4, the same limitation in process: a transaction of N2's load gets no answer in time (the store may
    still commit it). The publish does not put the store back over it: the FHIR step failed, nothing promoted, the
    store owed by name; the next recovery is refused by it."""
    cfg, lakes = _stub_cfg(tmp_path, stub)
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"]), snapshot=N1,
                      validate=False).passed  # fmt: skip

    def no_answer(*args: Any, **kwargs: Any) -> int:
        raise httpx.ReadTimeout("no answer in time")

    monkeypatch.setattr(load_fhir, "post_batches", no_answer)
    sent = len(stub.log())
    rep = run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False)
    assert not rep.passed and lakes.lake.current() == N1 and len(stub.log()) == sent
    assert any(publish_mod.UNFENCED in e for e in rep.errors or []), rep.errors
    assert _state(cfg)["reason"].startswith(publish_mod.UNFENCED)
    with pytest.raises(publish_mod.FhirRestoreOutstanding, match=publish_mod.UNFENCED):
        publish_mod.recover_all(cfg)
    assert len(stub.log()) == sent


def test_a_store_request_never_sent_is_put_back_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub: Stub
) -> None:
    """Review H4's refusal is for a request the store may have taken: one that never reached it (no connection) is
    an ordinary failure. The store is owed by its type, and the next recovery puts it back and settles it."""
    cfg, lakes = _stub_cfg(tmp_path, stub)
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"]), snapshot=N1,
                      validate=False).passed  # fmt: skip
    real = load_fhir.post_batches

    def no_connection(*args: Any, **kwargs: Any) -> int:
        raise httpx.ConnectError("no connection")

    monkeypatch.setattr(load_fhir, "post_batches", no_connection)
    rep = run_ingest(cfg, "csv", _night2(tmp_path), snapshot=N2, validate=False)
    assert not rep.passed and lakes.lake.current() == N1
    assert not _state(cfg)["reason"].startswith(publish_mod.UNFENCED), _state(cfg)
    monkeypatch.setattr(load_fhir, "post_batches", real)
    publish_mod.recover_all(cfg)
    assert stub.held() == _hashes(snapshot_dir(cfg.lake_dir, N1)) and _clean_at(cfg, N1)


def test_a_put_back_request_without_an_answer_in_time_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub: Stub
) -> None:
    """Review H4, on the put-back's own load: a put-back to N1 is owed and one of its transactions gets no answer in
    time. The store is owed by name, and the next recovery sends nothing over it."""
    cfg, _lakes = _stub_cfg(tmp_path, stub)
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")], ["10000001"]), snapshot=N1,
                      validate=False).passed  # fmt: skip
    _put_state(cfg, _owed(N2, N1))

    def no_answer(*args: Any, **kwargs: Any) -> int:
        raise httpx.ReadTimeout("no answer in time")

    real = load_fhir.post_batches
    monkeypatch.setattr(load_fhir, "post_batches", no_answer)
    with pytest.raises(publish_mod.FhirRestoreOutstanding, match=publish_mod.UNFENCED):
        publish_mod.recover_all(cfg)
    sent = len(stub.log())
    monkeypatch.setattr(load_fhir, "post_batches", real)
    with pytest.raises(publish_mod.FhirRestoreOutstanding, match=publish_mod.UNFENCED):
        publish_mod.recover_all(cfg)
    assert len(stub.log()) == sent and _state(cfg)["reason"].startswith(publish_mod.UNFENCED)


def test_a_full_volume_from_the_intent_on_fails_the_step_not_the_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review M1 (G3 of the second reviewer): the lake volume is full from the intent's write on, so the record of
    the failed step cannot be written either. ``publish_night`` still returns: the FHIR step failed, nothing sent,
    nothing promoted."""
    cfg, lakes, fhir = _served_n1(tmp_path, monkeypatch)
    real = publish_mod._durable
    full: list[str] = []

    def durable(path: Path, text: str) -> None:
        if path.name == publish_mod.FHIR_STATE and N2 in text:
            full.append(path.name)
        if full:
            raise OSError(28, "No space left on device")
        real(path, text)

    monkeypatch.setattr(publish_mod, "_durable", durable)
    fhir.calls = []
    out = publish_mod.publish_night(cfg, N2, _copy_night(cfg, N2), last_good=N1)
    assert full and out.steps["fhir"] == "failed" and not out.promoted and lakes.lake.current() == N1
    assert any(e.startswith("fhir-store load failed: OSError") for e in out.errors), out.errors
    assert fhir.calls == []


def test_an_ingest_that_meets_a_running_lake_build_is_busy_not_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review M3: a CLI ingest (``adapter.run_job``) starts while a killed re-run's lake build of the served night
    still runs (its swap left on disk). The recovery says the lake is busy: the run is refused by that, not
    ``failed``, and nothing of it reaches OMOP or the lake."""
    import lake.build
    import tb_common.logging
    from adapter import cli, dual_write, run_job, runs
    from adapter.pipeline import RERUN_DIR
    from lake.store import building

    cfg, lakes, _fhir = _served_n1(tmp_path, monkeypatch)
    omop: list[str] = []
    monkeypatch.setattr(dual_write, "load_night", lambda c, s, nd: omop.append(s))
    monkeypatch.setattr(cli, "build_config", lambda: (cfg, "csv", ""))
    monkeypatch.setattr(tb_common.logging, "setup_logging", lambda service, level="INFO": None)
    monkeypatch.setattr(lake.build, "prefer_me_when_memory_runs_out", lambda: None)
    lakes.calls.clear()
    (cfg.lake_dir / RERUN_DIR / f"{N1}.replaced").mkdir(parents=True)  # what the killed re-run left
    lock = runs.RunLock(cfg.lake_dir)
    state = {"run": "pthreem", "state": "running", "started": "2026-10-04T17:00:00+00:00", "ended": None, "detail": ""}
    runs.hold(cfg.lake_dir, "pthreem")
    runs.write(cfg.lake_dir, state)
    fd = os.dup(lock.fileno())
    lock.hand_over()
    req = {"source": "csv", "path": _night2(tmp_path), "since": None, "snapshot": N2, "load_fhir": True,
           "rebuild_lake": True, "validate": False}  # fmt: skip
    with building(cfg.lake_dir, N1):
        assert run_job.main([str(fd), json.dumps({"state": state, "lake_dir": str(cfg.lake_dir), "request": req})]) == 0
    end = runs.read(cfg.lake_dir, "pthreem")
    assert end is not None and end["state"] == "refused", end
    assert end["detail"].startswith("night refused:") and N1 in end["detail"], end
    assert omop == [] and lakes.calls == [] and lakes.lake.current() == N1
