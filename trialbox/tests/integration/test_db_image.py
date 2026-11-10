"""The box's database image (T-104, D-204): Debian ``postgres:16`` with pgvector 0.8.x and PGroonga 4.1.x.

The file checks (no marker, every ``make test``) keep ``deploy/images.lock``, ``deploy/docker/db.Dockerfile``, the
vendored Groonga key, ``db-init`` and the compose ``db`` line saying the same thing. The image checks (marker
``integration``, ``TB_INTEGRATION=1`` and a built ``trialbox-postgres`` image: ``make images``) start the image as compose
does, with ``db-init`` mounted, and use both extensions as the ``trialbox`` role from a store's own schema, and dump
and restore the whole ``trialbox_wf`` (no ``tb_prefix``: as on a box) as ``trialbox`` with the exact flags of
``tools/trialbox/backup.py`` and ``tools/trialbox/update.py`` (D-204: the extensions are trusted and owned by
``trialbox``, so ``pg_restore --clean --if-exists`` can drop and re-create them).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tb_common.db import IMAGE_EXTENSIONS, Database, extensions

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
LOCK = DEPLOY / "images.lock"
DOCKERFILE = DEPLOY / "docker" / "db.Dockerfile"


def _lock() -> dict[str, Any]:
    data = json.loads(LOCK.read_text(encoding="utf-8"))
    assert data["format"] == "trialbox-images-lock/1"
    return dict(data["images"]["db"])


def _args() -> dict[str, str]:
    """The Dockerfile's ``ARG NAME=default`` lines."""
    return dict(re.findall(r"^ARG (\w+)=(\S+)$", DOCKERFILE.read_text(encoding="utf-8"), re.MULTILINE))


# ----------------------------------------------------------------------------------------------- the files
def test_images_lock_pins_the_db_base_by_digest_and_matches_the_dockerfile() -> None:
    db, args = _lock(), _args()
    base = db["base"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", base["digest"])
    assert args["POSTGRES_BASE"] == f"{base['ref']}@{base['digest']}"
    assert base["ref"].startswith("postgres:16-") and base["ref"].split("-", 1)[1] in ("bookworm", "trixie")
    assert {"linux/amd64", "linux/arm64"} <= set(base["platforms"])
    assert db["packages"] == {
        "postgresql-16-pgvector": args["PGVECTOR_VERSION"],
        "postgresql-16-pgdg-pgroonga": args["PGROONGA_VERSION"],
        "libgroonga0": args["LIBGROONGA_VERSION"],
    }
    assert db["trusted_extensions"] == list(IMAGE_EXTENSIONS) and "trusted = true" in DOCKERFILE.read_text()
    assert db["healthcheck"] == "/usr/local/bin/tb-db-check"
    assert re.match(r"0\.8\.\d+-", args["PGVECTOR_VERSION"]) and re.match(r"4\.1\.\d+-", args["PGROONGA_VERSION"])
    assert set(db["extensions"]) == set(IMAGE_EXTENSIONS)
    assert args["PGVECTOR_VERSION"].startswith(db["extensions"]["vector"] + "-")
    assert args["PGROONGA_VERSION"].startswith(db["extensions"]["pgroonga"] + "-")
    assert db["dockerfile"] == "deploy/docker/db.Dockerfile" and db["context"] == "deploy/docker"
    assert db["digest"] is None or re.fullmatch(r"sha256:[0-9a-f]{64}", db["digest"])


def test_the_groonga_key_is_the_pinned_one() -> None:
    key = _lock()["keys"]["groonga"]
    assert key["fingerprint"] == _args()["GROONGA_KEY_FINGERPRINT"]
    path = ROOT / key["file"]
    assert path.parent == DOCKERFILE.parent and f"COPY {path.name} " in DOCKERFILE.read_text(encoding="utf-8")
    if shutil.which("gpg") is None:
        pytest.skip("gpg not installed")
    out = subprocess.run(
        ["gpg", "--show-keys", "--with-colons", str(path)], capture_output=True, text=True, check=True
    ).stdout
    pubs = [ln for ln in out.splitlines() if ln.startswith("pub:")]
    assert len(pubs) == 1 and f"fpr:::::::::{key['fingerprint']}:" in out  # one key, the pinned one


def test_compose_db_runs_the_locked_image_with_the_same_name_port_and_volume() -> None:
    compose = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    block = compose.split("\n  db:\n", 1)[1].split("\n\n", 1)[0]
    assert f"image: ${{POSTGRES_IMAGE:-{_lock()['image']}}}" in block
    assert "- db-pg:/var/lib/postgresql/data" in block and "- ./docker/db-init:/docker-entrypoint-initdb.d:ro" in block
    assert "ports:" not in block  # never published on the host (as before)


def test_db_init_creates_both_extensions_in_trialbox_wf() -> None:
    init = DEPLOY / "docker" / "db-init"
    names = sorted(p.name for p in init.iterdir())
    assert names.index("10-trialbox-wf.sh") < names.index("20-extensions.sh")  # the database exists first
    text = (init / "20-extensions.sh").read_text(encoding="utf-8")
    assert "--dbname trialbox_wf" in text and "ON_ERROR_STOP=1" in text and "SET ROLE trialbox;" in text
    for ext in IMAGE_EXTENSIONS:
        assert f"CREATE EXTENSION IF NOT EXISTS {ext} WITH SCHEMA public;" in text
    assert os.access(init / "20-extensions.sh", os.X_OK)


# ----------------------------------------------------------------------------------------------- the image
def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=300)


def _start(image: str, name: str, init: bool = True) -> str:
    """Start ``image`` as compose does (db-init mounted unless ``init`` is false); return the host port."""
    mount = ["-v", f"{DEPLOY / 'docker' / 'db-init'}:/docker-entrypoint-initdb.d:ro"] if init else []
    _docker(
        "run", "-d", "--name", name, "-p", "127.0.0.1::5432",
        "-e", "POSTGRES_DB=hapi", "-e", "POSTGRES_USER=hapi", "-e", "POSTGRES_PASSWORD=hapi-test",
        "-e", "POSTGRES_WF_PASSWORD=wf-test", *mount, image,
    )  # fmt: skip
    ready = "pg_isready -h 127.0.0.1 -U hapi -d hapi && psql -h 127.0.0.1 -U hapi -d hapi -tAc \
        \"SELECT 1 FROM pg_database WHERE datname='trialbox_wf' OR NOT {init}\" | grep -q 1".replace(
        "{init}", "true" if init else "false"
    )
    for _ in range(120):
        if _docker("exec", name, "sh", "-c", ready, check=False).returncode == 0:
            break
        time.sleep(1)
    else:
        pytest.fail("the db image did not become ready: " + _docker("logs", name, check=False).stderr[-2000:])
    return str(_docker("port", name, "5432/tcp").stdout.strip().splitlines()[0].rsplit(":", 1)[1])


def _image() -> str:
    if not os.environ.get("TB_INTEGRATION"):
        pytest.skip("TB_INTEGRATION=1 runs the image checks")
    image = os.environ.get("POSTGRES_IMAGE") or str(_lock()["image"])
    if shutil.which("docker") is None or _docker("image", "inspect", image, check=False).returncode != 0:
        pytest.skip(f"image {image} not built (make images)")
    return image


@pytest.fixture(scope="module")
def image_container() -> Iterator[tuple[str, str]]:
    """The image started as compose starts it; yields ``(container name, trialbox role's URL)``."""
    name = f"tb-dbimage-{uuid.uuid4().hex[:8]}"
    image = _image()
    try:
        port = _start(image, name)
        yield name, f"postgresql://trialbox:wf-test@127.0.0.1:{port}/trialbox_wf"
    finally:
        _docker("rm", "-f", "-v", name, check=False)


@pytest.fixture(scope="module")
def image_db(image_container: tuple[str, str]) -> str:
    return image_container[1]


@pytest.mark.integration
def test_the_image_has_both_extensions_at_the_locked_versions(image_db: str) -> None:
    with Database.connect(image_db, "probe") as db:
        assert extensions(db) == _lock()["extensions"]
        assert db.fetchval("SHOW server_version").startswith("16.")


@pytest.mark.integration
def test_a_store_uses_both_extensions_from_its_own_schema(image_db: str) -> None:
    """Non-superuser, store schema on the search path: the extensions are reached as ``public.*`` (D-204)."""
    ddl = (
        "CREATE TABLE doc (id INT PRIMARY KEY, body TEXT NOT NULL, emb public.vector(3) NOT NULL);"
        "CREATE INDEX doc_body ON doc USING pgroonga (body)"
    )
    with Database.connect(image_db, "vecstore") as db:
        assert db.migrate([ddl]) == 1
        with db.transaction() as tx:
            tx.executemany(
                "INSERT INTO doc VALUES (?, ?, ?::public.vector)",
                [(1, "肺がんの化学療法", "[1,0,0]"), (2, "2型糖尿病", "[0,1,0]"), (3, "胃がん 術後", "[0.9,0.1,0]")],
            )
        hits = db.fetchall("SELECT id FROM doc WHERE body OPERATOR(public.&@~) ? ORDER BY id", ("がん",))
        assert hits == [(1,), (3,)]
        near = db.fetchall("SELECT id FROM doc ORDER BY emb OPERATOR(public.<->) '[1,0,0]'::public.vector LIMIT 2")
        assert near == [(1,), (3,)]
        assert [r.version for r in db.applied()] == [1] and db.applied()[0].sha256


@pytest.mark.integration
def test_the_extensions_are_trusted_and_owned_by_the_box_role(image_container: tuple[str, str]) -> None:
    name, _ = image_container
    out = _docker(
        "exec", name, "psql", "-U", "hapi", "-d", "trialbox_wf", "-tAc",
        "SELECT extname || ':' || extowner::regrole FROM pg_extension WHERE extname IN ('vector', 'pgroonga') ORDER BY 1",
    ).stdout.split()  # fmt: skip
    assert out == ["pgroonga:trialbox", "vector:trialbox"]
    assert _docker("exec", name, "tb-db-check", check=False).returncode == 0


def _seed(url: str) -> None:
    with Database.connect(url, "seeded") as db:
        db.migrate(["CREATE TABLE doc (id INT PRIMARY KEY, body TEXT, emb public.vector(3)); "
                    "CREATE INDEX doc_body ON doc USING pgroonga (body)"])  # fmt: skip
        db.execute("INSERT INTO doc VALUES (1, '肺がん', '[1,0,0]') ON CONFLICT DO NOTHING")


def _seeded_ok(url: str) -> bool:
    with Database.connect(url, "seeded") as db:
        hit = db.fetchall("SELECT id FROM doc WHERE body OPERATOR(public.&@~) 'がん'")
        return hit == [(1,)] and all(extensions(db).values())


@pytest.mark.integration
def test_the_whole_database_restores_as_trialbox_with_the_update_paths_flags(image_container: tuple[str, str]) -> None:
    """``tools/trialbox/update.py``: ``pg_dump -Fc --no-owner`` then ``pg_restore --clean --if-exists --no-owner
    --single-transaction`` in the db container, as ``trialbox``, no ``tb_prefix`` (the dump holds the extensions)."""
    name, url = image_container
    _seed(url)
    r = _docker(
        "exec", name, "sh", "-c",
        "pg_dump -Fc --no-owner -U trialbox -d trialbox_wf > /tmp/u.dump && "
        "pg_restore -l /tmp/u.dump | grep -c ' EXTENSION - ' && "
        "pg_restore --clean --if-exists --no-owner --single-transaction -U trialbox -d trialbox_wf < /tmp/u.dump",
        check=False,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.split()[0] == "2"  # both extensions are in the dump, and restored by the box's role
    assert _seeded_ok(url)


@pytest.mark.integration
def test_the_whole_database_restores_as_trialbox_with_the_backups_flags(
    image_container: tuple[str, str], tmp_path: Path
) -> None:
    """``tools/trialbox/backup.py``'s own ``dump`` and ``restore_db`` (``--clean --if-exists --no-owner
    --no-privileges --single-transaction --exit-on-error``) on the whole ``trialbox_wf``, as ``trialbox``."""
    if shutil.which("pg_dump") is None:
        pytest.skip("pg_dump not on this host")
    from tools.trialbox import backup as bk

    _, url = image_container
    _seed(url)
    src = bk.DbSource("trialbox_wf", url, ())
    bk.dump(src, tmp_path / "wf.dump", {})
    bk.restore_db(src, tmp_path / "wf.dump", {})
    assert _seeded_ok(url)


@pytest.mark.integration
def test_superuser_owned_extensions_would_break_that_restore(image_container: tuple[str, str]) -> None:
    """Why D-204 creates them as ``trialbox``: owned by the superuser, the same restore stops."""
    name, _ = image_container
    script = (
        "set -e; psql -q -U hapi -d hapi -c 'CREATE DATABASE su_owned OWNER trialbox'; "
        "psql -q -U hapi -d su_owned -c 'CREATE EXTENSION vector'; "
        "pg_dump -Fc --no-owner -U trialbox -d su_owned > /tmp/s.dump; "
        "pg_restore --clean --if-exists --no-owner --single-transaction -U trialbox -d su_owned < /tmp/s.dump"
    )
    r = _docker("exec", name, "sh", "-c", script, check=False)
    _docker("exec", name, "psql", "-q", "-U", "hapi", "-d", "hapi", "-c", "DROP DATABASE su_owned", check=False)
    assert r.returncode != 0 and "must be owner of extension vector" in r.stderr


@pytest.mark.integration
def test_tb_db_check_fails_without_the_extensions() -> None:
    """A volume that never ran 20-extensions.sh (an old volume, a failed first start) is not healthy."""
    image = _image()
    name = f"tb-dbimage-noinit-{uuid.uuid4().hex[:8]}"
    try:
        _start(image, name, init=False)
        assert _docker("exec", name, "tb-db-check", check=False).returncode != 0
    finally:
        _docker("rm", "-f", "-v", name, check=False)
