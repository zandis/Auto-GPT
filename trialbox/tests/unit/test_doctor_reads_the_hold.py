"""H-136: ``trialbox doctor`` reads the hold after a restore through the box.

The walk found the operator's check blind right after a restore: on the box's host the installed doctor could not
import the database client (``ModuleNotFoundError``), and given the box's libraries it had no address of the box's
database (``OperationalError``); either way the line was a WARN that passed. Now the host asks the box's ``db``
container through its compose project (``box_hold.read``), the image's doctor takes what the host read that way, and
held, released and unreadable are three lines; unreadable is a FAIL naming the cause.

The engine here is a stand-in for ``docker`` named in the box file (``TB_DOCKER``): it logs what it was asked and
with which environment, and runs the reader's SQL with the real ``psql`` on the test cluster, where the hold is set
by ``tb_common.flags`` as a restore and ``/ops/flags`` set it. Synthetic values only."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
FLAG = "screening.after_restore"


def _engine(tmp_path: Path, body: str) -> Path:
    """A stand-in for the container engine: logs its argv and environment, then runs ``body``."""
    log = tmp_path / "engine.log"
    exe = tmp_path / "engine" / "docker"
    exe.parent.mkdir(mode=0o700, parents=True)
    exe.write_text(
        "#!/bin/sh\n# synthetic stand-in for the container engine (H-136 tests)\n"
        f'printf "%s\\n" "$*" >> {shlex.quote(str(log))}\n'
        f'env | sort | sed "s/^/env: /" >> {shlex.quote(str(log))}\n' + body
    )
    exe.chmod(0o700)
    return exe


def _box(tmp_path: Path, engine: Path, extra: str = "") -> Path:
    deploy = tmp_path / "box" / "deploy"
    deploy.mkdir(parents=True)
    env = deploy / ".env"
    env.write_text(f"TB_ENV=TEST\nCOMPOSE_PROJECT_NAME=tbhold\nTB_DOCKER={engine}\n{extra}")
    env.chmod(0o600)
    return deploy


def _psql_engine(tmp_path: Path, db_url: str) -> Path:
    """The engine whose ``compose exec -T db psql ... -f -`` runs the reader's SQL on this test's own schemas."""
    from tb_common.db import split_url

    dsn, prefix = split_url(db_url)
    return _engine(
        tmp_path,
        f"sed 's/app\\.flag/{prefix}app.flag/g' | exec psql {shlex.quote(dsn)} -X -q -At -v ON_ERROR_STOP=1 -f -\n",
    )


def _flags(db_url: str, tmp_path: Path) -> Any:
    from tb_common.audit import AuditLog
    from tb_common.flags import Flags

    return Flags(url=db_url, audit=AuditLog(tmp_path / "audit"))


def _doctor(deploy: Path | None, *, in_image: bool = False, env: dict[str, str] | None = None) -> Any:
    from tools.trialbox import doctor

    return doctor.check_restore_hold(doctor.DoctorInputs(env=env or {}, box=deploy, in_image=in_image))


def test_held_released_and_unreadable_each_give_their_own_line(tmp_path: Path, db_url: str) -> None:
    deploy = _box(tmp_path, _psql_engine(tmp_path, db_url))
    never = _doctor(deploy)
    assert (never.status, never.detail.split(":")[0]) == ("PASS", "released")
    assert "never set" in never.detail

    flags = _flags(db_url, tmp_path)
    flags.set(FLAG, "held", actor="trialbox restore", reason="synthetic: 1 event after the backup to re-apply")
    held = _doctor(deploy)
    assert held.status == "WARN" and held.detail.startswith("HELD since ")
    assert "by trialbox restore" in held.detail and "synthetic: 1 event after the backup to re-apply" in held.detail
    assert "/ops/flags" in held.detail and "confirm" in held.detail  # the release path, with its second step

    flags.set(FLAG, "released", actor="console:admin", reason="synthetic: the events were re-applied")
    released = _doctor(deploy)
    assert released.status == "PASS" and released.detail.startswith("released (last change ")
    assert "by console:admin" in released.detail

    dead = _box(tmp_path / "dead", _engine(tmp_path / "dead", 'echo "service \\"db\\" is not running" >&2\nexit 1\n'))
    unread = _doctor(dead)
    assert unread.status == "FAIL" and unread.detail.startswith("UNREADABLE: ")
    assert 'service "db" is not running' in unread.detail  # the cause, named

    lines = [c.detail for c in (never, held, released, unread)]
    assert len(set(lines)) == 4 and len({c.status for c in (held, released, unread)}) == 3


@pytest.mark.parametrize(
    "case",
    [
        "no engine",
        "group-writable box file",
        "no box file",
        "not a declared value",
        "no reading",
        "image: handed unread",
        "image: handed garbage",
        "image: database refused",
    ],
)
def test_an_unreadable_hold_is_a_fail_naming_its_cause_never_a_warn(tmp_path: Path, case: str) -> None:
    from tests.conftest import NODB_URL
    from tools.trialbox import doctor

    env: dict[str, str] = {}
    in_image = case.startswith("image:")
    deploy: Path | None = None
    if case == "no engine":
        deploy = _box(tmp_path, tmp_path / "nowhere" / "docker")
        cause = "the container engine cannot be started here"
    elif case == "group-writable box file":
        deploy = _box(tmp_path, _engine(tmp_path, "echo '{\"stored\": false}'\n"))
        (deploy / ".env").chmod(0o620)
        cause = "can be written by group or others"
    elif case == "no box file":
        deploy = tmp_path / "empty" / "deploy"
        deploy.mkdir(parents=True)
        cause = "no box file at"
    elif case == "not a declared value":
        deploy = _box(tmp_path, _engine(tmp_path, 'echo \'{"stored": true, "value": "paused"}\'\n'))
        cause = "'paused', not a value the box declares"
    elif case == "no reading":
        deploy = _box(tmp_path, _engine(tmp_path, "echo SET\n"))
        cause = "gave no reading"
    elif case == "image: handed unread":
        env["TB_DOCTOR_RESTORE_HOLD"] = json.dumps({"state": "unread", "cause": "synthetic: compose exec db ended 1"})
        cause = "synthetic: compose exec db ended 1"
    elif case == "image: handed garbage":
        env["TB_DOCTOR_RESTORE_HOLD"] = "held-ish"
        cause = "the host's reading of the hold is not one"
    else:
        env["TB_DB_URL"] = NODB_URL
        cause = "OperationalError from the trial database"
    got = _doctor(deploy, in_image=in_image, env=env)
    assert got.status == "FAIL", got  # never a WARN that passes: the box may be held
    assert got.detail.startswith("UNREADABLE: ") and cause in got.detail, got.detail
    assert not doctor.ok([got])


def test_the_host_reads_through_the_box_never_its_own_database_or_a_callers_variable(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The host's own database address says released, a caller's hand-in says released, the caller's engine variables
    name another engine and project: the box says held, and the line is the box's."""
    _flags(db_url, tmp_path).set(FLAG, "released", actor="console:admin", reason="synthetic: the host's copy")
    box_says = {
        "stored": True,
        "value": "held",
        "by": "trialbox restore",
        "at": "2026-11-24 18:10:21 UTC",
        "reason": "synthetic: 2 events after the backup",
    }
    deploy = _box(tmp_path, _engine(tmp_path, f"echo {shlex.quote(json.dumps(box_says))}\n"))
    elsewhere = _engine(tmp_path / "caller", "echo '{\"stored\": false}'\n")
    for k, v in {
        "TB_DOCKER": str(elsewhere),
        "TB_COMPOSE": f"{elsewhere} compose",
        "COMPOSE_PROJECT_NAME": "other",
        "COMPOSE_FILE": "/elsewhere.yml",
        "DOCKER_HOST": "unix:///elsewhere.sock",
    }.items():
        monkeypatch.setenv(k, v)
    caller = {"TB_DB_URL": db_url, "TB_DOCTOR_RESTORE_HOLD": json.dumps({"state": "released"})}
    got = _doctor(deploy, in_image=False, env=caller)
    assert got.status == "WARN" and got.detail.startswith("HELD since 2026-11-24 18:10:21 UTC by trialbox restore")
    assert not (tmp_path / "caller" / "engine.log").exists()  # the caller's engine was never run
    log = (tmp_path / "engine.log").read_text()
    asked = log.splitlines()[0]
    assert asked == (
        f"compose --project-directory {deploy} exec -T db psql -X -q -At -v ON_ERROR_STOP=1 -U trialbox "
        "-d trialbox_wf -f -"
    )
    seen = {ln[5:].split("=", 1)[0] for ln in log.splitlines() if ln.startswith("env: ")}
    assert not seen & {"COMPOSE_PROJECT_NAME", "COMPOSE_FILE", "DOCKER_HOST", "TB_DB_URL", "TB_DOCKER", "TB_COMPOSE"}


def test_in_the_box_image_the_doctor_takes_the_hosts_reading(tmp_path: Path, db_url: str) -> None:
    """The host check's doctor runs in the image with no network and no engine: the host's reading through the box
    decides, not the image's database address (here a database that says released)."""
    _flags(db_url, tmp_path).set(FLAG, "released", actor="console:admin", reason="synthetic")
    handed = {
        "state": "held",
        "stored": True,
        "by": "trialbox restore",
        "at": "2026-11-24 18:10:21 UTC",
        "reason": "synthetic: 1 event",
    }
    got = _doctor(None, in_image=True, env={"TB_DB_URL": db_url, "TB_DOCTOR_RESTORE_HOLD": json.dumps(handed)})
    assert got.status == "WARN" and "HELD since 2026-11-24 18:10:21 UTC by trialbox restore" in got.detail
    # without a hand-in (a hospital platform's doctor job, on the database's network): the image's own address
    alone = _doctor(None, in_image=True, env={"TB_DB_URL": db_url})
    assert alone.status == "PASS" and alone.detail.startswith("released (last change ")


def test_the_reader_needs_only_the_hosts_standard_library_and_says_one_line(tmp_path: Path, db_url: str) -> None:
    """As the host check runs it: ``python3 -m tools.trialbox.box_hold <deploy>`` with no site-packages (the host's
    python3 has no database client), a bare environment, one JSON line; the doctor's inputs name the box."""
    from tools.trialbox import doctor

    deploy = _box(tmp_path, _psql_engine(tmp_path, db_url))
    _flags(db_url, tmp_path).set(FLAG, "held", actor="trialbox restore", reason="synthetic: 3 events")
    r = subprocess.run(
        [sys.executable, "-S", "-m", "tools.trialbox.box_hold", str(deploy)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"]},
        timeout=60,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    (line,) = r.stdout.splitlines()
    got = json.loads(line)
    assert (got["state"], got["by"], got["reason"]) == ("held", "trialbox restore", "synthetic: 3 events")
    inp = doctor.inputs_from(env_file=deploy / ".env", settings=None, routing=None, lake=None)
    assert inp.box == deploy.resolve()


def test_the_host_check_and_the_rehearsal_hand_the_hosts_reading_to_the_image() -> None:
    """Both doctors that run in the image are handed what the host read through the box (``box_hold``)."""
    for rel in ("deploy/check_host.sh", "tools/rehearse_box/box.sh"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "tools.trialbox.box_hold" in text, rel
        assert '-e TB_DOCTOR_RESTORE_HOLD="$' in text, rel
