"""Study forms as FHIR R4 Questionnaires (D-123).

A REDCap data dictionary (the CSV REDCap exports from *Project setup > Data dictionary*) becomes one Questionnaire
per instrument, so an existing REDCap project moves into TrialBox without retyping. Field names become ``linkId``;
values are kept as REDCap's raw codes (``1``, ``2026-11-07``), so a record round-trips to REDCap unchanged, and are
typed only when a QuestionnaireResponse is written for FHIR.

TB-PLAN-04 step 4 (D-129) carries more of the dictionary through: ``Required Field?``, ``Text Validation Min`` and
``Max``, ``Branching Logic`` (the subset in ``datacore.branching``) and, as TrialBox's own extra columns, labels and
choice labels per language (``field_label:ja``, ``select_choices_or_calculations:zh-TW``). On the Questionnaire they
are FHIR's ``required``, the ``minValue``/``maxValue`` extensions, a TrialBox branching-logic extension (plus
``enableWhen`` when the rule fits it) and the core ``translation`` extension on ``text``, ``display`` and ``title``.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

# REDCap's data dictionary column headers (export names and the short API names)
# REDCap's 18 dictionary columns (export header -> API name), in REDCap's order: its import reads them by position
# (RC13-B, D-848: a short row or another order was refused on REDCap 13.7)
_COLS = {
    "Variable / Field Name": "field_name",
    "Form Name": "form_name",
    "Section Header": "section_header",
    "Field Type": "field_type",
    "Field Label": "field_label",
    "Choices, Calculations, OR Slider Labels": "select_choices_or_calculations",
    "Field Note": "field_note",
    "Text Validation Type OR Show Slider Number": "text_validation_type_or_show_slider_number",
    "Text Validation Min": "text_validation_min",
    "Text Validation Max": "text_validation_max",
    "Identifier?": "identifier",
    "Branching Logic (Show field only if...)": "branching_logic",
    "Required Field?": "required_field",
    "Custom Alignment": "custom_alignment",
    "Question Number (surveys only)": "question_number",
    "Matrix Group Name": "matrix_group_name",
    "Matrix Ranking?": "matrix_ranking",
    "Field Annotation": "field_annotation",
}
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
URL = "urn:trialbox:questionnaire:{study}:{form}"
FHIR_TYPES = {"date_ymd": "date", "date_dmy": "date", "date_mdy": "date", "integer": "integer", "number": "decimal",
              "datetime_ymd": "dateTime", "datetime_seconds_ymd": "dateTime", "datetime_dmy": "dateTime",
              "datetime_mdy": "dateTime", "datetime_seconds_dmy": "dateTime", "datetime_seconds_mdy": "dateTime",
              "number_comma_decimal": "decimal",
              **{f"number_{n}dp{c}": "decimal" for n in range(1, 5) for c in ("", "_comma_decimal")}}  # fmt: skip
#: REDCap validation types read as written and checked here beyond the FHIR type (STD-061, T-115): decimal places,
#: decimal comma, time, e-mail, phone. Any other type is free text, as before.
VALIDATION = "urn:trialbox:fhir:redcap-validation"
#: the types read before STD-061: their meaning is the FHIR type alone (the API sends dates as YYYY-MM-DD whatever
#: the display order), so they are not kept as a validation of their own
_PLAIN = frozenset({"date_ymd", "date_dmy", "date_mdy", "integer", "number", "datetime_ymd", "datetime_seconds_ymd"})
_DP = re.compile(r"^number_(\d)dp(_comma_decimal)?$")
LANGS = ("ja", "zh-TW")  # the translated languages; the plain label is the default (English for the built-in forms)
TRANSLATION = "http://hl7.org/fhir/StructureDefinition/translation"
MIN_VALUE = "http://hl7.org/fhir/StructureDefinition/minValue"
MAX_VALUE = "http://hl7.org/fhir/StructureDefinition/maxValue"
BRANCHING = "urn:trialbox:fhir:branching-logic"  # the REDCap rule as written


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
    labels: dict[str, str] = field(default_factory=dict)  # language -> label (ja, zh-TW)
    option_labels: dict[str, dict[str, str]] = field(default_factory=dict)  # language -> code -> label
    vmin: str = ""  # REDCap's text_validation_min / max (numbers or YYYY-MM-DD)
    vmax: str = ""
    branching: str = ""  # REDCap's branching logic, as written
    validation: str = ""  # REDCap's text validation type as written (``number_1dp``, ``time``...; STD-061)
    # CGRD-B1 (D-840): the decimal places TrialBox keeps for a ``number`` field, from ``@TB-DECIMALS=n`` in REDCap's
    # field annotation (an instance may not offer ``number_1dp``; REDCap ignores an action tag it does not know)
    places: str = ""

    def label_in(self, lang: str) -> str:
        return self.labels.get(lang) or self.label or self.name

    def options_in(self, lang: str) -> dict[str, str]:
        tr = self.option_labels.get(lang) or {}
        return {c: tr.get(c) or d for c, d in self.options.items()}


_TB_DECIMALS = re.compile(r"@TB-DECIMALS=(\d)\b")


def _places(row: dict[str, Any], kind: str) -> str:
    """CGRD-B1 (D-840): ``@TB-DECIMALS=n`` in a decimal field's annotation, else ""."""
    m = _TB_DECIMALS.search(str(row.get("field_annotation") or ""))
    return m.group(1) if m and kind == "decimal" else ""


def _decimals(f: Field) -> int | None:
    """The decimal places a decimal field keeps: its validation's (``number_1dp``), else its ``@TB-DECIMALS``."""
    dp = _DP.match(f.validation)
    if dp:
        return int(dp.group(1))
    return int(f.places) if f.places else None


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
    elif kind in ("calc", "sql"):  # computed or looked up by REDCap: never entered (STD-061)
        k = "calc"
    elif kind == "file":  # an upload or a signature drawing: never entered by TrialBox (STD-061)
        k = "file"
    elif kind == "slider":  # REDCap stores a slider as a whole number, 0 to 100 unless set otherwise
        k = "integer"
    elif kind == "notes":
        k = "notes"
    else:
        k = FHIR_TYPES.get(valid, "text")
    labels = {g: str(row.get(f"field_label:{g}") or "").strip() for g in LANGS}
    olabels = {g: parse_choices(str(row.get(f"select_choices_or_calculations:{g}") or "")) for g in LANGS}
    return Field(name, str(row.get("form_name") or "").strip(), k, str(row.get("field_label") or "").strip(), opts,
                 str(row.get("required_field") or "").strip().lower() == "y",
                 str(row.get("identifier") or "").strip().lower() == "y",
                 {g: v for g, v in labels.items() if v}, {g: v for g, v in olabels.items() if v},
                 str(row.get("text_validation_min") or "").strip(), str(row.get("text_validation_max") or "").strip(),
                 str(row.get("branching_logic") or "").strip(),
                 valid if kind in ("text", "") and valid not in _PLAIN else "",
                 _places(row, k))  # fmt: skip


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


def _translations(texts: dict[str, str]) -> dict[str, Any]:
    return {"extension": [{"url": TRANSLATION, "extension": [{"url": "lang", "valueCode": g},
                                                             {"url": "content", "valueString": v}]}
                          for g, v in texts.items() if v]}  # fmt: skip


def _read_translations(el: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for ext in el.get("extension", []) if isinstance(el, dict) else []:
        if ext.get("url") != TRANSLATION:
            continue
        parts = {x.get("url"): x.get("valueCode") or x.get("valueString") for x in ext.get("extension", [])}
        if parts.get("lang") and parts.get("content"):
            out[str(parts["lang"])] = str(parts["content"])
    return out


_BOUND = {"integer": "valueInteger", "decimal": "valueDecimal", "date": "valueDate", "dateTime": "valueDateTime"}


def _bound(f: Field, url: str, v: str) -> dict[str, Any]:
    key = _BOUND.get(f.kind, "valueString")
    val: Any = v
    try:
        if key in ("valueInteger", "valueDecimal"):  # 1 stays 1 (not 1.0), so the bound reads back as written
            val = int(v) if re.fullmatch(r"-?\d+", v) else float(v)
    except ValueError:
        key, val = "valueString", v
    return {"url": url, key: val}


def _enable_when(rule: str, fields: dict[str, Field]) -> dict[str, Any]:
    """FHIR ``enableWhen`` for a rule that is one comparison, or only ``and`` or only ``or`` of comparisons."""
    from datacore.branching import parse

    node = parse(rule)
    if node is None:
        return {}
    atoms = node[1:] if node[0] in ("and", "or") else [node]
    if any(a[0] in ("and", "or") or a[1] not in fields for a in atoms):
        return {}
    conds = []
    for op, name, val in atoms:
        f = fields[name]
        ans = {"answerCoding": {"code": val}} if f.kind in ("choice", "multi") else {"answerString": val}
        conds.append({"question": name, "operator": "=" if op == "=" else "!=", **ans})
    out: dict[str, Any] = {"enableWhen": conds}
    if len(conds) > 1:
        out["enableBehavior"] = "all" if node[0] == "and" else "any"
    return out


def _item(f: Field, fields: dict[str, Field] | None = None) -> dict[str, Any]:
    kind = {"choice": "choice", "multi": "choice", "display": "display", "notes": "text", "calc": "string",
            "text": "string", "file": "attachment"}.get(f.kind, f.kind)  # fmt: skip
    item: dict[str, Any] = {"linkId": f.name, "text": f.label or f.name, "type": kind}
    if f.labels:
        item["_text"] = _translations(f.labels)
    ext = [_bound(f, u, v) for u, v in ((MIN_VALUE, f.vmin), (MAX_VALUE, f.vmax)) if v]
    if f.validation:
        ext.append({"url": VALIDATION, "valueString": f.validation})
    if f.branching:
        ext.append({"url": BRANCHING, "valueString": f.branching})
        item.update(_enable_when(f.branching, fields or {}))
    if ext:
        item["extension"] = ext
    if f.required and kind != "display":
        item["required"] = True
    if f.kind == "multi":
        item["repeats"] = True
    if f.kind == "calc":
        item["readOnly"] = True
    if f.options:
        opts = []
        for c, d in f.options.items():
            coding: dict[str, Any] = {"code": c, "display": d}
            tr = {g: f.option_labels.get(g, {}).get(c, "") for g in f.option_labels}
            if any(tr.values()):
                coding["_display"] = _translations(tr)
            opts.append({"valueCoding": coding})
        item["answerOption"] = opts
    return item


def questionnaires(study: str, fields: list[Field], record_field: str | None = None,
                   titles: dict[str, dict[str, str]] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    """One Questionnaire per form, in first-seen order; identifier fields are dropped (never held by TrialBox).
    ``titles``: form -> language -> title (``en`` is the plain title)."""
    forms: dict[str, list[Field]] = {}
    for f in fields:
        if f.identifier:
            continue
        forms.setdefault(f.form, []).append(f)
    out = []
    by_name = {f.name: f for f in fields}
    for form, fs in forms.items():
        tt = (titles or {}).get(form) or {}
        q: dict[str, Any] = {
            "resourceType": "Questionnaire",
            "id": f"{study.lower()}-{form}".replace("_", "-")[:64],
            "url": URL.format(study=study, form=form),
            "name": form,
            "title": tt.get("en") or form.replace("_", " "),
            "status": "active",
            "subjectType": ["Patient"],
            "item": [_item(f, by_name) for f in fs if f.name != record_field],
        }  # fmt: skip
        if any(tt.get(g) for g in LANGS):
            q["_title"] = _translations({g: tt.get(g, "") for g in LANGS})
        out.append(q)
    return out


def titles_of(questionnaire: dict[str, Any]) -> dict[str, str]:
    """The form's title per language (``en`` is the plain title)."""
    return {"en": str(questionnaire.get("title") or questionnaire.get("name") or ""),
            **_read_translations(questionnaire.get("_title"))}  # fmt: skip


def fields_of(questionnaire: dict[str, Any]) -> list[Field]:
    """Questionnaire -> fields (the inverse of ``questionnaires`` for what TrialBox keeps)."""
    form = str(questionnaire.get("name") or "")
    out = []
    for it in questionnaire.get("item", []):
        opts = {str(o["valueCoding"]["code"]): str(o["valueCoding"].get("display", ""))
                for o in it.get("answerOption", []) if "valueCoding" in o}  # fmt: skip
        t = it.get("type")
        back = {"string": "calc" if it.get("readOnly") else "text", "text": "notes", "attachment": "file"}
        kind = "multi" if t == "choice" and it.get("repeats") else back.get(t, t)
        ext = {e.get("url"): e for e in it.get("extension", [])}

        def bound(url: str, ext: dict[str, Any] = ext) -> str:
            e = ext.get(url) or {}
            v = next((e[k] for k in e if k.startswith("value")), "")
            return "" if v == "" else str(v)

        olabels: dict[str, dict[str, str]] = {}
        for o in it.get("answerOption", []):
            for g, v in _read_translations(o.get("valueCoding", {}).get("_display")).items():
                olabels.setdefault(g, {})[str(o["valueCoding"]["code"])] = v
        out.append(Field(it["linkId"], form, kind, str(it.get("text") or ""), opts, bool(it.get("required")),
                         labels=_read_translations(it.get("_text")), option_labels=olabels,
                         vmin=bound(MIN_VALUE), vmax=bound(MAX_VALUE), branching=bound(BRANCHING),
                         validation=bound(VALIDATION)))  # fmt: skip
    return out


def _num(v: str) -> float | None:
    try:
        return float(v)
    except ValueError:
        return None


_DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def _real_date(value: str) -> bool:
    """YYYY-MM-DD and a day the calendar has (2026-02-30 is not)."""
    from datetime import date

    if not _DATE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


# EDC-010 (D-581): what XML 1.0 does not allow in a document (its ``Char`` production allows tab, line feed, carriage
# return, U+0020 to U+D7FF, U+E000 to U+FFFD and U+10000 to U+10FFFF). One such character in one value made the whole
# study's ODM file unreadable.
XML_ILLEGAL = re.compile("[^\t\n\r\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def xml_text(text: str) -> str:
    """``text`` for an XML file when it is not a value (a label, a name, a quote): a character XML 1.0 does not
    allow is written as U+FFFD, which a reader sees. A value is never altered: it is refused (:func:`problem`)."""
    return XML_ILLEGAL.sub("\ufffd", text)


def problem(f: Field, value: str) -> dict[str, str] | None:
    """None if ``value`` (a raw code) fits the field's type and range, else ``{field, code, ...}``. The code names
    the reason (chars, choice, date, datetime, integer, decimal, min, max, not_entered), for a message in any
    language."""
    if value == "":
        return None
    p = {"field": f.name}
    if XML_ILLEGAL.search(value):  # before every other check: the message never repeats the value
        return {**p, "code": "chars"}
    if f.kind in ("display", "calc", "file"):
        return {**p, "code": "not_entered"}
    v = f.validation
    if f.kind == "text" and v in ("time", "time_hh_mm") and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        return {**p, "code": "time"}
    if f.kind == "text" and v == "time_mm_ss" and not re.fullmatch(r"[0-5]\d:[0-5]\d", value):
        return {**p, "code": "time"}
    if f.kind == "text" and v == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        return {**p, "code": "email"}
    if f.kind == "text" and v.startswith("phone") and not re.fullmatch(r"\+?[0-9 ()\-]{6,20}", value):
        return {**p, "code": "phone"}
    if f.kind == "decimal" and "comma_decimal" in v:  # TrialBox keeps a point; REDCap's import gets the comma
        value = value.replace(",", ".", 1)
    if f.kind == "choice" and value not in f.options:
        return {**p, "code": "choice"}
    if f.kind == "multi" and any(v not in f.options for v in value.split(",")):
        return {**p, "code": "choice"}
    if f.kind == "date" and not _real_date(value):
        return {**p, "code": "date"}
    if f.kind == "dateTime" and not re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$", value):
        return {**p, "code": "datetime"}
    if f.kind == "integer" and not re.match(r"^-?\d+$", value):
        return {**p, "code": "integer"}
    if f.kind == "decimal" and not re.match(r"^-?\d+(\.\d+)?$", value):
        return {**p, "code": "decimal"}
    places = _decimals(f)
    if f.kind == "decimal" and places is not None and len(value.partition(".")[2]) > places:
        return {**p, "code": "decimals", "places": str(places)}  # never rounded here: a person decides the value
    if f.kind in ("integer", "decimal"):
        x, lo, hi = _num(value), _num(f.vmin.replace(",", ".")), _num(f.vmax.replace(",", "."))
        if x is not None and lo is not None and x < lo:
            return {**p, "code": "min", "min": f.vmin}
        if x is not None and hi is not None and x > hi:
            return {**p, "code": "max", "max": f.vmax}
    if f.kind in ("date", "dateTime"):  # ISO dates compare as text
        if _DATE.match(f.vmin[:10]) and value[:10] < f.vmin[:10]:
            return {**p, "code": "min", "min": f.vmin}
        if _DATE.match(f.vmax[:10]) and value[:10] > f.vmax[:10]:
            return {**p, "code": "max", "max": f.vmax}
    return None


_WHY = {"choice": "{v!r} is not a choice of {f}", "date": "{f} is a date (YYYY-MM-DD)",
        "datetime": "{f} is a date and time (YYYY-MM-DD HH:MM)", "integer": "{f} is a whole number",
        "decimal": "{f} is a number", "not_entered": "{f} is not entered", "min": "{f} is below {min}",
        "max": "{f} is above {max}", "required": "{f} is required", "owned": "{f}: owned by {owner}",
        "unknown": "{f}: not a field of this form", "decimals": "{f} has at most {places} decimal places",
        "chars": "{f} holds a character that cannot be stored (a control character from pasted text)",
        "time": "{f} is a time (HH:MM)", "email": "{f} is an e-mail address",
        "phone": "{f} is a phone number",
        "reason": "{f} was saved before: give the reason for the change (D-778)"}  # fmt: skip


def reason(p: dict[str, str], value: str = "") -> str:
    """A problem in plain English (the API's message; the console shows it in the reader's language)."""
    return _WHY.get(p["code"], "{f}: {code}").format(v=value, f=p["field"], min=p.get("min", ""),
                                                      max=p.get("max", ""), owner=p.get("owner", ""),
                                                      places=p.get("places", ""), code=p["code"])  # fmt: skip


def checkbox_column(field: str, code: str) -> str:
    """REDCap's column of one choice of a checkbox (NEW-EDC-3b, review F1): ``field___`` and the code lowercased,
    ``-`` and ``.`` written ``_`` (``Unknown, -99`` is ``field____99``; ``A`` is ``field___a``)."""
    return f"{field}___{code.lower().replace('-', '_').replace('.', '_')}"


def checkbox_code(f: Field, column: str) -> str | None:
    """The choice of ``f`` whose REDCap column is ``column`` (None: no choice of the field)."""
    return next((c for c in f.options if checkbox_column(f.name, c) == column), None)


def redcap_value(f: Field, value: str) -> str:
    """A value that passes :func:`problem`, written the way REDCap's import takes it for the field's validation
    (STD-061): ``number_1dp`` gets exactly one decimal place (``72`` -> ``72.0``, never rounded), a decimal-comma type
    gets the comma. REDCap refuses a whole import batch on one value in another format."""
    v = f.validation
    if f.kind == "multi" and value:  # NEW-EDC-3b: the codes chosen, once each, in the field's choice order
        chosen = {c.strip() for c in value.split(",") if c.strip()}
        return ",".join(c for c in f.options if c in chosen)
    if f.kind != "decimal" or not value:
        return value
    out = value.replace(",", ".", 1)
    places = _decimals(f)
    if places:
        whole, _, frac = out.partition(".")
        out = f"{whole}.{frac.ljust(places, '0')}"
    return out.replace(".", ",", 1) if "comma_decimal" in v else out


def field_sha(f: Field) -> str:
    """What a value's meaning rests on in the dictionary (E-16, T-115): name, form, type, validation, choices and
    their labels, range. Labels of the question and translations are left out; a changed choice label is not."""
    import hashlib
    import json

    body = {"name": f.name, "form": f.form, "kind": f.kind, "validation": f.validation, "options": f.options,
            "vmin": f.vmin, "vmax": f.vmax, **({"places": f.places} if f.places else {})}  # fmt: skip
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def check_value(f: Field, value: str) -> str | None:
    """None if ``value`` (a raw code) fits the field, else the reason."""
    p = problem(f, value)
    return None if p is None else reason(p, value)


_BACK = {"choice": "radio", "multi": "checkbox", "display": "descriptive", "calc": "calc", "notes": "notes",
         "file": "file"}  # fmt: skip
_VALID = {"date": "date_ymd", "integer": "integer", "decimal": "number", "dateTime": "datetime_ymd"}


def metadata(fields: list[Field], translations: bool = False) -> list[dict[str, str]]:
    """Fields -> REDCap data dictionary rows (API column names). ``translations`` adds TrialBox's language columns."""
    out = []
    for f in fields:
        row = dict.fromkeys(_COLS.values(), "")  # RC13-B (D-848): all 18 columns, in REDCap's order
        row.update({
            "field_name": f.name,
            "form_name": f.form,
            "field_type": _BACK.get(f.kind, "text"),
            "field_label": f.label,
            "select_choices_or_calculations": " | ".join(f"{c}, {d}" for c, d in f.options.items()),
            "text_validation_type_or_show_slider_number": f.validation or _VALID.get(f.kind, ""),
            "text_validation_min": f.vmin,
            "text_validation_max": f.vmax,
            "identifier": "y" if f.identifier else "",
            "branching_logic": f.branching,
            "required_field": "y" if f.required else "",
            "field_annotation": f"@TB-DECIMALS={f.places}" if f.places and f.kind == "decimal" else "",
        })  # fmt: skip
        if translations:
            for g in LANGS:
                row[f"field_label:{g}"] = f.labels.get(g, "")
                tr = f.option_labels.get(g, {})
                row[f"select_choices_or_calculations:{g}"] = " | ".join(f"{c}, {tr[c]}" for c in f.options if c in tr)
        out.append(row)
    return out


def dictionary_csv(fields: list[Field]) -> str:
    """Fields -> a REDCap data dictionary CSV (export column names), for building the project in REDCap."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(list(_COLS))
    for r in metadata(fields):
        w.writerow([r.get(k, "") for k in _COLS.values()])
    return buf.getvalue()
