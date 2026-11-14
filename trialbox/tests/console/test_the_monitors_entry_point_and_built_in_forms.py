"""NEW-JRN-8 (D-772, the deep review's JRN-008): the monitor finds the page, and the sheet shows the built-in forms.

The monitor's journey had a dead start and a thin end: after sign-in the CRO account saw only "Feasibility reports"
and nothing linked to ``/studies/{rs}/monitor`` (a typed address); and for a subject whose consent, visit and adverse
event were typed into TrialBox's built-in forms the source-reference sheet said "No CRF value of this subject has been
confirmed yet". Now:

* under a monitor grant the reports page and the menu say "Monitoring: GZQO (visit MV-12, until ...)" with the link;
  an account without a grant (or with an expired one) sees no such line;
* the sheet shows, read-only, the subject's values in the built-in forms (consent, enrolment, visits, adverse events,
  deviations, withdrawal) with who entered each and when, and every change to them; never a value of a study's own
  CRF imported from elsewhere (the cited-items rule still holds for those), never another subject's, never the
  pseudonym.

Synthetic data only (``tests.edc_kit``)."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from tests import edc_kit as k
from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_sdv import NO, PIDS, PW, VISIT, _grant, sb  # noqa: F401 - the fixture is used by name

CONSENT = {"ic_date": "2026-11-02"}
AE = {"ae_term": "Headache", "ae_onset": "2026-11-03", "ae_serious": "0"}


def _builtin(sb: dict[str, Any]) -> None:  # noqa: F811
    r = sb["oc"].post("/studies/GZQO/forms/builtin", json={"by": "crc"})
    assert r.status_code == 200, r.text
    for event, values in (("", CONSENT), ("ae1", AE)):
        r = sb["oc"].put(f"/studies/GZQO/data/{NO}", json={"event": event, "values": values, "by": "crc"})
        assert r.status_code == 200, r.text
    r = sb["oc"].put(f"/studies/GZQO/data/{NO}", json={"event": "ae1", "values": {"ae_onset": "2026-11-04"},
                                                       "by": "drsato"})  # fmt: skip
    assert r.status_code == 200, r.text
    other = sb["nos"][PIDS["fail"]]
    sb["oc"].put(f"/studies/GZQO/data/{other}", json={"event": "", "values": {"ic_date": "2026-10-30"}, "by": "crc"})


# ---------------------------------------------------------------------------------------------- the entry point
def test_under_a_grant_the_reports_page_and_the_menu_link_the_monitoring_page(sb: dict[str, Any]) -> None:  # noqa: F811
    mon, _ = login(sb["app"], "mon1", PW)
    page = mon.get("/reports").text
    assert 'data-testid="monitoring"' not in page and "/studies/GZQO/monitor" not in page  # no grant, no line
    _grant(sb)
    page = mon.get("/reports").text
    line = page[page.index('data-testid="monitoring"') :][:600]
    assert "GZQO" in line and VISIT in line and "2099-12-31" in line and 'href="/studies/GZQO/monitor"' in line
    nav = page[page.index('data-testid="nav"') :][:1500]
    assert 'href="/studies/GZQO/monitor"' in nav  # the menu too


def test_an_ended_grant_shows_no_line(sb: dict[str, Any]) -> None:  # noqa: F811
    _grant(sb)
    h = sb["app"].state.helpers
    e = next(x for x in h.team.entries("GZQO") if x.role == "monitor")
    h.team.update_entry(
        "GZQO",
        e.id,
        tasks=e.tasks,
        end="2026-01-02",
        training_day=e.training_day,
        training_ref=e.training_ref,
        by="drsato",
        at="2026-11-05T00:00:00+00:00",
    )
    mon, _ = login(sb["app"], "mon1", PW)
    assert "/studies/GZQO/monitor" not in mon.get("/reports").text


# ---------------------------------------------------------------------------------------------- the built-in forms
def test_the_sheet_shows_the_built_in_form_values_with_their_trail(sb: dict[str, Any]) -> None:  # noqa: F811
    _builtin(sb)
    _grant(sb)
    mon, _ = login(sb["app"], "mon1", PW)
    page = mon.get(f"/studies/GZQO/monitor/{NO}").text
    assert 'data-testid="sdv-forms"' in page
    assert 'data-testid="sdv-form-ic_date"' in page and "2026-11-02" in page
    row = page[page.index('data-testid="sdv-form-ae1-ae_onset"') :][:600]
    assert "2026-11-04" in row and "drsato" in row  # the value as it stands and who entered it
    trail = page[page.index('data-testid="sdv-form-trail"') :]
    assert "2026-11-03" in trail and "2026-11-04" in trail  # the change, old and new
    assert "Headache" in page
    assert "2026-10-30" not in page  # another subject's value
    assert k.PID not in page


def test_the_api_twin_carries_the_built_in_forms_and_nothing_imported(sb: dict[str, Any]) -> None:  # noqa: F811
    _builtin(sb)
    _grant(sb)
    api = TestClient(sb["app"])
    tok = api.post("/api/v1/session", json={"username": "mon1", "password": PW}).json()["token"]
    api.headers["Authorization"] = f"Bearer {tok}"
    body = api.get(f"/api/v1/studies/GZQO/monitor/{NO}").json()
    got = {(v["event"], v["field"]): v for v in body["forms"]}
    assert got[("", "ic_date")]["value"] == "2026-11-02" and got[("", "ic_date")]["form"] == "tb_consent"
    assert got[("ae1", "ae_onset")]["value"] == "2026-11-04" and got[("ae1", "ae_onset")]["by"] == "drsato"
    assert {f for _e, f in got} <= {f for f in got_fields(sb)}  # built-in fields only
    assert not {"weight", "urate", "brthdat", "sex"} & {f for _e, f in got}  # the EDC's own CRF: cited items only
    changes = [x for x in body["form_trail"] if x["field"] == "ae_onset"]
    assert [(x["old"], x["new"]) for x in changes] == [(None, "2026-11-03"), ("2026-11-03", "2026-11-04")]
    assert k.PID not in json.dumps(body)


def got_fields(sb: dict[str, Any]) -> set[str]:  # noqa: F811
    from datacore.builtin import fields

    return {f.name for f in fields()}


def test_a_study_without_the_built_in_forms_shows_the_sheet_as_before(sb: dict[str, Any]) -> None:  # noqa: F811
    _grant(sb)
    mon, _ = login(sb["app"], "mon1", PW)
    page = mon.get(f"/studies/GZQO/monitor/{NO}")
    assert page.status_code == 200 and 'data-testid="sdv-forms-none"' in page.text
