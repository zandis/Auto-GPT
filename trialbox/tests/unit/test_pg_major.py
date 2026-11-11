"""One PostgreSQL major for the db image, the demo image and CI (T-104b, D-371; DEP-013, DEP-014, DEP-027).

A file check, no server and no docker: ``deploy/images.lock`` declares ``postgres_major``; the db image's base and its
PGDG packages, the demo image's ``PG_MAJOR`` and every workflow step that sets up PostgreSQL (``tools/ci_postgres.sh``,
which reads the lock and fails on another ``pg_config --version``) must name that major. The images check
``pg_config --version`` when they build; ``ci_postgres.sh`` does in every CI job.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "deploy" / "images.lock"
DB_DOCKERFILE = ROOT / "deploy" / "docker" / "db.Dockerfile"
DEMO_DOCKERFILE = ROOT / "demo" / "Dockerfile"
CI_SCRIPT = ROOT / "tools" / "ci_postgres.sh"
WORKFLOWS = ROOT.parent / ".github" / "workflows"


def _major() -> str:
    db = json.loads(LOCK.read_text(encoding="utf-8"))["images"]["db"]
    major = str(db["postgres_major"])
    assert re.fullmatch(r"1[6-9]", major), major  # a supported major with PGDG, pgvector and PGroonga builds
    return major


def _args(path: Path) -> dict[str, str]:
    return dict(re.findall(r"^ARG (\w+)=(\S+)$", path.read_text(encoding="utf-8"), re.MULTILINE))


def test_the_db_image_builds_the_locked_major_on_debian_13() -> None:
    major, args = _major(), _args(DB_DOCKERFILE)
    db = json.loads(LOCK.read_text(encoding="utf-8"))["images"]["db"]
    assert args["POSTGRES_BASE"].startswith(f"postgres:{major}-trixie@sha256:")  # Debian 13
    assert db["base"]["ref"] == f"postgres:{major}-trixie"
    assert args["PG_MAJOR_EXPECTED"] == major
    assert db["image"].startswith(f"trialbox-postgres:{major}-")
    pg_packages = [p for p in db["packages"] if p.startswith("postgresql-")]
    assert pg_packages and all(p.startswith(f"postgresql-{major}-") for p in pg_packages)
    text = DB_DOCKERFILE.read_text(encoding="utf-8")
    assert 'pg_config --version | grep -q "^PostgreSQL ${PG_MAJOR_EXPECTED}\\."' in text


def test_pgbackrest_is_pinned_from_pgdg_in_the_db_image() -> None:
    db = json.loads(LOCK.read_text(encoding="utf-8"))["images"]["db"]
    args = _args(DB_DOCKERFILE)
    assert db["packages"]["pgbackrest"] == args["PGBACKREST_VERSION"]
    assert re.fullmatch(r"2\.\d+\.\d+-\d+\.pgdg13\+\d+", args["PGBACKREST_VERSION"])  # PGDG's Debian 13 build
    text = DB_DOCKERFILE.read_text(encoding="utf-8")
    assert '"pgbackrest=${PGBACKREST_VERSION}"' in text and "libgroonga0 pgbackrest;" in text  # installed and held


def test_the_demo_image_installs_the_locked_major_from_pgdg() -> None:
    major, text = _major(), DEMO_DOCKERFILE.read_text(encoding="utf-8")
    assert _args(DEMO_DOCKERFILE)["PG_MAJOR"] == major
    assert '"postgresql-${PG_MAJOR}"' in text and "apt.postgresql.org.sh -y" in text
    assert '"/usr/lib/postgresql/${PG_MAJOR}/bin/pg_config" --version' in text
    assert 'case "$v" in "PostgreSQL ${PG_MAJOR}."*) ;;' in text  # the build stops on another major
    assert not re.search(r"install -y --no-install-recommends postgresql\s", text)  # not the distribution's major


def test_every_workflow_sets_up_postgresql_with_the_one_script() -> None:
    if not WORKFLOWS.is_dir():
        pytest.skip("no .github/workflows next to trialbox/ (a bundle, not the repository)")
    users = []
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        assert not re.search(r"apt-get install[^\n]*\bpostgresql(-\d+)?\b", text), f"{wf.name}: use ci_postgres.sh"
        service = re.search(r"^\s*image:\s*[\"']?(docker\.io/)?(library/)?postgres\b", text, re.MULTILINE)
        assert not service, f"{wf.name}: a postgres service container has its own major"
        if "tools/ci_postgres.sh" in text:
            users.append(wf.name)
    assert "trialbox-ci.yml" in users


def test_ci_postgres_reads_the_lock_and_checks_pg_config() -> None:
    text = CI_SCRIPT.read_text(encoding="utf-8")
    assert os.access(CI_SCRIPT, os.X_OK)
    assert '["images"]["db"]["postgres_major"]' in text and "deploy/images.lock" in text
    assert '"$bin/pg_config" --version' in text and '"PostgreSQL $major."*' in text
    assert subprocess.run(["bash", "-n", str(CI_SCRIPT)], check=False).returncode == 0
