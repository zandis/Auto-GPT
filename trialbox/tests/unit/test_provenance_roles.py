"""D-989 step 2c, the role script's part (D-997): the provenance index's tables and who may do what with them.

``tb_common.provenance_index.INDEX_SQL`` (lane A2) makes ``provenance.model_calls`` and ``provenance.model_uses``. The
role scripts (the box's and the platform's, kept equal) run it word for word beside the journal's SQL, give the schema
and both tables to ``audit_writer`` (the journal's owner, whom nobody signs in as), and grant:

* ``tb_audit_writer`` (the drain, which writes each record's rows as the chain is written): USAGE, INSERT, SELECT;
* ``tb_console`` and ``tb_orchestrator`` (the search and the doctor's check): USAGE, SELECT;
* ``tb_orchestrator``, which runs the opt-out worker (D-465): DELETE on ``model_uses``, the rows that name a patient;
* ``trialbox``, the host's administrator (``trialbox provenance --rebuild`` and ``--check``), acts as the owner: it
  is ``audit_writer``'s one member, as for the journal (D-394);
* nobody else anything: no other service role, and not PUBLIC.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from tb_common import provenance_index as pi

from tests.unit.test_db_roles import ACCESS, SCRIPT, _as, _psql_env
from tools import pglocal

ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SCRIPT = ROOT / "deploy" / "platform" / "base" / "db-init" / "30-service-roles.sh"
BEGIN, END = "-- BEGIN PROVENANCE INDEX (D-989)\n", "-- END PROVENANCE INDEX"

PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
#: role -> (what it may do on model_calls, on model_uses)
MAY = {
    "tb_audit_writer": ({"SELECT", "INSERT"}, {"SELECT", "INSERT"}),
    "tb_console": ({"SELECT"}, {"SELECT"}),
    "tb_orchestrator": ({"SELECT"}, {"SELECT", "DELETE"}),
    "trialbox": (set(PRIVILEGES), set(PRIVILEGES)),  # the owner's, through its membership of audit_writer
}


def _block(text: str) -> str:
    return text.split(BEGIN, 1)[1].split(END, 1)[0]


# ------------------------------------------------------------------------------------------------ pure checks
def test_both_role_scripts_run_the_index_sql_of_the_module_word_for_word() -> None:
    for script in (SCRIPT, PLATFORM_SCRIPT):
        text = script.read_text(encoding="utf-8")
        assert _block(text) == pi.INDEX_SQL, script
        # after the journal's block: the owner audit_writer exists by then
        assert text.index("-- END AUDIT WRITER") < text.index(BEGIN), script


def test_the_two_role_scripts_are_the_same_file() -> None:
    assert SCRIPT.read_bytes() == PLATFORM_SCRIPT.read_bytes()


# ------------------------------------------------------------------------------------------------ on a cluster
@pytest.fixture(scope="module")
def cluster() -> Iterator[tuple[Path, str]]:
    if shutil.which("sh") is None:
        pytest.skip("no sh")
    try:
        pglocal.bindir()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    pytest.importorskip("psycopg")
    base = Path(os.environ["TB_TEST_ROOT"]) if os.environ.get("TB_TEST_ROOT") else None
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tb-pgprov-", dir=base))
    root.chmod(0o755)
    url = pglocal.ensure(root)
    env = {**_psql_env(root), "TB_DB_PW_AUDIT_WRITER": "synthetic-audit-writer"}
    try:
        for _ in range(2):  # idempotent: install.sh runs it on every install and upgrade
            r = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True, check=False)
            assert r.returncode == 0, r.stderr[-1500:]
        yield root, url
    finally:
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)


def _one(url: str, sql: str) -> object:
    import psycopg

    with psycopg.connect(url, autocommit=True) as con:
        row = con.execute(sql).fetchone()
        return row[0] if row else None


def test_the_schema_and_both_tables_belong_to_audit_writer(cluster: tuple[Path, str]) -> None:
    _, url = cluster
    assert (
        _one(url, "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'provenance'") == "audit_writer"
    )
    for table in pi.TABLES:
        assert _one(url, f"SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = '{table}'::regclass") == (
            "audit_writer"
        )
    assert pi.installed(__import__("psycopg").connect(url, autocommit=True))
    members = _one(url, "SELECT string_agg(pg_get_userbyid(member), ',') FROM pg_auth_members "
                        "WHERE roleid = 'audit_writer'::regrole")  # fmt: skip
    assert members == "trialbox"  # the one way to act as the owner


@pytest.mark.parametrize("role", sorted({*ACCESS, "tb_audit_writer", "trialbox"}))
def test_each_role_may_do_exactly_its_part(cluster: tuple[Path, str], role: str) -> None:
    _, url = cluster
    calls, uses = MAY.get(role, (set(), set()))
    for table, want in zip(pi.TABLES, (calls, uses), strict=True):
        for priv in PRIVILEGES:
            got = _one(url, f"SELECT has_table_privilege('{role}', '{table}', '{priv}')")
            assert got is (priv in want), f"{role} {priv} on {table}: {got}"
    usage = _one(url, f"SELECT has_schema_privilege('{role}', 'provenance', 'USAGE')")
    assert usage is (role in MAY), role
    assert _one(url, "SELECT has_schema_privilege('public', 'provenance', 'USAGE')") is False


def test_the_drain_writes_a_row_and_cannot_take_one_back(cluster: tuple[Path, str]) -> None:
    import psycopg

    _, url = cluster
    with psycopg.connect(_as(url, "tb_audit_writer"), autocommit=True) as con:
        con.execute(
            "INSERT INTO provenance.model_uses (rec_hash, call_id, event, record_kind, record_ref, pid, at) "
            "VALUES ('h1', 'c1', 'used', 'criterion', 'GZQO/v1/I1', 'P-SYN-1', now())"
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            con.execute("DELETE FROM provenance.model_uses WHERE rec_hash = 'h1'")
    # the opt-out worker (the orchestrator's role) clears a patient's use rows, as tb_common.provenance_index.erase
    with psycopg.connect(_as(url, "tb_orchestrator"), autocommit=True) as con:
        assert pi.erase(con, ["P-SYN-1"]) == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            con.execute("INSERT INTO provenance.model_calls (rec_hash, call_id, at) VALUES ('h2', 'c2', now())")
