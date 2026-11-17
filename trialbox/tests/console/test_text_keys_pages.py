# ruff: noqa: F811 - the box fixtures are imported from their test modules and taken by name
"""D-1220: the two pages where a raw text key or another page's words showed, rendered for real, in en, zh-TW and ja.

* A-M4 (journey review): a participant with no anchor date yet (approached, not enrolled) has visits in the state
  "unplanned", and the participant page showed the raw key ``life.vstate.unplanned``.
* G-5: the administrator's EDC connection page ``/admin/edc`` was titled "EDC prefill" with the prefill page's help:
  both pages defined ``edc.title`` and ``edc.help``, and the later module won.

In the suite's process a key no catalogue has raises (``console.i18n.STRICT``), so these pages could not render with a raw key;
the tests also read the words. Synthetic data only."""

from __future__ import annotations

import re
from typing import Any

import pytest
from console.i18n import CATALOGUES

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401 - the fixture is used by name

LANGS = ("en", "zh-TW", "ja")


def _in(c: Any, csrf: str, lang: str, back: str) -> None:
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": back})


@pytest.mark.parametrize("lang", LANGS)
def test_a_visit_with_no_date_yet_reads_in_words_on_the_participant_page(lb: dict[str, Any], lang: str) -> None:
    no = lb["nos"][0]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf}, follow_redirects=True)
    # opening the list makes the screening numbers participants
    assert f'data-testid="subject-{no}"' in c.get("/studies/GZQO/subjects").text
    r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "approached", "on_day": "2026-11-02"})
    assert r.status_code == 200, r.text
    sched = {"csrf": csrf, "action": "save", "visit": ["v1", "v2", ""], "label": ["", "", ""],
             "day": ["7", "28", ""], "before": ["2", "3", ""], "after": ["2", "3", ""],
             "anchor": ["enrolment", "enrolment", "enrolment"]}  # fmt: skip
    assert 'data-testid="schedule-saved"' in c.post("/studies/GZQO/schedule", data=sched).text
    assert {v["status"] for v in lb["oc"].get(f"/studies/GZQO/subjects/{no}").json()["visits"]} == {"unplanned"}
    _in(c, csrf, lang, f"/studies/GZQO/subjects/{no}")
    page = c.get(f"/studies/GZQO/subjects/{no}")
    assert page.status_code == 200
    assert f'<html lang="{lang}"' in page.text
    assert "life.vstate" not in page.text
    words = CATALOGUES[lang]["life.vstate.unplanned"]
    assert len(re.findall(r'class="pill v-unplanned">' + re.escape(words) + "<", page.text)) == 2


@pytest.mark.parametrize(("lang", "title", "not_title"), [
    ("en", "EDC connection", "EDC prefill"),
    ("zh-TW", "EDC 連線", "EDC 預填"),
    ("ja", "EDC 接続", "EDC 事前入力"),
])  # fmt: skip
def test_the_edc_connection_page_has_its_own_title_and_help(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch, lang: str, title: str, not_title: str
) -> None:
    for name in ("TB_EDC_TOOL_URL", "TB_EDC_TOOL_TOKEN", "TB_EDC_BACKEND"):
        monkeypatch.delenv(name, raising=False)
    c, csrf = login(box["app"])
    _in(c, csrf, lang, "/admin/edc")
    page = c.get("/admin/edc")
    assert page.status_code == 200
    head = re.search(r"<title>(.*?)</title>", page.text, re.S)
    assert head and head.group(1).startswith(title) and not_title not in head.group(1)
    assert f"<h1>{title}</h1>" in page.text
    assert CATALOGUES[lang]["edc.conn.help"] in page.text
    assert CATALOGUES[lang]["edc.help"] not in page.text  # the prefill page's help stays on the prefill page
