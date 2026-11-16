"""Plan v7 §3.1 (OPS-013, ARCH-013): the deploy files that no box uses are gone, and nothing tells an operator to use
them. RUNBOOK §5 told hospital IT to build `deploy/pgbackrest/Dockerfile` (Alpine) and set `POSTGRES_IMAGE` to it for
point-in-time restore: that swaps the box's Debian db image, which already carries pgBackRest 2.60 with pgvector and
PGroonga, for one without the two extensions and with another C library (the indexes' collation order)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb


def test_the_dead_files_are_gone() -> None:
    assert not (ROOT / "deploy" / "pgbackrest" / "Dockerfile").exists()
    assert not (ROOT / "deploy" / "topology_a").exists()
    assert (ROOT / "deploy" / "pgbackrest" / "pgbackrest.conf").is_file()  # the db service mounts it


def test_no_page_or_compose_file_says_to_build_or_swap_the_db_image() -> None:
    texts = [p.read_text(encoding="utf-8") for p in sorted((ROOT / "docs" / "runbook").glob("*.md"))]
    texts += [p.read_text(encoding="utf-8") for p in sorted((ROOT / "deploy").glob("docker-compose*.yml"))]
    for text in texts:
        assert "deploy/pgbackrest/Dockerfile" not in text and "docker build -t trialbox-db-pitr" not in text
        assert "POSTGRES_IMAGE=trialbox-db-pitr" not in text
    db = (ROOT / "deploy" / "docker" / "db.Dockerfile").read_text(encoding="utf-8")
    assert '"pgbackrest=${PGBACKREST_VERSION}"' in db  # the box's own image carries it
