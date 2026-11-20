# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""``/data/instruments`` (T-307, D-375): the instrument copyright register for the steward in three languages; a
site switch with an empty licence reference is refused and audited; an accepted one is stored and audited; 403 for
the other roles."""

from __future__ import annotations

import json
from typing import Any

import pytest
from console import i18n_instruments, instruments_page  # noqa: F401 - importing the page merges its texts into CATALOGUES
from console.i18n import CATALOGUES
from tb_common import instruments

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    box,
    login,
)
from tests.console.test_role_pages import _csrf, _user
from tests.console.test_site_setup_pages import sb  # noqa: F401 - the box with the orchestrator's set-up routes


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e["event"] == name]


@pytest.mark.parametrize(
    ("lang", "title"), [("en", "Instrument licences"), ("ja", "評価尺度のライセンス"), ("zh-TW", "評估量表授權")]
)
def test_the_steward_sees_the_register_with_each_instruments_terms(box: dict[str, Any], lang: str, title: str) -> None:
    c, csrf = login(box["app"])
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    r = c.get("/data/instruments")
    assert r.status_code == 200 and title in r.text
    reg = instruments.register()
    assert r.text.count('data-testid="instrument"') == len(reg)
    for i in reg:
        assert f'data-instrument="{i.id}"' in r.text
    assert "Cardiff University" in r.text and 'data-licence="needed"' in r.text
    assert 'data-item="neuro.mmse_total" data-storable="score"' in r.text
    assert r.text.count('data-testid="not-in-catalogue"') == sum(1 for i in reg if not i.items)


def test_a_switch_needs_a_licence_reference_and_both_are_audited(sb: dict[str, Any]) -> None:
    """NEW-ARCH-3 slice 3 (D-864): the switch is the orchestrator's (a signed ``PUT /setup/instruments/{iid}``); the
    console still writes both events."""
    box = sb
    c, _ = login(box["app"])
    csrf = _csrf(c.get("/data/instruments").text)
    r = c.post("/data/instruments/mmse", data={"csrf": csrf, "storable": "score+items", "licence_ref": "  "},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 400 and "licence reference" in r.text
    (ev,) = _events(box, "instrument.switch_refused")
    assert ev["actor"] == "console:admin" and ev["detail"] == {"instrument": "mmse", "storable": "score+items",
                                                              "why": "no_ref"}  # fmt: skip
    assert 'data-item="neuro.mmse_total" data-storable="score"' in c.get("/data/instruments").text  # unchanged
    r = c.post("/data/instruments/mmse", data={"csrf": csrf, "storable": "score+items", "licence_ref": "LIC-SYN-7"},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    page = c.get("/data/instruments").text
    assert 'data-item="neuro.mmse_total" data-storable="score+items"' in page and "LIC-SYN-7" in page
    (ev,) = _events(box, "instrument.switch")
    assert ev["detail"] == {"instrument": "mmse", "storable": "score+items", "licence_ref": "LIC-SYN-7"}
    r = c.post("/data/instruments/mmse", data={"csrf": csrf, "storable": "score", "licence_ref": ""},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 303  # back to the catalogue's level: no reference needed
    assert 'data-item="neuro.mmse_total" data-storable="score"' in c.get("/data/instruments").text
    assert c.post("/data/instruments/eq5d", data={"csrf": csrf, "storable": "score", "licence_ref": "x"},
                  follow_redirects=False).status_code == 400  # fmt: skip


def test_the_orchestrator_refuses_a_switch_signed_by_a_coordinator(sb: dict[str, Any]) -> None:
    """NEW-ARCH-3 slice 3 (D-864): the callee asks for the administrator, as the page does; a coordinator holds
    ``site.setup`` for the site's set-up but not the instrument switches."""
    from tb_common import actor_v3

    path, body = "/setup/instruments/mmse", {"storable": "score+items", "licence_ref": "LIC-SYN-7"}
    for role, want in (("coordinator", 403), ("admin", 200)):
        token = actor_v3.mint(sub=f"console:{role}1", role=role, action="site.setup", method="PUT", path=path,
                              body=body, study="")  # fmt: skip
        r = sb["oc"].put(path, json=body, headers={actor_v3.HEADER: token})
        assert r.status_code == want, (role, r.text)
    assert sb["oc"].put(path, json=body).status_code in (401, 403)  # no person: refused


@pytest.mark.parametrize("role", ["coordinator", "investigator", "viewer", "cro"])
def test_other_roles_get_403_and_an_audit_event(box: dict[str, Any], role: str) -> None:
    c = _user(box, f"u-{role}", role)
    assert c.get("/data/instruments").status_code == 403
    assert any(e["detail"].get("action") == "/data/instruments" for e in _events(box, "console.denied"))


def test_the_three_catalogues_have_the_same_keys() -> None:
    assert set(i18n_instruments.EN) == set(i18n_instruments.JA) == set(i18n_instruments.ZH)
    assert all(k in CATALOGUES["ja"] for k in i18n_instruments.EN)
