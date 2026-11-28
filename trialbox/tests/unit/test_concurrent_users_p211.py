"""P2-11 (ASSESS-1-ADDENDUM D7): the site declares its concurrent users at install, the console is sized from them.

The audit's load run found no declared number of concurrent users and one console process (25 users: p95 2.76 s,
the process at 120-135 % CPU). Here: ``TB_CONSOLE_USERS`` is declared beside ``TB_SITE_PATIENTS`` (25 by default) and the
installer writes it with ``TB_CONSOLE_WORKERS`` sized from it; compose starts that many uvicorn workers; the service
level (p95 under 1 s on the common pages at the declared users) has its measuring function. Several workers must not
change what a person sees: the timers run in one process only (a notice goes once), and what one request leaves for
the next (the one-time password, a pilot proposal) is seen by every process.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from console import held, timers
from console.app import ConsoleSettings
from console.held import Held
from console.proposals import Proposal
from tb_common.config import DECLARED

from tests.unit.test_compose_limits import BASE, DEPLOY, _merge
from tools import console_timing
from tools.trialbox import console_size

ROOT = DEPLOY.parent


@pytest.fixture
def shm() -> Iterator[Path]:
    """A folder of its own on a tmpfs (what TB_CONSOLE_HELD_DIR names), removed after."""
    root = Path(tempfile.mkdtemp(dir="/dev/shm"))
    yield root
    shutil.rmtree(root)


def test_the_concurrent_users_are_declared_with_the_patient_count() -> None:
    assert DECLARED["TB_CONSOLE_USERS"].default == "25" and DECLARED["TB_CONSOLE_USERS"].kind == "int"
    assert "TB_CONSOLE_WORKERS" in DECLARED
    assert console_size.DEFAULT_USERS == 25 and console_size.SLO_P95_S == 1.0
    runbook = (ROOT / "docs" / "runbook" / "01-install-a-new-site.md").read_text(encoding="utf-8")
    assert "`TB_CONSOLE_USERS`" in runbook and "within 1 s at the 95th percentile" in runbook


@pytest.mark.parametrize(
    ("users", "cpus", "want"), [(25, 16, 3), (1, 16, 1), (10, 16, 1), (11, 16, 2), (25, 2, 2), (100, 16, 4)]
)
def test_workers_from_the_users(users: int, cpus: int, want: int) -> None:
    assert console_size.workers(users, cpus) == want


def test_install_writes_the_default_then_follows_a_declared_number(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TB_ENV=DEV\nTB_SITE_PATIENTS=50000\n", encoding="utf-8")
    assert console_size.main(["--env-file", str(env), "--write", "--cpus", "16"]) == 0
    text = env.read_text(encoding="utf-8")
    assert "TB_CONSOLE_USERS=25\n" in text and "TB_CONSOLE_WORKERS=3\n" in text and "TB_SITE_PATIENTS=50000" in text
    assert env.stat().st_mode & 0o777 == 0o600
    env.write_text(text.replace("TB_CONSOLE_USERS=25", "TB_CONSOLE_USERS=40"), encoding="utf-8")
    console_size.main(["--env-file", str(env), "--write", "--cpus", "16"])
    assert "TB_CONSOLE_WORKERS=4\n" in env.read_text(encoding="utf-8")


def test_a_worker_count_set_by_hand_is_kept_and_a_bad_number_refused(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TB_CONSOLE_USERS=60\nTB_CONSOLE_WORKERS=2\n", encoding="utf-8")
    console_size.main(["--env-file", str(env), "--write", "--cpus", "16"])
    assert "TB_CONSOLE_WORKERS=2\n" in env.read_text(encoding="utf-8")
    env.write_text("TB_CONSOLE_USERS=many\n", encoding="utf-8")
    with pytest.raises(ValueError, match="TB_CONSOLE_USERS"):
        console_size.main(["--env-file", str(env)])
    for bad in ("0", "-1", "two"):
        env.write_text(f"TB_CONSOLE_WORKERS={bad}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="TB_CONSOLE_WORKERS"):
            console_size.main(["--env-file", str(env), "--write"])


def test_compose_starts_the_sized_workers_and_install_sizes_them() -> None:
    console = _merge((BASE,))["console"]
    cmd = [str(x) for x in console["command"]]
    assert cmd[cmd.index("--workers") + 1] == "${TB_CONSOLE_WORKERS:-1}"
    # a read-only root with /tmp a tmpfs (console.held keeps its entries in TB_CONSOLE_HELD_DIR, checked memory at start)
    assert console["read_only"] is True and "/tmp" in [str(x).split(":")[0] for x in console["tmpfs"]]
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "python3 -m tools.trialbox.console_size --env-file deploy/.env --write" in install
    assert install.index("tools.trialbox.console_size") < install.index("tools.trialbox.pgsize")  # before the start


def test_the_timers_run_in_one_worker_process(tmp_path: Path) -> None:
    lock = tmp_path / "timers.lock"
    assert timers.owns(lock)
    other = subprocess.run(
        [sys.executable, "-c", "import sys; from console import timers; print(timers.owns(__import__('pathlib').Path(sys.argv[1])))",
         str(lock)],
        capture_output=True, text=True, check=True, env={"PYTHONPATH": ":".join(sys.path)},
    )  # fmt: skip
    assert other.stdout.strip() == "False"  # another process: the timers are this one's
    assert timers.start(None, {"TB_CONSOLE_TIMERS": "on"}, "UTC", lock=lock) is None  # a second start here neither


def test_what_one_request_leaves_is_seen_by_another_process_once(shm: Path) -> None:
    mine, other = Held("t", 60.0, shm), Held("t", 60.0, shm)  # two views of the same tmpfs
    mine.put("session-sha", ("alice", "pw", 1.0))
    # TB-09: the read and the first take in another process (another uvicorn worker), the second take here
    child = subprocess.run(
        [sys.executable, "-c", "import json, sys, pathlib; from console.held import Held; h = Held('t', 60.0, "
         "pathlib.Path(sys.argv[1])); print(json.dumps([h.get('session-sha'), h.pop('session-sha')]))", str(shm)],
        capture_output=True, text=True, check=True, env={"PYTHONPATH": ":".join(sys.path)},
    )  # fmt: skip
    assert json.loads(child.stdout) == [["alice", "pw", 1.0]] * 2  # JSON: a tuple comes back as a list
    assert mine.pop("session-sha") is None  # taken once
    assert (mine.folder.stat().st_mode & 0o777) == 0o700
    stale = Held("s", 0.05, shm)
    stale.put("k", 1)
    time.sleep(0.1)
    assert stale.get("k") is None and not list(stale.folder.iterdir())  # never returned, and removed
    # a pilot proposal travels as its fields and comes back equal (app.py: asdict, then Proposal(**...))
    prop = Proposal(line="screen S-1", source="grammar", intent="screen", notes=("a", "b"))
    mine.put("pid", {"proposal": asdict(prop), "session_sha": "s", "created": 1.0})
    raw = other.pop("pid")
    assert Proposal(**{**raw["proposal"], "notes": tuple(raw["proposal"]["notes"])}) == prop


def test_a_folder_made_by_someone_else_is_not_used(shm: Path) -> None:
    folder = Held("x", 60.0, shm).folder
    folder.chmod(0o755)
    with pytest.raises(PermissionError):
        Held("x", 60.0, shm)


def test_a_symbolic_link_in_the_folders_place_is_not_followed(shm: Path) -> None:
    # TB-01: another account makes the predictable name first, as a link to a private folder of the console's user
    target = shm / "private"
    target.mkdir(mode=0o700)
    (target / "unrelated").write_text("x", encoding="utf-8")
    (shm / f"tb-console-held-{os.getuid()}-l").symlink_to(target)
    with pytest.raises(PermissionError):
        Held("l", 0.0, shm)
    assert (target / "unrelated").exists()


def test_a_sweep_never_removes_a_fresh_entry_that_replaced_an_expired_one(
    shm: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # TB-02: between the sweep's expiry check and its removal, another worker keeps a fresh password under the key
    mine, other = Held("r", 0.5, shm), Held("r", 0.5, shm)
    mine.put("k", "old")
    time.sleep(0.6)
    real_unlink = os.unlink
    worker: list[threading.Thread] = []

    def unlink_after_a_replace(*args: Any, **kwargs: Any) -> None:
        if not worker:
            worker.append(threading.Thread(target=other.put, args=("k", "fresh")))
            worker[0].start()
            worker[0].join(0.5)  # the other worker's keep, done at once unless it waits for this removal
        real_unlink(*args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink_after_a_replace)
    mine.get("k")
    worker[0].join()
    monkeypatch.undo()
    assert other.get("k") == "fresh"


def test_a_clock_set_back_does_not_extend_a_password_nor_keep_one_dated_ahead(
    shm: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # TB-03: the wall clock goes back an hour while ten minutes and one second pass
    once = Held("c", 600.0, shm)
    once.put("k", "pw")
    start = time.monotonic()
    clock = SimpleNamespace(time=lambda: time.time() - 3600, monotonic=lambda: start + 601)
    monkeypatch.setattr(held, "time", clock)
    assert once.get("k") is None
    once.put("ahead", "pw")  # kept at start + 601: seen from start, it is dated in the future
    clock.monotonic = lambda: start
    assert once.get("ahead") is None


def test_the_held_root_is_named_in_the_settings_and_must_be_memory(
    tmp_path: Path, shm: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # TB-06: never wherever the process's temporary folder points; no default (the integrator's ruling): compose sets it
    assert DECLARED["TB_CONSOLE_HELD_DIR"].default == ""
    assert ConsoleSettings.from_env({}).held_dir is None
    assert ConsoleSettings.from_env({"TB_CONSOLE_HELD_DIR": ""}).held_dir is None
    assert ConsoleSettings.from_env({"TB_CONSOLE_HELD_DIR": str(tmp_path)}).held_dir == tmp_path
    mounts = tmp_path / "mountinfo"
    mounts.write_text("22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw\n", encoding="utf-8")
    monkeypatch.setattr(held, "MOUNTINFO", mounts, raising=False)
    with pytest.raises(PermissionError, match="TB_CONSOLE_HELD_DIR"):
        Held("d", 60.0, tmp_path)
    assert not list(tmp_path.glob("tb-console-held-*"))  # nothing made on a disk
    point = str(shm.resolve()).replace(" ", "\\040")
    with mounts.open("a", encoding="utf-8") as fh:
        fh.write(f"40 22 0:5 / {point} rw - tmpfs tmpfs rw\n")
    Held("d", 60.0, shm)  # a real tmpfs, named as a memory mount


def test_the_folder_itself_must_be_memory_not_only_its_parent(shm: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # TB-06: the parent is a tmpfs, the held folder itself another filesystem (a bind mount, a disk volume over it)
    folder = Held("m", 60.0, shm).folder
    ino = folder.stat().st_ino
    real = held.fd_type
    monkeypatch.setattr(held, "fd_type", lambda fd: "ext4" if os.fstat(fd).st_ino == ino else real(fd))
    with pytest.raises(PermissionError, match="ext4, not memory"):
        Held("m", 60.0, shm)
    # the kernel's answer for the opened folder: a tmpfs is memory, /proc is not
    for path, want in ((shm, "tmpfs"), (Path("/proc"), "proc")):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            assert real(fd) == want
        finally:
            os.close(fd)


def test_unset_the_held_store_refuses_by_name_and_makes_nothing(tmp_path: Path) -> None:
    # TB-06 ruling: TB_CONSOLE_HELD_DIR unset: the console starts, its held store refuses every keep, read and removal
    store = Held("once", 60.0, None)
    for act in (lambda: store.put("k", "pw"), lambda: store.get("k"), lambda: store.pop("k"), store.ready):
        with pytest.raises(held.HeldUnset, match="TB_CONSOLE_HELD_DIR is unset"):
            act()
    assert issubclass(held.HeldUnset, PermissionError)


def test_compose_gives_the_console_a_held_dir_on_its_tmpfs() -> None:
    console = _merge((BASE,))["console"]
    assert console["environment"]["TB_CONSOLE_HELD_DIR"] == "/tmp"
    assert "/tmp" in [str(x).split(":")[0] for x in console["tmpfs"]] and console["read_only"] is True


def test_a_lock_error_is_not_read_as_another_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # TB-04: no lock to be had (ENOLCK) is not "another worker runs the timers": the start fails and says why
    def no_locks(_fh: object, _op: int) -> None:
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(fcntl, "flock", no_locks)  # the module console.timers locks with
    with pytest.raises(OSError, match="No locks available"):
        timers.owns(tmp_path / "timers.lock")
    with pytest.raises(OSError, match="No locks available"):
        timers.start(None, {"TB_CONSOLE_TIMERS": "on"}, "UTC", lock=tmp_path / "timers.lock")


def test_the_service_level_is_measured_with_the_users_at_once() -> None:
    def fast(_path: str) -> tuple[int, dict[str, str]]:
        time.sleep(0.002)
        return 200, {}

    p95, bad = console_timing.under_load(fast, ["/home", "/studies"], users=25, rounds=2)
    assert bad == 0 and p95 < console_size.SLO_P95_S
    # TB-05: the clients start together, each in its own thread, so all of them are at the console at once (not a
    # fast one done before the last began, its thread then lent to the next; nor one at a time after the start)
    lock, full, now, peak = threading.Lock(), threading.Event(), [0], [0]

    def quick(_path: str) -> tuple[int, dict[str, str]]:
        with lock:
            now[0] += 1
            peak[0] = max(peak[0], now[0])
            if now[0] == 25:
                full.set()
        full.wait(5.0)  # the first calls are held until all 25 are in (or 5 s)
        with lock:
            now[0] -= 1
        return 200, {}

    console_timing.under_load(quick, ["/home"], users=25, rounds=1)
    assert peak[0] == 25
    p95, bad = console_timing.under_load(lambda _p: (503, {}), ["/about"], users=3, rounds=1)
    assert bad == 3

    def one_slow(path: str) -> tuple[int, dict[str, str]]:
        time.sleep(0.05 if path == "/slow" else 0.0)
        return 200, {}

    fast_paths = [f"/p{i}" for i in range(30)]
    p95, _bad = console_timing.under_load(one_slow, [*fast_paths, "/slow"], users=2, rounds=2)
    assert p95 >= 0.05  # the slow page is not hidden among thirty fast ones


@pytest.mark.timeout(60)
def test_a_load_the_host_cannot_start_fails_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    # TB-08: fewer threads than clients (the host would start no more): the started ones do not wait forever
    monkeypatch.setattr(console_timing, "START_S", 0.5)
    real = ThreadPoolExecutor
    monkeypatch.setattr(console_timing, "ThreadPoolExecutor", lambda max_workers: real(max_workers=2))
    with pytest.raises(console_timing.LoadNotGenerated, match="25 clients"):
        console_timing.under_load(lambda _p: (200, {}), ["/home"], users=25, rounds=1)

    class NoThirdThread(ThreadPoolExecutor):
        def submit(self, *args: Any, **kwargs: Any) -> Any:
            if len(self._threads) == 2:
                raise RuntimeError("can't start new thread")
            return super().submit(*args, **kwargs)

    monkeypatch.setattr(console_timing, "ThreadPoolExecutor", NoThirdThread)
    with pytest.raises(console_timing.LoadNotGenerated, match="25 clients"):
        console_timing.under_load(lambda _p: (200, {}), ["/home"], users=25, rounds=1)


def _install_step(tmp_path: Path, env_text: str | None) -> subprocess.CompletedProcess[str]:
    """The installer's own console-size step (cut from deploy/install.sh) run as install runs it (errexit, pipefail)."""
    text = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    start, end = "# P2-11 (ASSESS-1-ADDENDUM D7)", "# T-703 (D-751)"
    assert text.count(start) == 1 and text.count(end) == 1
    (tmp_path / "deploy").mkdir()
    if env_text is not None:
        (tmp_path / "deploy" / ".env").write_text(env_text, encoding="utf-8")
    script = (
        "set -euo pipefail\nindent() { sed 's/^/  /'; }\n"
        "stop_or_warn() { echo 'a stop of the registry' >&2; exit 1; }\n"
        + text[text.index(start) : text.index(end)]
        + "\necho CONTINUED\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(["bash", "-c", script], env=env, cwd=tmp_path, capture_output=True, text=True, check=False)


@pytest.mark.parametrize("env_text", ["TB_CONSOLE_USERS=many\n", "TB_CONSOLE_USERS=0\n", "TB_ENV=DEV\n", None])
def test_a_missing_or_bad_number_of_users_warns_uses_25_and_the_install_continues(
    tmp_path: Path, env_text: str | None
) -> None:
    r = _install_step(tmp_path, env_text)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "CONTINUED" in r.stdout and "a stop of the registry" not in out, out
    assert "warning" in out and "set TB_CONSOLE_USERS in deploy/.env to a whole number, then re-run" in out
    written = (tmp_path / "deploy" / ".env").read_text(encoding="utf-8")
    assert "TB_CONSOLE_USERS=25\n" in written and "TB_CONSOLE_WORKERS=" in written


def test_a_declared_number_of_users_raises_no_warning(tmp_path: Path) -> None:
    r = _install_step(tmp_path, "TB_CONSOLE_USERS=40\n")
    assert r.returncode == 0 and "CONTINUED" in r.stdout and "warning" not in r.stdout + r.stderr


def test_a_tool_that_cannot_run_still_warns_and_the_install_continues(tmp_path: Path) -> None:
    r = _install_step(tmp_path, "TB_CONSOLE_USERS=40\nTB_CONSOLE_WORKERS=two\n")
    assert r.returncode == 0 and "CONTINUED" in r.stdout and "warning" in r.stderr, r.stderr


@pytest.mark.parametrize("bad", ["two", "0", "-1"])
def test_a_bad_worker_override_is_corrected_to_one_with_a_warning_and_the_install_continues(
    tmp_path: Path, bad: str
) -> None:
    r = _install_step(tmp_path, f"TB_CONSOLE_USERS=40\nTB_CONSOLE_WORKERS={bad}\n")
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "CONTINUED" in r.stdout and "a stop of the registry" not in out, out
    assert "warning" in r.stderr and f"TB_CONSOLE_WORKERS={bad!r}" in r.stderr and "using 1" in r.stderr, r.stderr
    env_file = tmp_path / "deploy" / ".env"
    written = env_file.read_text(encoding="utf-8").splitlines()
    assert written.count("TB_CONSOLE_WORKERS=1") == 1 and f"TB_CONSOLE_WORKERS={bad}" not in written
    assert console_size.main(["--env-file", str(env_file), "--cpus", "16"]) == 0  # the written file now reads clean


def test_doctor_warns_when_the_console_users_are_not_set() -> None:
    from tools.trialbox import doctor

    for env in ({}, {"TB_CONSOLE_USERS": ""}, {"TB_CONSOLE_USERS": "many"}):
        c = doctor.check_console_users(doctor.DoctorInputs(env=env))
        assert (c.name, c.status) == ("console_users", "WARN"), env
        assert "using 25" in c.detail and "TB_CONSOLE_USERS" in c.detail
    ok = doctor.check_console_users(doctor.DoctorInputs(env={"TB_CONSOLE_USERS": "40"}))
    assert ok.status == "PASS" and "40" in ok.detail
