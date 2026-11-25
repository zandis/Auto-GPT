# ruff: noqa: F811 - the fixtures are imported from other test modules and taken by name
"""Card 10C-3c (D-1258), the review's High 5: ``/week`` and its single-study redirect.

Synthetic data only. ``/week`` lists the investigator's studies with a screening run and, above them, the serious
AEs and overdue SAE reports of the studies whose SAE pages admit the account. With one such study and no criteria
waiting, it redirects to that study's week page. D-1258 narrowed the list to the studies whose logs admit the account,
so an investigator with one admitting screened study and a serious AE in an unscreened one was redirected away from
that alert. Now the redirect is taken only when the alert block holds nothing but the target study's own SAEs and
reports, which its week page shows (``life_sae``, ``life_reports``); another study's register that could not be read
holds the page too.

The studies: A is TRA (screened), B is GZQO (where the fixtures enter a serious AE, not screened), C is TRC (screened,
its log names others). For the target-study case, A is GZQO."""

from __future__ import annotations

from typing import Any

from console.backend import RulesetInfo
from fastapi.testclient import TestClient

from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi, sub_investigator  # noqa: F401
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401

B = "GZQO"


def _screen(lb: dict[str, Any], rs: str, n: int) -> None:
    """A finished screening run filed under ``rs`` (the fixture's run, re-filed)."""
    jid = _ulid(12580 + n)
    job = _done_screen(lb["backend"], jid)
    lb["backend"].jobs[jid] = job.model_copy(update={"ruleset": rs})


def _sae_in_gzqo(lb: dict[str, Any]) -> str:
    """One enrolled GZQO participant with an unacknowledged serious AE (no reporting rule set: an overdue report)."""
    no: str = lb["nos"][0]
    crc, csrf = login(lb["app"], "crc", PW)
    crc.post(f"/studies/{B}/forms/builtin", data={"csrf": csrf})
    crc.get(f"/studies/{B}/subjects")
    _save(crc, csrf, no, "tb_consent", {"ic_date": "2026-11-01", "ic_version": "v1", "ic_copy": "1"})
    _save(crc, csrf, no, "tb_enrolment", {"en_date": "2026-11-01", "en_eligible": "1"})
    r = _save(crc, csrf, no, "tb_adverse_event", {"ae_term": "Pneumonia 1258", "ae_onset": "2026-11-08",
              "ae_serious": "1", "ae_serious_why": "3", "ae_severity": "3", "ae_related": "9"}, "ae1",
              "subject")  # fmt: skip
    assert 'data-testid="ae-ae1"' in r.text
    return no


def _seed(lb: dict[str, Any], *, a: str, screened: tuple[str, ...], sae: bool) -> tuple[str, dict[str, TestClient]]:
    """Trials TRA and TRC beside GZQO; ``both`` on A's and B's logs, ``onlya`` on A's log only (B's log names its PI,
    so ``onlya`` is off it); C's log names another investigator. Returns the serious AE's participant and clients."""
    real = lb["backend"].rulesets
    extra = [RulesetInfo("TRA", "1.0.0", "approved", "trial"), RulesetInfo("TRC", "1.0.0", "approved", "trial")]
    lb["backend"].rulesets = lambda: [*real(), *extra]
    name_pi(lb, "pi")  # B's log has an entry
    for i, rs in enumerate(screened):
        _screen(lb, rs, i)
    no = _sae_in_gzqo(lb) if sae else ""
    for name in ("both", "onlya", "otherc"):
        lb["users"].create(name, "investigator", PW, f"{name}@hospa.test")
    sub_investigator(lb, "both", ("screen",), rs=a)
    sub_investigator(lb, "both", ("screen",), rs=B if a != B else "TRA")  # A and one other study, unscreened
    sub_investigator(lb, "onlya", ("screen",), rs=a)
    sub_investigator(lb, "otherc", ("screen",), rs="TRC")  # C's log names someone else
    return no, {name: login(lb["app"], name, PW)[0] for name in ("both", "onlya")}


def _main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>", 1)[0] if "<main" in page else page


def test_week_never_hides_an_sae_alert_of_another_study_behind_the_redirect(lb: dict[str, Any]) -> None:
    """Invariant: /week never hides an SAE alert the account may read (case a, the reviewer's exact case)."""
    no, c = _seed(lb, a="TRA", screened=("TRA", "TRC"), sae=True)
    r = c["both"].get("/week", follow_redirects=False)
    assert r.status_code == 200, (r.status_code, r.headers.get("location"))
    body = _main(r.text)
    assert body.count('data-testid="sae-banner"') == 1 and f'data-testid="sae-{no}-ae1"' in body
    assert 'data-testid="sae-reports"' in body and "/studies/TRA/week" in body


def test_with_no_sae_anywhere_week_redirects_to_the_one_study_as_before(lb: dict[str, Any]) -> None:
    """Invariant: /week never hides an SAE alert the account may read (case b: nothing to hide, the redirect stays)."""
    _no, c = _seed(lb, a="TRA", screened=("TRA", "TRC"), sae=False)
    for name in ("both", "onlya"):
        r = c[name].get("/week", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/studies/TRA/week", name


def test_an_sae_in_the_redirect_target_alone_keeps_the_redirect_its_week_page_shows_it(lb: dict[str, Any]) -> None:
    """Invariant: /week never hides an SAE alert the account may read (case c: the SAE is in the study redirected to;
    that study's week page shows its own serious AEs and overdue reports, so the redirect is kept)."""
    no, c = _seed(lb, a=B, screened=(B, "TRC"), sae=True)
    r = c["both"].get("/week", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/studies/{B}/week"
    page = c["both"].get(r.headers["location"])
    assert page.status_code == 200
    assert 'data-testid="sae-banner"' in page.text and "Pneumonia 1258" in page.text and no in page.text


def test_an_sae_the_account_may_not_read_neither_shows_nor_holds_the_redirect(lb: dict[str, Any]) -> None:
    """Invariant: /week never hides an SAE alert the account may read (case d: off B's log, B's SAE is not one it may
    read, so it is not shown and the redirect to A happens as before: nothing is widened)."""
    no, c = _seed(lb, a="TRA", screened=("TRA", "TRC"), sae=True)
    assert c["onlya"].get(f"/studies/{B}/sae/{no}/ae1", follow_redirects=False).status_code == 403
    r = c["onlya"].get("/week", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/studies/TRA/week"
    assert no not in r.text and "Pneumonia 1258" not in r.text


def test_another_studys_sae_register_that_cannot_be_read_holds_the_week_page(lb: dict[str, Any]) -> None:
    """Invariant: /week never hides an SAE alert the account may read (another study's register that could not be
    read is shown on /week as ``sae_failed`` and is on no other page, so it keeps the account there; the redirect
    target's own, which its week page does not show either, is answered as before)."""
    _no, c = _seed(lb, a="TRA", screened=("TRA", "TRC"), sae=False)
    h = lb["app"].state.helpers
    real = h.life_home
    for failed_rs, want in ((B, 200), ("TRA", 303)):

        def failed(*a: Any, _rs: str = failed_rs, **kw: Any) -> dict[str, Any]:
            return {**real(*a, **kw), "sae_failed": [_rs]}

        h.life_home = failed
        r = c["both"].get("/week", follow_redirects=False)
        assert r.status_code == want, (failed_rs, r.status_code, r.headers.get("location"))
    h.life_home = real
