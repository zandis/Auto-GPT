"""A refusal for a file's character set tells the person what to do, in three languages. D-599 and D-680 made the
refusal more frequent (never wrong text), and a refused file may be valid UTF-8 that is too short to tell: the
remedy that always works is UTF-8 with a byte order mark, which a spreadsheet writes as "CSV UTF-8"."""

from __future__ import annotations

import pytest
from console import i18n_copyassist, i18n_data

CATALOGUES = {
    "dc.err.FORM-ENCODING": i18n_data,  # the data dictionary upload
    "dc.err.DATA-SHEET": i18n_data,  # a sheet source of the data core
    "edc.err.odm.encoding": i18n_copyassist,  # the ODM import
}


@pytest.mark.parametrize("key", sorted(CATALOGUES))
@pytest.mark.parametrize("lang", ["EN", "JA", "ZH"])
def test_the_sentence_is_there_and_names_the_remedy(key: str, lang: str) -> None:
    text = getattr(CATALOGUES[key], lang)[key]
    assert "UTF-8" in text and len(text) > 20
    if key != "edc.err.odm.encoding":  # a sheet: the mark, as a spreadsheet names it
        assert "CSV UTF-8" in text


def test_the_dictionary_sentence_no_longer_says_the_file_is_not_utf8() -> None:
    """A refused file can be valid UTF-8 that is too short to tell from Shift_JIS or Big5 (D-599)."""
    assert "is not UTF-8" not in i18n_data.EN["dc.err.FORM-ENCODING"]
