"""H-106: the external review of #1452 at f724fbf (7126707961), one test per finding fixed here.

1452-1 (High): a test box's update (the serving check, the terminology volume), its decommission plan and its host
check name its own project's objects. 1452-2 (Medium): PRODUCTION's refusal of a host with a test box fails closed (a
test box whose folder is gone; a listing that fails; two installs together wait on the host's lock). 1452-3 (Medium):
a test box whose record is lost is refused, never run as the ordinary box. Lows: 1452-4 (testboxes.sh names), 1452-5
(remove never takes another box's folder), 1452-6 (an empty name), 1452-7 (ASCII digits), 1452-8 (one name, one
offset a host).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_test_box_h106 import TEST_ARGS, Engine, H106Box
from tools.trialbox import testbox

pytestmark = [pytest.mark.nodb, pytest.mark.skipif(sys.platform != "linux", reason="bash and GNU tools")]
ROOT = Path(__file__).resolve().parents[2]


def _test_box(tmp: Path) -> tuple[Path, testbox.Box]:
    d = tmp / "a" / "deploy"
    (d / "site").mkdir(parents=True)
    box = testbox.record(d, "a", "1")
    (d / ".env").write_text("\n".join([*box.lines(), "TB_ENV=TEST", "COMPOSE_PROFILES=gpu", ""]), encoding="utf-8")
    (d / ".env").chmod(0o600)
    return d, box


# ------------------------------------------------------------------------------------------------ 1452-1 (High)
def test_1452_1_a_test_box_s_update_serving_check_and_terminology_are_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import update as up

    d, box = _test_box(tmp_path)
    calls: list[str] = []

    def run(argv: Sequence[str], **_kw: Any) -> str:
        calls.append(" ".join(argv))
        return ""

    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    cb = up.ComposeBox(d, run=run)
    cb.check_serving()
    f = tmp_path / "stage" / "icd10cm" / "codes.txt"
    f.parent.mkdir(parents=True)
    f.write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(up, "terminology_files", lambda plan: [f])
    plan = up.Plan.__new__(up.Plan)
    object.__setattr__(plan, "bundle_id", "b1")
    with contextlib.suppress(Exception):  # the stand-in runner answers nothing: the engine calls are what is checked
        cb.terminology(plan)
    assert any(f"--network {box.project}-model-net " in c for c in calls), calls
    assert any(f"{box.project}_tb-terminology:/data/terminology" in c for c in calls), calls
    assert not [c for c in calls if "trialbox-model-net" in c or "trialbox_tb-terminology" in c], calls


def test_1452_1_a_test_box_s_decommission_plan_names_its_own_volumes(tmp_path: Path) -> None:
    from tools.trialbox import decommission

    d, box = _test_box(tmp_path)
    (d / "docker-compose.yml").write_bytes((ROOT / "deploy" / "docker-compose.yml").read_bytes())
    stores = [s for s in decommission.stores(d, testbox.read_env(d / ".env")) if s.name.startswith("volume ")]
    assert stores and all(f"/{box.project}_" in s.where for s in stores), stores[:2]
    plain = decommission.stores(d, {})
    assert all("/trialbox_" in s.where for s in plain if s.name.startswith("volume "))  # the ordinary box: as before


def test_1452_1_the_host_check_of_a_test_box_reads_its_own_secrets_volume(tmp_path: Path) -> None:
    d, box = _test_box(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "COMPOSE_"))}
    r = subprocess.run(["sh", str(ROOT / "deploy" / "check_host.sh"), "--env", str(d / ".env")], env=env,
                       capture_output=True, text=True, timeout=120, check=False)  # fmt: skip
    assert f"/var/lib/docker/volumes/{box.project}_tb-secrets/_data" in r.stdout, r.stdout[-2000:]
    assert "trialbox_tb-secrets" not in r.stdout


# ------------------------------------------------------------------------------------------------ 1452-2 (Medium)
def test_1452_2_production_refuses_a_test_box_whose_folder_is_gone(tmp_path: Path) -> None:
    p = H106Box(tmp_path / "prod", env="TB_ENV=PRODUCTION\n")
    gone = tmp_path / "gone"  # the test box's folder was removed; its containers and volumes run on
    proj = testbox.project_for("walk", gone)
    r = p.run("--environment", "PRODUCTION", *TEST_ARGS, engine=f"volume {proj}\ndir {proj} {gone / 'deploy'}\n")
    assert r.rc == 1 and r.err.splitlines()[-1].startswith(f"install: this host runs test boxes ({proj})"), r.err[-800:]
    assert not (p.tmp / "current").exists()


def test_1452_2_production_refuses_when_the_boxes_cannot_be_listed(tmp_path: Path) -> None:
    """A listing that fails (here: a record in the folder that names no box, so it cannot be read) is no longer read
    as "no test box": only an engine that cannot be asked at all (exit 3) leaves the install as before."""
    p = H106Box(tmp_path / "prod", env="TB_ENV=PRODUCTION\n")
    (p.deploy / testbox.RECORD).write_text("COMPOSE_PROJECT_NAME=tbt-x-000000\n", encoding="utf-8")
    r = p.run("--environment", "PRODUCTION", *TEST_ARGS)
    assert r.rc == 1 and "the boxes on this host could not be listed" in r.err.splitlines()[-1], r.err[-800:]
    assert not (p.tmp / "current").exists()


def test_1452_2_two_installs_never_both_pass_the_host_check(tmp_path: Path) -> None:
    """The host's lock: while another install holds it, a test-box (or PRODUCTION) install waits for it before it
    looks at the host's boxes, then goes on (a wait, never a stop). The installer runs as root on a host, where the
    lock file can always be opened; a user who cannot open one another account made installs without it, as before."""
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert text.index("# HOST-LOCK (H-106") < text.index("TB_OTHERS=") < text.index("# ---- end of TEST-BOX: the host")
    lock = Path("/run/lock/trialbox-boxes.lock")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    except PermissionError:  # another account's lock file (a root install ran here): the install takes no lock
        r = H106Box(tmp_path / "t").run("--test-box", "w", "--port-offset", "1", *TEST_ARGS)
        assert r.rc == 0 and "holds this host's lock" not in r.err, r.text[-1500:]
        return
    fcntl.flock(fd, fcntl.LOCK_EX)
    released: list[float] = []

    def release() -> None:
        time.sleep(3)
        released.append(time.monotonic())
        fcntl.flock(fd, fcntl.LOCK_UN)

    holder = threading.Thread(target=release)
    holder.start()
    try:
        r = H106Box(tmp_path / "t").run("--test-box", "w", "--port-offset", "1", *TEST_ARGS)
        done = time.monotonic()
    finally:
        holder.join()
        os.close(fd)
    assert r.rc == 0 and released and done >= released[0], r.text[-1500:]  # it waited for the lock, then went on
    assert "holds this host's lock" not in r.err  # the note is a terminal's only: a captured output never varies


# ------------------------------------------------------------------------------------------------ 1452-3 (Medium)
@pytest.mark.parametrize("lost", ["empty", "removed"])
def test_1452_3_a_lost_record_is_refused_not_an_ordinary_box(tmp_path: Path, lost: str) -> None:
    t = H106Box(tmp_path / "t")
    assert t.run("--test-box", "t", "--port-offset", "1", *TEST_ARGS).rc == 0
    rec = t.deploy / testbox.RECORD
    if lost == "empty":
        rec.write_text("", encoding="utf-8")
    else:
        rec.unlink()
    r = t.run(*TEST_ARGS)
    assert r.rc == 1 and "its record (deploy/site/test-box.env) is missing or empty" in r.err, r.text[-1500:]
    assert not list((t.tmp / "cron").iterdir())  # the host's cron files are never the test box's


def test_1452_3_the_record_is_written_to_the_disk_before_it_is_renamed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[int] = []
    real = os.fsync

    def fsync(fd: int) -> None:
        synced.append(fd)
        real(fd)

    monkeypatch.setattr(os, "fsync", fsync)  # the one os module testbox imports
    d = tmp_path / "x" / "deploy"
    (d / "site").mkdir(parents=True)
    testbox.record(d, "f", "1")
    assert len(synced) == 2  # the file, then its folder (the rename)


# ------------------------------------------------------------------------------------------------ 1452-4 .. 1452-8
@pytest.mark.parametrize("spec", ["../esc:1", "Walk:1", "a;b:1", ":1", "toolongname123:1", "ok:x"])
def test_1452_4_a_bad_spec_is_refused_before_anything(tmp_path: Path, spec: str) -> None:
    (tmp_path / "b.tar").write_bytes(b"x")
    (tmp_path / "k.pub").write_bytes(b"x")
    r = subprocess.run(["bash", str(ROOT / "tools" / "testboxes.sh"), "up", str(tmp_path / "b.tar"), "--pub",
                        str(tmp_path / "k.pub"), "--parent", str(tmp_path / "parent"), spec],
                       capture_output=True, text=True, timeout=120, check=False)  # fmt: skip
    made = sorted(p.name for p in tmp_path.rglob("*") if p.name not in ("b.tar", "k.pub"))
    assert r.returncode == 2 and made == [] and "NAME is a lower-case letter" in r.stderr, (r.returncode, made)


def test_1452_5_remove_refuses_a_folder_that_holds_another_box(tmp_path: Path) -> None:
    roots = {}
    for name, folder in (("a", tmp_path / "a"), ("b", tmp_path / "a" / "b")):
        (folder / "deploy" / "site").mkdir(parents=True)
        roots[testbox.record(folder / "deploy", name, "1" if name == "a" else "2").project] = str(folder)
    eng = Engine(roots)
    with pytest.raises(testbox.Refused, match="holds another box's folder"):
        testbox.remove("a", eng, yes=True, say=lambda s: None)
    assert (tmp_path / "a" / "b" / "deploy" / testbox.RECORD).exists()
    assert not [c for c in eng.calls if "rm" in c[1:3] or "down" in c]  # nothing of either box was removed
    assert testbox.remove("b", eng, yes=True, say=lambda s: None) == 0 and (tmp_path / "a" / "deploy").exists()


def test_1452_6_an_empty_test_box_name_is_refused(tmp_path: Path) -> None:
    t = H106Box(tmp_path / "e")
    r = t.run("--test-box", "", "--environment", "TEST", *TEST_ARGS)
    assert r.rc == 1 and r.err.splitlines()[-1].startswith("install: --test-box needs a NAME"), r.text[-1500:]
    assert not (t.tmp / "current").exists() and not (t.deploy / ".env").exists()


@pytest.mark.parametrize(("offset", "gpus", "cap"), [("²", "", ""), ("٣", "", ""), ("1", "٣", ""),
                                                     ("1", "1", "٣٢")])  # fmt: skip
def test_1452_7_non_ascii_digits_are_refused(offset: str, gpus: str, cap: str) -> None:
    with pytest.raises(testbox.Refused):
        testbox.check_values(offset, gpus, cap)


@pytest.mark.parametrize("clash", ["name", "offset", "project"])
def test_1452_8_one_name_and_one_offset_a_host(tmp_path: Path, clash: str) -> None:
    a = tmp_path / "a" / "deploy"
    (a / "site").mkdir(parents=True)
    first = testbox.record(a, "walk", "1")
    engine = f"volume {first.project}\ndir {first.project} {a}\n"
    name, offset = {"name": ("walk", "2"), "offset": ("other", "1"), "project": ("trialbox", "3")}[clash]
    if clash == "project":
        prod = tmp_path / "walkbox" / "deploy"
        prod.mkdir(parents=True)
        (prod / ".env").write_text("TB_ENV=TEST\n", encoding="utf-8")
        engine = f"volume trialbox\ndir trialbox {prod}\n"
    b = H106Box(tmp_path / "b")
    r = b.run("--test-box", name, "--port-offset", offset, *TEST_ARGS, engine=engine)
    want = {"name": "test box 'walk' is already at", "offset": "port offset 1 is test box 'walk'",
            "project": "the name 'trialbox' is the project of another box"}[clash]  # fmt: skip
    assert r.rc == 1 and want in r.err, r.text[-1500:]
    assert not (b.deploy / testbox.RECORD).exists() and not (b.tmp / "current").exists()


# ------------------------------------------------------------------------------------------------ H106-14
def test_h106_14_the_heartbeat_s_sleep_never_holds_the_caller_s_output() -> None:
    """Found by the card's pre-push run (the integrator, 7130040223: an order-dependent failure is a finding): a heartbeat
    stopped between its `sleep &` and `s=$!` left the sleep running with the caller's output pipe, so whoever reads the
    install's output waited for it (a test's 120 s, a log's tee). The worst case, the heartbeat killed outright with its
    sleep running: the install's output still closes at once."""
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    start = text.index("alive_start() {")
    end = text.index("\n}\n", text.index("alive_stop() {")) + 3
    script = text[start:end] + 'alive_start test; sleep 0.5; kill -9 "$ALIVE_PID"; echo done\n'
    t0 = time.monotonic()
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=False)
    # the orphaned sleep ends by itself within 60 s; it holds no pipe of the caller's (what is checked)
    assert r.stdout.strip() == "done" and time.monotonic() - t0 < 10, r
