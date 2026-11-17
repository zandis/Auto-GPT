"""D-399 (T-302a, FIT-009, LIFE-018, LIFE-019, UX-012): the consent record on the console, on the orchestrator's real
data-core and lifecycle API.

The path: an enrolment saved without a consent form holds the participant with an alert, and the step bar's one
consent action opens the consent form → the approved ICF versions are listed on the IRB page with their history → a
consent on a version not on the list is saved with a warning and logged → an enrolment and a visit dated before the
consent are flagged with a deviation entry → a new version that asks for re-consent lists the participants to
re-consent (page and ``/api/v1``) → a re-consent on the new version takes one off the list; one on the old version is
warned as superseded → the registry no longer records consent."""

from __future__ import annotations

import re
from typing import Any

from console import i18n_consent

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import _csrf
from tests.console.test_team_pages import _events


def _icf(c: Any, csrf: str, **form: str) -> Any:
    return c.post("/studies/GZQO/irb/icf", data={"csrf": csrf, "reconsent": "1", **form})


def test_consent_record_version_check_order_flags_and_reconsent_list(lb: dict[str, Any]) -> None:  # noqa: F811
    no, other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    for rec in (no, other):
        c.post(f"/studies/GZQO/subjects/{rec}/step", data={"csrf": csrf, "to": "approached", "on_day": "2026-10-01"})
    # acceptance 1: an enrolment without a consent record is held, with an alert; the one consent action opens the form
    r = _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-05", "en_eligible": "1"}, back="subject")
    # D-1221: the participant's one state, as every list names it (the record's "approached" is "Contacted")
    assert 'data-state="contacted"' in r.text and 'data-testid="consent-missing"' in r.text
    go = re.search(r'<a class="button" href="([^"]+)" data-testid="go-consented">', r.text)
    assert go and "form=tb_consent" in go.group(1) and 'value="consented"' not in r.text
    # the approved ICF versions, as history rows
    irb = c.get("/studies/GZQO/irb").text
    assert 'data-testid="icf-empty"' in irb
    r = _icf(c, csrf, version="v1", version_date="2025-12-20", irb_approved_on="2026-01-01")
    assert 'data-testid="icf-saved"' in r.text and 'data-testid="icf-v1"' in r.text
    assert _events(lb, "console.icf")[-1]["detail"]["version"] == "v1"
    r = _icf(c, csrf, version="v1", version_date="2025-12-21", irb_approved_on="2026-01-01")  # a change: a new row
    assert r.status_code == 200 and "2025-12-21" in r.text
    assert _icf(c, csrf, version="v0", irb_approved_on="2026-01-01", effective_from="2025-12-01").status_code == 400
    # a consent on a version not on the list: saved, with the warning on the page, and logged
    r = _save(c, csrf, no, "tb_consent", {"ic_date": "2026-10-06", "ic_version": "v9", "ic_copy": "1"})
    assert r.status_code == 200 and 'data-testid="icf-w-icf_not_listed"' in r.text
    ov = _events(lb, "console.consent_version_override")
    assert [(e["detail"]["version"], e["detail"]["warnings"]) for e in ov] == [("v9", "icf_not_listed")]
    assert lb["dc"].record("GZQO", no)["ic_version"] == "v9"  # a warning, never a refusal
    # acceptance 2: the enrolment (10-05) is before the consent (10-06): flagged, with a deviation entry
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert 'data-state="enrolled"' in page and 'data-testid="consent-flag-enrolment_before_consent"' in page
    assert "form=tb_deviation&amp;event=dv1" in page
    r = _save(
        c,
        csrf,
        no,
        "tb_consent",
        {"ic_date": "2026-10-04", "ic_version": "V1", "ic_copy": "1"},
        reason="the signed form says V1, dated the 4th",
    )  # D-778: a saved value changes with a reason
    assert "/history?" in str(r.url)  # in order and on the list: no warning
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert "consent-flag-" not in page and 'data-testid="consent-reconsent-do"' in page
    # a visit done before the consent is flagged too
    _save(c, csrf, other, "tb_consent", {"ic_date": "2026-10-10", "ic_version": "v1", "ic_copy": "1"})
    _save(c, csrf, other, "tb_enrolment", {"en_date": "2026-10-10", "en_eligible": "1"})
    _save(c, csrf, other, "tb_visit", {"vs_status": "1", "vs_date": "2026-10-09"}, "v1")
    page = c.get(f"/studies/GZQO/subjects/{other}").text
    assert 'data-testid="consent-flag-visit_before_consent"' in page and "Visit v1 done on 2026-10-09" in page
    # acceptance 3: a new version that asks for re-consent lists the participants to re-consent
    assert 'data-testid="reconsent-empty"' in c.get("/studies/GZQO/reconsent").text  # all on v1
    _icf(c, csrf, version="v2", irb_approved_on="2026-11-01")
    page = c.get("/studies/GZQO/reconsent").text
    assert 'data-testid="reconsent-target">Version v2' in page
    assert f'data-testid="rc-{no}"' in page and f'data-testid="rc-{other}"' in page
    assert f"record={no}&amp;form=tb_consent&amp;event=rc1" in page
    tok = c.post("/api/v1/session", json={"username": "crc", "password": PW}).json()["token"]
    auth = {"Authorization": f"Bearer {tok}"}
    api = c.get("/api/v1/studies/GZQO/reconsent", headers=auth).json()
    assert api["version"] == "v2" and [s["record"] for s in api["subjects"]] == sorted([no, other])
    # a re-consent on v2 takes the participant off; one on v1 after v2 is in use is warned as superseded
    r = _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-07", "ic_version": "v2", "ic_copy": "1"}, "rc1",
              "subject")  # fmt: skip
    assert str(r.url).endswith("done=entry") and 'data-testid="consent-rc1"' in r.text
    r = _save(c, csrf, other, "tb_consent", {"ic_date": "2026-11-07", "ic_version": "v1", "ic_copy": "1"}, "rc1")
    assert 'data-testid="icf-w-icf_superseded"' in r.text and 'data-testid="rc-event"' in r.text
    page = c.get("/studies/GZQO/reconsent").text
    assert f'data-testid="rc-{no}"' not in page and f'data-testid="rc-{other}"' in page
    hist = c.get("/api/v1/studies/GZQO/icf", headers=auth).json()
    assert [v["version"] for v in hist["versions"]] == ["v1", "v2"] and len(hist["history"]) == 3


def test_registry_no_longer_records_consent(lb: dict[str, Any]) -> None:  # noqa: F811
    """D-399 (UX-012): consent is recorded one way, the consent form. Since D-1221 the registry chooses no status at
    all: its page has no status field, and a "consented" sent to its add is refused (400)."""
    c, _ = login(lb["app"], "crc", PW)
    page = c.get("/pilot/registry/GZQO").text
    assert 'id="status"' not in page and 'name="status"' not in page and 'value="consented"' not in page
    pid = "ab" * 16
    r = c.post("/pilot/registry/GZQO", data={"csrf": _csrf(page), "pid": pid, "status": "consented"})
    assert r.status_code == 400 and ("GZQO", pid) not in lb["backend"].registry  # refused, nothing written


def test_consent_strings_in_every_language() -> None:
    assert set(i18n_consent.EN) == set(i18n_consent.JA) == set(i18n_consent.ZH)
    for cat in (i18n_consent.JA, i18n_consent.ZH):
        for k, v in cat.items():
            for name in re.findall(r"\{(\w+)\}", i18n_consent.EN[k]):
                assert "{" + name + "}" in v, (k, name)
            assert v != i18n_consent.EN[k] or v.isascii() is False, k
