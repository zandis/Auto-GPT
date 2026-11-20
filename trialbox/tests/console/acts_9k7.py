"""Helpers of the 9k-7 tests (D-1388): what a test can see written, and a test of another module run under a guard
that every confirmation page it reaches was reached with nothing written.

``snapshot`` is the test's database (every table of the test's own schemas, each as a digest of its rows) and every
file under the test's folder (the audit trail is files there: ``audit/*.jsonl``, the console's own folder). The
orchestrator's stand-in keeps its jobs in memory; that is not the database, and the tests run here assert their own
"not cancelled", "not retried" on it.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
import pytest
from console.act_classes import SHEETS
from fastapi.testclient import TestClient
from psycopg import sql
from tb_common.db import split_url

SHEET = re.compile(r'data-testid="(?:admin-)?confirm"')


def _db() -> dict[str, str]:
    dsn, prefix = split_url(os.environ["TB_DB_URL"])
    out: dict[str, str] = {}
    with psycopg.connect(dsn, autocommit=True) as con:
        like = prefix.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%") + "%"
        tables = con.execute(
            "SELECT schemaname, tablename FROM pg_tables WHERE schemaname LIKE %s ORDER BY 1, 2", (like,)
        ).fetchall()
        for schema, table in tables:
            q = sql.SQL("SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {}.{} x").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
            row = con.execute(q).fetchone()
            out[f"db:{schema[len(prefix) :]}.{table}"] = str(row[0] if row else "")
    return out


def _files(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            try:
                out[f"file:{p.relative_to(root)}"] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:  # a socket or a file removed while walking
                continue
    return out


def snapshot(root: Path) -> dict[str, str]:
    """The database and the files under ``root`` as they are now."""
    return {**_db(), **_files(root)}


# not an act: the signed-in session's own row (its last use), touched by every request of a signed-in person
SESSION = "db:auth.sessions"


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """What changed, leaving out the session's own row and the tables a store made on its first opening (its schema
    and seed rows: a migration, not an act)."""
    out = []
    for k in sorted(before.keys() | after.keys()):
        if before.get(k) == after.get(k) or k == SESSION or (k.startswith("db:") and k not in before):
            continue
        out.append(k)
    return out


def route_of(url: str, routes: Any = SHEETS) -> str | None:
    """The route pattern of ``routes`` that a request path matches (``{x}`` is one segment)."""
    path = url.split("://", 1)[-1]
    path = path[path.find("/") :] if "://" in url else path
    path = path.split("?", 1)[0]
    for r in sorted(routes, key=lambda x: x.count("{")):
        if re.fullmatch(re.sub(r"\\\{\w+\\\}", "[^/]+", re.escape(r)), path):
            return r
    return None


def run_guarded(
    fn: Callable[..., Any],
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    given: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Run the test ``fn`` (its fixtures from this module) while every POST that answers with a confirmation page is
    checked: nothing in the database or the folder changed between the request and the page. Returns, per sheet
    route reached, what changed (empty lists when nothing did)."""
    root = request.getfixturevalue("tmp_path")
    reached: dict[str, list[str]] = {}
    real = TestClient.request

    def guarded(self: TestClient, method: str, url: Any, *args: Any, **kwargs: Any) -> Any:
        if str(method).upper() != "POST":
            return real(self, method, url, *args, **kwargs)
        data = kwargs.get("data") or {}
        confirming = isinstance(data, dict) and str(data.get("confirm") or "") == "yes"
        before = snapshot(root) if not confirming else {}
        r = real(self, method, url, *args, **kwargs)
        if not confirming and SHEET.search(r.text or ""):
            route = route_of(str(url)) or f"(not a SHEETS route) {url}"
            reached.setdefault(route, []).extend(changed(before, snapshot(root)))
        return r

    monkeypatch.setattr(TestClient, "request", guarded)
    kwargs = dict(given or {})
    for name in inspect.signature(fn).parameters:
        if name not in kwargs:
            kwargs[name] = request.getfixturevalue(name)
    fn(**kwargs)
    return reached
