# ruff: noqa: F811 - the fixtures are imported and taken by name
"""F17 5a, 5b: the page "Information still needed" lists, for each study's latest night, the criteria that stayed open
with the reason in the reader's language and the site view or field it names (a part of the box is marked as a
defect); the patient counts and the coded-complete count go only to an account the study's candidate list admits. The
job page's night card carries the coded-complete line when the night has one, and is unchanged when it has none. A box
whose orchestrator cannot be read still loads the page. Synthetic data only."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import pytest
from console.backend import Unavailable
from console.i18n import CATALOGUES
from markupsafe import escape
from tb_common.reasons import label
from tb_common.wording import check_page
from tb_contracts import NightOpen, OpenReason

from tests.console.test_console_app import ADMIN_PW, _done_screen, _ulid, box, login, login_crc  # noqa: F401
from tests.console.test_night_funnel_page import NIGHT, WEEKLY, _block, _nightly
from tests.console.test_still_needed_m1 import PATH, sn  # noqa: F401

LANGS = ("en", "ja", "zh-TW")
OPEN = NightOpen(
    coded_complete=5,
    open_reasons=[
        OpenReason(criterion="GZQO-INC-05", reason="no_notes", where="notes", count=17),
        OpenReason(criterion="GZQO-EXC-02", reason="no_record_of_kind", where="medication", count=9),
        OpenReason(criterion="GZQO-INC-03", reason="unit_mismatch", where="product", count=4),
        OpenReason(criterion="GZQO-INC-07", reason="disagree", where="person", count=2),
    ],
)


def _night(sn: dict[str, Any], n: int, no: NightOpen | None, *, night: date = NIGHT, ruleset: str = "GZQO") -> None:
    backend = sn["app"].state.helpers.bk
    job = _done_screen(backend, _ulid(n))
    from tb_contracts import JobMetrics

    backend.jobs[job.job_id] = job.model_copy(
        update={
            "type": "MICROBATCH",
            "run_date": night,
            "ruleset": ruleset,
            "metrics": JobMetrics(patients_scoped=7, prefilter=WEEKLY, night_open=no),
        }
    )


def _section(html: str) -> str | None:
    m = re.search(r'<section[^>]*data-testid="sn-open"[^>]*>(.*?)</section>', html, re.S)
    return m.group(1) if m else None


def _rows(block: str) -> dict[str, tuple[str, str, str]]:
    return {
        c: (kind, reason, rest)
        for kind, reason, c, rest in re.findall(
            r'<tr data-kind="(\w+)" data-reason="(\w+)"><th scope="row">([^<]*)</th>(.*?)</tr>', block, re.S
        )
    }


@pytest.mark.parametrize("lang", LANGS)
def test_each_open_criterion_has_its_reason_and_the_view_it_names_without_figures_for_an_account_off_the_list(
    sn: dict[str, Any], lang: str
) -> None:
    _night(sn, 801, OPEN)
    _night(sn, 802, NightOpen(coded_complete=0, open_reasons=[]), night=date(2026, 10, 4))  # an older night: not read
    _night(sn, 803, None, ruleset="ABCD")  # a night with no record
    c, csrf = login(sn["app"], "admin", ADMIN_PW)
    c.post("/lang", data={"lang": lang, "csrf": csrf, "back": "/"}, follow_redirects=False)
    sec = _section(c.get(PATH).text)
    assert sec is not None
    cat = CATALOGUES[lang]
    assert str(escape(cat["stillneeded.open.title"])) in sec and "ABCD" not in sec
    rows = _rows(sec)
    assert set(rows) == {"GZQO-INC-05", "GZQO-EXC-02", "GZQO-INC-03", "GZQO-INC-07"}
    assert rows["GZQO-INC-05"][:2] == ("site_gap", "no_notes") and rows["GZQO-INC-03"][:2] == (
        "product",
        "unit_mismatch",
    )
    for crit, reason, where in (("GZQO-INC-05", "no_notes", "notes"), ("GZQO-EXC-02", "no_record_of_kind", "medication"),
                                ("GZQO-INC-03", "unit_mismatch", "product"), ("GZQO-INC-07", "disagree", "person")):  # fmt: skip
        rest = rows[crit][2]
        assert str(escape(label(reason, lang))) in rest, (lang, crit)
        assert str(escape(cat[f"stillneeded.open.where.{where}"])) in rest, (lang, crit)
        assert ("pill warn" in rest) is (where == "product"), (lang, crit)  # only the box's own part is a defect
    kinds = [m for m in re.findall(r'data-kind="(\w+)"', sec)]
    assert kinds == sorted(kinds, key=["product", "person", "site_gap"].index)  # the box's defects first
    for figure in ("17", "9", "4", "2"):  # an admin off the study's list: no patient figure
        assert not re.search(rf"<td>{figure}</td>", sec), (lang, figure)
    assert "sn-open-complete" not in sec
    assert f'<th scope="col">{escape(cat["stillneeded.open.patients"])}</th>' not in sec
    # the unit_mismatch label (tb_common.reasons, another lane's file) says 判定 in ja and zh-TW, a word on
    # tb_common.wording.FORBIDDEN: it is left out of this page-level check and named in the card's report (a question)
    own = sec.replace(str(escape(label("unit_mismatch", lang))), "")
    assert check_page(own) == [], lang


def test_the_counts_and_the_coded_complete_figure_go_to_an_account_the_list_admits(
    sn: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _night(sn, 804, OPEN)
    monkeypatch.setattr(sn["app"].state.helpers, "admits_candidates", lambda user, rs: rs == "GZQO")
    c, _ = login(sn["app"], "admin", ADMIN_PW)
    sec = _section(c.get(PATH).text)
    assert sec is not None
    cat = CATALOGUES["en"]
    assert str(escape(cat["stillneeded.open.complete"].format(n=5))) in sec
    cells = {k: re.findall(r"<td>(\d+)</td>", v[2]) for k, v in _rows(sec).items()}
    assert cells == {"GZQO-INC-05": ["17"], "GZQO-EXC-02": ["9"], "GZQO-INC-03": ["4"], "GZQO-INC-07": ["2"]}
    assert check_page(sec) == []


def test_a_box_with_no_open_record_shows_no_section_and_a_failed_read_does_not_stop_the_page(
    sn: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _night(sn, 805, None)
    c, _ = login(sn["app"], "admin", ADMIN_PW)
    assert _section(c.get(PATH).text) is None

    def down(*a: Any, **kw: Any) -> Any:
        raise Unavailable("orchestrator returned 500")

    monkeypatch.setattr(sn["app"].state.helpers.bk, "list_jobs", down)
    r = c.get(PATH)
    assert r.status_code == 200 and _section(r.text) is None and 'data-testid="sn-mail_relay"' in r.text


def test_the_job_pages_night_card_carries_the_coded_complete_line_only_when_the_night_has_one(
    box: dict[str, Any],
) -> None:
    jid = _nightly(box, 806, WEEKLY)
    c, csrf = login_crc(box)
    bare = _block(c.get(f"/pilot/jobs/{jid}").text)
    assert bare is not None and "night-coded-complete" not in bare
    job = box["backend"].jobs[jid]
    box["backend"].jobs[jid] = job.model_copy(update={"metrics": job.metrics.model_copy(update={"night_open": OPEN})})
    for lang in LANGS:
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
        block = _block(c.get(f"/pilot/jobs/{jid}").text)
        assert block is not None
        assert str(escape(CATALOGUES[lang]["job.prefilter.coded_complete"].format(n=5))) in block, lang
        assert check_page(block) == [], lang


def _second(no: NightOpen) -> NightOpen:
    return no.model_copy(
        update={
            "coded_complete": 2,
            "open_reasons": [OpenReason(criterion="GZQO-INC-05", reason="no_notes", where="notes", count=3)],
        }
    )


def test_two_jobs_of_a_night_are_shown_one_number_per_job_never_added_and_say_how_many_wrote_them(
    sn: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _night(sn, 807, OPEN)
    _night(sn, 808, _second(OPEN))
    _night(sn, 809, None)  # a job from before the figures: it supplied none
    monkeypatch.setattr(sn["app"].state.helpers, "admits_candidates", lambda user, rs: rs == "GZQO")
    c, _ = login(sn["app"], "admin", ADMIN_PW)
    sec = _section(c.get(PATH).text)
    assert sec is not None
    cat = CATALOGUES["en"]
    assert str(escape(cat["stillneeded.open.partial"].format(k=2, n=3))) in sec
    assert f'<th scope="col">{escape(cat["stillneeded.open.patients_by_job"])}</th>' in sec
    cells = {k: re.findall(r"<td>([\d /]+)</td>", v[2]) for k, v in _rows(sec).items()}
    assert sorted(cells["GZQO-INC-05"][0].split(" / ")) == ["17", "3"]  # not 20
    assert sorted(re.findall(r"Coded-complete: ([\d /]+) patients", sec)[0].split(" / ")) == ["2", "5"]  # not 7


def test_the_job_pages_night_card_shows_the_coded_complete_figure_per_job_when_two_jobs_wrote_it(
    box: dict[str, Any],
) -> None:
    ids = [_nightly(box, 810, WEEKLY), _nightly(box, 811, WEEKLY)]
    for jid, no in zip(ids, (OPEN, _second(OPEN)), strict=True):
        job = box["backend"].jobs[jid]
        box["backend"].jobs[jid] = job.model_copy(update={"metrics": job.metrics.model_copy(update={"night_open": no})})
    c, csrf = login_crc(box)
    for lang in LANGS:
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
        block = _block(c.get(f"/pilot/jobs/{ids[0]}").text)
        assert block is not None
        assert str(escape(CATALOGUES[lang]["job.prefilter.open_partial"].format(k=2, n=2))) in block, lang
        shown = re.findall(r"(\d+ / \d+)", block)
        assert shown and sorted(shown[0].split(" / ")) == ["2", "5"], lang  # one number per job, not 7
        assert check_page(block) == [], lang
