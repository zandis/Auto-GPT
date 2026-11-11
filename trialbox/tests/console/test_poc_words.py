"""T-511 (D-398): the PoC-path pages show words, in ja, zh-TW and en (TB-DR-02a UX-029 help half, UX-016, UX-010).

* Help: the examples name the tester's own study (the study of the page the help was opened from, else the study
  whose delegation log lists the account), and the candidate, referral and EDC pages get their own "This page" text.
* Referral form: the staff-directory select says "Choose a doctor", not "Choose a reason"; the department select
  says "Choose a department" when the row names none.
* EDC review: the item's name in the reader's language first and the variable name small; a coded value with its
  word ("1 · 男性"); a readable source line; after "no REDCap record", the next step.

Synthetic data only."""

from __future__ import annotations

import html
import re
from typing import Any

import pytest
from console import step4
from console.edc_pages import item_words
from console.i18n import CATALOGUES, translate
from console.i18n_help import EN, JA, ZH

from tests import edc_kit as k
from tests.console.test_console_app import _done_screen, _ulid, box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_edc_pages import NO, PW, _ready, eb  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import _csrf, _user
from tests.console.test_team_pages import A

LANGS = ("ja", "zh-TW", "en")


def _lang(c: Any, lang: str) -> None:
    c.post("/lang", data={"csrf": _csrf(c.get("/home").text), "lang": lang, "back": "/home"})


def _text(page: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _log(b: dict[str, Any], rs: str, user: str) -> None:
    b["app"].state.helpers.team.add_entry(rs, username=user, name="Dr Sato", role="pi", tasks=(), start="2026-01-01",
                                          end=None, training_day="2026-01-01", training_ref="GCP-1", by="admin",
                                          at="2026-01-01T00:00:00+00:00")  # fmt: skip


def _examples(page: str) -> list[str]:
    m = re.search(r'data-testid="help-examples">(.*?)</ul>', page, re.S)
    assert m
    return [html.unescape(x) for x in re.findall(r"<code>(.*?)</code>", m.group(1))]


# ---------------------------------------------------------------------------------------------- UX-029 (help half)
def test_own_study_prefers_the_page_then_the_delegation_log() -> None:
    studies = ["GZQO", "RA-BIO"]
    assert step4.own_study("/studies/gzqo/week", studies, ["RA-BIO"]) == "GZQO"
    assert step4.own_study("/home", studies, ["RA-BIO"]) == "RA-BIO"
    assert step4.own_study("/studies/OTHER/week", studies, []) == "GZQO"  # not in scope: never named
    assert step4.own_study("/home", [], []) == ""


@pytest.mark.parametrize("lang", LANGS)
def test_help_examples_name_the_testers_own_study(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    pi = _user(box, "drsato", "investigator")
    _log(box, "RA-BIO", "drsato")  # the PI's own study is RA-BIO, though GZQO sorts first
    _lang(pi, lang)
    home = _examples(pi.get("/help?back=/home").text)
    assert home and any("RA-BIO" in x for x in home) and not any("GZQO" in x for x in home), home
    week = _examples(pi.get("/help?back=/studies/GZQO/week").text)
    assert any("GZQO" in x for x in week) and not any("RA-BIO" in x for x in week), week


@pytest.mark.parametrize("lang", LANGS)
def test_help_this_page_on_the_poc_pages(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    crc = _user(box, "crc1", "coordinator")
    _lang(crc, lang)
    for back, slug in (("/studies/GZQO/candidates/x", "candidates"), ("/studies/GZQO/referrals", "referrals"),
                       ("/studies/GZQO/edc/review/GZQO-0001", "edc")):  # fmt: skip
        page = crc.get(f"/help?back={back}").text
        assert f'data-page="{slug}"' in page
        assert translate(lang, f"help.page.{slug}") in html.unescape(page), (lang, slug)


# ---------------------------------------------------------------------------------------------- UX-016
@pytest.mark.parametrize("lang", LANGS)
def test_the_referral_form_selects_say_what_to_choose(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(991))
    pi = _user(box, "drsato", "investigator")
    _lang(pi, lang)
    page = pi.get(f"/studies/GZQO/candidates/{A}?purpose=referral").text
    assert 'data-testid="referral-form"' in page
    staff = re.search(r'data-testid="staff-pick"><option value="">([^<]*)</option>', page)
    assert staff and html.unescape(staff.group(1)) == translate(lang, "team.ref.choose_doctor")
    assert translate(lang, "mark.reason.choose") not in _text(page[page.find('data-testid="referral-form"') :])
    dept = re.search(r'data-testid="dept-pick"><option value="">([^<]*)</option>', page)
    assert dept and dept.group(1).strip()  # the row's department, or "Choose a department": never blank


# ---------------------------------------------------------------------------------------------- UX-010
def test_item_words_reads_the_reader_language_first() -> None:
    f = {"name": "sex", "label": "Sex", "labels": {}, "options": {"1": "Male", "2": "Female"},
         "option_labels": {"ja": {"1": "男"}}}  # fmt: skip
    d = {"item": "sex", "cdash": "DM.SEX", "test": "", "value": "1",
         "citation": {"kind": "record", "table": "patient", "row": "sex", "day": "", "text": "patient sex male"}}  # fmt: skip
    ja = item_words(d, f, None, "ja")
    assert ja["label"] == "性別" and not ja["given"]  # the standard name; the dictionary has no ja label
    assert ja["options"] == {"1": "男", "2": "女性"}  # the dictionary's own ja word first, then the common word
    assert ja["source"] == "患者基本情報"
    en = item_words(d, f, None, "en")
    assert en["label"] == "Sex" and en["options"]["1"] == "Male"
    odd = item_words({"item": "x_q", "cdash": "", "test": ""}, {"label": "Odd question"}, None, "zh-TW")
    assert odd["label"] == "Odd question" and odd["given"]  # no word in zh-TW: shown as written, marked
    obs = item_words({"item": "urate", "cdash": "LB.LBORRES", "test": "URATE", "value": "8.4",
                      "citation": {"kind": "record", "table": "observation", "day": "2026-10-20", "text": "x"}},
                     {"label": "Serum uric acid (mg/dL)"}, {"unit": "mg/dL", "what": "value"}, "zh-TW")  # fmt: skip
    assert obs["label"] == "血清尿酸" and obs["source"] == "檢驗或量測 2026-10-20: 8.4 mg/dL"


@pytest.mark.parametrize(
    "lang,birth,sex,lab",
    [
        ("ja", "生年月日", "1 · 男性", "検査・測定 2026-11-01: 72.5 kg"),
        ("zh-TW", "出生日期", "1 · 男", "檢驗或量測 2026-11-01: 72.5 kg"),
        ("en", "Birth date", "1 · Male", "Test or measurement 2026-11-01: 72.5 kg"),
    ],
)
def test_edc_review_shows_words_not_codes(eb: dict[str, Any], lang: str, birth: str, sex: str, lab: str) -> None:  # noqa: F811
    _ready(eb)
    eb["svc"].build("GZQO", NO, k.PID, "", k.VISIT_DATE, "crc")
    crc, csrf = login(eb["app"], "crc", PW)
    crc.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    page = html.unescape(crc.get(f"/studies/GZQO/edc/review/{NO}").text)
    label = re.search(r'data-testid="draft-brthdat">\s*<td><strong data-testid="label-brthdat">([^<]*)</strong>', page)
    assert label and label.group(1) == birth  # the label first, the variable name after it
    assert re.search(r'data-testid="value-sex">\s*' + re.escape(sex), page), lang
    src = re.search(r'data-testid="source-weight">([^<]*)<', page)
    assert src and src.group(1) == lab
    assert translate(lang, "edc.src.detail") in page  # the record reference stays on the page
    sent = html.unescape(crc.get(f"/studies/GZQO/edc/review/{NO}?sent=0&no_record=1").text)
    assert translate(lang, "edc.sent.no_record_next") in sent and 'data-testid="edc-sent-next"' in sent
    calm = crc.get(f"/studies/GZQO/edc/review/{NO}?sent=1&no_record=0").text
    assert 'data-testid="edc-sent-next"' not in calm


def test_every_new_key_in_every_language() -> None:
    assert set(EN) == set(JA) == set(ZH)
    for lang in LANGS:
        for key in EN:
            assert CATALOGUES[lang][key] == {"en": EN, "ja": JA, "zh-TW": ZH}[lang][key], (lang, key)
    assert set(step4.HELP_SLUGS) >= {"candidates", "referrals", "edc"}
