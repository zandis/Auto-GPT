"""Card 10G-43 (OT-5): the REDCap data dictionary on malformed input (``datacore.forms.read_dictionary``, then
``forms.questionnaires`` as ``POST /studies/{rs}/forms/dictionary`` calls them).

``read_dictionary`` returns fields or refuses with :class:`forms.FormError` (the route turns it into a 400); the
fields it returns build questionnaires. No REDCap source is used: the dictionaries are generated from the column
names the reader itself knows (``forms._COLS``, its keys as REDCap exports them and its values as the API sends them).
"""

from __future__ import annotations

import csv
import io

import pytest
from tests.malformed_kit import Escaped, SETTINGS, returns_or_refuses

from hypothesis import example, given
from hypothesis import strategies as st

from datacore import forms

_COLUMNS = sorted(set(forms._COLS) | set(forms._COLS.values()) | {f"field_label:{g}" for g in forms.LANGS}
                  | {f"select_choices_or_calculations:{g}" for g in forms.LANGS})  # fmt: skip
_TYPES = ["text", "notes", "radio", "dropdown", "checkbox", "yesno", "truefalse", "calc", "slider", "file", "descriptive",
          "sql", "", "RADIO", "bogus"]  # fmt: skip
_CELL = st.one_of(
    st.sampled_from(_TYPES + ["a", "f", "a1", "1, Yes | 2, No", "|", ",", "y", "Y", "@TB-DECIMALS=2", "number_2dp",
                              "date_ymd", "integer", "[a] = '1'", "", " ", "﻿", "\"", "山田"]),
    st.text(max_size=12),
)  # fmt: skip


@st.composite
def dictionaries(draw: st.DrawFn) -> str:
    """A dictionary as text: a header from the reader's own column names, then rows; sometimes damaged."""
    head = draw(st.lists(st.sampled_from(_COLUMNS), min_size=1, max_size=8))
    if draw(st.booleans()):
        head = draw(st.permutations(["field_name", "form_name", "field_type", "select_choices_or_calculations",
                                     *head]))  # fmt: skip
    rows = draw(st.lists(st.lists(_CELL, max_size=len(head) + 2), max_size=6))
    buf = io.StringIO()
    w = csv.writer(buf, quoting=draw(st.sampled_from([csv.QUOTE_MINIMAL, csv.QUOTE_ALL, csv.QUOTE_NONNUMERIC])))
    w.writerow(head)
    w.writerows(rows)
    text = buf.getvalue()
    if draw(st.booleans()):
        text = draw(st.sampled_from(["", "﻿"])) + text.replace("\r\n", draw(st.sampled_from(["\n", "\r\n"])))
    return text


def _import(text: str) -> None:
    fields = forms.read_dictionary(text)
    forms.questionnaires("rs-1", fields, record_field=fields[0].name)


@SETTINGS
@given(st.one_of(dictionaries(), st.text(max_size=300).map(lambda t: t.replace("\r", "\n"))))
@example("")
@example("field_name,form_name\n")
@example("field_name,form_name,field_type\na,f,radio\n")
@example("Variable / Field Name,Form Name\nrecord_id,f\nrecord_id,f\n")
@example("field_name,form_name,field_type,select_choices_or_calculations\na,f,checkbox,\"1, A|1, B\"\n")
def test_read_dictionary_returns_fields_or_refuses(text: str) -> None:
    """Dictionaries written by the csv module's own writer, and any text without a CR: a bare CR in a cell is
    H10G43-03 (its own test below), so it is the one thing left out here."""
    returns_or_refuses(lambda: _import(text), (forms.FormError,))


@SETTINGS
@given(st.just("field_name,form_name\na\rb,f\n"))
@example("field_name,form_name\n" + "a" * 131073 + ",f\n")
@pytest.mark.xfail(strict=True, raises=Escaped, reason="H10G43-03: csv.Error leaves read_dictionary (a bare CR; a cell over the "
                                       "csv field limit), not FormError")  # fmt: skip
def test_h10g43_03_csv_errors_escape(text: str) -> None:
    returns_or_refuses(lambda: _import(text), (forms.FormError,))
