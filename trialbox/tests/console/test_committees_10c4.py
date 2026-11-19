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

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from console.i18n import CATALOGUES
from tb_common import committees as cm

from tests.console.test_cjk_layout import PHONE, SCRIPT, _node_playwright
from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - box is a fixture
from tests.console.test_role_pages import PW, _csrf, _user
from tests.console.test_t102b_roles import _api

AT = "2026-11-02T00:00:00+00:00"
DAY = date(2026, 11, 2)
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
    assert cm.findings("JP", full, None, DAY) == []
    assert cm.findings("JP", cm.Committee("chiken", current_version="2.0"), None, DAY) == [("no_approval", "refuse")]
    assert cm.findings("JP", cm.Committee("tokutei", current_version="2.0"), None, DAY) == [("no_approval", "refuse")]
    amended = cm.Committee("tokutei", current_version="2.0", approved_version="1.0", approved_on="2026-01-05")
    assert cm.findings("JP", amended, None, DAY) == [("earlier_approval", "refuse")]
    shishin = cm.Committee("shishin", current_version="1.0", approved_version="1.0", approved_on="2026-10-01")
    assert cm.findings("JP", shishin, None, DAY) == [("no_permission", "refuse")]
    assert cm.findings("JP", shishin, cm.Permission("A", "1.0", "2026-10-10"), DAY) == []
    assert cm.findings("JP", shishin, cm.Permission("A", "0.9", "2026-01-10"), DAY) == [
        ("earlier_permission", "refuse")
    ]
    ext = cm.Committee("chiken", True, "見本法人", "", "2.0", "2.0", "2026-10-01")
    assert cm.findings("JP", ext, None, DAY) == [("no_contract", "warn")]
    assert cm.findings("JP", cm.Committee(), None, DAY) == [("kind_unset", "warn")]
    for country in ("TW", "", "US"):
        assert cm.findings(country, cm.Committee("shishin"), None, DAY) == []
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


def test_no_kind_chosen_refuses_a_new_open(jbox: dict[str, Any]) -> None:
    """Review item 5: under the Japan profile a study opens only once its kind is chosen (clearing the kind cannot
    turn the gate off); a study already open keeps running (the transition rule)."""
    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    assert 'data-testid="cmt-finding-kind_unset"' in crc.get("/studies/GZQO/committee").text
    r = _open(crc)
    assert r.status_code == 409 and _en("sid.cmt.kind_unset") in r.text
    # a paused 指針 study whose kind is cleared does not reopen
    _record(crc, **SHISHIN, permission_version="1.0", permitted_on="2026-10-10")
    assert _open(crc).status_code == 303
    page = crc.get("/studies/GZQO/state").text
    crc.post("/studies/GZQO/state", data={"csrf": _csrf(page), "state": "paused", "reason": "sponsor letter"})
    _record(crc, **{**SHISHIN, "kind": ""}, reason="kind cleared by mistake")
    r = _open(crc)
    assert r.status_code == 409 and _en("sid.cmt.kind_unset") in r.text


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


# ---------------------------------------------------------------------------------------------- a phone
@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
def test_the_pages_fit_a_phone_in_three_languages(jbox: dict[str, Any], tmp_path: Path) -> None:
    """The committee page (form, findings), the IRB page with its committee card and the state page's refusal, at
    390 px in en, ja and zh-TW, measured in Chromium (``tests/console/cjk_layout.js``: no sideways scroll, no label
    broken to one character)."""
    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    _record(crc, kind="shishin", external="1", establisher="見本大学", current_version="1.0")
    out = tmp_path / "pages"
    out.mkdir()
    pages: list[dict[str, Any]] = []
    for lang in ("en", "ja", "zh-TW"):
        crc.post("/lang", data={"csrf": _csrf(crc.get("/").text), "lang": lang, "back": "/"})
        for name, text in (
            ("committee", crc.get("/studies/GZQO/committee").text),
            ("irb", crc.get("/studies/GZQO/irb").text),
            ("state", _open(crc).text),
        ):
            assert CATALOGUES[lang]["cmt.title"] in text or name == "state", (name, lang)
            f = f"{name}-{lang}.html"
            (out / f).write_text(text.replace('href="/static/console.css"', 'href="console.css"'), encoding="utf-8")
            pages.append({"file": f, "lang": lang, "width": PHONE[0], "height": PHONE[1], "checks": []})
    (out / "console.css").write_text(crc.get("/static/console.css").text, encoding="utf-8")
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps({"dir": str(out), "pages": pages, "shots": ""})],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=600, check=False,
    )  # fmt: skip
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and res["failed"] == 0, (res.get("results"), r.stderr[-2000:])


# ---------------------------------------------------------------------------------------------- the review's cases
def _scheduler() -> Any:
    from orchestrator import scheduler

    return scheduler


def _held_now(rid: str = "GZQO") -> list[str]:
    """The orchestrator's open check before a list: [] when a list runs, else the codes that hold it."""
    from orchestrator.clients import StepFailed

    try:
        _scheduler().require_open(rid)
    except StepFailed as exc:
        return [str(exc)]
    return []


def test_the_rule_at_open_at_lists_and_in_waiting() -> None:
    shishin = cm.Committee("shishin", current_version="2.0", approved_version="2.0", approved_on="2026-10-01")
    none = cm.findings("JP", shishin, None, DAY)
    assert cm.at_open(none) == ["no_permission"] and cm.at_lists(none, True) == ["no_permission"]
    amended = cm.findings("JP", shishin, cm.Permission("A", "1.0", "2026-10-10"), DAY)
    assert cm.at_open(amended) == ["earlier_permission"]
    assert cm.at_lists(amended, True) == [] and cm.in_waiting(amended) == ["earlier_permission"]
    assert cm.at_lists(amended, False) == ["earlier_permission"]  # no recorded state: never passed the move into open
    unset = cm.findings("JP", cm.Committee(), None, DAY)
    assert (
        cm.at_open(unset) == ["kind_unset"]
        and cm.at_lists(unset, False) == []
        and cm.in_waiting(unset) == ["kind_unset"]
    )
    # review item 6: a date after the site's today is not yet held
    future = cm.findings("JP", shishin, cm.Permission("A", "2.0", "2026-12-01"), DAY)
    assert cm.at_open(future) == ["no_permission"]
    late = cm.Committee("chiken", True, "見本法人", "2026-12-01", "2.0", "2.0", "2026-12-01")
    assert cm.findings("JP", late, None, DAY) == [("no_approval", "refuse"), ("no_contract", "warn")]


def test_a_study_with_no_recorded_state_is_held(jbox: dict[str, Any]) -> None:
    """Review blocker 1: a known study with no recorded state counts as open; its lists are held by the record."""
    sch = _scheduler()
    assert sch.recorded_study_state("GZQO") is None and _held_now() == []  # no record: the other-country default
    team = jbox["app"].state.helpers.team
    team.save_committee("GZQO", cm.Committee("shishin", current_version="1.0", approved_version="1.0",
                                             approved_on="2026-10-01"), "crc0", AT)  # fmt: skip
    held = _held_now()
    assert held and "no_permission" in held[0] and "committee page" in held[0]
    orch = _Orch()
    sch._submit(orch, "MICROBATCH", "GZQO")
    assert orch.created == [] and orch.events[-1][1]["detail"]["state"] == "committee: no_permission"
    team.save_permission("GZQO", cm.Permission("SAMPLE-A", "1.0", "2026-10-10"), "crc0", AT)
    assert _held_now() == []


def test_the_kind_set_after_the_study_opened_holds_its_lists(jbox: dict[str, Any]) -> None:
    """Review blocker 1: an open study whose kind is then set to 指針 without a permission stops listing, and the
    state page and the IRB page say why."""
    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    _record(crc, kind="chiken", current_version="1.0", approved_version="1.0", approved_on="2026-10-01")
    assert _open(crc).status_code == 303 and _held_now() == []
    r = _record(crc, **SHISHIN, reason="it is a guideline study after all")
    assert r.status_code == 303
    assert "no_permission" in _held_now()[0]
    state = crc.get("/studies/GZQO/state").text
    assert 'data-testid="cmt-held-no_permission"' in state
    assert 'data-testid="cmt-held"' in crc.get("/studies/GZQO/irb").text


def test_a_close_taken_back_to_open_passes_the_gate(jbox: dict[str, Any]) -> None:
    """Review blocker 1: open, amend, close, the PI's take-back: back to open is a move into open."""
    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    _user(jbox, "dr1", "investigator")
    name_pi(jbox, "dr1")
    _record(crc, **SHISHIN, permission_version="1.0", permitted_on="2026-10-10")
    assert _open(crc).status_code == 303
    _record(crc, **{**SHISHIN, "current_version": "2.0"}, reason="protocol version 2.0 received")
    assert _held_now() == []  # the amendment: an open study keeps screening on the version before
    page = crc.get("/studies/GZQO/state").text
    r = crc.post("/studies/GZQO/state", data={"csrf": _csrf(page), "state": "closed", "reason": "sponsor stopped",
                                              "confirm": "yes"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-400:]
    pi, csrf = login(jbox["app"], "dr1", PW)
    r = pi.post("/studies/GZQO/state/take-back", data={"csrf": csrf, "reason": "closed by mistake"})
    assert r.status_code == 409 and _en("sstate.committee_back")[:30] in r.text
    assert _scheduler().study_state("GZQO") == "closed"


def test_a_study_open_when_the_profile_arrives_keeps_running(
    jbox: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transition rule (the coordinator's ruling, for the owner to confirm): a study opened while the profile was
    off keeps running when it is switched on; the state page and the IRB page show what is still to record, with the
    date the site sets; nothing stops by itself."""
    monkeypatch.setenv("TB_TZ", "Asia/Taipei")
    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    assert _open(crc).status_code == 303
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")  # the Japan profile switched on
    assert _held_now() == []
    state = crc.get("/studies/GZQO/state").text
    assert 'data-testid="cmt-waiting-kind_unset"' in state and "Record by" not in state
    _record(crc, due_on="2026-12-31")
    state = crc.get("/studies/GZQO/state").text
    assert 'data-testid="cmt-waiting-kind_unset"' in state and "2026-12-31" in state
    assert 'data-testid="cmt-waiting"' in crc.get("/studies/GZQO/irb").text
    assert _held_now() == []


def test_the_permission_is_changed_only_on_purpose(jbox: dict[str, Any]) -> None:
    """Review item 4: an API save without the permission fields leaves the site's 実施許可日; clearing it is its own
    action, with a reason, audited."""
    _startup(jbox)
    _user(jbox, "crc1", "coordinator")
    api = _api(jbox, "crc1")
    body = {k: v for k, v in SHISHIN.items() if k != "central"}
    r = api.post(
        "/api/v1/studies/GZQO/committee", json={**body, "permission_version": "1.0", "permitted_on": "2026-10-10"}
    )
    assert r.status_code == 200 and r.json()["permission"] == {"version": "1.0", "permitted_on": "2026-10-10"}
    assert "by" not in json.dumps(r.json()["permission"])  # review item 7: as the IRB API, not who recorded it
    r = api.post(
        "/api/v1/studies/GZQO/committee", json={**body, "documents": "Sample notice v2", "reason": "notice renamed"}
    )
    assert r.status_code == 200 and r.json()["permission"]["permitted_on"] == "2026-10-10"
    r = api.post("/api/v1/studies/GZQO/committee", json={**body, "clear_permission": True})
    assert r.status_code == 400  # a reason first
    r = api.post("/api/v1/studies/GZQO/committee", json={**body, "documents": "Sample notice v2", "clear_permission": True,
                                                         "reason": "permission withdrawn by the head"})  # fmt: skip
    assert r.status_code == 200 and r.json()["permission"] is None
    ev = [e for e in _audit(jbox) if (e.get("detail") or {}).get("permission") == "cleared"]
    assert ev and ev[-1]["detail"]["before_permission"] == "1.0 2026-10-10"


def test_a_future_permission_date_stored_does_not_open(jbox: dict[str, Any]) -> None:
    """Review item 6: the gate compares with the site's today, not only the save."""
    _startup(jbox)
    team = jbox["app"].state.helpers.team
    team.save_committee("GZQO", cm.Committee("shishin", current_version="1.0", approved_version="1.0",
                                             approved_on="2026-10-01"), "crc0", AT)  # fmt: skip
    team.save_permission("GZQO", cm.Permission("SAMPLE-A", "1.0", "2099-01-01"), "crc0", AT)
    crc = _user(jbox, "crc1", "coordinator")
    r = _open(crc)
    assert r.status_code == 409 and _en("sid.cmt.no_permission") in r.text


def test_a_too_long_field_is_400_and_the_right_comes_first(jbox: dict[str, Any]) -> None:
    """Review item 3: the right is checked before the fields are read; a field too long is 400, never 500."""
    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    page = crc.get("/studies/GZQO/committee").text
    r = crc.post("/studies/GZQO/committee", data={"csrf": _csrf(page), "kind": "x" * 40, "contract_on": "9" * 30})
    assert r.status_code == 400
    stw = _user(jbox, "stw1", "steward")
    page = stw.get("/studies/GZQO/committee").text
    r = stw.post("/studies/GZQO/committee", data={"csrf": _csrf(page), "kind": "x" * 40})
    assert r.status_code == 403


def test_without_a_site_id_no_permission_is_recorded(jbox: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Review item 7: an unset site id never keys a permission under ""."""
    monkeypatch.delenv("TB_SITE_ID")
    _startup(jbox)
    crc = _user(jbox, "crc1", "coordinator")
    r = _record(crc, **SHISHIN, permission_version="1.0", permitted_on="2026-10-10")
    assert r.status_code == 400 and "TB_SITE_ID" in r.text
    assert jbox["app"].state.helpers.team.permission("GZQO", "") is None


def test_outside_japan_the_routes_answer_as_absent_ones(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Review item 7: with the profile off the committee routes answer exactly as a route the console does not have,
    signed in or not, page or API; the one exception is D-444's: an anonymous API POST is asked for its session (401)
    first, as on every state-changing API route."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("TB_TZ", "Asia/Taipei")
    _user(box, "crc1", "coordinator")
    html = {"accept": "text/html"}
    bearer = _api(box, "crc1")
    for client in (TestClient(box["app"]), login(box["app"], "crc1", PW)[0], bearer):
        for method in ("GET", "POST"):
            for kind in ("/studies/GZQO/", "/api/v1/studies/GZQO/"):
                for headers in (html, {}):
                    ours = client.request(method, kind + "committee", headers=headers)
                    if method == "POST" and kind.startswith("/api/") and client is not bearer:
                        assert ours.status_code == 401  # D-444: every state-changing API route asks its token first
                        continue
                    none = client.request(method, kind + "no-such-route", headers=headers)
                    same = none.text.replace("no-such-route", "committee")  # a page names the path it was asked
                    assert (ours.status_code, ours.text) == (none.status_code, same), (method, kind, headers)


class _Orch:
    def __init__(self) -> None:
        self.scenarios = {"MICROBATCH": None}
        self.created: list[Any] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.audit = cast(Any, type("A", (), {"append": lambda _s, ev, **kw: self.events.append((ev, kw))})())

    def create(self, req: Any) -> None:
        self.created.append(req)
