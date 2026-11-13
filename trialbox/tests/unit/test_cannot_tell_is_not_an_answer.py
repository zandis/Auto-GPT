"""NEW-FR-2 (D-711): two places in the console where "could not be read" was shown as an answer.

1. The audit page's Verify listed an anchor folder whose ``heads/`` the console may not read as reachable, with
   "no signed head yet" (``Path.glob`` passes over a folder it may not list). It is not reachable.
2. The scan of stored demo input (``python -m console.demo_guard scan --db``) reads the columns its database role
   may read. On a box with service roles the console's role sees its own stores; the scan said "clean" for the
   whole database. It names the stores it could not read and exits 1; run as the box's admin role it reads all.

The second under the real role script (``deploy/docker/db-init/30-service-roles.sh``). Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from console import audit_page, demo_guard
from tb_common.audit import AuditLog
from tb_common.crypto import ed25519_generate

from tests.unit.test_db_roles import ACCESS, SCHEMAS, _as, roles_cluster  # noqa: F401 - the fixture, by name


# ------------------------------------------------------------------ 1. the anchor folder
def _signed(tmp_path: Path) -> tuple[AuditLog, Path]:
    log = AuditLog(tmp_path / "audit", "UTC")
    log.append("synthetic.event", actor="test", detail={})
    share = tmp_path / "share"
    share.mkdir()
    priv, pub = ed25519_generate()
    log.sign_head(priv, pub, [share])
    return log, share


def test_an_anchor_folder_whose_heads_cannot_be_listed_is_not_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log, share = _signed(tmp_path)
    ok = audit_page.verify_now(Path(log.directory), [share])
    assert ok["anchors"] == [{"name": "share", "reachable": True, "count": 1, "newest": ok["anchors"][0]["newest"]}]
    real = Path.iterdir

    def refused(self: Path) -> Any:
        if self == share / "heads":
            raise PermissionError(13, "Permission denied")
        return real(self)

    monkeypatch.setattr(Path, "iterdir", refused)
    got = audit_page.verify_now(Path(log.directory), [share])
    assert got["anchors"] == [{"name": "share", "reachable": False, "newest": None, "count": 0}]


def test_an_anchor_folder_with_no_head_yet_is_reachable_and_one_that_is_gone_is_not(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit", "UTC")
    log.append("synthetic.event", actor="test", detail={})
    empty = tmp_path / "empty"
    empty.mkdir()
    got = audit_page.verify_now(Path(log.directory), [empty, tmp_path / "gone"])
    assert [(a["name"], a["reachable"], a["count"]) for a in got["anchors"]] == [("empty", True, 0), ("gone", False, 0)]


# ------------------------------------------------------------------ 2. the scan of stored demo input
def test_the_scan_names_the_stores_its_role_may_not_read(
    roles_cluster: tuple[Path, str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    url = roles_cluster[1]
    not_the_consoles = sorted(set(SCHEMAS) - set(ACCESS["tb_console"]))
    assert "edc" in not_the_consoles
    # as the console's own role: its stores are read, the others are named, and the scan does not say "clean"
    unread: set[str] = set()
    list(demo_guard._db_texts(_as(url, "tb_console"), None, unread))
    # every store of another service is named (and stores no service's list holds, such as the audit's), and none
    # of the console's own
    assert set(not_the_consoles) <= unread and not unread & set(ACCESS["tb_console"]), sorted(unread)
    monkeypatch.setenv("TB_DB_URL", _as(url, "tb_console"))
    monkeypatch.setattr(demo_guard, "MUST_SCAN", ())  # this cluster holds the role fixture's tables, not the console's
    assert demo_guard.main(["scan", "--db"]) == 1
    said = capsys.readouterr()
    assert "clean" not in said.out
    assert all(s in said.err for s in not_the_consoles) and "trialbox" in said.err
    # as the box's admin role, which is a member of every store's group: everything is read
    unread = set()
    list(demo_guard._db_texts(url, None, unread))
    assert unread == set()
    monkeypatch.setenv("TB_DB_URL", url)
    assert demo_guard.main(["scan", "--db"]) == 0
    assert "clean" in capsys.readouterr().out
