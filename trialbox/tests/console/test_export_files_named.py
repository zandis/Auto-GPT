"""NEW-CSV-2 (D-553): the data pages say which export is the file for REDCap and which is the file for a person.

The REDCap CSV goes into REDCap exactly as it is written (no mark, no guard on a cell: D-549 left it so), so a
reader is told to load it as it is and not to open and save it in a spreadsheet program first; the Excel workbook
is the file to open and read. Both pages that carry the export buttons say it, under the buttons, in each
language, with none of the forbidden words. Synthetic data only."""

from __future__ import annotations

import re
from typing import Any

import pytest
from console.i18n import CATALOGUES
from markupsafe import escape
from tb_common.wording import check_page

from tests.console.test_data_pages import PW, dcb  # noqa: F401 - the fixture is used by name
from tests.console.test_entry_pages import _builtin, _numbers
from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name

LANGS = ("en", "ja", "zh-TW")


def _section(page: str) -> str:
    m = re.search(r'<section class="card" data-testid="dc-exports">(.*?)</section>', page, re.S)
    assert m, "no export section"
    return m.group(1)


@pytest.mark.parametrize("lang", LANGS)
def test_the_export_buttons_say_which_file_is_for_redcap_and_which_for_a_person(dcb: dict[str, Any],
                                                                                lang: str) -> None:  # fmt: skip
    (no,) = _numbers(dcb, 1)
    c, csrf = login(dcb["app"], "crc", PW)
    _builtin(c, csrf)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    cat = CATALOGUES[lang]
    for path in ("/studies/GZQO/forms", f"/studies/GZQO/entry?record={no}&form=tb_consent"):
        sec = _section(c.get(path).text)
        said = str(escape(cat["dc.export.files"]))
        assert 'data-testid="dc-export-files"' in sec, (lang, path)
        assert said in sec, (lang, path)
        # under the buttons, all of them: the forms page has a CDISC button after the workbook's
        end = sec.index("</p>", sec.index('class="exports"'))
        assert end < sec.index(said), (lang, path)
        # the links are the same files as before
        assert 'href="/studies/GZQO/export.csv"' in sec and 'href="/studies/GZQO/export.xlsx"' in sec
        assert check_page(sec) == [], (lang, path)


def test_the_words_name_both_files_in_each_language() -> None:
    for lang in LANGS:
        text = CATALOGUES[lang]["dc.export.files"]
        assert "REDCap" in text and "Excel" in text, lang
        # the line adds to the two already there; it does not say which file a REDCap project takes (the ODM
        # help line above the buttons and the CDISC line below it say that)
        assert "是匯入 REDCap 用的檔案" not in text and "ファイルです。表計算" not in text, lang
        assert check_page(f"<p>{text}</p>") == [], lang
