"""STEPS-ROLE (D-877, the owner's D-1063): the role x route matrix, walked once per acting role.

One account (its own role ``viewer``, and every other hospital role as an extra role) switches its acting role, and
every route of the router table is called once in each, as ``test_role_route_matrix`` calls it for each column (the
page with the role's CSRF token, ``/api/v1`` with its bearer token). No route may let the acting role in where the
design table's column of an account of that role does not: acting adds no right. The column of an investigator is
``pi`` (an investigator the GZQO log does not name); the account is on no log.

A second account (its own role ``admin``) acting as ``viewer`` holds the same: an acting role never keeps the rights
of the account's own role."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.console.test_console_app import _done_feas, _done_screen, _ulid, box, login  # noqa: F401 - fixture by name
from tests.console.test_role_route_matrix import (
    CHANGING,
    TABLE,
    _cell,
    _fill,
    _for,
    _orchestrator_routes,
    _routes,
    parse,
)

PW = "acting-matrix-password-01"
#: acting role -> the design table's column of an account of that role
COLUMN = {"admin": "admin", "coordinator": "crc", "investigator": "pi", "viewer": "viewer", "steward": "steward",
          "privacy": "privacy"}  # fmt: skip


def _walk(b: dict[str, Any], page: TestClient, csrf: str, api: TestClient, job_id: str) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for changing in (False, True):
        for method, path in _routes(b["app"]):
            if (method in CHANGING) != changing:
                continue
            url = _fill(path, job_id)
            _for(b, path)
            if path.startswith("/api/v1/"):
                r = api.request(method, url, json={} if changing else None, follow_redirects=False)
            else:
                r = page.request(method, url, data={"csrf": csrf} if changing else None, follow_redirects=False)
            out[(method, path)] = _cell(r)
    _for(b, "")
    return out


def _acting_walks(b: dict[str, Any], name: str, own: str, roles: list[str]) -> dict[str, dict[tuple[str, str], str]]:
    from tb_common.flags import Flags

    users = b["users"]
    users.create(name, own, PW, f"{name}@hospa.test")
    users.grant_roles(name, [r for r in COLUMN if r != own], allowed=True)
    if Flags(audit=b["audit"]).get("steps.acting_role", "off") != "on":
        Flags(audit=b["audit"]).set("steps.acting_role", "on", "console:admin", "the matrix per acting role")
    page, csrf = login(b["app"], name, PW)
    token, sess = users.new_session(users.get(name), via="api")
    api = TestClient(b["app"], headers={"Authorization": f"Bearer {token}"})
    job_id = _ulid(991)
    out = {}
    for role in roles:
        assert page.post("/role", data={"csrf": csrf, "role": role}, follow_redirects=False).status_code == 303
        users.set_acting(sess, role)
        out[role] = _walk(b, page, csrf, api, job_id)
    return out


def _opened_beyond(design: dict[tuple[str, str], dict[str, str]], walked: dict[tuple[str, str], str],
                   column: str) -> list[str]:  # fmt: skip
    return [f"{m} {p}: acting {cell}, the {column} column {design.get((m, p), {}).get(column)}"
            for (m, p), cell in sorted(walked.items())
            if cell == "Y" and design.get((m, p), {}).get(column) != "Y"]  # fmt: skip


@pytest.fixture
def walked_box(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:  # noqa: F811
    monkeypatch.setenv("TB_ENV", "TEST")
    _orchestrator_routes(box)
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(991))
    return box


def test_no_acting_role_opens_a_route_its_own_column_does_not(walked_box: dict[str, Any]) -> None:
    design = parse(TABLE.read_text(encoding="utf-8"))
    walks = _acting_walks(walked_box, "mei", "viewer", list(COLUMN))
    assert len(next(iter(walks.values()))) > 150  # the walk reached the router table
    beyond = [line for role, walked in walks.items() for line in _opened_beyond(design, walked, COLUMN[role])]
    assert not beyond, "an acting role opened a route its own column does not:\n" + "\n".join(beyond)
    errors = [f"{role} {m} {p}" for role, walked in walks.items() for (m, p), c in walked.items() if c == "E"]
    assert not errors, errors
    # D-280 per acting role: acting as the administrator answers every patient-level route as the administrator's own
    # column does, and opens no patient-level page to read (a change with an empty body is refused with 400 before
    # some routes ask the role: the design table's Y for the administrator there too)
    patient = [k for k in walks["admin"] if "/patients/" in k[1] or "{pid}" in k[1]]
    assert patient and all(walks["admin"][k] == design[k]["admin"] for k in patient if k in design)
    assert not [k for k in patient if k[0] == "GET" and walks["admin"][k] == "Y"]


def test_an_administrator_acting_as_a_viewer_keeps_no_administrators_right(walked_box: dict[str, Any]) -> None:
    design = parse(TABLE.read_text(encoding="utf-8"))
    walks = _acting_walks(walked_box, "ops2", "admin", ["viewer"])
    beyond = _opened_beyond(design, walks["viewer"], "viewer")
    assert not beyond, "acting as a viewer kept a right:\n" + "\n".join(beyond)
