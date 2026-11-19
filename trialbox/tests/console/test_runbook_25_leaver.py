"""Card 10K-9 (D-1362): the drill of RUNBOOK §25, leavers (``docs/runbook/25-leavers.md``), step 1 for a member of the
trial team.

Two coordinators leave (synthetic accounts). One is disabled on **Users** (``/ops/users``, with its confirmation), the
other with ``console.cli disable NAME``: the two ways step 1 gives. Each could sign in before; after, the sign-in is
refused, the account is still there (never deleted: the audit names it), and the disable is in the audit with the
account's name. Steps 2 to 5 (the hospital directory, the delegation log, the mail lists, the hand-over) and the key
steward's KEK rotation are people's work or covered elsewhere (``tests/unit/test_kek.py``); the page says what this
drill does not rehearse.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from console import cli
from fastapi.testclient import TestClient

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name

PW = "coordinator-password-25"


def _sign_in(app: Any, user: str) -> int:
    """The sign-in form, as a person uses it: the status of the POST (303 into the console when it is taken)."""
    c = TestClient(app)
    token = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
    assert token
    r = c.post("/login", data={"username": user, "password": PW, "login_csrf": token.group(1)}, follow_redirects=False)
    return int(r.status_code)


def _disables(audit_dir: Path) -> list[str]:
    """The accounts named by the audit's disable events (the raw chain: the console's reader shows fewer fields)."""
    lines = [json.loads(x) for f in sorted(audit_dir.glob("*.jsonl"))
             for x in f.read_text(encoding="utf-8").splitlines() if x.startswith("{")]  # fmt: skip
    return [str(e["detail"].get("user")) for e in lines
            if e.get("event") == "console.user" and (e.get("detail") or {}).get("action") == "disable"]  # fmt: skip


def test_runbook_25_leaver(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    users, app, audit_dir = box["users"], box["app"], box["dir"] / "audit"
    users.create("crc.leaver1", "coordinator", PW, "crc.leaver1@hospa.test")
    users.create("crc.leaver2", "coordinator", PW, "crc.leaver2@hospa.test")
    assert _sign_in(app, "crc.leaver1") == 303 and _sign_in(app, "crc.leaver2") == 303

    # step 1 on Users: the administrator disables the account, and confirms
    admin, csrf = login(app)
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "disable", "username": "crc.leaver1"})
    assert "Disable the account crc.leaver1?" in r.text  # asks first
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "disable", "username": "crc.leaver1", "confirm": "yes"},
                   follow_redirects=False)  # fmt: skip
    assert r.status_code == 303

    # step 1 from the shell: console.cli disable NAME
    monkeypatch.setenv("TB_AUDIT_DIR", str(audit_dir))
    assert cli.main(["disable", "crc.leaver2"]) == 0

    for name in ("crc.leaver1", "crc.leaver2"):
        assert _sign_in(app, name) != 303, f"{name} can still sign in"
        # never deleted: the account stays, disabled, with its role (the audit and the signatures name it)
        assert users.get(name) is None and users.role_of(name) == "coordinator"
        assert name in {u.username for u in users.disabled_users()}
    assert sorted(_disables(audit_dir)) == ["crc.leaver1", "crc.leaver2"]
    # the administrator still signs in: step 1 closed only the leavers
    login(app)  # asserts the sign-in is taken
