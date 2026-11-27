"""P2-06 (ASSESS-1-ADDENDUM D3/D4, the integrator's rulings of 2026-11-27): the database's access posture.

An installed box ran with the socket at 0777 and ``trust``, ``ssl=off`` and no connection log. Now, from the files a
box starts with (no Docker here; the start itself was run on the db image, see the pull request):

* the access file is the repo's (``hba_file``, mounted read-only, read on every start, old volumes too): no ``trust``;
  the socket by ``peer`` with a map that admits only the container's own user; every TCP line ``hostssl`` with
  ``scram-sha-256``, so a client without TLS is refused;
* the socket is 0770; TLS is on, with a key made at each start in the db's tmpfs (0600, never on disk);
* each connection and disconnection is logged;
* the access model is written down: grants per role in 1.0, row-level policies in R2.
"""

from __future__ import annotations

import re

from tests.unit.test_compose_limits import BASE, DEPLOY, _merge

DOCKER = DEPLOY / "docker"
DOC = DEPLOY.parent / "docs" / "security" / "db-access-model.md"


def _rules(name: str) -> list[list[str]]:
    lines = (DOCKER / name).read_text(encoding="utf-8").splitlines()
    return [x.split() for x in lines if x.strip() and not x.lstrip().startswith("#")]


def _settings(db: dict) -> dict[str, str]:
    cmd = [str(x) for x in db["command"]]
    return dict(cmd[i + 1].split("=", 1) for i, x in enumerate(cmd) if x == "-c")


def test_the_access_file_has_no_trust_and_tls_on_every_tcp_line() -> None:
    rules = _rules("pg_hba.conf")
    assert rules and not [r for r in rules if "trust" in r]
    assert [r for r in rules if r[0] == "local"] == [["local", "all", "all", "peer", "map=tb_local"]]
    tcp = [r for r in rules if r[0] != "local"]
    assert tcp and all(r[0] == "hostssl" and r[-1] == "scram-sha-256" for r in tcp)
    assert _rules("pg_ident.conf") == [["tb_local", "postgres", "all"]]  # the container's user only


def test_the_db_reads_the_repos_access_file_on_every_start() -> None:
    db = _merge((BASE,))["db"]
    s = _settings(db)
    mounts = {v.split(":")[1]: v for v in db["volumes"]}
    for key, name in (("hba_file", "pg_hba.conf"), ("ident_file", "pg_ident.conf")):
        assert mounts[s[key]] == f"./docker/{name}:{s[key]}:ro"
    assert s["unix_socket_permissions"] == "0770"


def test_tls_is_on_with_a_key_made_at_each_start_in_the_tmpfs() -> None:
    db = _merge((BASE,))["db"]
    s = _settings(db)
    assert s["ssl"] == "on"
    assert s["ssl_cert_file"].startswith("/tmp/") and s["ssl_key_file"].startswith("/tmp/")
    assert any(str(t).startswith("/tmp") for t in db["tmpfs"]) and db["read_only"] is True
    start = " ".join(str(x) for x in db["entrypoint"])
    assert re.search(r"umask 077 && openssl req -x509 .*-nodes", start)
    assert f"-keyout {s['ssl_key_file']}" in start and f"-out {s['ssl_cert_file']}" in start
    assert start.rstrip().endswith('exec docker-entrypoint.sh "$$@" tb-db-start')  # the image's own entrypoint


def test_every_connection_is_logged() -> None:
    s = _settings(_merge((BASE,))["db"])
    assert s["log_connections"] == "on" and s["log_disconnections"] == "on"
    assert s["log_min_error_statement"] == "panic"  # T-209c still holds: no statement text in the log


def test_the_access_model_is_written() -> None:
    text = DOC.read_text(encoding="utf-8")
    for needle in ("grants", "row-level security", "R2", "pgaudit", "archive_mode", "hapi"):
        assert needle in text, needle
