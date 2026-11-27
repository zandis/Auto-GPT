"""P-30 (E2E R1): ``ERROR: relation "pidmap.site_key" does not exist`` twice at every boot of a fresh box.

The host check (``deploy/check_host.sh``) and the doctor's image runner (``tools/trialbox/doctor_image.py``) read the
pid map's row for the site before the first night has made the table. The doctor's own read was already guarded by
``to_regclass``; these two were not, so the database logged an ERROR each time. The class: no host-side read of the
pid map (deploy scripts, the trialbox tools) may name ``pidmap.`` without the same guard."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

from tools.trialbox import doctor_image

ROOT = Path(__file__).resolve().parents[2]
HOST_SIDE = ("deploy", "tools/trialbox")


def test_every_host_side_pidmap_read_is_guarded() -> None:
    unguarded = []
    for top in HOST_SIDE:
        for path in sorted((ROOT / top).rglob("*")):
            if path.suffix not in (".sh", ".py") or not path.is_file():
                continue
            text = path.read_text(errors="replace")
            if "FROM pidmap." in text and "to_regclass('pidmap." not in text:
                unguarded.append(str(path.relative_to(ROOT)))
    assert not unguarded, f"reads of the pid map with no to_regclass guard (P-30): {unguarded}"


def test_check_host_guards_before_it_reads() -> None:
    text = (ROOT / "deploy/check_host.sh").read_text()
    read = text.index("FROM pidmap.site_key")
    guard = text.rfind("to_regclass('pidmap.site_key')", 0, read)
    assert guard != -1 and "\\\\if :tb_has_pidmap" in text[guard:read]


def _psql() -> str:
    found = shutil.which("psql")
    if found:
        return found
    from tools import pglocal

    return str(pglocal.bindir() / "psql")


def _in_db(url: str, db: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{db}"))


def _run(url: str, sql: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_psql(), "-X", "-q", "-tA", "-v", "ON_ERROR_STOP=1", "-v", "site=SITE", "-d", url],
        input=sql, capture_output=True, text=True, check=False, timeout=60,
    )  # fmt: skip


@pytest.fixture
def fresh_db(pg_cluster_url: str) -> str:
    """A database of its own: like a box before its first night, it has no pid map schema."""
    name = f"r1p1d_p30_{os.getpid()}"
    admin = _in_db(pg_cluster_url, "postgres")
    assert _run(admin, f"DROP DATABASE IF EXISTS {name};\nCREATE DATABASE {name};\n").returncode == 0
    yield _in_db(pg_cluster_url, name)
    _run(admin, f"DROP DATABASE IF EXISTS {name} WITH (FORCE);\n")


def test_doctor_image_read_logs_no_error_before_the_first_night(fresh_db: str) -> None:
    got = _run(fresh_db, doctor_image.PIDMAP_ROW_SQL)
    assert got.returncode == 0 and "ERROR" not in got.stderr, got.stderr
    assert got.stdout.strip() == ""  # pidmap_row() turns this into "none": asked, no row


def test_doctor_image_read_returns_the_row_once_the_table_exists(fresh_db: str) -> None:
    made = _run(fresh_db, "CREATE SCHEMA pidmap;\nCREATE TABLE pidmap.site_key (site_id text, fingerprint text, "
                          "chartno_rule text);\nINSERT INTO pidmap.site_key VALUES ('SITE', 'abc123', 'digits:8');\n")  # fmt: skip
    assert made.returncode == 0, made.stderr
    got = _run(fresh_db, doctor_image.PIDMAP_ROW_SQL)
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip() == "abc123|digits:8"
