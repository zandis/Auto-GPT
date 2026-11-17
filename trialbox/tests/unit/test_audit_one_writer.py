"""D-394 (T-211b, CR-042): the audit writers, enumerated.

A service gets its audit writer from :func:`tb_common.audit_writer.open_audit` and nowhere else; only the writer
module and the role scripts write the journal table; code run inside a service container writes through
``open_audit``; and on the box only the ``audit-writer`` container mounts the audit volume read-write. A new direct
write fails here: route it through ``open_audit`` (or, for a host tool, add it to the list below with its reason).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "docker-compose.yml"

#: The modules (services and shared libraries) that write the audit, each through open_audit. A new one is a review
#: point: add it here.
WRITERS = {
    "libs/tb_common/flags.py",  # docstring example
    "libs/tb_common/llm.py",
    "services/adapter/backfill.py",
    "services/adapter/licensed.py",
    "services/adapter/pipeline.py",
    "services/console/app.py",
    "services/console/cli.py",
    "services/criteria_compiler/app.py",
    "services/gateway/app.py",
    "services/lake/source.py",
    "services/mail_gateway/app.py",
    "services/orchestrator/app.py",
    "services/orchestrator/selftest.py",
}
#: Where the chain itself is written or the journal is made.
CHAIN_MODULES = {"libs/tb_common/audit.py", "libs/tb_common/audit_writer.py"}
JOURNAL_DDL = {
    "libs/tb_common/audit_writer.py",
    "deploy/docker/db-init/30-service-roles.sh",
    "deploy/platform/base/db-init/30-service-roles.sh",
}
CONSTRUCT = re.compile(r"\bAuditLog\(")
WRITE_SQL = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|COPY)\s+\"?audit\"?\.", re.I)
#: Python run inside a service container by a host tool (``docker compose exec ... python -c``).
IN_CONTAINER = re.compile(r"""AuditLog\(\s*(?:Path\()?["']/data/audit""")


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _code(*dirs: str, suffixes: tuple[str, ...] = (".py",)) -> list[Path]:
    out: list[Path] = []
    for d in dirs:
        out += [p for p in (ROOT / d).rglob("*") if p.suffix in suffixes and p.is_file()
                and "/tests/" not in _rel(p) and not p.name.startswith("test_")]  # fmt: skip
    return sorted(out)


def test_no_service_or_library_builds_its_own_chain_writer() -> None:
    direct = [_rel(p) for p in _code("services", "libs")
              if _rel(p) not in CHAIN_MODULES and CONSTRUCT.search(p.read_text(encoding="utf-8"))]  # fmt: skip
    assert direct == [], "use tb_common.audit_writer.open_audit (D-394), not AuditLog(...)"


def test_the_writers_are_the_ones_listed() -> None:
    found = {_rel(p) for p in _code("services", "libs") if "open_audit(" in p.read_text(encoding="utf-8")}
    assert found - CHAIN_MODULES == WRITERS


def test_nothing_but_the_writer_writes_the_journal_table() -> None:
    hits = [
        _rel(p)
        for p in _code("services", "libs", "tools", "deploy", suffixes=(".py", ".sh", ".sql"))
        if _rel(p) not in JOURNAL_DDL and WRITE_SQL.search(p.read_text(encoding="utf-8", errors="replace"))
    ]
    assert hits == [], "only audit.append (tb_common.audit_writer) writes the audit journal"
    for rel in JOURNAL_DDL:  # and the one INSERT there is inside audit.append
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert len(re.findall(r"INSERT\s+INTO\s+audit\.", text, re.I)) == 1, rel


def test_code_run_in_a_service_container_writes_through_open_audit() -> None:
    hits = [_rel(p) for p in _code("tools", "deploy", suffixes=(".py", ".sh"))
            if IN_CONTAINER.search(p.read_text(encoding="utf-8", errors="replace"))]  # fmt: skip
    assert hits == []


def test_only_the_audit_writer_mounts_the_chain_read_write() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    rw: set[str] = set()
    ro: set[str] = set()
    for name, svc in services.items():
        for v in svc.get("volumes") or []:
            if isinstance(v, str) and v.startswith("audit-data:"):
                (ro if v.split("#")[0].strip().endswith(":ro") else rw).add(name)
    assert rw == {"audit-writer"}
    assert ro == {"criteria-compiler", "adapter", "orchestrator", "mail-gateway", "gateway", "console"}
    for name in ro:  # the six former writers send their events to the journal
        assert services[name]["environment"]["TB_AUDIT_WRITER"] == "db", name
    aw = services["audit-writer"]
    assert aw["command"] == ["python", "-m", "tb_common.audit_writer", "drain"]
    assert aw["environment"]["TB_DB_URL"].startswith("postgresql://tb_audit_writer:${TB_DB_PW_AUDIT_WRITER:-")
    assert "TB_AUDIT_WRITER" not in aw["environment"]
