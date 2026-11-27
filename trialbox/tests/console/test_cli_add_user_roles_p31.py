"""P-31: ``console.cli add-user`` makes an account of every role the console knows, and a CRO account takes its
studies on the command line (D-380: never without one). A CRO account made there sees its own study and no other."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from console import cli
from console.auth import ROLES, UserStore, needs_studies

from tests.console import test_console_app as base

box = base.box
PW = "p31-cli-password-0001"


def _add(monkeypatch: pytest.MonkeyPatch, name: str, role: str, *extra: str) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(PW + "\n"))
    return cli.main(["add-user", name, "--role", role, *extra, "--password-stdin"])


def _created(audit: Path) -> list[dict[str, Any]]:
    lines = [json.loads(x) for f in sorted(audit.glob("*")) if f.is_file()
             for x in f.read_text(encoding="utf-8").splitlines() if x.startswith("{")]  # fmt: skip
    return [e["detail"] for e in lines if e.get("event") == "console.user" and e["detail"]["action"] == "create"]


@pytest.mark.parametrize("role", ROLES)
def test_add_user_takes_every_role(role: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "audit"))
    users = UserStore()
    scoped = needs_studies(role, "hospital")
    extra = ("--studies", "gzqo") if scoped else ()
    assert _add(monkeypatch, "p31.user", role, *extra) == 0
    made = users.get("p31.user")
    assert made is not None and made.role == role
    assert made.studies == (("GZQO",) if scoped else ())
    assert users.must_change("p31.user")  # D-279: set by the operator, replaced by its owner
    [event] = _created(tmp_path / "audit")
    assert event["user"] == "p31.user" and event["role"] == role
    assert event["studies"] == ("GZQO" if scoped else "")


def test_a_cro_account_without_studies_is_refused_and_not_made(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "audit"))
    users = UserStore()
    assert _add(monkeypatch, "p31.cro", "cro") == 2
    assert not users.role_of("p31.cro")  # no account in any state
    assert _add(monkeypatch, "p31.cro", "cro", "--studies", "bad id!") == 2
    assert not users.role_of("p31.cro")  # no account in any state
    assert _created(tmp_path / "audit") == []


def test_a_cro_account_from_the_command_line_sees_no_other_study(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "cli-audit"))
    base._done_feas(box["backend"])  # a done feasibility of study GZQO
    users: UserStore = box["users"]
    for name, studies in (("cra.own", "GZQO"), ("cra.other", "OTHER")):
        assert _add(monkeypatch, name, "cro", "--studies", studies) == 0
        users.set_password(name, PW, must_change=False)  # its owner's own password
    own, _ = base.login(box["app"], "cra.own", PW)
    other, _ = base.login(box["app"], "cra.other", PW)
    assert own.get("/studies/GZQO/feasibility").status_code == 200
    assert other.get("/studies/GZQO/feasibility").status_code == 404
    assert "GZQO" not in other.get("/reports").text
