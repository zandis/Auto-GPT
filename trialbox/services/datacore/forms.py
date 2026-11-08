"""Study forms as FHIR R4 Questionnaires (D-123).

A REDCap data dictionary (the CSV REDCap exports from *Project setup > Data dictionary*) becomes one Questionnaire
per instrument, so an existing REDCap project moves into TrialBox without retyping. Field names become ``linkId``;
values are kept as REDCap's raw codes (``1``, ``2026-11-07``), so a record round-trips to REDCap unchanged, and are
typed only when a QuestionnaireResponse is written for FHIR.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

# REDCap's data dictionary column headers (export names and the short API names)
_COLS = {
    "Variable / Field Name": "field_name",
    "Form Name": "form_name",
    "Field Type": "field_type",
    "Field Label": "field_label",
    "Choices, Calculations, OR Slider Labels": "select_choices_or_calculations",
    "Text Validation Type OR Show Slider Number": "text_validation_type_or_show_slider_number",
    "Required Field?": "required_field",
    "Identifier?": "identifier",
    "Section Header": "section_header",
}
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
URL = "urn:trialbox:questionnaire:{study}:{form}"
FHIR_TYPES = {"date_ymd": "date", "date_dmy": "date", "date_mdy": "date", "integer": "integer", "number": "decimal",
              "datetime_ymd": "dateTime", "datetime_seconds_ymd": "dateTime"}  # fmt: skip


class FormError(ValueError):
    def __init__(self, code: str, message: str, fields: list[str] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.fields = fields or []


@dataclass
class Field:
    name: str
    form: str
    kind: str  # text, date, integer, decimal, dateTime, choice, multi, display, calc, notes
    label: str
    options: dict[str, str] = field(default_factory=dict)
    required: bool = False
    identifier: bool = False  # REDCap's "Identifier?" (PHI): never imported into TrialBox


def parse_choices(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (text or "").split("|"):
        code, _, label = part.strip().partition(",")
        if code.strip():
            out[code.strip()] = label.strip()
    return out


def field_of(row: dict[str, Any]) -> Field:
    name = str(row.get("field_name") or "").strip()
    kind = str(row.get("field_type") or "text").strip()
    valid = str(row.get("text_validation_type_or_show_slider_number") or "").strip()
    opts: dict[str, str] = {}
    if kind in ("radio", "dropdown"):
        k, opts = "choice", parse_choices(str(row.get("select_choices_or_calculations") or ""))
    elif kind == "checkbox":
        k, opts = "multi", parse_choices(str(row.get("select_choices_or_calculations") or ""))
    elif kind == "yesno":
        k, opts = "choice", {"1": "Yes", "0": "No"}
    elif kind == "truefalse":
        k, opts = "choice", {"1": "True", "0": "False"}
    elif kind == "descriptive":
        k = "display"
    elif kind == "calc":
        k = "calc"
    elif kind == "notes":
        k = "notes"
    else:
        k = FHIR_TYPES.get(valid, "text")
    return Field(name, str(row.get("form_name") or "").strip(), k, str(row.get("field_label") or "").strip(), opts,
                 str(row.get("required_field") or "").strip().lower() == "y",
                 str(row.get("identifier") or "").strip().lower() == "y")  # fmt: skip


def read_dictionary(text: str) -> list[Field]:
    """REDCap data dictionary CSV (export or API column names) -> fields, in order; checked like REDCap does."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        raise FormError("FORM-EMPTY", "the data dictionary has no rows")
    norm = [{_COLS.get(k.strip(), k.strip()): (v or "") for k, v in r.items() if k} for r in rows]
    if "field_name" not in norm[0] or "form_name" not in norm[0]:
        raise FormError("FORM-COLUMNS", "this is not a REDCap data dictionary (no field or form name column)")
    fields = [field_of(r) for r in norm]
    bad = [f.name for f in fields if not _NAME.match(f.name) or not _NAME.match(f.form)]
    if bad:
        raise FormError("FORM-NAME", "field and form names are lower-case letters, digits and _", bad)
    seen: set[str] = set()
    dup = [f.name for f in fields if f.name in seen or seen.add(f.name)]  # type: ignore[func-returns-value]
    if dup:
        raise FormError("FORM-DUP", "a field name appears twice", dup)
    empty = [f.name for f in fields if f.kind in ("choice", "multi") and not f.options]
    if empty:
        raise FormError("FORM-CHOICES", "these choice fields have no choices", empty)
    return fields


def _item(f: Field) -> dict[str, Any]:
    kind = {"choice": "choice", "multi": "choice", "display": "display", "notes": "text", "calc": "string",
            "text": "string"}.get(f.kind, f.kind)  # fmt: skip
    item: dict[str, Any] = {"linkId": f.name, "text": f.label or f.name, "type": kind}
    if f.required and kind != "display":
        item["required"] = True
    if f.kind == "multi":
        item["repeats"] = True
    if f.kind == "calc":
        item["readOnly"] = True
    if f.options:
        item["answerOption"] = [{"valueCoding": {"code": c, "display": d}} for c, d in f.options.items()]
    return item


def questionnaires(study: str, fields: list[Field], record_field: str | None = None) -> list[dict[str, Any]]:
    """One Questionnaire per form, in first-seen order; identifier fields are dropped (never held by TrialBox)."""
    forms: dict[str, list[Field]] = {}
    for f in fields:
        if f.identifier:
            continue
        forms.setdefault(f.form, []).append(f)
    out = []
    for form, fs in forms.items():
        out.append({
            "resourceType": "Questionnaire",
            "id": f"{study.lower()}-{form}".replace("_", "-")[:64],
            "url": URL.format(study=study, form=form),
            "name": form,
            "title": form.replace("_", " "),
            "status": "active",
            "subjectType": ["Patient"],
            "item": [_item(f) for f in fs if f.name != record_field],
        })  # fmt: skip
    return out


def fields_of(questionnaire: dict[str, Any]) -> list[Field]:
    """Questionnaire -> fields (the inverse of ``questionnaires`` for what TrialBox keeps)."""
    form = str(questionnaire.get("name") or "")
    out = []
    for it in questionnaire.get("item", []):
        opts = {str(o["valueCoding"]["code"]): str(o["valueCoding"].get("display", ""))
                for o in it.get("answerOption", []) if "valueCoding" in o}  # fmt: skip
        t = it.get("type")
        kind = "multi" if t == "choice" and it.get("repeats") else {"string": "calc" if it.get("readOnly") else "text",
                                                                   "text": "notes"}.get(t, t)  # fmt: skip
        out.append(Field(it["linkId"], form, kind, str(it.get("text") or ""), opts, bool(it.get("required"))))
    return out


def check_value(f: Field, value: str) -> str | None:
    """None if ``value`` (a raw code) fits the field, else the reason."""
    if value == "":
        return None
    if f.kind == "choice" and value not in f.options:
        return f"{value!r} is not a choice of {f.name}"
    if f.kind == "multi" and any(v not in f.options for v in value.split(",")):
        return f"{value!r} is not a choice of {f.name}"
    if f.kind == "date" and not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return f"{f.name} is a date (YYYY-MM-DD)"
    if f.kind == "integer" and not re.match(r"^-?\d+$", value):
        return f"{f.name} is a whole number"
    if f.kind == "decimal" and not re.match(r"^-?\d+(\.\d+)?$", value):
        return f"{f.name} is a number"
    if f.kind in ("display", "calc"):
        return f"{f.name} is not entered"
    return None


def dictionary_csv(fields: list[Field]) -> str:
    """Fields -> a REDCap data dictionary CSV (export column names), for building the project in REDCap."""
    buf = io.StringIO()
    names = list(_COLS)
    w = csv.writer(buf)
    w.writerow(names)
    back = {"choice": "radio", "multi": "checkbox", "display": "descriptive", "calc": "calc", "notes": "notes"}
    valid = {"date": "date_ymd", "integer": "integer", "decimal": "number", "dateTime": "datetime_ymd"}
    for f in fields:
        kind = back.get(f.kind, "text")
        choices = " | ".join(f"{c}, {d}" for c, d in f.options.items())
        w.writerow([f.name, f.form, kind, f.label, choices, valid.get(f.kind, ""), "y" if f.required else "", "", ""])
    return buf.getvalue()
