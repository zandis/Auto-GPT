"""NEW-JRN-7 (D-770, the deep review's JRN-007): a consent date in the future is refused, and flagged when it comes
another way.

The built-in consent form saved "Consent: given 2027-03-01" without a word, and the screening log and the enrolment
report carried it: consent before any study procedure is the first thing an inspector checks.

* A consent date (``ic_date``, ``ic_reconsent_date``) later than the site's day is refused when a person enters or
  changes it (the entry page, ``PUT /studies/{rs}/data``), by the field's name, so a study that added the built-in
  forms before this rule is held by it too; a value already stored is never rechecked.
* One that arrives by a REDCap read-back (written as REDCap holds it) is flagged on the subject page.
* A visit done before consent is a possible deviation, as an enrolment before consent was.

On the orchestrator's real data core and lifecycle routes (the lifecycle box, day 2026-11-08 in Taipei). Synthetic
data only."""

from __future__ import annotations

from typing import Any

from datacore.sync import consent_after_today

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401 - the fixture is used by name


def _forms(lb: dict[str, Any]) -> tuple[Any, str, str]:  # noqa: F811
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})  # added before the rule: the stored copy has no max
    c.get("/studies/GZQO/subjects")
    return c, csrf, no


def test_the_rule_is_the_sites_day() -> None:
    at = "2026-11-14T23:30:00+00:00"  # 07:30 on the 15th in Taipei (TB_TZ of the test box)
    assert consent_after_today("ic_date", "2026-11-15", at) is None
    got = consent_after_today("ic_date", "2026-11-16", at)
    assert got == {"field": "ic_date", "code": "max", "max": "2026-11-15"}
    assert consent_after_today("ic_reconsent_date", "2027-03-01", at) is not None
    assert consent_after_today("vs_date", "2027-03-01", at) is None  # only the consent dates


def test_a_future_consent_date_is_refused_at_entry_and_today_is_saved(lb: dict[str, Any]) -> None:  # noqa: F811
    c, csrf, no = _forms(lb)
    r = _save(c, csrf, no, "tb_consent", {"ic_date": "2027-03-01", "ic_version": "v1", "ic_copy": "1"})
    assert r.status_code in (200, 409) and "2026-11-08" in r.text  # refused, naming the site's day
    assert not lb["dc"].record("GZQO", no, "").get("ic_date")
    r = _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-08", "ic_version": "v1", "ic_copy": "1"})
    assert lb["dc"].record("GZQO", no, "").get("ic_date") == "2026-11-08"
    r = lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "", "values": {"ic_date": "2027-03-01"}, "by": "crc"})
    assert r.status_code >= 400 and lb["dc"].record("GZQO", no, "").get("ic_date") == "2026-11-08"


def test_a_future_consent_from_redcap_is_flagged_and_does_not_block_other_saves(lb: dict[str, Any]) -> None:  # noqa: F811
    c, csrf, no = _forms(lb)
    for f, v in (("ic_date", "2027-03-01"), ("ic_version", "v1"), ("ic_copy", "1")):  # as the read-back writes it
        lb["dc"].write("GZQO", no, "", f, v, "rc:read", "2026-11-08T01:00:00+00:00", "redcap")
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert 'data-testid="consent-flag-consent_in_future"' in page and "2027-03-01" in page
    r = _save(
        c,
        csrf,
        no,
        "tb_consent",
        {"ic_date": "2027-03-01", "ic_version": "v1", "ic_copy": "0"},
        reason="no copy was given",
    )  # D-778: a saved value changes with a reason
    assert lb["dc"].record("GZQO", no, "").get("ic_copy") == "0"  # the stored date is not rechecked
    assert r.status_code in (200, 303)


def test_a_visit_before_consent_is_a_possible_deviation(lb: dict[str, Any]) -> None:  # noqa: F811
    c, csrf, no = _forms(lb)
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-05", "ic_version": "v1", "ic_copy": "1"})
    lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "v1", "values": {"vs_date": "2026-11-03", "vs_status": "1"},
                                                   "by": "crc"})  # fmt: skip
    page = c.get("/studies/GZQO/deviations").text
    assert f'data-testid="dev-{no}-consent_after_visit"' in page and "Visit v1 done on 2026-11-03" in page
