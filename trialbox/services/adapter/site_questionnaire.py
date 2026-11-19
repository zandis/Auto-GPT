"""The site questionnaire as a form that fills a site profile (10B-19, D-1249; docs/data/15-the-site-profile.md).

The questionnaire is review 12 section 9 (``docs/reviews/2026-11-root/12-ssi-data.md``): 9.1, thirty questions for the
hospital's IT, and 9.2, the sample exports to ask for. :data:`QUESTIONS` says which profile field each fills, or why
it fills none. A hospital's answers, written in one answers file (``fill --template`` prints it in en, ja or zh-TW),
become a profile folder in D-1233's format, so nobody hand-writes the folder:

    python -m adapter.site_profile fill --template --lang ja > answers.yaml
    python -m adapter.site_profile fill --answers answers.yaml --out <new folder> [--check-only] [--lang ja]

**The form writes; it never loads.** Loading stays D-1233's one path (``load --by``: versioned, audited, refused when
the content changes under the same version). The folder it writes is read back by the real loader before it is
put in place, so the form cannot leave a folder the loader would refuse.

**Allow-list.** :func:`parse` accepts an answer only when it is positively recognised: a key of the form, a name from
a list (a country, a door, a data type, a standard, a master, a category, a kind, a unit the product knows), a value
of a fixed shape (a profile name, a version, a date, a site code, a YJ code, a standard code checked as the loader
checks it, a LOINC answer code), a bounded number. Anything else is a :class:`Problem` whose
``code`` is a key of the console's text catalogue (``profileform.err.<code>``, en, ja and zh-TW) that says what is
expected. The few free-text cells (a code's name, a lab test's display, an answer's display) are printable text only
(no control or format character, no leading ``=``, ``+``, ``-`` or ``@``), written by the csv module, so they are
quoted where needed and never reach the manifest. No path, no file name and no command comes from an answer: the
tables are ``codes/diagnosis.csv``, ``codes/drug.csv`` and ``codes/lab.csv``, and a table's ``source`` is composed of
the form's own words, a master from the list and a checked date.

**An unchecked mapping stays unchecked.** A row is ``verified`` only when its answer says exactly ``verified``; a row
without a state is ``verify``, as D-1233 stores a row nobody checked. Whether such a row may exclude a patient is
the owner's open question (DATA section 15); this form does not decide it.
"""

from __future__ import annotations

import csv
import io
import os
import re
import shutil
import tempfile
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from tb_common.codekey import fold_key
from tb_common.labunit import UCUM
from tb_common.site_profile import FORMAT, MANIFEST, check_code, load

ANSWERS_FORMAT = "tb-site-questionnaire/1"
LANGS = ("en", "ja", "zh-TW")
MAX_BYTES = 5 * 1024 * 1024  # an answers file larger than any hospital's three masters: a wrong file
MAX_ROWS = 50_000  # rows of one table
MAX_TEXT = 120  # characters of a name or a display

#: the manifest's fields (libs/tb_common/site_profile.schema.json)
PROFILE_FIELDS = ("format", "id", "site_id", "country", "version", "synthetic", "door", "standards", "data_types",
                  "tables")  # fmt: skip
#: the manifest fields no question of the questionnaire fills, and where they come from instead
NOT_FROM_THE_QUESTIONNAIRE = {
    "format": "fixed by the form (tb-site-profile/1)",
    "id": "the steward names the profile (the form's header)",
    "site_id": "the box's settings.site.id (the form's header; load refuses another site)",
    "country": "the box's settings (the form's header; load refuses another country)",
    "version": "the steward's version (the form's header)",
    "synthetic": "the steward says whether the data is synthetic (the form's header)",
}


@dataclass(frozen=True)
class Question:
    number: str  # 9.1.<n> or 9.2.<n> of review 12
    fills: tuple[str, ...] = ()  # profile fields, as <field> or <field>.<key>
    no_field_because: str = ""


_N = "no profile field"
#: every question of review 12 section 9 and the profile field it fills, or why it fills none (DATA section 15)
QUESTIONS = (
    Question("9.1.1", no_field_because=f"{_N}: the chart system and its version are not in the profile"),
    Question("9.1.2", no_field_because=f"{_N}: departmental and third-party systems; what reaches the box is q6"),
    Question("9.1.3", no_field_because=f"{_N}: the database engine (a door's connection is settings)"),
    Question("9.1.4", ("door",)),
    Question("9.1.5", no_field_because=f"{_N}: where the storage is and its size: the box's mount, never an answer"),
    Question("9.1.6", ("data_types",)),
    Question("9.1.7", no_field_because=f"{_N}: the order-number habit is TB_SSMIX2_ORDER_NUMBERS (D-594) and 10B-2"),
    Question("9.1.8", ("standards.ssmix2",), "the character set has no profile field (settings.data_source.encoding)"),
    Question("9.1.9", ("standards.icd10",), "where PPR-01 writes ICD-10 and its 転帰 table have no profile field"),
    Question("9.1.10", ("tables.drug",), "RXE-2 and TQ1-3 habits have no profile field (usage codes: 10B-4)"),
    Question("9.1.11", ("tables.lab",), "the share of JLAC10 is counted by the coverage lines, not answered"),
    Question("9.1.12", ("data_types",), "the document-type list has no profile field yet (10B-5, 10B-15)"),
    Question("9.1.13", no_field_because=f"{_N}: templates (10B-15)"),
    Question("9.1.14", ("data_types",), "only whether vitals are stored (vital)"),
    Question("9.1.15", ("data_types",), "only whether appointments are stored (appointment)"),
    Question("9.1.16", no_field_because=f"{_N}: DPC files have no door yet (10B-12)"),
    Question("9.1.17", no_field_because=f"{_N}: regimens (10A-8)"),
    Question("9.1.18", no_field_because=f"{_N}: a separate 健診 ID and its linking"),
    Question("9.1.19", no_field_because=f"{_N}: UKE receipts have no door yet"),
    Question("9.1.20", no_field_because=f"{_N}: the cancer registry's export"),
    Question("9.1.21", ("standards", "tables"), "the share of local codes mapped is counted, not answered"),
    Question("9.1.22", no_field_because=f"{_N}: network zone (infrastructure)"),
    Question("9.1.23", no_field_because=f"{_N}: hardware and physical access (infrastructure)"),
    Question("9.1.24", no_field_because=f"{_N}: who operates (people)"),
    Question("9.1.25", no_field_because=f"{_N}: the vendor's maintenance network (infrastructure)"),
    Question("9.1.26", no_field_because=f"{_N}: the data-use approval path (policy)"),
    Question("9.1.27", no_field_because=f"{_N}: the vendor's cost and lead time"),
    Question("9.1.28", no_field_because=f"{_N}: REDCap (settings and the REDCap connection)"),
    Question("9.1.29", no_field_because=f"{_N}: users and terminals (accounts)"),
    Question("9.1.30", no_field_because=f"{_N}: the chart system's trial module"),
    Question("9.2.1", no_field_because=f"{_N}: a sample storage is read by the reader, not described"),
    Question("9.2.2", no_field_because=f"{_N}: sample documents (10B-5)"),
    Question("9.2.3", ("tables",), "用法 (10B-4) and 診療科 (settings.departments) have no profile table yet"),
    Question("9.2.4", no_field_because=f"{_N}: DPC samples (10B-12)"),
    Question("9.2.5", no_field_because=f"{_N}: a UKE sample"),
    Question("9.2.6", no_field_because=f"{_N}: templates and the regimen master (10B-15, 10A-8)"),
    Question("9.2.7", no_field_because=f"{_N}: the REDCap data dictionary"),
)

COUNTRIES = ("jp", "tw", "us", "other")
DOORS = ("ssmix2", "csv", "cgrd_sql")
#: the 26 message types of the SS-MIX2 standardised storage (review 12 section 4.3) and the words the profiles use for
#: what the extended storage and the other exports hold
SSMIX2_TYPES = ("ADT-00", "ADT-01", "ADT-12", "ADT-21", "ADT-22", "ADT-31", "ADT-32", "ADT-41", "ADT-42", "ADT-51",
                "ADT-52", "ADT-61", "PPR-01", "OMP-01", "OMP-02", "OMP-11", "OMP-12", "OML-01", "OML-11", "OMG-01",
                "OMG-02", "OMG-03", "OMG-11", "OMG-12", "OMG-13", "OMD")  # fmt: skip
OTHER_TYPES = ("document", "vital", "report", "procedure", "appointment", "claim", "registry")
#: the source tables of a csv or SQL door, by their canonical names (the mapping templates')
TABLE_TYPES = ("patient", "practitioner", "encounter", "appointment", "diagnosis", "lab", "vital", "medication",
               "procedure", "report", "note", "claim", "registry")  # fmt: skip
_SEMVER = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}")
_DATE = "date"
#: the standards the form knows, each with the shape of its value (a master's value is its release date)
STANDARDS: dict[str, re.Pattern[str] | str] = {
    "ssmix2": re.compile(r"1\.2[a-z]?"),
    "jp_core": _SEMVER,
    "tw_core": _SEMVER,
    "icd10": re.compile(r"WHO-(19|20)[0-9]{2}"),
    "icd10cm": re.compile(r"(19|20)[0-9]{2}"),
    "medis_byomei": _DATE,
    "hot": _DATE,
    "jlac10": _DATE,
    "jlac11": _DATE,
    "jj1017": _DATE,
    "yj": _DATE,
    "receipt_masters": _DATE,
    "jami_usage": _DATE,
}
#: where a table's rows came from: the master's words as the manifest's ``source`` writes them
SOURCE_WORDS = {
    "synthetic": "synthetic codes (questionnaire form)",
    "hospital": "the hospital's own master",
    "medis_byomei": "MEDIS standard disease-name master",
    "yj": "YJ codes of the drug price list",
    "hot": "HOT codes",
    "jlac10": "JLAC10 master",
    "jlac11": "JLAC11 master",
}
TABLES = ("diagnosis", "drug", "lab")
_TABLE_KEYS = frozenset({"source", "rows"})
_SOURCE_KEYS = frozenset({"master", "date"})
_ROW_KEYS = {
    "diagnosis": frozenset({"code", "name", "icd10", "state"}),
    "drug": frozenset({"code", "name", "atc", "state"}),
    "lab": frozenset({"code", "loinc", "score", "display", "unit", "factor", "category", "kind", "answers",
                      "source_unit", "state"}),
}  # fmt: skip
_TOP = frozenset({"format", "profile", "door", "data_types", "standards", "tables"})
_PROFILE = frozenset({"id", "site_id", "country", "version", "synthetic"})
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
_SITE = re.compile(r"[A-Za-z0-9_-]{1,32}")
_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")  # a site's own code
_YJ = re.compile(r"[0-9]{7}[0-9A-Z][0-9]{4}")
_WORD = re.compile(r"[A-Z][A-Z0-9_]{0,7}")
_LA = re.compile(r"LA[1-9][0-9]{0,5}-[0-9]")
_FACTOR = re.compile(r"[0-9]{1,4}(\.[0-9]{1,6})?")
CATEGORIES = ("laboratory", "survey")
KINDS = ("quantity", "coded")
#: the FHIR profile a lab row's results carry, by country and category (the shipped tables' own values)
LAB_PROFILES = {
    ("jp", "laboratory"): "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult",
    ("jp", "survey"): "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common",
    (
        "tw",
        "laboratory",
    ): "https://twcore.mohw.gov.tw/ig/twcore/StructureDefinition/Observation-laboratoryResult-twcore",
}
#: a lab row's unit is a UCUM code the product knows (``tb_common.labunit.UCUM``); a source unit may be any of its
#: spellings
UNITS = frozenset(UCUM)
SOURCE_UNITS = frozenset({*UCUM, *(s for spellings in UCUM.values() for s in spellings)})
#: the columns of each table as the form writes it: the SS-MIX2 reader's own columns, and for the lab table the
#: columns of the shipped look-up files (``jp_core/jlac10_to_loinc.csv``, ``tw_core/lab_local_to_loinc.csv``)
COLUMNS = {
    "diagnosis": ("code", "name", "icd10", "state"),
    "drug": ("yj_code", "name", "atc", "state"),
    "lab": ("local_code", "system", "code", "display", "ucum", "factor", "category", "value_type", "answers",
            "profile", "state", "source_unit"),
}  # fmt: skip
KEY_TARGET = {"diagnosis": ("code", "icd10"), "drug": ("yj_code", "atc"), "lab": ("local_code", "code")}
#: every refusal the form gives: ``profileform.err.<code>`` in the console's catalogue, en, ja and zh-TW
CODES = ("unreadable", "format", "unknown_key", "missing", "not_text", "id", "site_id", "country", "version",
         "synthetic", "synthetic_id", "door", "data_type", "std_name", "std_value", "table_name", "table_door",
         "lab_country", "master", "master_synthetic", "date", "rows_empty", "rows_too_many", "code_shape",
         "code_repeat", "yj_shape", "target_code", "text", "state", "system_one", "unit", "factor", "category", "kind",
         "answers", "answer_word", "answer_code", "out_exists", "out_live", "loader")  # fmt: skip


@dataclass(frozen=True)
class Problem:
    """One refused answer: ``code`` is ``profileform.err.<code>``; ``where`` names the answer (``profile.id``,
    ``tables.lab.rows[3].unit``); ``values`` fill the message."""

    code: str
    where: str
    values: Mapping[str, str] = field(default_factory=dict)


@dataclass
class Form:
    """The accepted answers: the manifest and each table's rows, ready to be written."""

    manifest: dict[str, Any]
    tables: dict[str, list[dict[str, str]]]

    def rows(self) -> int:
        return sum(len(r) for r in self.tables.values())


def message(p: Problem, lang: str) -> str:
    """The refusal in ``lang`` from the console's catalogue (the one catalogue of the product's words)."""
    from console.i18n import translate

    return translate(lang if lang in LANGS else "en", f"profileform.err.{p.code}", where=p.where, **p.values)


def text(lang: str, key: str, **values: object) -> str:
    from console.i18n import translate

    return translate(lang if lang in LANGS else "en", f"profileform.{key}", **values)


# ------------------------------------------------------------------ reading the answers file
def _plain_yaml(raw: str | bytes) -> bool:
    """No alias (a document that grows as it is read) and no key written twice in one mapping (YAML keeps the last
    silently): asked of the event stream and the composed nodes, before the safe loader builds anything."""
    if any(isinstance(e, yaml.AliasEvent) for e in yaml.parse(raw, Loader=yaml.SafeLoader)):
        return False
    todo = [yaml.compose(raw, Loader=yaml.SafeLoader)]
    while todo:
        node = todo.pop()
        if isinstance(node, yaml.MappingNode):
            keys = [(k.tag, k.value) for k, _ in node.value]
            if len(set(keys)) != len(keys):
                return False
            todo += [v for _, v in node.value]
        elif isinstance(node, yaml.SequenceNode):
            todo += node.value
    return True


def parse_text(raw: str | bytes) -> Form | list[Problem]:
    """The answers file's text, read strictly, then :func:`parse`."""
    if len(raw) > MAX_BYTES:
        return [Problem("unreadable", "answers")]
    try:
        doc = yaml.safe_load(raw) if _plain_yaml(raw) else None
    except (yaml.YAMLError, UnicodeDecodeError, RecursionError):
        return [Problem("unreadable", "answers")]
    if not isinstance(doc, dict):
        return [Problem("unreadable", "answers")]
    return parse(doc)


class _Check:
    def __init__(self) -> None:
        self.problems: list[Problem] = []

    def no(self, code: str, where: str, **values: str) -> None:
        self.problems.append(Problem(code, where, values))

    def keys(self, node: Mapping[Any, Any], allowed: frozenset[str], where: str) -> None:
        for k in node:
            if k not in allowed:
                at = f"{where}.{k}" if where else str(k)
                self.no("unknown_key", at, expected=", ".join(sorted(allowed)))

    def mapping(self, node: Any, where: str) -> dict[Any, Any] | None:
        if node is None:
            self.no("missing", where)
            return None
        if not isinstance(node, dict):
            self.no("missing", where)
            return None
        return node

    def string(self, node: Mapping[Any, Any], key: str, where: str, *, required: bool = True) -> str | None:
        v = node.get(key)
        if v is None or v == "":
            if required:
                self.no("missing", where)
            return None
        if isinstance(v, date):
            v = v.isoformat()  # an unquoted date in YAML is a date: its ISO form is what was written
        if not isinstance(v, str):
            self.no("not_text", where)
            return None
        return v

    def shaped(self, node: Mapping[Any, Any], key: str, where: str, rx: re.Pattern[str], code: str) -> str | None:
        v = self.string(node, key, where)
        if v is not None and not (v.isascii() and rx.fullmatch(v)):
            self.no(code, where, value=_show(v))
            return None
        return v

    def choice(self, node: Mapping[Any, Any], key: str, where: str, allowed: tuple[str, ...], code: str) -> str | None:
        v = self.string(node, key, where)
        if v is not None and v not in allowed:
            self.no(code, where, value=_show(v), expected=", ".join(allowed))
            return None
        return v


def _show(v: object) -> str:
    """An answer as a refusal quotes it: printable, short, so a message never carries a control character."""
    s = "".join(ch if unicodedata.category(ch)[0] != "C" else "?" for ch in str(v))
    return s[:40] + ("…" if len(s) > 40 else "")


def _is_date(v: str) -> bool:
    try:
        return date.fromisoformat(v).isoformat() == v
    except ValueError:
        return False


def text_ok(v: str) -> bool:
    """Printable text a code table may hold: 1 to :data:`MAX_TEXT` characters, starting with a letter, a digit or an
    opening bracket (so no ``=``, ``+``, ``-``, ``@``: nothing a spreadsheet runs), no control or format character
    (no line break, no direction override, no zero-width character), and single spaces only."""
    if not v or len(v) > MAX_TEXT or v != v.strip() or "  " in v:
        return False
    if not (unicodedata.category(v[0])[0] in "LN" or v[0] in "([（［【「"):
        return False
    return all(unicodedata.category(ch)[0] in "LMNPS" or ch == " " for ch in v)


def parse(doc: Mapping[Any, Any]) -> Form | list[Problem]:
    """The answers, every one checked by allow-list: a :class:`Form`, or every :class:`Problem` found."""
    c = _Check()
    c.keys(doc, _TOP, "")
    if doc.get("format") != ANSWERS_FORMAT:
        c.no("format", "format", expected=ANSWERS_FORMAT)
    prof = c.mapping(doc.get("profile"), "profile") or {}
    c.keys(prof, _PROFILE, "profile")
    pid = c.shaped(prof, "id", "profile.id", _ID, "id")
    site = c.shaped(prof, "site_id", "profile.site_id", _SITE, "site_id")
    country = c.choice(prof, "country", "profile.country", COUNTRIES, "country")
    version = c.shaped(prof, "version", "profile.version", _SEMVER, "version")
    synthetic = prof.get("synthetic")
    if synthetic is None:
        c.no("missing", "profile.synthetic")
    elif not isinstance(synthetic, bool):
        c.no("synthetic", "profile.synthetic")
        synthetic = None
    elif pid is not None and pid.startswith("synthetic-") != synthetic:
        c.no("synthetic_id", "profile.synthetic")
    door = c.choice(doc, "door", "door", DOORS, "door")
    types = _data_types(c, doc.get("data_types"), door)
    standards = _standards(c, doc.get("standards"))
    tables = _tables(c, doc.get("tables"), door=door, country=country, synthetic=synthetic)
    if c.problems:
        return c.problems
    assert pid and site and country and version and door and synthetic is not None  # checked above
    manifest: dict[str, Any] = {
        "format": FORMAT, "id": pid, "site_id": site, "country": country, "version": version,
        "synthetic": synthetic, "door": door, "standards": standards, "data_types": types,
        "tables": {name: spec for name, (spec, _) in tables.items()},
    }  # fmt: skip
    return Form(manifest, {name: rows for name, (_, rows) in tables.items()})


def _data_types(c: _Check, node: Any, door: str | None) -> list[str]:
    if not isinstance(node, list) or not node:
        c.no("missing", "data_types")
        return []
    allowed = (*SSMIX2_TYPES, *OTHER_TYPES) if door == "ssmix2" else TABLE_TYPES
    out: list[str] = []
    for i, v in enumerate(node):
        if not isinstance(v, str) or v not in allowed or v in out:
            c.no("data_type", f"data_types[{i}]", value=_show(v), expected=", ".join(allowed))
        else:
            out.append(v)
    return out


def _standards(c: _Check, node: Any) -> dict[str, str]:
    st = c.mapping(node, "standards") or {}
    if node is not None and isinstance(node, dict) and not node:
        c.no("missing", "standards")
    out: dict[str, str] = {}
    for name in st:
        where = f"standards.{name}"
        shape = STANDARDS.get(name) if isinstance(name, str) else None
        if shape is None:
            c.no("std_name", where, expected=", ".join(STANDARDS))
            continue
        v = c.string(st, name, where)
        if v is None:
            continue
        if isinstance(shape, re.Pattern):
            ok, expected = bool(v.isascii() and shape.fullmatch(v)), SHAPE_TEXT.get(name, "1.0.0")
        else:
            ok, expected = _is_date(v), "YYYY-MM-DD"
        if not ok:
            c.no("std_value", where, value=_show(v), expected=expected)
        else:
            out[name] = v
    return out


#: how a refusal shows the expected shape of a standard's value
SHAPE_TEXT = {"ssmix2": "1.2 / 1.2i", "icd10": "WHO-2013", "icd10cm": "2023"}


def _tables(
    c: _Check, node: Any, *, door: str | None, country: str | None, synthetic: bool | None
) -> dict[str, tuple[dict[str, Any], list[dict[str, str]]]]:
    tb = c.mapping(node, "tables") or {}
    if isinstance(node, dict) and not node:
        c.no("missing", "tables")
    out: dict[str, tuple[dict[str, Any], list[dict[str, str]]]] = {}
    for name in tb:
        where = f"tables.{_show(name)}"
        if name not in TABLES:
            c.no("table_name", where, expected=", ".join(TABLES))
            continue
        if name in ("diagnosis", "drug") and door is not None and door != "ssmix2":
            c.no("table_door", where)
            continue
        if name == "lab" and country is not None and (country, "laboratory") not in LAB_PROFILES:
            c.no("lab_country", where)
            continue
        t = c.mapping(tb[name], where)
        if t is None:
            continue
        c.keys(t, _TABLE_KEYS, where)
        source = _source(c, t.get("source"), f"{where}.source", synthetic)
        rows = _rows(c, name, t.get("rows"), f"{where}.rows", country)
        used_by = {"diagnosis": ["ssmix2.diagnosis"], "drug": ["ssmix2.drug"],
                   "lab": ["mapping.lab", "ssmix2.lab"] if door == "ssmix2" else ["mapping.lab"]}[name]  # fmt: skip
        key, target = KEY_TARGET[name]
        spec = {"file": f"codes/{name}.csv", "key": key, "target": target, "state": "state", "source": source or "",
                "used_by": used_by}  # fmt: skip
        out[name] = (spec, rows)
    return out


def _source(c: _Check, node: Any, where: str, synthetic: bool | None) -> str | None:
    s = c.mapping(node, where)
    if s is None:
        return None
    c.keys(s, _SOURCE_KEYS, where)
    master = c.choice(s, "master", f"{where}.master", tuple(SOURCE_WORDS), "master")
    if master == "synthetic" and synthetic is False:
        c.no("master_synthetic", f"{where}.master")
    day = c.string(s, "date", f"{where}.date", required=False)
    if day is not None and not _is_date(day):
        c.no("date", f"{where}.date", value=_show(day))
        day = None
    if master is None:
        return None
    return f"{SOURCE_WORDS[master]} {day}" if day else SOURCE_WORDS[master]


def _rows(c: _Check, name: str, node: Any, where: str, country: str | None) -> list[dict[str, str]]:
    if not isinstance(node, list) or not node:
        c.no("rows_empty", where)
        return []
    if len(node) > MAX_ROWS:
        c.no("rows_too_many", where, most=str(MAX_ROWS))
        return []
    out: list[dict[str, str]] = []
    seen: dict[str, int] = {}
    for i, r in enumerate(node):
        at = f"{where}[{i}]"
        if not isinstance(r, dict):
            c.no("missing", at)
            continue
        c.keys(r, _ROW_KEYS[name], at)
        before = len(c.problems)
        code = c.string(r, "code", f"{at}.code")
        if code is not None:
            rx, bad = (_YJ, "yj_shape") if name == "drug" else (_CODE, "code_shape")
            if not (code.isascii() and rx.fullmatch(code)):
                c.no(bad, f"{at}.code", value=_show(code))
            elif fold_key(code) in seen:
                c.no("code_repeat", f"{at}.code", value=code, first=str(seen[fold_key(code)]))
            else:
                seen[fold_key(code)] = i
        state = r.get("state", "verify")
        if state not in ("verified", "verify"):
            c.no("state", f"{at}.state", value=_show(state))
        row = {"diagnosis": _diagnosis, "drug": _drug, "lab": _lab}[name](c, r, at, country)
        if len(c.problems) == before and code is not None and row is not None:
            out.append({KEY_TARGET[name][0]: code, **row, "state": str(state)})
    return out


def _target(c: _Check, r: Mapping[Any, Any], key: str, at: str, system: str) -> str | None:
    v = c.string(r, key, f"{at}.{key}")
    if v is not None and check_code(system, v):
        c.no("target_code", f"{at}.{key}", value=_show(v), system=system)
        return None
    return v


def _text(c: _Check, r: Mapping[Any, Any], key: str, where: str, *, required: bool = True) -> str | None:
    v = c.string(r, key, where, required=required)
    if v is not None and not text_ok(v):
        c.no("text", where, most=str(MAX_TEXT))
        return None
    return v


def _diagnosis(c: _Check, r: Mapping[Any, Any], at: str, country: str | None) -> dict[str, str] | None:
    name = _text(c, r, "name", f"{at}.name")
    icd = _target(c, r, "icd10", at, "icd10")
    return {"name": name or "", "icd10": icd or ""}


def _drug(c: _Check, r: Mapping[Any, Any], at: str, country: str | None) -> dict[str, str] | None:
    name = _text(c, r, "name", f"{at}.name")
    atc = _target(c, r, "atc", at, "atc")
    return {"name": name or "", "atc": atc or ""}


def _lab(c: _Check, r: Mapping[Any, Any], at: str, country: str | None) -> dict[str, str] | None:
    systems = [s for s in ("loinc", "score") if r.get(s) not in (None, "")]
    if len(systems) != 1:
        c.no("system_one", f"{at}.{'/'.join(systems) or 'loinc'}")
        target = None
        system = "loinc"
    else:
        system = systems[0]
        target = _target(c, r, system, at, system)
    display = _text(c, r, "display", f"{at}.display")
    category = c.choice(r, "category", f"{at}.category", CATEGORIES, "category")
    if category is not None and country is not None and (country, category) not in LAB_PROFILES:
        c.no("category", f"{at}.category", value=category, expected=", ".join(
            cat for (ctry, cat) in LAB_PROFILES if ctry == country))  # fmt: skip
    kind = c.choice(r, "kind", f"{at}.kind", KINDS, "kind")
    unit = c.string(r, "unit", f"{at}.unit", required=False)
    if unit is not None and unit not in UNITS:
        c.no("unit", f"{at}.unit", value=_show(unit))
    source_unit = c.string(r, "source_unit", f"{at}.source_unit", required=False)
    if source_unit is not None and source_unit not in SOURCE_UNITS:
        c.no("unit", f"{at}.source_unit", value=_show(source_unit))
    factor = _factor(c, r.get("factor", 1), f"{at}.factor")
    answers = _answers(c, r.get("answers"), f"{at}.answers", kind)
    if not (target and display and category and kind and country) or factor is None or answers is None:
        return None
    return {"system": system, "code": target, "display": display, "ucum": unit or "", "factor": factor,
            "category": category, "value_type": kind, "answers": answers,
            "profile": LAB_PROFILES[(country, category)], "source_unit": source_unit or ""}  # fmt: skip


def _factor(c: _Check, v: Any, where: str) -> str | None:
    """A bounded number: more than 0 and at most :data:`tb_common.labunit.MAX_SCALE`, written plainly."""
    from tb_common.labunit import MAX_SCALE

    s = str(v) if isinstance(v, int | float | str) and not isinstance(v, bool) else ""
    if not _FACTOR.fullmatch(s) or not 0 < float(s) <= MAX_SCALE:
        c.no("factor", where, most=f"{MAX_SCALE:g}")
        return None
    return s


def _answers(c: _Check, node: Any, where: str, kind: str | None) -> str | None:
    """A coded result's answers as the look-up writes them (``POS:LA6576-8|Positive;NEG:...``): each a word, a LOINC
    answer code (``LA`` and its number), and its display. A quantity has none; a coded result needs at least two."""
    if kind != "coded":
        if node not in (None, [], ""):
            c.no("answers", where)
            return None
        return ""
    if not isinstance(node, list) or len(node) < 2:
        c.no("answers", where)
        return None
    parts: list[str] = []
    words: set[str] = set()
    for i, a in enumerate(node):
        at = f"{where}[{i}]"
        if not isinstance(a, dict):
            c.no("missing", at)
            return None
        c.keys(a, frozenset({"word", "code", "display"}), at)
        word, code = c.string(a, "word", f"{at}.word"), c.string(a, "code", f"{at}.code")
        disp = _text(c, a, "display", f"{at}.display")
        if word is not None and (not _WORD.fullmatch(word) or word in words):
            c.no("answer_word", f"{at}.word", value=_show(word))
            word = None
        if code is not None and not _LA.fullmatch(code):
            c.no("answer_code", f"{at}.code", value=_show(code))
            code = None
        if disp is not None and any(ch in disp for ch in ";|:"):
            c.no("text", f"{at}.display", most=str(MAX_TEXT))
            disp = None
        if not (word and code and disp):
            return None
        words.add(word)
        parts.append(f"{word}:{code}|{disp}")
    return ";".join(parts)


# ------------------------------------------------------------------ writing the folder
def _csv(name: str, rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(COLUMNS[name]), lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in COLUMNS[name]})
    return buf.getvalue()


def manifest_text(form: Form) -> str:
    head = (
        "# Written by `python -m adapter.site_profile fill` from the site questionnaire (10B-19, D-1249).\n"
        "# Not loaded: check it, then load it by name (python -m adapter.site_profile load --by <name>).\n"
    )
    return head + yaml.safe_dump(form.manifest, sort_keys=False, allow_unicode=True, default_flow_style=None)


def write(form: Form, out: Path) -> Path:
    """Write the profile folder at ``out`` (which must not exist). The folder is built beside it, read back by the
    real loader, and only then renamed into place: the form never leaves a folder the loader refuses, nor half a
    folder. Raises :class:`tb_common.site_profile.ProfileError` when the loader refuses (a fault of the form)."""
    out = Path(out)
    if out.exists() or out.is_symlink():
        raise FileExistsError(str(out))
    out.parent.mkdir(parents=True, exist_ok=True)
    build = Path(tempfile.mkdtemp(prefix=".profile-form-", dir=out.parent))
    try:
        (build / "codes").mkdir()
        (build / MANIFEST).write_text(manifest_text(form), encoding="utf-8")
        for name, rows in form.tables.items():
            (build / "codes" / f"{name}.csv").write_text(_csv(name, rows), encoding="utf-8")
        load(build)  # the real loader: every check of D-1233
        os.rename(build, out)
    except BaseException:
        shutil.rmtree(build, ignore_errors=True)
        raise
    return out


# ------------------------------------------------------------------ the template
def template(lang: str) -> str:
    """The answers file to fill, its questions as comments in ``lang`` (the console's catalogue), every answer
    empty. Filled in, it is what ``fill --answers`` reads."""

    def say(key: str, **v: object) -> Iterator[str]:
        for line in text(lang, f"tpl.{key}", **v).splitlines():
            yield f"# {line}".rstrip()

    lines: list[str] = [*say("head")]
    lines += [f"format: {ANSWERS_FORMAT}", "", *say("profile"), "profile:"]
    lines += ["  id:", "  site_id:", f"  country:          # {', '.join(COUNTRIES)}", '  version: "1.0.0"',
              "  synthetic: false", "", *say("door"), f"door:               # {', '.join(DOORS)}", "",
              *say("data_types"), "data_types: []", "", *say("standards", names=", ".join(STANDARDS)),
              "standards: {}", "", *say("tables"), "tables:"]  # fmt: skip
    for name in TABLES:
        masters = ", ".join(SOURCE_WORDS)
        lines += [
            *(f"  {x}" for x in say(name)),
            f"  {name}:",
            f"    source: {{master: }}   # {masters}",
            "    rows: []",
        ]
    lines += ["", *say("not_asked", questions=", ".join(q.number for q in QUESTIONS if not q.fills))]
    return "\n".join(lines) + "\n"
