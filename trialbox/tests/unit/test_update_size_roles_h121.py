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
        return ""  # docker info and the rest: no Docker here

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
