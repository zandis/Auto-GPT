"""RC13-B (D-848): the data dictionary TrialBox hands out has REDCap's 18 columns, in REDCap's order.

On the private REDCap 13.7 instance (D-521; synthetic projects) the dictionary import read its columns by position:
a row with fewer columns, or the columns in another order, was refused (the field type was read from the wrong
column). ``forms.metadata`` gave 12 of the 18 columns and ``dictionary_csv`` wrote them in another order; the field
annotation, where ``@TB-DECIMALS`` lives, and the identifier flag were lost."""

from __future__ import annotations

import csv
import io

from datacore import forms

ORDER = ["field_name", "form_name", "section_header", "field_type", "field_label", "select_choices_or_calculations",
         "field_note", "text_validation_type_or_show_slider_number", "text_validation_min", "text_validation_max",
         "identifier", "branching_logic", "required_field", "custom_alignment", "question_number", "matrix_group_name",
         "matrix_ranking", "field_annotation"]  # fmt: skip
HEADERS = ["Variable / Field Name", "Form Name", "Section Header", "Field Type", "Field Label",
           "Choices, Calculations, OR Slider Labels", "Field Note", "Text Validation Type OR Show Slider Number",
           "Text Validation Min", "Text Validation Max", "Identifier?", "Branching Logic (Show field only if...)",
           "Required Field?", "Custom Alignment", "Question Number (surveys only)", "Matrix Group Name",
           "Matrix Ranking?", "Field Annotation"]  # fmt: skip


def _fields() -> list[forms.Field]:
    return [
        forms.Field("record_id", "screening", "text", "Record ID"),
        forms.Field("initials", "screening", "text", "Initials", identifier=True),
        forms.Field("weight", "screening", "decimal", "Weight", validation="number", places="1"),
        forms.Field("sex", "screening", "choice", "Sex", {"1": "Male", "2": "Female"}, required=True),
    ]


def test_every_row_has_the_18_columns_in_redcaps_order() -> None:
    for row in forms.metadata(_fields()):
        assert list(row) == ORDER


def test_the_csv_writes_redcaps_18_headers_in_order() -> None:
    head = next(csv.reader(io.StringIO(forms.dictionary_csv(_fields()))))
    assert head == HEADERS


def test_the_annotation_keeps_the_decimal_places_and_the_identifier_flag_stays() -> None:
    rows = {r["field_name"]: r for r in forms.metadata(_fields())}
    assert rows["weight"]["field_annotation"] == "@TB-DECIMALS=1"
    assert rows["initials"]["identifier"] == "y"
    back = {f.name: f for f in forms.read_dictionary(forms.dictionary_csv(_fields()))}
    assert back["weight"].places == "1"
    assert back["initials"].identifier is True
