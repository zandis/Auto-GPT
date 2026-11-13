"""The item map of one study (D-160): which eCRF item is drafted from which part of the record.

One :class:`ItemMap` per item. ``source`` names where a value may come from:

* ``patient``: the patient row (``what`` = ``birth_date`` or ``sex``);
* ``observation``: a lab or vital sign, by code (``what`` = ``value`` or ``date``), in one unit;
* ``condition``: a diagnosis, by code (``what`` = ``presence`` or ``date``);
* ``medication``: a medicine, by ATC or hospital code (``what`` = ``presence``, ``term`` or ``start``);
* ``note``: a note passage, read by the model with a verbatim quote (``what`` = ``value``), only for items whose
  value is written in notes and nowhere coded;
* ``none``: never drafted; the coordinator enters it in the EDC as before.

:func:`check` refuses a map that could draft a wrong kind of value: an item the dictionary does not have, a REDCap
identifier or link field, a numeric item without a unit, a coded source without codes, a ``presence`` item whose
"yes" code is not a choice of the field, an item tagged as the CTCAE grade (``AE.AETOXGR``) that is not a choice of
grades 1 to 5 (D-396). A ``presence`` item is only ever drafted as its yes code: the absence of a
record never becomes "No" (unknown never excludes).

D-598: a lab, vital sign or diagnosis item reads only records whose code is of the item's code system
(:func:`systems_of`): the one the row names when the box reads it for that source, else all the box reads for that
source (:data:`SYSTEMS`). A medicine is read by column (ATC, the hospital's drug code), so its row needs none.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from datacore.forms import Field
from tb_common.derived import SCORE

from edc import cdash

# D-598: the code systems a record's code may be of, by source. A lab or vital sign is LOINC, or a clinical score
# the box codes itself (TJC28, ...); a diagnosis is ICD-10-CM (also under a TW Core edition's name, as a FHIR feed
# may send it first) at a Taiwan site and WHO ICD-10 at a Japan site
_TW_ICD10CM = "https://twcore.mohw.gov.tw/ig/twcore/CodeSystem/icd-10-cm-"
SYSTEMS: dict[str, tuple[str, ...]] = {
    "observation": (cdash.LOINC, SCORE),
    "condition": (
        "http://hl7.org/fhir/sid/icd-10-cm",
        "http://hl7.org/fhir/sid/icd-10",
        _TW_ICD10CM + "2014-tw",
        _TW_ICD10CM + "2021-tw",
        _TW_ICD10CM + "2023-tw",
    ),
}

SOURCES = ("patient", "observation", "condition", "medication", "note", "none")
WHAT: dict[str, tuple[str, ...]] = {
    "patient": ("birth_date", "sex"),
    "observation": ("value", "date"),
    "condition": ("presence", "date"),
    "medication": ("presence", "term", "start"),
    "note": ("value",),
    "none": ("",),
}
PICKS = ("latest_before", "nearest")
SEXES = ("male", "female")
GRADES = ("1", "2", "3", "4", "5")  # CTCAE grades (D-396)
MAX_WINDOW = 3650
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,19}$")
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


@dataclass(frozen=True)
class ItemMap:
    item: str
    cdash: str = ""  # DOMAIN.VARIABLE, e.g. VS.VSORRES
    test: str = ""  # the CDASH test code for findings, e.g. WEIGHT
    source: str = "none"
    what: str = ""
    codes: tuple[str, ...] = ()
    system: str = ""
    unit: str = ""
    pick: str = "latest_before"
    window_days: int = 30  # how far before (latest_before) or around (nearest) the visit date a record may be
    yes_code: str = "1"  # presence: the choice code that means "yes"
    sex_codes: dict[str, str] = field(default_factory=dict)  # sex: male/female -> the field's choice codes
    question: str = ""  # note: what to look for, in plain words

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> ItemMap:
        known = set(cls.__dataclass_fields__)
        data = {k: v for k, v in body.items() if k in known}
        data["codes"] = tuple(str(c).strip() for c in (data.get("codes") or ()) if str(c).strip())
        data["sex_codes"] = {str(k): str(v) for k, v in (data.get("sex_codes") or {}).items()}
        data["window_days"] = int(data.get("window_days") or 0)
        for k in ("item", "cdash", "test", "source", "what", "system", "unit", "pick", "yes_code", "question"):
            if k in data:
                data[k] = str(data[k] or "").strip()
        data.setdefault("source", "none")
        data["source"] = data["source"] or "none"
        data["pick"] = data.get("pick") or "latest_before"
        data["yes_code"] = data.get("yes_code") or "1"
        return cls(**data)

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["codes"] = list(self.codes)
        return out

    @property
    def drafted(self) -> bool:
        return self.source != "none"


def systems_of(m: ItemMap) -> tuple[str, ...]:
    """The code systems a record must be of to count for this item (D-598); empty = the source is not read by a
    code with a system (a medicine, the patient row, a note). The row's own ``system`` narrows them when it is one
    the box reads for the source. Any other (a suggestion's LOINC kept under a diagnosis, hidden on the map page; a
    free text) is not a problem of the map and narrows nothing: the item reads the box's own systems."""
    known = SYSTEMS.get(m.source, ())
    return (m.system,) if m.system in known else known


def dumps(items: list[ItemMap]) -> str:
    return json.dumps([i.as_dict() for i in items], ensure_ascii=False, sort_keys=True)


def item_sha(item: ItemMap | dict[str, Any]) -> str:
    """The hash of one item's map row (E-15, T-115): stored on each draft and in what a signature covers. A draft
    whose item's row changed since is superseded (open or decided, not signed) or not sent (signed)."""
    m = item if isinstance(item, ItemMap) else ItemMap.from_dict(item)
    return hashlib.sha256(json.dumps(m.as_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def suggest(fields: list[Field], protected: set[str]) -> list[ItemMap]:
    """A first map from the dictionary: a CDASH tag and source where :func:`edc.cdash.suggest` recognises the field,
    ``none`` elsewhere. Codes for diagnoses and medicines are left empty on purpose (``check`` then refuses to draft
    them until the coordinator types the codes)."""
    out: list[ItemMap] = []
    for f in fields:
        if f.kind in ("display", "calc") or f.identifier or f.name in protected:
            continue
        h = cdash.suggest(f.name, f.label)
        if h is None:
            out.append(ItemMap(f.name))
            continue
        if h.tag == "AE.AETOXGR" and (f.kind != "choice" or not set(f.options) <= set(GRADES)):
            out.append(ItemMap(f.name))  # not a choice of grades 1 to 5: no tag rather than a refused one
            continue
        source, what = h.source, h.what
        if what == "presence" and f.kind != "choice":
            source, what = "none", ""
        if source == "observation" and f.kind not in ("integer", "decimal", "text"):
            source, what = "none", ""
        if source in ("condition", "medication"):  # never guess the codes: typed by the coordinator
            source, what = "none", ""
        sex = {}
        if what == "sex":
            sex = {s: c for s in SEXES for c, lbl in f.options.items() if lbl.strip().lower().startswith(s[0])}
            if len(sex) != 2:
                source, what = "none", ""
        out.append(ItemMap(f.name, h.tag, h.test, source, what, h.codes, h.system, h.unit, sex_codes=sex))
    return out


def check(items: list[ItemMap], fields: dict[str, Field], protected: set[str]) -> list[dict[str, str]]:
    """Every problem of the map, as ``{item, code}``; empty = the map may be used to draft."""
    bad: list[dict[str, str]] = []

    def no(item: str, code: str) -> None:
        bad.append({"item": item, "code": code})

    seen: set[str] = set()
    for m in items:
        if not _NAME.match(m.item):
            no(m.item, "name")
            continue
        if m.item in seen:
            no(m.item, "twice")
        seen.add(m.item)
        f = fields.get(m.item)
        if f is None:
            no(m.item, "not_in_dictionary")
            continue
        if m.item in protected or f.identifier:
            no(m.item, "protected")
        if m.cdash and not cdash.valid_tag(m.cdash):
            no(m.item, "cdash")
        if not cdash.valid_test(m.test):
            no(m.item, "cdash_test")
        if m.cdash == "AE.AETOXGR" and (f.kind != "choice" or not set(f.options) <= set(GRADES)):
            no(m.item, "cdash_grade")  # D-396: a CTCAE grade is a choice of 1 to 5, nothing else
        if m.source not in SOURCES:
            no(m.item, "source")
            continue
        if m.what not in WHAT[m.source]:
            no(m.item, "what")
            continue
        if not m.drafted:
            continue
        if f.kind in ("display", "calc", "multi"):
            no(m.item, "kind")
        if m.pick not in PICKS:
            no(m.item, "pick")
        if not 0 <= m.window_days <= MAX_WINDOW:
            no(m.item, "window")
        if m.source in ("observation", "condition", "medication") and (
            not m.codes or any(not _CODE.match(c) for c in m.codes)
        ):
            no(m.item, "codes")
        if m.what in ("birth_date", "date", "start") and f.kind != "date":
            no(m.item, "kind")
        if m.source == "observation" and m.what == "value":
            if f.kind not in ("integer", "decimal", "text"):
                no(m.item, "kind")
            if not m.unit:
                no(m.item, "unit")
        if m.what == "presence" and (f.kind != "choice" or m.yes_code not in f.options):
            no(m.item, "yes_code")
        if m.what == "sex" and (f.kind != "choice" or set(m.sex_codes) != set(SEXES)
                                or not set(m.sex_codes.values()) <= set(f.options)):  # fmt: skip
            no(m.item, "sex_codes")
        if m.what == "term" and f.kind not in ("text", "notes"):
            no(m.item, "kind")
        if m.source == "note" and not m.question.strip():
            no(m.item, "question")
    return bad


def unit_key(unit: str) -> str:
    """Units compared without case, brackets or spaces: ``mm[Hg]`` = ``mmHg``, ``mg/dl`` = ``mg/dL``."""
    return re.sub(r"[\s\[\]]", "", unit or "").lower()
