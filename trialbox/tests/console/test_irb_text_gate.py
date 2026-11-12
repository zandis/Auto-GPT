"""D-395 (T-310b, RSK-42): the IRB-text record on the study set-up page and the gate on the candidate view.

* The study's PI records, on ``/studies/{rs}/state``, that the approved IRB text covers "identified pre-screening
  across departments by the investigator before referral", with the approval number of that text. Each record is
  audited (``console.irb_text``) in the store's transaction.
* Without the record a candidate's page, its chart number and the ``/api/v1`` candidate are refused (403) with the
  reason, in three languages, and the refusal is audited. With it they open. Taking it back closes them again.
* ``TB_IRB_TEXT_GATE``: on by default in VALIDATION and PRODUCTION, off in DEV and TEST; ``off`` is refused where it
  is on by default.

Synthetic data only."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from console.app import create_app
from console.sitestore import IRB_SENTENCE_ID, IrbText, SiteStore
from console.team import irb_text_gate
from fastapi.testclient import TestClient
from tb_common.authz import NO_STANDING, Standing, permit

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    PILOT_ENV,
    _done_screen,
    _ulid,
    box,
    login,
    name_pi,
)
from tests.console.test_role_pages import PW, _csrf
from tests.console.test_team_pages import _log_pi_and_sub

A = "a" * 32
AT = "2026-11-02T00:00:00+00:00"
TODAY = date(2026, 11, 2)
REF = "IRB-SYN-2026-014"


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line and json.loads(line).get("event") == name:
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------------------------- the record
def test_the_record_validates() -> None:
    assert IrbText().problems(TODAY) == ["note"]  # an empty "does not cover" is a withdrawal: it needs a note
    assert IrbText(covers=True).problems(TODAY) == ["approval_ref"]
    assert IrbText(covers=True, approval_ref=REF, text_version="v2.1", approved_on="2026-10-30").problems(TODAY) == []
    bad = IrbText(covers=True, approval_ref="-x", text_version="#1", approved_on="2026-11-03", note="a\x00")
    assert bad.problems(TODAY) == ["approval_ref", "text_version", "approved_on", "note"]  # a future day is refused
    assert IrbText(covers=False, note="committee letter 2026-11-01").problems(TODAY) == []
    assert not IrbText().enables and IrbText(covers=True, approval_ref=REF).enables
    # a record made for another sentence never opens the view for this one
    assert not IrbText(covers=True, approval_ref=REF, sentence="older_wording").enables


def test_store_round_trip_history_and_failed_audit() -> None:
    s = SiteStore()
    assert s.irb_text("GZQO") == IrbText() and s.irb_text_history("GZQO") == []

    def boom(_new: Any) -> None:
        raise RuntimeError("audit down")

    with pytest.raises(RuntimeError):
        s.record_irb_text("GZQO", IrbText(covers=True, approval_ref=REF), "drsato", AT, TODAY, before_commit=boom)
    assert s.irb_text_history("GZQO") == []  # a failed audit keeps nothing
    with pytest.raises(ValueError, match="approval_ref"):
        s.record_irb_text("GZQO", IrbText(covers=True), "drsato", AT, TODAY)
    s.record_irb_text("gzqo", IrbText(covers=True, approval_ref=REF, text_version="v2"), "drsato", AT, TODAY)
    got = s.irb_text("GZQO")
    assert got.enables and got.by == "drsato" and got.sentence == IRB_SENTENCE_ID and got.text_version == "v2"
    s.record_irb_text("GZQO", IrbText(note="committee letter"), "drsato", "2026-11-02T01:00:00+00:00", TODAY)
    assert not s.irb_text("GZQO").enables
    assert [e.covers for e in s.irb_text_history("GZQO")] == [True, False]
    assert not s.irb_text("OTHER").enables  # per study


@pytest.mark.parametrize(
    ("env", "on"),
    [
        ({"TB_ENV": "PRODUCTION"}, True),
        ({}, True),  # TB_ENV unset is PRODUCTION (D-127)
        ({"TB_ENV": "VALIDATION"}, True),
        ({"TB_ENV": "TEST"}, False),
        ({"TB_ENV": "DEV"}, False),
        ({"TB_ENV": "DEV", "TB_IRB_TEXT_GATE": "on"}, True),
        ({"TB_ENV": "TEST", "TB_IRB_TEXT_GATE": "off"}, False),
        ({"TB_ENV": "PRODUCTION", "TB_IRB_TEXT_GATE": "on"}, True),
    ],
)
def test_the_gate_setting(env: dict[str, str], on: bool) -> None:
    assert irb_text_gate(env) is on


def test_the_gate_cannot_be_turned_off_on_a_site_box() -> None:
    for name in ("PRODUCTION", "VALIDATION"):
        with pytest.raises(ValueError, match="refused"):
            irb_text_gate({"TB_ENV": name, "TB_IRB_TEXT_GATE": "off"})
    with pytest.raises(ValueError, match="auto, on or off"):
        irb_text_gate({"TB_IRB_TEXT_GATE": "maybe"})


def test_only_the_pi_records_it() -> None:
    assert permit("investigator", "study.irb_text", Standing(is_pi=True, tasks=frozenset(), log_names_pi=True)).allowed
    sub = Standing(is_pi=False, tasks=frozenset({"screen"}), log_names_pi=True)
    assert not permit("investigator", "study.irb_text", sub).allowed
    for role in ("admin", "coordinator", "viewer", "cro", "steward"):
        assert not permit(role, "study.irb_text", NO_STANDING).allowed


# ---------------------------------------------------------------------------------------------- the pages
def _gated_app(b: dict[str, Any]) -> Any:
    env = {**PILOT_ENV, "TB_CONSOLE_DIR": str(b["dir"] / "console-irbt"), "TB_IRB_TEXT_GATE": "on"}
    return create_app(env, backend=b["backend"], audit=b["audit"], users=b["users"])


def test_the_candidate_view_waits_for_the_irb_text(box: dict[str, Any]) -> None:  # noqa: F811
    """Acceptance: refused without the record, open with it, every record audited; taken back, refused again."""
    _done_screen(box["backend"], _ulid(971))
    app = _gated_app(box)
    for name, role in (("drsato", "investigator"), ("drkato", "investigator"), ("crc9", "coordinator")):
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    pi, _ = login(app, "drsato", PW)
    sub, _ = login(app, "drkato", PW)
    crc, _ = login(app, "crc9", PW)
    box["app"] = app
    _log_pi_and_sub(box, pi, ("screen", "refer"))

    # no record: the list says why and links the record; a candidate's page, its reveal and the API are refused
    lst = pi.get("/studies/GZQO/candidates")
    assert (
        lst.status_code == 200 and 'data-testid="irbt-off"' in lst.text and "/studies/GZQO/state#irb-text" in lst.text
    )
    for c in (pi, sub):
        for path in (f"/studies/GZQO/candidates/{A}?purpose=eligibility", f"/studies/GZQO/candidates/{A}"):
            r = c.get(path)
            assert r.status_code == 403 and "has not recorded" in r.text and "two flares" not in r.text, path
    r = pi.post(f"/studies/GZQO/candidates/{A}/reveal",
                data={"csrf": _csrf(lst.text), "purpose": "contact", "reason": "contact"})  # fmt: skip
    assert r.status_code == 403 and not box["backend"].revealed
    api = TestClient(app)
    tok = api.post("/api/v1/session", json={"username": "drsato", "password": PW}).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    assert api.get("/api/v1/studies/GZQO/candidates", headers=hdr).json()["candidate_view"] is False
    r = api.get(f"/api/v1/studies/GZQO/candidates/{A}?purpose=eligibility", headers=hdr)
    assert r.status_code == 403 and r.json()["error"] == "irbt.refused"
    denied = [e for e in _events(box, "console.denied") if e["detail"].get("reason") == "irb_text"]
    assert denied and denied[-1]["ruleset"] == "GZQO"
    assert not _events(box, "console.candidate_view")

    # the set-up page: the PI may record it; the coordinator and the sub-investigator may not
    page = pi.get("/studies/GZQO/state")
    assert 'data-testid="irbt-none"' in page.text and "Identified pre-screening across departments" in page.text
    assert 'data-testid="irbt-readonly"' not in page.text
    for c in (crc, sub):
        p = c.get("/studies/GZQO/state").text
        assert 'data-testid="irbt-readonly"' in p
        r = c.post("/studies/GZQO/irb-text", data={"csrf": _csrf(p), "covers": "1", "approval_ref": REF})
        assert r.status_code == 403
    # ticking without the approval number is refused and keeps nothing
    r = pi.post("/studies/GZQO/irb-text", data={"csrf": _csrf(page.text), "covers": "1"})
    assert r.status_code == 400 and 'data-testid="irbt-error"' in r.text and "IRB approval number" in r.text
    assert not _events(box, "console.irb_text")
    r = pi.post("/studies/GZQO/irb-text",
                data={"csrf": _csrf(page.text), "covers": "1", "approval_ref": REF, "text_version": "v2.1",
                      "approved_on": "2026-10-30"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    ev = _events(box, "console.irb_text")
    assert len(ev) == 1 and ev[0]["ruleset"] == "GZQO" and ev[0]["actor"] == "console:drsato"
    assert ev[0]["detail"]["covers"] is True and ev[0]["detail"]["approval_ref"] == REF
    assert ev[0]["detail"]["sentence"] == IRB_SENTENCE_ID
    page = pi.get("/studies/GZQO/state").text
    assert 'data-testid="irbt-on"' in page and REF in page and 'data-testid="irbt-history"' in page

    # with the record: the view opens for the PI and the delegated sub-investigator
    assert 'data-testid="irbt-off"' not in pi.get("/studies/GZQO/candidates").text
    for c in (pi, sub):
        r = c.get(f"/studies/GZQO/candidates/{A}?purpose=eligibility")
        assert r.status_code == 200 and "two flares this spring" in r.text
    assert api.get(f"/api/v1/studies/GZQO/candidates/{A}?purpose=eligibility", headers=hdr).status_code == 200
    r = pi.post(f"/studies/GZQO/candidates/{A}/reveal",
                data={"csrf": _csrf(page), "purpose": "contact", "reason": "contact"})  # fmt: skip
    assert "MRN-000123" in r.text

    # taken back: a note is required, then the view is closed again
    r = pi.post("/studies/GZQO/irb-text", data={"csrf": _csrf(page)})
    assert r.status_code == 400 and len(_events(box, "console.irb_text")) == 1
    r = pi.post("/studies/GZQO/irb-text", data={"csrf": _csrf(page), "note": "committee letter 2026-11-01"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and _events(box, "console.irb_text")[-1]["detail"]["covers"] is False
    assert pi.get(f"/studies/GZQO/candidates/{A}?purpose=eligibility").status_code == 403
    assert 'data-testid="irbt-withdrawn"' in pi.get("/studies/GZQO/state").text


def test_the_refusal_and_the_record_in_three_languages(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(972))
    app = _gated_app(box)
    box["users"].create("drsato", "investigator", PW, "drsato@hospa.test")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    pi, csrf = login(app, "drsato", PW)
    for lang, refused, sentence in (
        ("ja", "まだ記録していません", "診療科をまたぐ識別可能な事前スクリーニング"),
        ("zh-TW", "尚未記錄", "跨科可識別預先篩選"),
        ("en", "has not recorded", "Identified pre-screening across departments"),
    ):
        pi.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
        r = pi.get(f"/studies/GZQO/candidates/{A}?purpose=eligibility")
        assert r.status_code == 403 and refused in r.text, lang
        page = pi.get("/studies/GZQO/state").text
        assert sentence in page and 'data-testid="irbt-sentence"' in page, lang
        if lang != "en":  # the English original is shown beside the translation
            assert "Identified pre-screening across departments by the investigator before referral" in page


def test_off_in_a_test_environment_the_view_is_as_before(box: dict[str, Any]) -> None:  # noqa: F811
    """TB_ENV=TEST (the fixture): the view does not wait, and the page says so."""
    _done_screen(box["backend"], _ulid(973))
    box["users"].create("drsato", "investigator", PW, "drsato@hospa.test")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    pi, _ = login(box["app"], "drsato", PW)
    assert pi.get(f"/studies/GZQO/candidates/{A}?purpose=eligibility").status_code == 200
    assert 'data-testid="irbt-off"' not in pi.get("/studies/GZQO/candidates").text
    assert 'data-testid="irbt-gate-off"' in pi.get("/studies/GZQO/state").text
