"""H-121 (the walk's red 7125822972, the integrator's 7125878918): the update's size check on a site's database roles.

The walk box's ``trialbox update`` failed with ``ERROR: permission denied for database hapi``. The update runs the
INSTALLED release's ``tools/trialbox/update.py`` (``tools/apply_update.sh`` runs ``python3 -m tools.trialbox update``
from the box's own tree), and the box's release predated H-99: it asked ``pg_database_size('hapi')`` as ``trialbox``
from ``trialbox_wf``. On a site's roles ``trialbox`` has no CONNECT on ``hapi``, and the function needs it.

The roles here are built by the install's own scripts, as the database image's first start builds them: the cluster's
superuser is ``hapi`` (compose's POSTGRES_USER) and the image's database is ``hapi`` (POSTGRES_DB); then
``deploy/docker/db-init/10-trialbox-wf.sh`` makes ``trialbox`` and ``trialbox_wf``, and ``30-service-roles.sh`` gives
``hapi`` to the FHIR store's role and takes CONNECT from everyone else. (``20-extensions.sh`` needs the image's
extensions, which a test server lacks; it changes no role or grant.) The box's own command lines run against it.
Passwords are synthetic test strings.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tools import pglocal
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]
INIT = ROOT / "deploy" / "docker" / "db-init"


def _env(root: Path) -> dict[str, str]:
    """What the image's entrypoint gives the db-init scripts (compose's ``db`` service), with synthetic passwords."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PG", "POSTGRES_", "TB_DB_PW_"))}
    env.update(PATH=f"{pglocal.bindir()}:{env.get('PATH', '')}", PGHOST=str((root / "run").resolve()),
               POSTGRES_USER="hapi", POSTGRES_DB="hapi", POSTGRES_PASSWORD="synthetic-superuser",
               POSTGRES_WF_PASSWORD="synthetic-wf", TB_DB_PW_FHIR_STORE="synthetic-fhir-store")  # fmt: skip
    return env


def _psql(root: Path, user: str, db: str, sql: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(pglocal.bindir() / "psql"), "-X", "-At", "-v", "ON_ERROR_STOP=1", "-U", user, "-d", db,
                           "-c", sql], env=_env(root), capture_output=True, text=True, check=False)  # fmt: skip


@pytest.fixture(scope="module")
def site_roles() -> Iterator[Path]:
    """A cluster of its own (roles are cluster-wide) with a site's roles, made by the install's own scripts."""
    try:
        pglocal.bindir()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    base = Path(os.environ["TB_TEST_ROOT"]) if os.environ.get("TB_TEST_ROOT") else None
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tb-h121-", dir=base))
    root.chmod(0o755)
    pglocal.ensure(root)
    try:
        # the image's first start: POSTGRES_USER the superuser, POSTGRES_DB its database; the test server's own
        # `trialbox` and `trialbox_wf` go, so that 10-trialbox-wf.sh makes them as on a box
        for sql in ("DROP DATABASE trialbox_wf", "DROP ROLE trialbox", "CREATE ROLE hapi SUPERUSER LOGIN",
                    "CREATE DATABASE hapi OWNER hapi"):  # fmt: skip
            r = _psql(root, "postgres", "postgres", sql)
            assert r.returncode == 0, r.stderr
        for script in ("10-trialbox-wf.sh", "30-service-roles.sh"):
            r = subprocess.run(["sh", str(INIT / script)], env=_env(root), capture_output=True, text=True, check=False)
            assert r.returncode == 0, f"{script}: {r.stderr[-1500:]}"
        yield root
    finally:
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)


def _box(root: Path, deploy: Path, monkeypatch: pytest.MonkeyPatch) -> up.ComposeBox:
    """The site box; its ``compose exec -T db <cmd>`` runs the real command against the cluster's socket."""
    monkeypatch.setenv("TB_COMPOSE", "dc")
    sock = str((root / "run").resolve())

    def run(argv: list[str], **kw: Any) -> str:
        if argv[:4] == ["dc", "exec", "-T", "db"]:
            return up.run_cmd([str(pglocal.bindir() / argv[4]), *argv[5:]], env={"PGHOST": sock}, **kw)
        if argv[:2] == ["docker", "info"]:  # OCR 1469-7: the engine's data root is the test's own, never the host's
            return f"{deploy.parent / 'docker-root'}\n"
        return ""  # the rest: no Docker here

    deploy.mkdir(exist_ok=True)
    return up.ComposeBox(deploy, run=run)


def test_h121_the_cluster_has_a_sites_roles(site_roles: Path) -> None:
    """The layout is a site's, not the test server's: `trialbox` cannot connect to `hapi`, the FHIR store owns it."""
    r = _psql(site_roles, "trialbox", "hapi", "SELECT 1")
    assert r.returncode != 0 and "permission denied for database" in r.stderr, r.stderr
    owner = _psql(site_roles, "hapi", "hapi", "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='hapi'")
    assert owner.stdout.strip() == "tb_fhir_store"
    assert _psql(site_roles, "hapi", "hapi", "SELECT rolsuper FROM pg_roles WHERE rolname='hapi'").stdout.strip() == "t"


def test_h121_the_size_check_reads_both_databases_on_a_sites_roles(
    site_roles: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The invariant: the update's space check and the backup's limit read each database's size on a site's roles."""
    box = _box(site_roles, tmp_path / "deploy", monkeypatch)
    read = {db: box.db_size(db, user) for db, user in up.DB_SIZE_ROLES}
    sizes = {db: n for db, n in read.items() if n}
    assert set(sizes) == {"trialbox_wf", "hapi"} == set(read), read
    plan = up.Plan("B1", "f" * 64, "v", [], tmp_path / "stage")
    needs = {what: n for _p, n, what in box.space_needs(plan, tmp_path / "deploy" / "updates")}
    assert not [p for p, _n, _w in box.space_needs(plan, tmp_path / "deploy" / "updates")
                if str(p).startswith("/var/lib/docker")]  # OCR 1469-7: never the host's own engine folder  # fmt: skip
    assert needs["database dumps"] == 2 * sum(sizes.values())
    assert needs["rollback script (largest database) on the db volume"] == max(sizes.values())
    assert all(box.db_bytes(db, user) == sizes[db] for db, user in up.DB_SIZE_ROLES)  # apply_limit_s, backup


def test_h121_the_walk_boxs_read_is_refused_on_the_same_roles(site_roles: Path) -> None:
    """What the walk box's release asked (before H-99): the walk's exact error on these roles."""
    r = _psql(site_roles, "trialbox", "trialbox_wf", "SELECT pg_database_size('hapi')")
    assert r.returncode != 0 and "ERROR:  permission denied for database hapi" in r.stderr, r.stderr


def test_h121_a_size_that_cannot_be_read_stops_the_update_plainly(
    site_roles: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old role put back (`hapi` read as `trialbox`): the update stops before anything changes, naming the
    database and the role, and the backup's limit is unknown (None: no limit, D-455), never a fixed guess."""
    monkeypatch.setattr(up, "DB_SIZE_ROLES", (("trialbox_wf", "trialbox"), ("hapi", "trialbox")))
    box = _box(site_roles, tmp_path / "deploy", monkeypatch)
    plan = up.Plan("B1", "f" * 64, "v", [], tmp_path / "stage")
    with pytest.raises(up.UpdateFailed) as exc:
        box.space_needs(plan, tmp_path / "deploy" / "updates")
    said = str(exc.value)
    assert said.startswith("the size of database hapi could not be read as role trialbox: "), said
    assert "permission denied for database" in said and said.endswith("the space check needs it, nothing was changed")
    assert box.db_bytes("hapi", "trialbox") is None


def test_h121_an_answer_that_is_not_a_size_stops_the_update_never_counted_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_COMPOSE", "dc")
    (tmp_path / "deploy").mkdir()
    box = up.ComposeBox(tmp_path / "deploy", run=lambda argv, **kw: "")
    plan = up.Plan("B1", "f" * 64, "v", [], tmp_path / "stage")
    with pytest.raises(up.UpdateFailed, match=r"^the size of database trialbox_wf could not be read as role trialbox: "
                                              r"no size in the answer; the space check needs it"):  # fmt: skip
        box.space_needs(plan, tmp_path / "deploy" / "updates")
    assert box.db_bytes("trialbox_wf", "trialbox") is None  # the backup's limit: unknown, no limit (D-455)


def test_h121_the_update_path_runs_as_a_non_root_user_without_docker_s_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The integrator's red 7134736821 (CI's unit shard 7, a non-root user): the update path's space check stood on
    Docker's data root (the rollback script's need on its volumes), and a user who may not read that folder had the
    update crash with PermissionError. The database sizes come only through the box's own commands; a host folder the
    user cannot read is measured on its nearest readable parent, as a missing one is.
    Docker's data root here is a folder of its own that nobody but its owner may enter (mode 000). As a non-root user
    the kernel refuses it; as root (who passes any mode) the same refusal is what os.stat answers for it."""
    from tests.unit.test_update_path import FakeRun

    docker_root = tmp_path / "docker-root"
    (docker_root / "volumes").mkdir(parents=True)
    docker_root.chmod(0)
    if os.geteuid() == 0:  # root passes any mode: give it the refusal a non-root user gets from the kernel
        real_stat = os.stat

        def stat(p: Any, *a: Any, **k: Any) -> os.stat_result:
            if str(p).startswith(str(docker_root) + os.sep):
                raise PermissionError(13, "Permission denied", str(p))
            return real_stat(p, *a, **k)

        monkeypatch.setattr(os, "stat", stat)

    class Run(FakeRun):
        def __call__(self, argv: list[str], *a: Any, **k: Any) -> str:
            if argv[:2] == ["docker", "info"]:
                return f"{docker_root}\n"
            return super().__call__(argv, *a, **k)

    deploy = tmp_path / "deploy"
    (deploy / "updates").mkdir(parents=True)
    monkeypatch.setenv("TB_COMPOSE", "dc")
    monkeypatch.setenv("TB_MODELS_DIR", str(tmp_path / "models"))
    box = up.ComposeBox(deploy, run=Run())
    plan = up.Plan("B1", "f" * 64, "v", [], tmp_path / "stage")
    try:
        needs = box.space_needs(plan, deploy / "updates")
        notes = up.Updater(box, deploy / "updates", say=lambda _m: None).space(needs)
    finally:
        docker_root.chmod(0o755)
    assert "rollback script (largest database) on the db volume" in " ".join(w for _p, _n, w in needs)
    assert notes and all("needs" in n for n in notes)


# ------------------------------------------------------------------------------------------------ OCR re-reviews of #1469
def test_ocr_1469_7_the_update_paths_stand_ins_never_measure_the_hosts_docker_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OCR 1469-7 (escape check (i)): the space check of a stand-in box measures no folder of the host's own."""
    from tests.unit.test_update_path import FakeRun

    deploy = tmp_path / "deploy"
    (deploy / "updates").mkdir(parents=True)
    monkeypatch.setenv("TB_COMPOSE", "dc")
    monkeypatch.setenv("TB_MODELS_DIR", str(tmp_path / "models"))
    needs = up.ComposeBox(deploy, run=FakeRun()).space_needs(up.Plan("B1", "f" * 64, "v", [], tmp_path / "stage"),
                                                             deploy / "updates")  # fmt: skip
    assert not [p for p, _n, _w in needs if str(p).startswith("/var/lib/docker")], needs


def test_1469_1_the_rehearsals_size_check_fails_when_a_size_is_not_read(tmp_path: Path) -> None:
    """The doctor phase's program (tools/rehearse_box/box.sh) must exit non-zero when psql answers, but not a size."""
    import re
    import sys

    text = (ROOT / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")
    prog = re.search(r"sizes=\"\$\(cd \"\$BOX\" && python3 -c '(.*?)' 2>&1\)\"", text, re.S)
    assert prog, "the H-121 program is no longer in box.sh"
    dc = tmp_path / "dc"
    dc.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")  # every compose command answers nothing
    dc.chmod(0o755)
    (tmp_path / "deploy").mkdir()
    env = {**os.environ, "TB_COMPOSE": str(dc), "PYTHONPATH": str(ROOT)}
    r = subprocess.run([sys.executable, "-c", prog.group(1)], cwd=tmp_path, env=env, capture_output=True, text=True,
                       check=False)  # fmt: skip
    assert r.returncode != 0, r.stdout + r.stderr


def test_1469_2_an_answer_of_digit_like_characters_is_no_size_never_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_COMPOSE", "dc")
    (tmp_path / "deploy").mkdir()
    box = up.ComposeBox(tmp_path / "deploy", run=lambda argv, **kw: "\u00b2\n")  # isdigit() is True, int() refuses
    assert box.db_bytes("trialbox_wf", "trialbox") is None
    plan = up.Plan("B1", "f" * 64, "v", [], tmp_path / "stage")
    with pytest.raises(up.UpdateFailed, match="no size in the answer"):
        box.space_needs(plan, tmp_path / "deploy" / "updates")


def test_1469_3_a_size_that_cannot_be_read_is_a_preflight_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_COMPOSE", "dc")
    (tmp_path / "deploy").mkdir()
    plan = up.Plan("B1", "f" * 64, "v", [], tmp_path / "stage")

    def refused(argv: list[str], **kw: Any) -> str:
        raise up.UpdateFailed("psql exit 2: permission denied for database")

    for run in (lambda argv, **kw: "", refused):
        with pytest.raises(up.UpdateRefused, match="nothing was changed$"):
            up.ComposeBox(tmp_path / "deploy", run=run).space_needs(plan, tmp_path / "deploy" / "updates")


def test_1469_4_the_role_pairs_are_written_once(tmp_path: Path) -> None:
    """OCR 1469-4: DB_SIZE_ROLES is the one list; the update's dumps and the nightly's reads and dumps take it. The
    restore's read (tools/trialbox/box_restore.py) is #1470's file in those lines: it moves to the list after #1470
    (H-129), and this test names it until then."""
    literal = re.compile(r'\(\("trialbox_wf", "trialbox"\), \("hapi", "hapi"\)\)')
    found = sorted(f"{p.relative_to(ROOT)}:{i}" for p in (ROOT / "tools").rglob("*.py")
                   for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                   if literal.search(line) and not line.startswith("DB_SIZE_ROLES = "))  # fmt: skip
    assert [f.split(":")[0] for f in found] == ["tools/trialbox/box_restore.py"], found


@pytest.mark.parametrize("module", ["tools.trialbox.update", "tools.packs", "tools.trialbox.backup_schedule",
                                    "tools.fetch_weights"])  # fmt: skip
def test_1469_8_every_existing_measures_an_unreadable_folder_on_its_readable_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: str
) -> None:
    """OCR 1469-8: each copy of _existing, given a folder inside one the user may not enter (mode 000; as root, the
    refusal os.stat gives a user who is not root), returns the nearest readable folder, never a PermissionError."""
    import importlib

    existing = importlib.import_module(module)._existing
    locked = tmp_path / "locked"
    (locked / "volumes").mkdir(parents=True)
    locked.chmod(0)
    if os.geteuid() == 0:
        real_stat = os.stat

        def stat(p: Any, *a: Any, **k: Any) -> os.stat_result:
            if str(p).startswith(str(locked) + os.sep):
                raise PermissionError(13, "Permission denied", str(p))
            return real_stat(p, *a, **k)

        monkeypatch.setattr(os, "stat", stat)
    try:
        got = Path(existing(locked / "volumes" / "x"))
    finally:
        locked.chmod(0o755)
    assert got == locked, got
