"""D-394 (T-211b, CR-042): one audit writer.

The real ``deploy/docker/db-init/30-service-roles.sh`` runs against a throwaway cluster of its own (roles are
cluster-wide), twice. Then: each service role of D-378 can only call ``audit.append`` (no INSERT, SELECT, UPDATE,
DELETE or TRUNCATE on the journal, and it cannot become ``audit_writer``); nobody, the superuser included, changes or
deletes a journal row; and the drain copies the journal into a hash chain that verifies, once, in order, with the
database role of each event. Passwords are synthetic test strings.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from tb_common import audit_writer as aw
from tb_common.audit import AuditLog, verify

from tests.unit.test_db_roles import ACCESS, SCRIPT, _as, _psql_env
from tools import pglocal

ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SCRIPT = ROOT / "deploy" / "platform" / "base" / "db-init" / "30-service-roles.sh"
TZ = "Asia/Taipei"


def _block(text: str) -> str:
    return text.split("-- BEGIN AUDIT WRITER (D-394)\n", 1)[1].split("-- END AUDIT WRITER", 1)[0]


# ------------------------------------------------------------------------------------------------ pure checks
def test_the_role_scripts_run_the_journal_sql_of_the_module() -> None:
    for script in (SCRIPT, PLATFORM_SCRIPT):
        text = script.read_text(encoding="utf-8")
        assert _block(text) == aw.JOURNAL_SQL, script
        assert '-v pw_audit_writer="${TB_DB_PW_AUDIT_WRITER:-}"' in text
        assert "ALTER ROLE tb_audit_writer PASSWORD :'pw_audit_writer';" in text


def test_every_service_role_may_call_the_writer_and_none_may_read() -> None:
    sql = " ".join(aw.JOURNAL_SQL.split())
    execute = sql.split("GRANT EXECUTE ON FUNCTION audit.append(text, text, jsonb) TO ", 1)[1].split(";", 1)[0]
    assert sorted(r.strip() for r in execute.split(",")) == sorted(ACCESS)
    select = sql.split("GRANT SELECT ON audit.journal TO ", 1)[1].split(";", 1)[0]
    assert sorted(r.strip() for r in select.split(",")) == ["tb_audit_writer", "trialbox"]
    assert "GRANT INSERT" not in sql and "GRANT UPDATE" not in sql and "GRANT DELETE" not in sql


def test_open_audit_chooses_the_writer_by_the_environment(tmp_path: Path) -> None:
    f = aw.open_audit(tmp_path / "a", TZ, env={})
    assert type(f) is AuditLog
    d = aw.open_audit(tmp_path / "b", TZ, env={"TB_AUDIT_WRITER": "db", "TB_DB_URL": "postgresql://x@h/db"})
    assert isinstance(d, aw.DbAuditWriter) and isinstance(d, AuditLog)
    assert not (tmp_path / "b").exists()  # the journal writer never touches the (read-only) chain folder
    with pytest.raises(ValueError, match="TB_DB_URL"):
        aw.open_audit(tmp_path, TZ, env={"TB_AUDIT_WRITER": "db"})
    with pytest.raises(ValueError, match="'db' or 'file'"):
        aw.open_audit(tmp_path, TZ, env={"TB_AUDIT_WRITER": "both"})


def test_an_unreachable_journal_is_an_oserror_and_journal_is_reserved(tmp_path: Path) -> None:
    pytest.importorskip("psycopg")
    w = aw.DbAuditWriter(tmp_path, TZ, url="postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
    with pytest.raises(aw.AuditUnavailable):  # an OSError: callers that stop an action on an audit failure still do
        w.append("x.y", actor="t")
    with pytest.raises(ValueError, match="journal"):
        w.append("x.y", actor="t", journal={"seq": 1})


# ------------------------------------------------------------------------------------------------ the cluster
def _superuser(root: Path, sql: str, db: str = pglocal.DB) -> str:
    r = subprocess.run(
        [str(pglocal.bindir() / "psql"), "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1", "-tAqc", sql],
        env=_psql_env(root), capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _run_script(root: Path, db: str = pglocal.DB) -> None:
    env = {**_psql_env(root), "TB_WF_DB": db, "TB_DB_PW_AUDIT_WRITER": "synthetic-audit-writer"}
    r = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr[-1500:]


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
    root = Path(tempfile.mkdtemp(prefix="tb-auditw-", dir=base))
    root.chmod(0o755)
    url = pglocal.ensure(root)
    try:
        _superuser(root, "CREATE DATABASE hapi", db="postgres")
        _run_script(root)
        _run_script(root)  # idempotent: install.sh runs it on every install and upgrade
        yield root, url
    finally:
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.parametrize("role", sorted(ACCESS))
def test_a_service_role_writes_audit_rows_only_through_the_writer(cluster: tuple[Path, str], role: str) -> None:
    """Acceptance: no service role inserts, changes or deletes a journal row directly; audit.append works."""
    import psycopg
    from psycopg import errors

    root, url = cluster
    with psycopg.connect(_as(url, role), autocommit=True) as con:
        for stmt in (
            "INSERT INTO audit.journal (db_role, event, ts, fields) VALUES ('tb_console', 'forged', 'x', '{}')",
            "UPDATE audit.journal SET event = 'rewritten'",
            "DELETE FROM audit.journal",
            "TRUNCATE audit.journal",
            "SELECT count(*) FROM audit.journal",
            "SET ROLE audit_writer",
            "CREATE TABLE audit.planted (k INT)",
        ):
            with pytest.raises(errors.InsufficientPrivilege):
                con.execute(stmt)
        seq = con.execute("SELECT audit.append(%s, %s, %s::jsonb)", ("probe.write", "2026-11-11T09:00:00.000+08:00",
                                                                      json.dumps({"actor": role}))).fetchone()  # fmt: skip
        assert seq is not None and seq[0] > 0
    # the row names the role that signed in, whatever the caller says
    assert _superuser(root, f"SELECT db_role FROM audit.journal WHERE seq = {seq[0]}") == role


def test_the_journal_is_append_only_for_everyone(cluster: tuple[Path, str]) -> None:
    import psycopg
    from psycopg import errors

    root, url = cluster
    w = aw.DbAuditWriter(root, TZ, url=_as(url, "tb_orchestrator"))
    rec = w.append("probe.keep", actor="t")
    w.close()
    seq = rec["journal"]["seq"]
    for stmt in (f"UPDATE audit.journal SET event = 'x' WHERE seq = {seq}", f"DELETE FROM audit.journal WHERE seq = {seq}",
                 "TRUNCATE audit.journal"):  # fmt: skip
        r = subprocess.run(
            [str(pglocal.bindir() / "psql"), "-U", "postgres", "-d", pglocal.DB, "-v", "ON_ERROR_STOP=1", "-c", stmt],
            env=_psql_env(root), capture_output=True, text=True, check=False,
        )  # fmt: skip
        assert r.returncode != 0 and "append-only" in r.stderr, stmt  # the trigger holds even for the superuser
    assert _superuser(root, f"SELECT event FROM audit.journal WHERE seq = {seq}") == "probe.keep"
    roles = _superuser(root, "SELECT rolcanlogin, (SELECT count(*) FROM pg_auth_members WHERE roleid = r.oid), "
                             "has_table_privilege(r.oid, 'audit.journal', 'UPDATE,DELETE,TRUNCATE') "
                             "FROM pg_roles r WHERE rolname = 'audit_writer'")  # fmt: skip
    assert roles == "f|1|f"  # nobody signs in as the owner, and the owner cannot change a row either
    assert (
        _superuser(
            root,
            "SELECT string_agg(pg_get_userbyid(member), ',') FROM pg_auth_members "
            "WHERE roleid = 'audit_writer'::regrole",
        )
        == "trialbox"
    )  # the host admin only (restores)
    with psycopg.connect(url) as con:  # trialbox (the host tools) can drop the schema, as a restore does
        con.execute("DROP SCHEMA audit CASCADE")
        con.rollback()
    with psycopg.connect(_as(url, "tb_audit_writer"), autocommit=True) as con:  # the drain only reads
        count = con.execute("SELECT count(*) FROM audit.journal").fetchone()
        assert count is not None and count[0] >= 1
        for stmt in ("SELECT audit.append('x', 'y', '{}')", "DELETE FROM audit.journal",
                     "INSERT INTO audit.journal (db_role, event, ts, fields) VALUES ('a', 'b', 'c', '{}')"):  # fmt: skip
            with pytest.raises(errors.InsufficientPrivilege):
                con.execute(stmt)


def test_the_drain_copies_the_journal_into_the_chain_once_in_order(cluster: tuple[Path, str], tmp_path: Path) -> None:
    _root, url = cluster
    chain = tmp_path / "audit"
    sent = []
    for role, event in (("tb_console", "console.view"), ("tb_gateway", "gateway.call"), ("tb_adapter", "ingest.done")):
        env = {"TB_AUDIT_WRITER": "db", "TB_DB_URL": _as(url, role)}
        w = aw.open_audit(chain, TZ, env=env)
        ts = datetime(2026, 11, 11, 9, 0, tzinfo=ZoneInfo(TZ))
        sent.append(w.append(event, ts=ts, actor=f"{role}:synthetic", job_id="J1", detail={"mrn": "•••"}, n=1))
        assert isinstance(w, aw.DbAuditWriter)
        w.close()
    AuditLog(chain, TZ).append("ops.host", actor="host-tool")  # a host tool's own line in between is kept
    drain = aw.Drain(_as(url, "tb_audit_writer"), chain, TZ)
    drain.open()
    first = drain.run(once=True, alive=None)
    assert first >= 3
    assert drain.run(once=True, alive=None) == 0  # nothing twice
    lines = [json.loads(ln) for p in sorted(chain.glob("*.jsonl")) for ln in p.read_text(encoding="utf-8").splitlines()]
    from_journal = [r for r in lines if "journal" in r]
    assert [r["journal"]["seq"] for r in from_journal] == sorted(r["journal"]["seq"] for r in from_journal)
    mine = {r["journal"]["seq"]: r for r in from_journal}
    for rec in sent:
        got = mine[rec["journal"]["seq"]]
        assert got["event"] == rec["event"] and got["actor"] == rec["actor"] and got["job_id"] == "J1"
        assert got["detail"] == {"mrn": "•••", "n": 1} and got["ts"] == rec["ts"]
        assert got["journal"]["role"] == rec["actor"].split(":")[0]
    assert verify(chain).ok
    again = aw.Drain(_as(url, "tb_audit_writer"), chain, TZ)  # a restart reads where it stands from the chain
    again.open()
    assert again.run(once=True, alive=None) == 0


def test_a_restored_journal_is_recorded_and_nothing_after_it_is_passed_over(
    cluster: tuple[Path, str], tmp_path: Path
) -> None:
    root, url = cluster
    chain = tmp_path / "audit"
    w = aw.DbAuditWriter(chain, TZ, url=_as(url, "tb_console"))
    w.append("before.restore", actor="t")
    w.close()
    d = aw.Drain(_as(url, "tb_audit_writer"), chain, TZ)
    d.open()
    d.run(once=True, alive=None)
    # a database restored or made new: the same roles, an empty journal whose seq starts again at 1
    _superuser(root, "CREATE DATABASE wf_restored", db="postgres")
    _run_script(root, db="wf_restored")
    other = url.replace(f"/{pglocal.DB}", "/wf_restored")
    w2 = aw.DbAuditWriter(chain, TZ, url=_as(other, "tb_console"))
    w2.append("after.restore", actor="t")
    w2.close()
    d2 = aw.Drain(_as(other, "tb_audit_writer"), chain, TZ)
    d2.open()  # the chain's last journal row is not in this journal: recorded, then the rows after it
    assert d2.run(once=True, alive=None) == 1
    recs = [json.loads(ln) for p in sorted(chain.glob("*.jsonl")) for ln in p.read_text().splitlines()]
    assert [r["event"] for r in recs[-2:]] == ["audit.journal_resync", "after.restore"]
    assert "restored or replaced" in recs[-2]["detail"]["problem"] and recs[-1]["journal"]["seq"] == 1
    assert verify(chain).ok
