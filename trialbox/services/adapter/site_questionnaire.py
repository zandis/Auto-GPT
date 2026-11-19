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

**Every answer is text.** The answers file is read by a YAML reader that builds no number, no boolean and no date
(:func:`read_answers`): ``010``, ``0x10``, ``1:30`` and ``1_0`` are the text the steward wrote, never 8, 16, 90 or
10. Each typed answer is then accepted by one pattern of its own (a plain decimal factor, a version, an ISO date,
``true`` or ``false``), or refused.

**Allow-list.** :func:`parse` accepts an answer only when it is positively recognised: a key of the form, a name from
a list (a country, a door, a data type, a standard, a master, a category, a kind, a unit the product knows), a value
of a fixed shape (a profile name, a version, a date, a site code, a YJ code, a standard code checked as the loader
checks it, a LOINC answer code), a bounded plain decimal. Answers must also go together (:data:`GOES_WITH`: country,
door, standards and each table's master). Anything else is a :class:`Problem` whose ``code`` is a key of the
console's text catalogue (``profileform.err.<code>``, en, ja and zh-TW) that says what is expected. A refusal names
the answer by its key and line and gives its length; it never repeats what was written there, so a patient's name
typed into the wrong field is not shown back.

**No free text unescaped; no path, file name or command from an answer.** The few free-text cells (a code's name, a
lab test's display, an answer's display) are printable text only (no control or format character, no leading ``=``,
``+``, ``-`` or ``@``, nothing like a URL with a password), written by the csv module, so they are quoted where needed
and never reach the manifest. The tables are ``codes/diagnosis.csv``, ``codes/drug.csv`` and ``codes/lab.csv``, and
a table's ``source`` is composed of the form's own words, a master from the list and a checked date.

**Units.** A lab row's factor turns a result in its ``source_unit`` into its ``unit``. When the two are one unit (or
no source unit is given) the factor is 1. When they differ a factor must be given; where ``tb_common.labunit`` knows
the conversion the factor must agree with it; where it does not, the row is stored as ``verify`` whatever the answer
said, and the summary says so.

**An unchecked mapping stays unchecked.** A row is ``verified`` only when its answer says exactly ``verified``; a row
with no state is ``verify``, as D-1233 stores a row nobody checked. Whether such a row may exclude a patient is
the owner's open question (DATA section 15); this form does not decide it. Every default the form applies is said
in the template and in the summary the command prints (:meth:`Form.summary`).
"""

from __future__ import annotations

import contextlib
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
from tb_common import labunit
from tb_common.codekey import fold_key
from tb_common.labunit import MAX_SCALE, UCUM
from tb_common.site_profile import FORMAT, MANIFEST, check_code, load

ANSWERS_FORMAT = "tb-site-questionnaire/1"
LANGS = ("en", "ja", "zh-TW")
MAX_BYTES = 5 * 1024 * 1024  # an answers file larger than any hospital's three masters: a wrong file
MAX_ROWS = 50_000  # rows of one table
MAX_TEXT = 120  # characters of a name or a display
DIR_MODE = 0o755  # the folder the form writes: readable by the box's user, whoever ran the command
FILE_MODE = 0o644

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

#: the countries the settings know. The form makes a profile for jp and tw only: its tables are the SS-MIX2 reader's
#: (Japan) and the lab look-up, whose results carry Japan's or Taiwan's FHIR profile
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
_NUM = r"(0|[1-9][0-9]{0,3})"  # a plain whole number: no sign, no leading zero, no _, no other base
_SEMVER = re.compile(rf"{_NUM}\.{_NUM}\.{_NUM}")
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
#: how a refusal shows the expected shape of a standard's value
SHAPE_TEXT = {"ssmix2": "1.2 / 1.2i", "icd10": "WHO-2013", "icd10cm": "2023"}
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
#: what goes together, by country: the doors, the standards, and each table's masters. An answer outside its
#: country's row is refused with both answers named. (Japan's own layer, 10C-25, is not on master; when it is, this
#: table should be read from it rather than kept here: D-1249.)
GOES_WITH: dict[str, dict[str, Any]] = {
    "jp": {
        "doors": ("ssmix2", "csv"),
        "standards": (
            "ssmix2",
            "jp_core",
            "icd10",
            "medis_byomei",
            "hot",
            "jlac10",
            "jlac11",
            "jj1017",
            "yj",
            "receipt_masters",
            "jami_usage",
        ),
        "masters": {
            "diagnosis": ("synthetic", "hospital", "medis_byomei"),
            "drug": ("synthetic", "hospital", "yj", "hot"),
            "lab": ("synthetic", "hospital", "jlac10", "jlac11"),
        },
    },
    "tw": {
        "doors": ("csv", "cgrd_sql"),
        "standards": ("tw_core", "icd10cm"),
        "masters": {"lab": ("synthetic", "hospital")},
    },
}
#: a standard that only one door writes
STANDARD_DOOR = {"ssmix2": "ssmix2"}
#: the tables only the SS-MIX2 reader reads
SSMIX2_TABLES = ("diagnosis", "drug")
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
#: a factor: a plain decimal, no sign, no exponent, no leading zero, no other base, no _ or :
FACTOR = re.compile(rf"{_NUM}(\.[0-9]{{1,6}})?")
_URL_SECRET = re.compile(r"[a-z][a-z0-9+.-]*://[^\s/@]*:[^\s/@]*@", re.IGNORECASE)
_SAFE_KEY = re.compile(r"[A-Za-z0-9_-]{1,40}")
BOOLEANS = {"true": True, "false": False}
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
_LOINC = "http://loinc.org"
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
CODES = ("unreadable", "alias", "doubled_key", "format", "unknown_key", "missing", "not_text", "id", "site_id",
         "country", "country_none", "version", "synthetic", "synthetic_id", "door", "data_type", "std_name",
         "std_value", "apart", "table_name", "table_door", "master", "master_synthetic", "date", "rows_empty",
         "rows_too_many", "code_shape", "code_repeat", "yj_shape", "target_code", "text", "text_url", "state",
         "system_one", "unit", "unit_missing", "unit_coded", "factor", "factor_needed", "factor_same", "factor_wrong",
         "category", "kind", "answers", "answer_word", "answer_code", "out_exists", "out_live", "out_parent",
         "write_failed", "interrupted", "loader")  # fmt: skip


@dataclass(frozen=True)
class Problem:
    """One refused answer: ``code`` is ``profileform.err.<code>``; ``where`` names the answer (``profile.id``,
    ``tables.lab.rows[3].unit``); ``line`` is its line in the answers file (0: not known); ``values`` fill the
    message. No value ever holds what the answer said, only its length or a word from the form's own lists."""

    code: str
    where: str
    values: Mapping[str, str] = field(default_factory=dict)
    line: int = 0


@dataclass
class Form:
    """The accepted answers: the manifest and each table's rows, ready to be written, and what the form decided for
    an answer left out (``defaults``: table -> what -> the rows it applied to)."""

    manifest: dict[str, Any]
    tables: dict[str, list[dict[str, str]]]
    defaults: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    def rows(self) -> int:
        return sum(len(r) for r in self.tables.values())

    def summary(self, lang: str) -> list[str]:
        """What will be written and every default the form applied, in ``lang``: the lines the command prints."""
        m = self.manifest
        out = [text(lang, "sum.profile", id=m["id"], version=m["version"], synthetic=str(m["synthetic"]).lower(),
                    country=m["country"], door=m["door"])]  # fmt: skip
        for name, rows in self.tables.items():
            out.append(text(lang, "sum.table", table=name, rows=len(rows)))
            for what, where in self.defaults.get(name, {}).items():
                if where:
                    out.append("  " + text(lang, f"sum.{what}", count=len(where), rows=_few(where)))
        return out


def _few(where: list[str]) -> str:
    return ", ".join(where[:5]) + (f", … (+{len(where) - 5})" if len(where) > 5 else "")


def message(p: Problem, lang: str) -> str:
    """The refusal in ``lang`` from the console's catalogue (the one catalogue of the product's words): the answer's
    key, its line and its length, then what is expected."""
    from console.i18n import translate

    lang = lang if lang in LANGS else "en"
    head = p.where
    if p.line and "length" in p.values:
        head = translate(lang, "profileform.at_line_length", where=p.where, line=p.line, length=p.values["length"])
    elif p.line:
        head = translate(lang, "profileform.at_line", where=p.where, line=p.line)
    elif "length" in p.values:
        head = translate(lang, "profileform.at_length", where=p.where, length=p.values["length"])
    values = {k: v for k, v in p.values.items() if k != "length"}
    return translate(lang, "profileform.colon", where=head, said=translate(lang, f"profileform.err.{p.code}", **values))


def text(lang: str, key: str, **values: object) -> str:
    from console.i18n import translate

    return translate(lang if lang in LANGS else "en", f"profileform.{key}", **values)


# ------------------------------------------------------------------ reading the answers file
_Loader: type[Any] = getattr(yaml, "CBaseLoader", yaml.BaseLoader)


class _Unreadable(Exception):
    def __init__(self, code: str, where: str, line: int) -> None:
        super().__init__(code)
        self.problem = Problem(code, where, {}, line)


def _key(k: str) -> str:
    """A key as a refusal shows it: the key itself when it is a plain word, else only its length."""
    return k if _SAFE_KEY.fullmatch(k) else f"<{len(k)}>"


def read_answers(raw: str | bytes) -> tuple[Any, dict[str, int]]:
    """The answers file as plain text values (dicts, lists and str: never a number, a boolean or a date), parsed once,
    with the line of every answer by its ``where``. Refused: an alias (a document that grows as it is read) and a key
    written twice in one mapping (YAML keeps the last silently)."""
    try:
        node = yaml.compose(raw, Loader=_Loader)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        raise _Unreadable("unreadable", "answers", mark.line + 1 if mark else 0) from None
    except (yaml.YAMLError, UnicodeDecodeError, RecursionError):
        raise _Unreadable("unreadable", "answers", 0) from None
    lines: dict[str, int] = {}
    seen: set[int] = set()

    def build(n: Any, where: str) -> Any:
        line = n.start_mark.line + 1
        if id(n) in seen:  # the same node twice: an alias
            raise _Unreadable("alias", where or "answers", line)
        seen.add(id(n))
        lines[where] = line
        if isinstance(n, yaml.MappingNode):
            out: dict[str, Any] = {}
            for kn, vn in n.value:
                k = kn.value if isinstance(kn, yaml.ScalarNode) else f"<{type(kn).__name__}>"
                at = f"{where}.{_key(k)}" if where else _key(k)
                if k in out:
                    raise _Unreadable("doubled_key", at, kn.start_mark.line + 1)
                lines[at] = kn.start_mark.line + 1
                out[k] = build(vn, at)
            return out
        if isinstance(n, yaml.SequenceNode):
            return [build(v, f"{where}[{i}]") for i, v in enumerate(n.value)]
        return str(n.value)

    return (build(node, "") if node is not None else None), lines


def _line_of(where: str, lines: Mapping[str, int]) -> int:
    while where:
        if where in lines:
            return lines[where]
        cut = max(where.rfind("."), where.rfind("["))
        where = where[:cut] if cut > 0 else ""
    return 0


def parse_text(raw: str | bytes) -> Form | list[Problem]:
    """The answers file's text, read strictly as text, then :func:`parse`; every refusal carries its line."""
    if len(raw) > MAX_BYTES:
        return [Problem("unreadable", "answers")]
    try:
        doc, lines = read_answers(raw)
    except _Unreadable as exc:
        return [exc.problem]
    if not isinstance(doc, dict):
        return [Problem("unreadable", "answers", {}, 1)]
    got = parse(doc)
    if isinstance(got, Form):
        return got
    return [Problem(p.code, p.where, p.values, _line_of(p.where, lines)) for p in got]


class _Check:
    def __init__(self) -> None:
        self.problems: list[Problem] = []

    def no(self, code: str, where: str, value: object = None, **values: str) -> None:
        """Refuse the answer at ``where``. ``value`` is what it said: only its length is kept."""
        if isinstance(value, str):
            values["length"] = str(len(value))
        self.problems.append(Problem(code, where, values))

    def keys(self, node: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
        for k in node:
            if k not in allowed:
                at = f"{where}.{_key(k)}" if where else _key(k)
                self.no("unknown_key", at, expected=", ".join(sorted(allowed)))

    def mapping(self, node: Any, where: str) -> dict[str, Any] | None:
        if not isinstance(node, dict) or not node:
            self.no("missing", where)
            return None
        return node

    def string(self, node: Mapping[str, Any], key: str, where: str, *, required: bool = True) -> str | None:
        """The answer's text. Absent: None (refused when required). Present but empty, or a list or a mapping:
        refused, whether required or not; an empty answer is not taken for a left-out one."""
        if key not in node:
            if required:
                self.no("missing", where)
            return None
        v = node[key]
        if not isinstance(v, str):
            self.no("not_text", where)
            return None
        if v == "":
            self.no("missing", where)
            return None
        return v

    def shaped(self, node: Mapping[str, Any], key: str, where: str, rx: re.Pattern[str], code: str) -> str | None:
        v = self.string(node, key, where)
        if v is not None and not (v.isascii() and rx.fullmatch(v)):
            self.no(code, where, v)
            return None
        return v

    def choice(self, node: Mapping[str, Any], key: str, where: str, allowed: tuple[str, ...], code: str) -> str | None:
        v = self.string(node, key, where)
        if v is not None and v not in allowed:
            self.no(code, where, v, expected=", ".join(allowed))
            return None
        return v


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


def parse(doc: Mapping[str, Any]) -> Form | list[Problem]:
    """The answers (every value text, as :func:`read_answers` gives them), every one checked by allow-list: a
    :class:`Form`, or every :class:`Problem` found."""
    c = _Check()
    c.keys(doc, _TOP, "")
    if doc.get("format") != ANSWERS_FORMAT:
        c.no("format", "format", expected=ANSWERS_FORMAT)
    prof = c.mapping(doc.get("profile"), "profile") or {}
    c.keys(prof, _PROFILE, "profile")
    pid = c.shaped(prof, "id", "profile.id", _ID, "id")
    site = c.shaped(prof, "site_id", "profile.site_id", _SITE, "site_id")
    country = c.choice(prof, "country", "profile.country", COUNTRIES, "country")
    if country is not None and country not in GOES_WITH:
        c.no("country_none", "profile.country", name=country, expected=", ".join(GOES_WITH))
        country = None
    version = c.shaped(prof, "version", "profile.version", _SEMVER, "version")
    said = c.string(prof, "synthetic", "profile.synthetic")
    synthetic = BOOLEANS.get(said) if said is not None else None
    if said is not None and synthetic is None:
        c.no("synthetic", "profile.synthetic", said)
    elif synthetic is not None and pid is not None and pid.startswith("synthetic-") != synthetic:
        c.no("synthetic_id", "profile.synthetic")
    door = c.choice(doc, "door", "door", DOORS, "door")
    if door is not None and country is not None and door not in GOES_WITH[country]["doors"]:
        c.no("apart", "door", name=door, other="profile.country", other_value=country)
        door = None
    types = _data_types(c, doc.get("data_types"), door)
    standards = _standards(c, doc.get("standards"), country, door)
    tables, defaults = _tables(c, doc.get("tables"), door=door, country=country, synthetic=synthetic)
    if c.problems:
        return c.problems
    assert pid and site and country and version and door and synthetic is not None  # checked above
    manifest: dict[str, Any] = {
        "format": FORMAT, "id": pid, "site_id": site, "country": country, "version": version,
        "synthetic": synthetic, "door": door, "standards": standards, "data_types": types,
        "tables": {name: spec for name, (spec, _) in tables.items()},
    }  # fmt: skip
    return Form(manifest, {name: rows for name, (_, rows) in tables.items()}, defaults)


def _data_types(c: _Check, node: Any, door: str | None) -> list[str]:
    if not isinstance(node, list) or not node:
        c.no("missing", "data_types")
        return []
    allowed = (*SSMIX2_TYPES, *OTHER_TYPES) if door == "ssmix2" else TABLE_TYPES
    out: list[str] = []
    for i, v in enumerate(node):
        if not isinstance(v, str) or v not in allowed or v in out:
            c.no("data_type", f"data_types[{i}]", v, expected=", ".join(allowed))
        else:
            out.append(v)
    return out


def _standards(c: _Check, node: Any, country: str | None, door: str | None) -> dict[str, str]:
    st = c.mapping(node, "standards") or {}
    out: dict[str, str] = {}
    for name in st:
        where = f"standards.{_key(name)}"
        shape = STANDARDS.get(name)
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
            c.no("std_value", where, v, expected=expected)
        elif country is not None and name not in GOES_WITH[country]["standards"]:
            c.no("apart", where, name=name, other="profile.country", other_value=country)
        elif door is not None and STANDARD_DOOR.get(name, door) != door:
            c.no("apart", where, name=name, other="door", other_value=door)
        else:
            out[name] = v
    return out


def _tables(
    c: _Check, node: Any, *, door: str | None, country: str | None, synthetic: bool | None
) -> tuple[dict[str, tuple[dict[str, Any], list[dict[str, str]]]], dict[str, dict[str, list[str]]]]:
    tb = c.mapping(node, "tables") or {}
    out: dict[str, tuple[dict[str, Any], list[dict[str, str]]]] = {}
    defaults: dict[str, dict[str, list[str]]] = {}
    for name in tb:
        where = f"tables.{_key(name)}"
        if name not in TABLES:
            c.no("table_name", where, expected=", ".join(TABLES))
            continue
        if name in SSMIX2_TABLES and door is not None and door != "ssmix2":
            c.no("table_door", where, other_value=door)
            continue
        t = c.mapping(tb[name], where)
        if t is None:
            continue
        c.keys(t, _TABLE_KEYS, where)
        source = _source(c, t.get("source"), f"{where}.source", name, synthetic, country)
        said = defaults.setdefault(name, {"state_default": [], "factor_same": [], "factor_checked": [],
                                          "forced_verify": [], "no_source_unit": []})  # fmt: skip
        rows = _rows(c, name, t.get("rows"), f"{where}.rows", country, said)
        used_by = {"diagnosis": ["ssmix2.diagnosis"], "drug": ["ssmix2.drug"],
                   "lab": ["mapping.lab", "ssmix2.lab"] if door == "ssmix2" else ["mapping.lab"]}[name]  # fmt: skip
        key, target = KEY_TARGET[name]
        spec = {"file": f"codes/{name}.csv", "key": key, "target": target, "state": "state", "source": source or "",
                "used_by": used_by}  # fmt: skip
        out[name] = (spec, rows)
    return out, defaults


def _source(c: _Check, node: Any, where: str, table: str, synthetic: bool | None, country: str | None) -> str | None:
    s = c.mapping(node, where)
    if s is None:
        return None
    c.keys(s, _SOURCE_KEYS, where)
    master = c.choice(s, "master", f"{where}.master", tuple(SOURCE_WORDS), "master")
    if master is not None and country is not None and master not in GOES_WITH[country]["masters"].get(table, ()):
        c.no("apart", f"{where}.master", name=master, other="profile.country", other_value=country)
        master = None
    if master == "synthetic" and synthetic is False:
        c.no("master_synthetic", f"{where}.master")
    day = c.string(s, "date", f"{where}.date", required=False)
    if day is not None and not _is_date(day):
        c.no("date", f"{where}.date", day)
        day = None
    if master is None:
        return None
    return f"{SOURCE_WORDS[master]} {day}" if day else SOURCE_WORDS[master]


def _rows(
    c: _Check, name: str, node: Any, where: str, country: str | None, said: dict[str, list[str]]
) -> list[dict[str, str]]:
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
                c.no(bad, f"{at}.code", code)
            elif fold_key(code) in seen:
                c.no("code_repeat", f"{at}.code", code, first=str(seen[fold_key(code)]))
            else:
                seen[fold_key(code)] = i
        state: str | None = "verify"
        if "state" not in r:
            said["state_default"].append(at)
        elif r["state"] not in ("verified", "verify"):  # an empty state too: left out is verify, empty is refused
            c.no("state", f"{at}.state", r["state"])
            state = None
        else:
            state = r["state"]
        notes: dict[str, bool] = {}
        row = {"diagnosis": _diagnosis, "drug": _drug, "lab": _lab}[name](c, r, at, country, notes)
        if len(c.problems) == before and code is not None and row is not None and state is not None:
            if notes.get("forced_verify"):
                state = "verify"
            for what, on in notes.items():
                if on:
                    said[what].append(at)
            out.append({KEY_TARGET[name][0]: code, **row, "state": state})
    return out


def _target(c: _Check, r: Mapping[str, Any], key: str, at: str, system: str) -> str | None:
    v = c.string(r, key, f"{at}.{key}")
    if v is not None and check_code(system, v):
        c.no("target_code", f"{at}.{key}", v, system=system)
        return None
    return v


def _text(c: _Check, r: Mapping[str, Any], key: str, where: str, *, required: bool = True) -> str | None:
    v = c.string(r, key, where, required=required)
    if v is not None and not text_ok(v):
        c.no("text", where, v, most=str(MAX_TEXT))
        return None
    if v is not None and _URL_SECRET.search(v):
        c.no("text_url", where, v)
        return None
    return v


def _diagnosis(
    c: _Check, r: Mapping[str, Any], at: str, country: str | None, notes: dict[str, bool]
) -> dict[str, str] | None:
    name = _text(c, r, "name", f"{at}.name")
    icd = _target(c, r, "icd10", at, "icd10")
    return {"name": name or "", "icd10": icd or ""}


def _drug(
    c: _Check, r: Mapping[str, Any], at: str, country: str | None, notes: dict[str, bool]
) -> dict[str, str] | None:
    name = _text(c, r, "name", f"{at}.name")
    atc = _target(c, r, "atc", at, "atc")
    return {"name": name or "", "atc": atc or ""}


def _lab(
    c: _Check, r: Mapping[str, Any], at: str, country: str | None, notes: dict[str, bool]
) -> dict[str, str] | None:
    systems = [s for s in ("loinc", "score") if s in r]
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
        c.no("category", f"{at}.category", category, expected=", ".join(
            cat for (ctry, cat) in LAB_PROFILES if ctry == country))  # fmt: skip
        category = None
    kind = c.choice(r, "kind", f"{at}.kind", KINDS, "kind")
    units = _units(c, r, at, kind, system, target, notes)
    answers = _answers(c, r.get("answers"), f"{at}.answers", kind, "answers" in r)
    if not (target and display and category and kind and country) or units is None or answers is None:
        return None
    unit, factor, source_unit = units
    return {"system": system, "code": target, "display": display, "ucum": unit, "factor": factor,
            "category": category, "value_type": kind, "answers": answers,
            "profile": LAB_PROFILES[(country, category)], "source_unit": source_unit}  # fmt: skip


def _same_unit(a: str, b: str) -> bool:
    return a == b or b in UCUM.get(a, ()) or labunit.key(a) == labunit.key(b)


def expected_factor(source_unit: str, unit: str, system: str, code: str | None) -> float | None:
    """The factor that turns a result in ``source_unit`` into ``unit``, as the product's engines convert it
    (``tb_common.labunit.conversion``), or None when the product has no tested factor for the pair."""
    conv = labunit.conversion(labunit.key(source_unit), labunit.key(unit), _LOINC if system == "loinc" else None, code)
    if conv is None:
        return None
    op, k = conv
    return k if op == "*" else 1 / k


def _units(
    c: _Check, r: Mapping[str, Any], at: str, kind: str | None, system: str, target: str | None,
    notes: dict[str, bool],
) -> tuple[str, str, str] | None:  # fmt: skip
    """(unit, factor, source_unit) as the row is written, or None when refused. A coded result has no unit and a
    factor of 1. A quantity needs its unit; its factor is 1 when the source unit is the same unit or not given;
    otherwise the factor must be given and, where the product knows the conversion, agree with it. Where it does
    not know it, the row is ``verify`` whatever the answer said."""
    before = len(c.problems)
    unit = c.string(r, "unit", f"{at}.unit", required=False)
    if unit is not None and unit not in UNITS:
        c.no("unit", f"{at}.unit", unit)
        unit = None
    source_unit = c.string(r, "source_unit", f"{at}.source_unit", required=False)
    if source_unit is not None and source_unit not in SOURCE_UNITS:
        c.no("unit", f"{at}.source_unit", source_unit)
        source_unit = None
    factor = c.string(r, "factor", f"{at}.factor", required=False)
    if factor is not None and not (FACTOR.fullmatch(factor) and 0 < float(factor) <= MAX_SCALE):
        c.no("factor", f"{at}.factor", factor, most=f"{MAX_SCALE:g}")
        factor = None
    if len(c.problems) > before or kind is None:
        return None
    if kind == "coded":
        for key in ("unit", "source_unit"):
            if key in r:
                c.no("unit_coded", f"{at}.{key}")
        if factor is not None and float(factor) != 1:
            c.no("unit_coded", f"{at}.factor")
        return None if len(c.problems) > before else ("", "1", "")
    if unit is None:
        c.no("unit_missing", f"{at}.unit")
        return None
    if source_unit is None or _same_unit(unit, source_unit):
        if factor is not None and float(factor) != 1:
            c.no("factor_same", f"{at}.factor", factor)
            return None
        notes["factor_same"] = True
        notes["no_source_unit"] = source_unit is None
        return unit, "1", source_unit or ""
    if factor is None:
        c.no("factor_needed", f"{at}.factor", source_unit=source_unit, unit=unit)
        return None
    want = expected_factor(source_unit, unit, system, target)
    if want is None:
        notes["forced_verify"] = True
    elif abs(float(factor) - want) > 1e-9 * max(1.0, want):
        c.no("factor_wrong", f"{at}.factor", factor, source_unit=source_unit, unit=unit, expected=f"{want:.10g}")
        return None
    else:
        notes["factor_checked"] = True
    return unit, factor, source_unit


def _answers(c: _Check, node: Any, where: str, kind: str | None, given: bool) -> str | None:
    """A coded result's answers as the look-up writes them (``POS:LA6576-8|Positive;NEG:...``): each a word, a LOINC
    answer code (``LA`` and its number), and its display. A quantity has none; a coded result needs at least two.
    Every refused answer is reported, not only the first."""
    if kind != "coded":
        if given and node not in ([], ""):
            c.no("answers", where)
            return None
        return ""
    if not isinstance(node, list) or len(node) < 2:
        c.no("answers", where)
        return None
    parts: list[str] = []
    words: set[str] = set()
    before = len(c.problems)
    for i, a in enumerate(node):
        at = f"{where}[{i}]"
        if not isinstance(a, dict):
            c.no("missing", at)
            continue
        c.keys(a, frozenset({"word", "code", "display"}), at)
        word, code = c.string(a, "word", f"{at}.word"), c.string(a, "code", f"{at}.code")
        disp = _text(c, a, "display", f"{at}.display")
        if word is not None and (not _WORD.fullmatch(word) or word in words):
            c.no("answer_word", f"{at}.word", word)
            word = None
        if code is not None and not _LA.fullmatch(code):
            c.no("answer_code", f"{at}.code", code)
            code = None
        if disp is not None and any(ch in disp for ch in ";|:"):
            c.no("text", f"{at}.display", disp, most=str(MAX_TEXT))
            disp = None
        if word:
            words.add(word)
        parts.append(f"{word}:{code}|{disp}")
    return None if len(c.problems) > before else ";".join(parts)


# ------------------------------------------------------------------ writing the folder
def _csv(name: str, rows: list[dict[str, str]]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(COLUMNS[name]), lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in COLUMNS[name]})
    return buf.getvalue().encode("utf-8")


def manifest_text(form: Form) -> str:
    head = (
        "# Written by `python -m adapter.site_profile fill` from the site questionnaire (10B-19, D-1249).\n"
        "# Not loaded: check it, then load it by name (python -m adapter.site_profile load --by <name>).\n"
    )
    return head + yaml.safe_dump(form.manifest, sort_keys=False, allow_unicode=True, default_flow_style=None)


def _files(form: Form) -> dict[str, bytes]:
    files = {MANIFEST: manifest_text(form).encode("utf-8")}
    files.update({f"codes/{name}.csv": _csv(name, rows) for name, rows in form.tables.items()})
    return files


def _new_file(path: Path, data: bytes) -> None:
    """A new file, never one that is there (``x``), readable by the box's user."""
    with open(path, "xb") as fh:
        fh.write(data)
    os.chmod(path, FILE_MODE)


def write(form: Form, out: Path) -> Path:
    """Write the profile folder at ``out``, which must not exist; its parent folders are made when missing. The
    files are built beside it and read back by the real loader; only then is ``out`` made (refused if it appeared
    meanwhile: nothing that is there is ever replaced) and the checked files written into it, folders
    :data:`DIR_MODE`, files :data:`FILE_MODE`. On any failure nothing of it is left. Raises
    :class:`tb_common.site_profile.ProfileError` when the loader refuses (a fault of the form),
    :class:`FileExistsError` when ``out`` is there, and :class:`OSError` when the disk refuses."""
    out = Path(out)
    if out.exists() or out.is_symlink():
        raise FileExistsError(str(out))
    out.parent.mkdir(parents=True, exist_ok=True)
    files = _files(form)
    build = Path(tempfile.mkdtemp(prefix=".profile-form-", dir=out.parent))
    made: list[Path] = []
    try:
        (build / "codes").mkdir()
        for rel, data in files.items():
            (build / rel).write_bytes(data)
        load(build)  # the real loader: every check of D-1233
        os.mkdir(out, DIR_MODE)  # FileExistsError when it appeared since the check
        made.append(out)
        os.chmod(out, DIR_MODE)
        os.mkdir(out / "codes", DIR_MODE)
        made.append(out / "codes")
        os.chmod(out / "codes", DIR_MODE)
        for rel, data in files.items():
            _new_file(out / rel, data)
            made.append(out / rel)
    except BaseException:
        for p in reversed(made):  # only what this call made; a folder someone else put there is left alone
            with contextlib.suppress(OSError):
                p.rmdir() if p.is_dir() else p.unlink()
        raise
    finally:
        shutil.rmtree(build, ignore_errors=True)
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
    lines += ["  id:", "  site_id:", f"  country:          # {', '.join(GOES_WITH)}", "  version:          # 1.0.0",
              "  synthetic:        # true, false", "", *say("door"), f"door:               # {', '.join(DOORS)}", "",
              *say("data_types"), "data_types: []", "", *say("standards", names=", ".join(STANDARDS)),
              "standards: {}", "", *say("tables"), *say("defaults"), "tables:"]  # fmt: skip
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
