"""RC13-E (D-851): the dictionary TrialBox hands out keeps a calculated field's expression and a decimal field's
places, also after the form has been stored as a Questionnaire.

The handed-out dictionary is built from the study's stored Questionnaires (``export.export_fields``). A calculated
field's expression was never kept, so it went out empty and a site could not build the field from it; a decimal
field's ``@TB-DECIMALS`` places (D-840) were lost on the way through the Questionnaire. REDCap 13.7 (D-1021) takes a
calculated field only with its expression."""

from __future__ import annotations

from datacore import forms

CSV = (
    'Variable / Field Name,Form Name,Field Type,Field Label,"Choices, Calculations, OR Slider Labels",'
    "Text Validation Type OR Show Slider Number,Field Annotation\n"
    "record_id,screening,text,Record ID,,,\n"
    "weight,screening,text,Weight,,number,@TB-DECIMALS=1\n"
    "height,screening,text,Height,,number,\n"
    'bmi,screening,calc,BMI,"round([weight]/(([height]/100)*([height]/100)),1)",,\n'
)


def test_a_calculated_field_keeps_its_expression_in_the_dictionary_rows() -> None:
    rows = {r["field_name"]: r for r in forms.metadata(forms.read_dictionary(CSV))}
    assert rows["bmi"]["field_type"] == "calc"
    assert rows["bmi"]["select_choices_or_calculations"] == "round([weight]/(([height]/100)*([height]/100)),1)"


def test_the_expression_and_the_places_survive_the_questionnaire() -> None:
    qs = forms.questionnaires("GZQO", forms.read_dictionary(CSV), record_field="record_id")
    back = {f.name: f for f in forms.fields_of(qs[0])}
    assert back["bmi"].kind == "calc"
    assert back["bmi"].calculation == "round([weight]/(([height]/100)*([height]/100)),1)"
    assert back["weight"].places == "1"
    rows = {r["field_name"]: r for r in forms.metadata(list(back.values()))}
    assert rows["bmi"]["select_choices_or_calculations"].startswith("round(")
    assert rows["weight"]["field_annotation"] == "@TB-DECIMALS=1"


def test_an_sql_fields_query_is_never_kept() -> None:
    sql = CSV + "site,screening,sql,Site,select value from somewhere,,\n"
    f = next(x for x in forms.read_dictionary(sql) if x.name == "site")
    assert f.calculation == ""
