# ruff: noqa: F811 - the fixtures are imported from other test modules and taken by name
"""Card 10C-3c (D-1258), gap 2: the investigator's start page and a study off the investigator's delegation log.

Synthetic data only. An investigator holds ``list.mark``, so ``/home`` sends them to ``/week`` (``HOME_STARTS``),
the page that lists their studies' weekly lists with the serious adverse events and overdue SAE reports above
them. An investigator off study GZQO's log is refused GZQO's week list, candidates and patient pages (D-147,
D-273). Before D-1258, ``/week`` still:

* showed GZQO's serious adverse events (participant record, study, term, onset day) and its overdue SAE reports
  (``lifecycle_pages.life_home`` was called with no study filter), with links to that participant's page;
* listed GZQO as a study with a weekly list and, when it was the only one, redirected straight to its week page
  (the ``Location`` says that GZQO has had a screening run).

Now the list and the redirect ask the week page's own delegation check (``Helpers.delegated_ok``), and the serious
AEs are read only where the SAE pages show them (``sae_pages.sae_scope``, as the J-6 opening page reads them). The
PI, a sub-investigator on the log and the coordinator are served as before."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi, sub_investigator  # noqa: F401
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401

STUDY = "GZQO"


def _seed(lb: dict[str, Any], screened: bool) -> tuple[str, dict[str, TestClient]]:
    """GZQO with a PI on its log, one enrolled participant with a serious AE (no reporting rule set, so its report
    has no deadline and is listed as overdue reporting), and the accounts of the walk: the coordinator, the PI, a
    sub-investigator on GZQO's log (screen), one on study RA-BIO's log only, and an investigator on no log."""
    if screened:
        _done_screen(lb["backend"], _ulid(1258))
    name_pi(lb, "pi")
    no = lb["nos"][0]
    crc, csrf = login(lb["app"], "crc", PW)
    crc.post(f"/studies/{STUDY}/forms/builtin", data={"csrf": csrf})
    crc.get(f"/studies/{STUDY}/subjects")
    _save(crc, csrf, no, "tb_consent", {"ic_date": "2026-11-01", "ic_version": "v1", "ic_copy": "1"})
    _save(crc, csrf, no, "tb_enrolment", {"en_date": "2026-11-01", "en_eligible": "1"})
    r = _save(crc, csrf, no, "tb_adverse_event", {"ae_term": "Pneumonia 1258", "ae_onset": "2026-11-08",
              "ae_serious": "1", "ae_serious_why": "3", "ae_severity": "3", "ae_related": "9"}, "ae1",
              "subject")  # fmt: skip
    assert 'data-testid="ae-ae1"' in r.text
    for name in ("subg", "offlog", "nolog"):
        lb["users"].create(name, "investigator", PW, f"{name}@hospa.test")
    sub_investigator(lb, "subg", ("screen",), rs=STUDY)  # on GZQO's log
    sub_investigator(lb, "offlog", ("screen",), rs="RA-BIO")  # on RA-BIO's log only
    clients = {"crc": crc}
    for name in ("pi", "subg", "offlog", "nolog"):
        clients[name], _ = login(lb["app"], name, PW)
    return no, clients


def _main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>", 1)[0] if "<main" in page else page


def test_the_start_page_shows_no_serious_ae_of_a_study_off_the_investigators_log(lb: dict[str, Any]) -> None:
    no, c = _seed(lb, screened=False)
    # the control: GZQO's pages refuse the two investigators off its log today (D-147, D-273)
    for name in ("offlog", "nolog"):
        assert c[name].get(f"/studies/{STUDY}/week", follow_redirects=False).status_code == 403
        assert c[name].get(f"/studies/{STUDY}/sae/{no}/ae1", follow_redirects=False).status_code == 403
        r = c[name].get("/week", follow_redirects=False)
        assert r.status_code == 200, name
        body = _main(r.text)
        assert 'data-testid="sae-banner"' not in body and 'data-testid="sae-reports"' not in body, name
        assert no not in body and "Pneumonia 1258" not in body and f"/studies/{STUDY}/" not in body, name
    # the accounts GZQO's SAE pages admit still see its serious AE and its report on the same page
    for name in ("crc", "pi", "subg"):
        assert c[name].get(f"/studies/{STUDY}/sae/{no}/ae1", follow_redirects=False).status_code == 200, name
        body = _main(c[name].get("/week", follow_redirects=False).text)
        assert body.count('data-testid="sae-banner"') == 1 and 'data-testid="sae-reports"' in body, name
        assert f'data-testid="sae-{no}-ae1"' in body and f"/studies/{STUDY}/subjects/{no}" in body, name


def test_the_start_page_names_no_weekly_list_of_a_study_off_the_investigators_log(lb: dict[str, Any]) -> None:
    _no, c = _seed(lb, screened=True)
    for name in ("offlog", "nolog"):
        r = c[name].get("/week", follow_redirects=False)
        # answered as for an account with no study screened: the page, never a redirect to GZQO's week
        assert r.status_code == 200, (name, r.status_code, r.headers.get("location"))
        assert f"/studies/{STUDY}/week" not in _main(r.text), name
        assert 'data-testid="sae-banner"' not in r.text, name
        # the start page itself sends the investigator to /week (``HOME_STARTS``), which now stays there
        assert c[name].get("/home", follow_redirects=False).headers["location"] == "/week"
    for name in ("crc", "pi", "subg"):
        r = c[name].get("/week", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == f"/studies/{STUDY}/week", name
        assert c[name].get(r.headers["location"]).status_code == 200, name
