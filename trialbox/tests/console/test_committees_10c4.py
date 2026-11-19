"""10C-4 (D-1227, JP-3): Japan's committees and the head of the institution's permission, on the one gate a study
passes to screen (the move to open: screening runs only for an open study).

* The plan's proof: a 指針 study cannot screen without this site's permission date; with it, it can.
* Each study kind: a 治験 and a 特定臨床研究 need their committee's approval of the current version.
* An external committee without a contract date warns; it does not refuse.
* An amendment: the old approval and permission read "for an earlier version"; an open study keeps screening on the
  version before (as every amendment today, D-311, D-364); a study in start-up does not open.
* A second site of a multi-site study needs its own permission date.
* The profile off (a Taiwanese site): no page, no item, no refusal.
* Each role records and reads exactly as on the study's IRB record.

Synthetic data only: committees, establishing bodies and versions are samples (見本)."""

from __future__ import annotations

from typing import Any, cast

import pytest
from console.i18n import CATALOGUES
from tb_common import committees as cm

from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - box is a fixture
from tests.console.test_role_pages import PW, _csrf, _user
from tests.console.test_t102b_roles import _api

AT = "2026-11-02T00:00:00+00:00"
SHISHIN = {"kind": "shishin", "establisher": "見本大学", "current_version": "1.0", "approved_version": "1.0",
           "approved_on": "2026-10-01", "central": "1", "documents": "Sample approval notice, 2026-10-01"}  # fmt: skip


@pytest.fixture
def jbox(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:  # noqa: F811
    """The console's test box at a Japanese site (the Japan profile on), site SAMPLE-A."""
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    monkeypatch.setenv("TB_SITE_ID", "SAMPLE-A")
    return box


def _en(key: str) -> str:
    """The English words of ``key`` as the page prints them (escaped)."""
    from markupsafe import escape

    return str(escape(CATALOGUES["en"][key]))


def _startup(b: dict[str, Any]) -> None:
    assert b["app"].state.helpers.store.begin_study("GZQO", "console:crc", AT) is not None


def _record(c: Any, **form: str) -> Any:
    page = c.get("/studies/GZQO/committee").text
    return c.post("/studies/GZQO/committee", data={"csrf": _csrf(page), **form}, follow_redirects=False)


def _open(c: Any) -> Any:
    page = c.get("/studies/GZQO/state").text
    return c.post("/studies/GZQO/state", data={"csrf": _csrf(page), "state": "open"}, follow_redirects=False)


# ---------------------------------------------------------------------------------------------- the rule itself
def test_the_rule_per_kind_amendment_contract_and_profile() -> None:
    full = cm.Committee("chiken", current_version="2.0", approved_version="2.0", approved_on="2026-10-01")
    assert cm.findings("JP", full, None) == []
    assert cm.findings("JP", cm.Committee("chiken", current_version="2.0"), None) == [("no_approval", "refuse")]
    assert cm.findings("JP", cm.Committee("tokutei", current_version="2.0"), None) == [("no_approval", "refuse")]
    amended = cm.Committee("tokutei", current_version="2.0", approved_version="1.0", approved_on="2026-01-05")
    assert cm.findings("JP", amended, None) == [("earlier_approval", "refuse")]
    shishin = cm.Committee("shishin", current_version="1.0", approved_version="1.0", approved_on="2026-10-01")
    assert cm.findings("JP", shishin, None) == [("no_permission", "refuse")]
    assert cm.findings("JP", shishin, cm.Permission("A", "1.0", "2026-10-10")) == []
    assert cm.findings("JP", shishin, cm.Permission("A", "0.9", "2026-01-10")) == [("earlier_permission", "refuse")]
    ext = cm.Committee("chiken", True, "見本法人", "", "2.0", "2.0", "2026-10-01")
    assert cm.findings("JP", ext, None) == [("no_contract", "warn")]
    assert cm.findings("JP", cm.Committee(), None) == [("kind_unset", "warn")]
    for country in ("TW", "", "US"):
        assert cm.findings(country, cm.Committee("shishin"), None) == []
    assert {k: cm.committee_of(k) for k in cm.KINDS} == {"chiken": "irb", "tokutei": "crb", "shishin": "ethics"}


# ---------------------------------------------------------------------------------------------- the plan's proof
def test_a_shishin_study_cannot_screen_without_the_permission_date(
    jbox: dict[str, Any],
) -> None:
    from types import SimpleNamespace

    from orchestrator import scheduler
    from orchestrator.clients import StepFailed
    from orchestrator.scenarios import screen

    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    assert _record(crc, **SHISHIN).status_code == 303
    r = _open(crc)
    assert r.status_code == 409 and 'data-testid="state-error"' in r.text
    assert _en("sid.cmt.no_permission") in r.text and _en("sstate.committee").split(":")[0] in r.text
    assert scheduler.study_state("GZQO") == "startup"
    with pytest.raises(StepFailed, match="lists run only for an open study"):
        screen.run(cast(Any, SimpleNamespace(job=SimpleNamespace(ruleset="GZQO", options={}))))
    # with this site's permission for the current version, the study opens and lists run
    r = _record(crc, **SHISHIN, permission_version="1.0", permitted_on="2026-10-10", reason="permission letter in")
    assert r.status_code == 303
    assert _open(crc).status_code == 303
    assert scheduler.study_state("GZQO") == "open"
    scheduler.require_open("GZQO")


def test_the_state_page_lists_the_committee_before_open(
    jbox: dict[str, Any],
) -> None:
    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    page = crc.get("/studies/GZQO/state").text
    assert 'data-testid="before-open-committee" data-done="no"' in page and 'href="/studies/GZQO/committee"' in page
    _record(crc, kind="chiken", current_version="3.0", approved_version="3.0", approved_on="2026-10-01")
    assert 'data-testid="before-open-committee" data-done="yes"' in crc.get("/studies/GZQO/state").text


# ---------------------------------------------------------------------------------------------- each kind
@pytest.mark.parametrize("kind", ["chiken", "tokutei"])
def test_a_trial_or_specified_research_needs_its_committee_approval(
    jbox: dict[str, Any],
    kind: str,
) -> None:
    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    assert _record(crc, kind=kind, current_version="1.0").status_code == 303
    r = _open(crc)
    assert r.status_code == 409 and _en("sid.cmt.no_approval") in r.text
    page = crc.get("/studies/GZQO/committee").text
    assert CATALOGUES["en"]["cmt.committee." + cm.committee_of(kind)] in page
    _record(crc, kind=kind, current_version="1.0", approved_version="1.0", approved_on="2026-10-01",
            reason="approval notice arrived")  # fmt: skip
    assert _open(crc).status_code == 303  # no permission date is asked of a 治験 or 特定臨床研究


def test_no_kind_chosen_warns_and_does_not_refuse(
    jbox: dict[str, Any],
) -> None:
    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    assert 'data-testid="cmt-finding-kind_unset"' in crc.get("/studies/GZQO/committee").text
    assert _open(crc).status_code == 303


def test_an_external_committee_without_a_contract_warns(
    jbox: dict[str, Any],
) -> None:
    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    _record(crc, kind="chiken", external="1", establisher="見本医療法人", current_version="1.0",
            approved_version="1.0", approved_on="2026-10-01")  # fmt: skip
    page = crc.get("/studies/GZQO/committee").text
    assert 'data-testid="cmt-finding-no_contract" data-level="warn"' in page
    assert _open(crc).status_code == 303  # a warning, not a refusal
    _record(crc, kind="chiken", external="1", establisher="見本医療法人", contract_on="2026-09-01",
            current_version="1.0", approved_version="1.0", approved_on="2026-10-01", reason="contract filed today")  # fmt: skip
    assert "cmt-finding-no_contract" not in crc.get("/studies/GZQO/committee").text


# ---------------------------------------------------------------------------------------------- amendment
def test_an_amendment_reads_as_an_earlier_version_and_an_open_study_keeps_screening(
    jbox: dict[str, Any],
) -> None:
    from orchestrator import scheduler

    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    _record(crc, **SHISHIN, permission_version="1.0", permitted_on="2026-10-10")
    assert _open(crc).status_code == 303
    r = _record(crc, **{**SHISHIN, "current_version": "2.0"}, permission_version="1.0", permitted_on="2026-10-10",
                reason="protocol version 2.0 received")  # fmt: skip
    assert r.status_code == 303
    page = crc.get("/studies/GZQO/committee").text
    assert (
        'data-testid="cmt-finding-earlier_approval"' in page and 'data-testid="cmt-finding-earlier_permission"' in page
    )
    assert _en("cmt.f.earlier_permission") in page  # says what is needed
    assert scheduler.study_state("GZQO") == "open"  # screening goes on, on the version before (D-311, D-364)
    irb = crc.get("/studies/GZQO/irb").text
    assert 'data-testid="committee-link"' in irb and 'data-testid="cmt-finding-earlier_permission"' in irb
    # paused and opened again under the amendment: the gate holds until the new version is approved and permitted
    page = crc.get("/studies/GZQO/state").text
    crc.post("/studies/GZQO/state", data={"csrf": _csrf(page), "state": "paused", "reason": "awaiting v2 permission"})
    r = _open(crc)
    assert r.status_code == 409 and _en("sid.cmt.earlier_permission") in r.text
    _record(crc, **{**SHISHIN, "current_version": "2.0", "approved_version": "2.0", "approved_on": "2026-11-01"},
            permission_version="2.0", permitted_on="2026-11-02", reason="version 2.0 approved and permitted")  # fmt: skip
    assert _open(crc).status_code == 303


# ---------------------------------------------------------------------------------------------- a second site
def test_a_second_site_needs_its_own_permission(
    jbox: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _startup(jbox)
    team = jbox["app"].state.helpers.team
    team.save_committee("GZQO", cm.Committee("shishin", current_version="1.0", approved_version="1.0",
                                             approved_on="2026-10-01", central=True), "crc0", AT)  # fmt: skip
    team.save_permission("GZQO", cm.Permission("SAMPLE-A", "1.0", "2026-10-10"), "crc0", AT)
    monkeypatch.setenv("TB_SITE_ID", "SAMPLE-B")  # the same central review, another site's jbox
    crc = _user(jbox, "crc1", "coordinator")
    r = _open(crc)
    assert r.status_code == 409 and _en("sid.cmt.no_permission") in r.text
    page = crc.get("/studies/GZQO/committee").text
    assert "SAMPLE-B" in page and 'data-testid="cmt-finding-no_permission"' in page
    _record(crc, **SHISHIN, permission_version="1.0", permitted_on="2026-10-20", reason="site B permission letter")
    assert team.permission("GZQO", "SAMPLE-B").permitted_on == "2026-10-20"
    assert team.permission("GZQO", "SAMPLE-A").permitted_on == "2026-10-10"
    assert _open(crc).status_code == 303


# ---------------------------------------------------------------------------------------------- the profile off
def test_with_the_profile_off_nothing_changes(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setenv("TB_TZ", "Asia/Taipei")
    _startup(box)
    crc = _user(box, "crc1", "coordinator")
    assert crc.get("/studies/GZQO/committee").status_code == 404
    assert _api(box, "crc1").get("/api/v1/studies/GZQO/committee").status_code == 404
    irb = crc.get("/studies/GZQO/irb").text
    assert "committee" not in irb
    state = crc.get("/studies/GZQO/state").text
    assert "before-open-committee" not in state and "/committee" not in state
    box["app"].state.helpers.team.save_committee("GZQO", cm.Committee("shishin", current_version="1.0"), "x", AT)
    assert _open(crc).status_code == 303  # a record made elsewhere is not read here


# ---------------------------------------------------------------------------------------------- each role
ROLES: tuple[tuple[str, str, dict[str, str]], ...] = (("admin_r", "admin", {}), ("crc_h", "coordinator", {}),
         ("crc_smo", "coordinator", {"affiliation": "smo", "studies": "GZQO"}), ("dr_pi", "investigator", {}),
         ("dr_sub", "investigator", {}), ("view_r", "viewer", {}), ("cro_r", "cro", {"affiliation": "cro", "studies": "GZQO"}),
         ("stw_r", "steward", {}), ("prv_r", "privacy", {}))  # fmt: skip


def test_each_role_records_and_reads_as_on_the_irb_record(
    jbox: dict[str, Any],
) -> None:
    """No new right and no role sees more: for every role, reading the committee page answers as the IRB page, and
    recording answers as recording the IRB record (page and API)."""
    for name, role, scope in ROLES:
        _user(jbox, name, role, **scope)
    name_pi(jbox, "dr_pi")
    body = {"approval_no": "IRB-SAMPLE-1", "approved_on": "2026-10-01"}
    for name, _role, _scope in ROLES:
        c, csrf = login(jbox["app"], name, PW)
        irb_read, cmt_read = c.get("/studies/GZQO/irb").status_code, c.get("/studies/GZQO/committee").status_code
        assert irb_read == cmt_read, (name, irb_read, cmt_read)
        api = _api(jbox, name)
        assert api.get("/api/v1/studies/GZQO/irb").status_code == api.get("/api/v1/studies/GZQO/committee").status_code
        irb_ok = c.post("/studies/GZQO/irb", data={"csrf": csrf, **body, "reason": f"role walk {name} entry"},
                        follow_redirects=False).status_code  # fmt: skip
        cmt_ok = c.post("/studies/GZQO/committee", data={"csrf": csrf, **SHISHIN, "reason": f"role walk {name} entry"},
                        follow_redirects=False).status_code  # fmt: skip
        assert (irb_ok == 303) == (cmt_ok == 303), (name, irb_ok, cmt_ok)
        api_irb = api.post("/api/v1/studies/GZQO/irb", json={**body, "reason": f"role walk {name} api"}).status_code
        api_cmt = api.post("/api/v1/studies/GZQO/committee", json={"kind": "shishin", "current_version": "1.0",
                                                                    "reason": f"role walk {name} api"}).status_code  # fmt: skip
        assert (api_irb == 200) == (api_cmt == 200), (name, api_irb, api_cmt)
        if cmt_read == 200:
            page = c.get("/studies/GZQO/committee").text
            assert ('data-testid="cmt-form"' in page) == (cmt_ok == 303), name
    writers = {
        str(e["actor"]).split(":")[-1] for e in _audit(jbox) if (e.get("detail") or {}).get("action") == "committee"
    }
    assert writers == {"crc_h", "dr_pi"}  # a hospital coordinator and the logged PI; never SMO, CRO, admin, a sub-I


def _audit(b: dict[str, Any]) -> list[dict[str, Any]]:
    import json

    out = []
    for f in sorted((b["dir"] / "audit").glob("*")):
        out += [json.loads(x) for x in f.read_text().splitlines() if x and '"console.irb"' in x]
    return out


# ---------------------------------------------------------------------------------------------- the words
def test_every_key_in_the_three_languages() -> None:
    from console import i18n_committee as ic

    assert set(ic.EN) == set(ic.JA) == set(ic.ZH)
    for code in ("kind_unset", "no_version", "no_approval", "earlier_approval", "no_permission", "earlier_permission",
                 "no_contract"):  # fmt: skip
        for lang in ("en", "ja", "zh-TW"):
            assert f"cmt.f.{code}" in CATALOGUES[lang]
            if code not in ("kind_unset", "no_contract"):
                assert f"sid.cmt.{code}" in CATALOGUES[lang]
