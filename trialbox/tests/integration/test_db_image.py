"""The box's database image (T-104, D-204): Debian ``postgres:16`` with pgvector 0.8.x and PGroonga 4.1.x.

The file checks (no marker, every ``make test``) keep ``deploy/images.lock``, ``deploy/docker/db.Dockerfile``, the
vendored Groonga key, ``db-init`` and the compose ``db`` line saying the same thing. The image checks (marker
``integration``, ``TB_INTEGRATION=1`` and a built ``trialbox-postgres`` image: ``make images``) start the image as compose
does, with ``db-init`` mounted, and use both extensions as the ``trialbox`` role from a store's own schema.
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
    }
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
    assert f"fpr:::::::::{key['fingerprint']}:" in out


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
    assert "--dbname trialbox_wf" in text and "ON_ERROR_STOP=1" in text
    for ext in IMAGE_EXTENSIONS:
        assert f"CREATE EXTENSION IF NOT EXISTS {ext} WITH SCHEMA public;" in text
    assert os.access(init / "20-extensions.sh", os.X_OK)


# ----------------------------------------------------------------------------------------------- the image
def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=300)


@pytest.fixture(scope="module")
def image_db() -> Iterator[str]:
    """The ``trialbox-db`` image started as compose starts it (db-init mounted); yields the ``trialbox`` role's URL."""
    if not os.environ.get("TB_INTEGRATION"):
        pytest.skip("TB_INTEGRATION=1 runs the image checks")
    image = os.environ.get("POSTGRES_IMAGE") or _lock()["image"]
    if shutil.which("docker") is None or _docker("image", "inspect", image, check=False).returncode != 0:
        pytest.skip(f"image {image} not built (make images)")
    name = f"tb-dbimage-{uuid.uuid4().hex[:8]}"
    _docker(
        "run", "-d", "--name", name, "-p", "127.0.0.1::5432",
        "-e", "POSTGRES_DB=hapi", "-e", "POSTGRES_USER=hapi", "-e", "POSTGRES_PASSWORD=hapi-test",
        "-e", "POSTGRES_WF_PASSWORD=wf-test",
        "-v", f"{DEPLOY / 'docker' / 'db-init'}:/docker-entrypoint-initdb.d:ro", image,
    )  # fmt: skip
    try:
        ready = "pg_isready -h 127.0.0.1 -U hapi -d hapi && psql -h 127.0.0.1 -U hapi -d hapi -tAc \
            \"SELECT 1 FROM pg_database WHERE datname='trialbox_wf'\" | grep -q 1"
        for _ in range(120):
            if _docker("exec", name, "sh", "-c", ready, check=False).returncode == 0:
                break
            time.sleep(1)
        else:
            pytest.fail("the db image did not become ready: " + _docker("logs", name, check=False).stderr[-2000:])
        port = _docker("port", name, "5432/tcp").stdout.strip().splitlines()[0].rsplit(":", 1)[1]
        yield f"postgresql://trialbox:wf-test@127.0.0.1:{port}/trialbox_wf"
    finally:
        _docker("rm", "-f", "-v", name, check=False)


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
