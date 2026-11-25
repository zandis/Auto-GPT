"""H-99 (the integrator's red 7105785224): the box's own update path updates a PoC box.

1. The preflight read the size of `hapi` as `trialbox` from the trial database; on the real roles
   (``deploy/docker/db-init/30-service-roles.sh``) `trialbox` may not connect to `hapi`, so the read was refused
   (``permission denied for database hapi``). Each size is now read on its own database as the role that dumps it.
   Tested on a throwaway cluster of its own with the real role script, through the box's own command lines.
2. On a PoC box (D-1091, ``tools/trialbox/stops.py``) no backup key is not one of the five stops: ``trialbox update``
   warns, lists it in ``deploy/site/poc-stops.jsonl`` and goes on without the backup (the rollback point's local
   dumps are its way back). PRODUCTION keeps its refusal word for word; a caller's ``TB_ENV`` changes nothing.
   Driven through the real entry (``python -m tools.trialbox update``, as ``tools/apply_update.sh`` runs it) with
   the commands answered by the update tests' fake runner (no Docker here).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_update_path import FakeRun
from tests.unit.test_update_safety import _main_apply_stage
from tools import pglocal
from tools.trialbox import stops
from tools.trialbox import update as up
from tools.trialbox.__main__ import main as trialbox_main

ROOT = Path(__file__).resolve().parents[2]
ROLES = ROOT / "deploy" / "docker" / "db-init" / "30-service-roles.sh"
POC = ("DEV", "TEST", "VALIDATION")


# ------------------------------------------------------------------------------------------- 1. the size reads
@pytest.fixture(scope="module")
def real_roles() -> Iterator[Path]:
    """A cluster of its own: `hapi` its superuser (the db image's POSTGRES_USER), the `hapi` database, the real
    role script applied (it gives `hapi` to the FHIR store's role and takes CONNECT from everyone else)."""
    try:
        b = pglocal.bindir()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    base = Path(os.environ["TB_TEST_ROOT"]) if os.environ.get("TB_TEST_ROOT") else None
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tb-h99-", dir=base))
    root.chmod(0o755)
    pglocal.ensure(root)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PATH=f"{b}:{env.get('PATH', '')}", PGHOST=str((root / "run").resolve()), POSTGRES_USER="hapi",
               TB_WF_DB=pglocal.DB, TB_DB_PW_FHIR_STORE="synthetic-fhir-store")  # fmt: skip
    try:
        for sql in ("CREATE ROLE hapi SUPERUSER LOGIN", "CREATE DATABASE hapi OWNER hapi"):
            r = subprocess.run([str(b / "psql"), "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c",
                                sql], env=env, capture_output=True, text=True, check=False)  # fmt: skip
            assert r.returncode == 0, r.stderr
        r = subprocess.run(["sh", str(ROLES)], env=env, capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stderr[-1500:]
        yield root
    finally:
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)


def _box_on(root: Path, deploy: Path, monkeypatch: pytest.MonkeyPatch) -> up.ComposeBox:
    """The site box, its ``compose exec -T db <cmd>`` run by the real runner against the cluster's socket."""
    monkeypatch.setenv("TB_COMPOSE", "dc")
    sock = str((root / "run").resolve())

    def run(argv: list[str], **kw: Any) -> str:
        if argv[:4] == ["dc", "exec", "-T", "db"]:
            return up.run_cmd([str(pglocal.bindir() / argv[4]), *argv[5:]], env={"PGHOST": sock}, **kw)
        if argv[:2] == ["docker", "info"]:  # OCR 1469-7: the engine's data root is the test's own, never the host's
            return f"{deploy.parent / 'docker-root'}\n"
        return ""  # the rest: no Docker here

    return up.ComposeBox(deploy, run=run)


def test_h99_the_size_reads_work_on_the_real_roles(
    real_roles: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    box = _box_on(real_roles, deploy, monkeypatch)
    # the red, as the walk saw it: the size of `hapi` asked as `trialbox` from the trial database
    with pytest.raises(up.UpdateFailed, match="permission denied for database hapi"):
        box._psql("SELECT pg_database_size('hapi')")
    plan = up.Plan("B1", "f" * 64, "v", [], tmp_path / "stage")
    needs = {what: n for _p, n, what in box.space_needs(plan, deploy / "updates")}
    assert needs["database dumps"] > 0 and needs["rollback script (largest database) on the db volume"] > 0
    for db, user in (("trialbox_wf", "trialbox"), ("hapi", "hapi")):  # apply_limit_s and backup read these
        assert (box.db_bytes(db, user) or 0) > 0, db


# ------------------------------------------------------------------------------------- 2. no backup key, the CLI
def _box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tb_env: str) -> tuple[Path, FakeRun]:
    """An installed, running site box with a backup target and no backup key; ``tb_env`` its deploy/.env's."""
    deploy = tmp_path / "deploy"
    (deploy / "updates").mkdir(parents=True)
    (deploy / "updates" / "installed.json").write_text(
        json.dumps({"format": "trialbox-installed/1", "release_seq": 1, "bundle_id": "B1", "state": {}})
    )
    (deploy / ".env").write_text((f"TB_ENV={tb_env}\n" if tb_env else "") + f"TB_BACKUP_TARGETS={tmp_path / 'nas'}\n")
    (tmp_path / "models/judge").mkdir(parents=True)
    (tmp_path / "models/judge/config.json").write_text("old")
    monkeypatch.setenv("TB_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("TB_COMPOSE", "dc")
    monkeypatch.setenv("TB_DOCKER", "true")
    monkeypatch.delenv("TB_SKIP_AUDIT", raising=False)
    monkeypatch.delenv("TB_BACKUP_PUBKEY", raising=False)
    run = FakeRun()

    class Box(up.ComposeBox):  # the box main_apply makes, its commands answered by the fake runner
        def __init__(self, d: Path, run_: Any = run) -> None:
            super().__init__(d, run=run_)

    monkeypatch.setattr(up, "ComposeBox", Box)
    return deploy, run


def _update(tmp_path: Path, deploy: Path) -> int:
    stage, summary = _main_apply_stage(tmp_path)
    return trialbox_main(["update", "--stage", str(stage), "--summary", str(summary), "--deploy", str(deploy)])


@pytest.mark.parametrize("env", POC)
def test_h99_a_poc_box_without_a_backup_key_updates_and_lists_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], env: str
) -> None:
    deploy, run = _box(tmp_path, monkeypatch, env)
    assert _update(tmp_path, deploy) == 0
    out, err = capsys.readouterr()
    assert "applied, checked and audited" in out
    assert "warning (PoC box, H-94): backup not possible: no backup key" in err
    lines = [" ".join(c) for c in run.calls]
    assert not any("docker run --rm --network trialbox-net" in ln for ln in lines)  # no backup container
    assert any("pg_dump -Fc --no-owner -U hapi -d hapi" in ln for ln in lines)  # the rollback point's own dumps
    entries, problems = stops.read(deploy)
    assert problems == [] and [(e.key, e.by) for e in entries] == [("update.backup", "trialbox update")]
    assert "no backup key" in entries[0].what and "rollback point" in entries[0].skipped
    hist = [json.loads(x) for x in (deploy / "updates/history.jsonl").read_text().splitlines()]
    skip = next(h for h in hist if h["step"].startswith("backup"))
    assert skip["step"] == "backup skipped (PoC box, H-99: deploy/site/poc-stops.jsonl)" and skip["ok"]


@pytest.mark.parametrize("caller", ["", "DEV"])
def test_h99_production_keeps_its_refusal_whatever_the_caller_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], caller: str
) -> None:
    """The twin: a box whose deploy/.env names no environment is PRODUCTION (D-127); a ``TB_ENV=DEV`` in the
    caller's environment is not the box's state."""
    deploy, run = _box(tmp_path, monkeypatch, "")
    if caller:
        monkeypatch.setenv("TB_ENV", caller)
    assert _update(tmp_path, deploy) == 1
    out, err = capsys.readouterr()
    key = deploy / "secrets" / "backup.pub"
    assert out.splitlines()[-1] == (f"update FAILED: backup not possible, nothing was changed: no backup key {key} "
                                    "(trialbox backup-keygen with hospital IT, RUNBOOK §5)")  # fmt: skip
    assert "warning" not in err and not (deploy / stops.LIST).exists()
    lines = [" ".join(c) for c in run.calls]
    assert not any("pg_dump" in ln or "dc stop" in ln for ln in lines)  # refused in the preflight
    assert (tmp_path / "models/judge/config.json").read_text() == "old"


def test_h99_production_with_the_key_still_backs_up_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deploy, run = _box(tmp_path, monkeypatch, "PRODUCTION")
    (deploy / "secrets").mkdir()
    (deploy / "secrets" / "backup.pub").write_text("pub")
    assert _update(tmp_path, deploy) == 0
    lines = [" ".join(c) for c in run.calls]
    assert any("docker run --rm --network trialbox-net" in ln for ln in lines)
    assert not (deploy / stops.LIST).exists()
