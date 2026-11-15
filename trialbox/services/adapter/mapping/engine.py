"""Declarative source-row → FHIR R4 mapping driven by ``mapping/<profile>/<site>.yaml`` (SPEC §4.6).

A site is onboarded by writing a mapping YAML (no code changes). Each resource entry maps one source table to one
FHIR resource type; element paths use dotted FHIR paths with list indices (``code.coding[1].code``).

Value expressions (one key per element)::

    const: <value>                                  literal
    column: <col>   [type, map, default, factor, add_minutes]
    template: "text {col} {sys.loinc} {site_id}"     string interpolation
    pid: <col>                                      pseudonymous patient id (HMAC of the column, D-09)
    hid: <col>                                      pseudonymous resource id: HMAC("<Type>|<value>")
    ref: {type: <T>, pid|hid|column: <col>}          reference "T/<id>"
    lookup: {name: <lookup>, key: <col>, field: <f>} value from a lookup CSV
    base64: <col>                                   base64 of the UTF-8 column text
    builder: <name> [args]                          typed helper, merged at the element path

``type`` is one of ``str|int|decimal|date|datetime|instant|bool``. Datetimes are interpreted in the mapping's
``tz`` and emitted with offset. ``when`` (element) / ``where`` (resource) filter on columns or lookups
(``equals``, ``in``, ``not_in``, ``not_empty``, ``numeric``, and the ISO date bounds ``date_before`` / ``date_from``);
``{fhir_profiles: tw-core}`` holds only when the mapping's profile set is that one (T-619a: TW Core slices).

Site mappings (onboarding kit, D-84) usually ``extends`` a shared profile mapping (e.g. ``tw_core/demo_his.yaml``)
and only declare their ``tables``: each table's ``rename`` (local column → canonical column) and ``values``
(canonical column → {local code: canonical code}) are applied to every source row before the shared resource
definitions run; ``key`` / ``delta`` / ``identity`` name canonical columns. Resources of tables the site does not
declare are dropped; lookups resolve relative to the file that declares them.

A mapping can also re-profile the shared resources (D-137: the Japan mapping puts JP Core profiles on the TW Core
resource set): ``profiles`` maps a base profile URL to this mapping's profile (``""`` drops the claim), and
``overlay`` adds or replaces elements of the base resources of one type and table
(``- {type: Observation, table: lab, elements: {code.text: {column: item_name}}}``).

**Row provenance (T-106b, DATA-010).** A mapper given the night it ingests (``ingest_time``, which the nightly
pipeline sets) stamps every resource it makes from a source row: ``meta.source`` is ``<site>/<table>#<row hash>``
(the hash is an HMAC of the canonical source row under the site key, so it names the row without revealing it),
``meta.lastUpdated`` the night, and a ``meta.tag`` of ``urn:trialbox:mapping-version`` the mapping's version
(:attr:`Mapping.version`: its name and a hash of its files). The lake carries the four as columns.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from tb_common import dates as tb_dates
from tb_common import labvalue
from tb_common.crypto import pid_for_mrn

Row = dict[str, Any]
Resource = dict[str, Any]

DATA_ABSENT = "http://terminology.hl7.org/CodeSystem/data-absent-reason"
_PATH_RE = re.compile(r"([A-Za-z_$][A-Za-z0-9_$]*)(?:\[(\d+)\])?")
_TOKEN_RE = re.compile(r"\{([^{}]+)\}")
# T-616 (STD-015): a source date-time that states its own offset (``+09:00``, ``+0900``, ``Z``) after a time of day
_OFFSET_RE = re.compile(r"\d[T ]\d{2}:?\d{2}(?::?\d{2}(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}:?\d{2})$", re.IGNORECASE)
MAPPING_VERSION = "urn:trialbox:mapping-version"  # the meta.tag system of the mapping version (lake.flatten)


# the earliest year a feed date may carry. Reason, not a tuning value: no person alive was born before it (the
# longest verified human life is 122 years) and no hospital system holds an older record of a living patient; a
# smaller year is a date of another calendar read as western (ROC year 115, an era year), which must be refused.
EARLIEST_YEAR = 1850
# the latest year a feed date may carry is this many years after today's. Reason, not a tuning value: what a feed
# dates ahead is a booked visit or the end of a prescription, both within a study's length; a year further on is a
# two-digit-year value read as western (`640712081500` as the year 6407) or a placeholder (`9999-12-31`), and
# neither is a fact about a patient (DIN-001, DIN-012).
LATEST_YEARS_AHEAD = 10
# a value of digits only is a date, a minute or a second by its length, and nothing else: `strptime` takes a
# one-digit month, so a 7- or 13-digit Republic-of-China value used to match as the year 1150 (DIN-001), and 12
# digits matched the seconds form as 08:03 for 08:30 (DIN-014).
_COMPACT_FORMS = {8: "%Y%m%d", 12: "%Y%m%d%H%M", 14: "%Y%m%d%H%M%S"}
_DIGIT_RUN_RE = re.compile(r"\d+")
_FRACTION_RE = re.compile(r"\.\d+")
# NEW-DIN-1 (D-589): the calendars a site may declare for a date column (``tables.<t>.dates: {col: roc}``)
CALENDARS = ("western", "roc", "era", "roc_or_western")  # F8 (D-807): roc_or_western, an export that writes both
DATE_TYPES = ("date", "datetime", "instant")
_NOT_CALENDAR = "\x00not-a-date-of:"  # what ``normalize`` leaves for the date readers to refuse, with the value
_CLOCK = r"(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?"
# Digits only: YYYMMDD, alone or with hhmm or hhmmss. A two-digit year (YYMMDD, 6, 10 or 12 digits) is not read:
# the same digits are a western date (260512, 201208151000), and a declared column must never read one as ROC
_ROC_COMPACT_LENGTHS = (7, 11, 13)
# written with separators: the year has three digits (049/03/12), or fewer only when 民國 stands before it
_ROC_WRITTEN = re.compile(
    rf"(?:(?:民國|民国|中華民國)\s*(\d{{1,3}})|(\d{{3}}))\s*[年./\-]\s*(\d{{1,2}})\s*[月./\-]\s*(\d{{1,2}})\s*日?{_CLOCK}"
)
_MIDNIGHT = re.compile(r"[ T]00:00(?::00(?:\.0+)?)?$")
_ERA_WRITTEN = re.compile(rf"(.*?){_CLOCK}")
# a western date-time with a time of day, the seconds' fraction allowed (DIN-014)
_WESTERN_CLOCK = re.compile(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}) +(\d{1,2}):(\d{2})(?::(\d{2})(?:[.,]\d+)?)?")


def _clock(h: str | None, mi: str | None, sec: str | None) -> str | None:
    """`` hh:mm:ss`` of a time the clock has, "" for no time, None for one it does not have (24:00, a minute 60)."""
    if h is None or mi is None:
        return ""
    hh, mm, ss = int(h), int(mi), int(sec or 0)
    return f" {hh:02d}:{mm:02d}:{ss:02d}" if hh < 24 and mm < 60 and ss < 60 else None


# F8 (D-807): a western date no ROC form can be: a four-digit year with separators, or 8, 12 or 14 digits
_WESTERN_SURE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:[.,]\d+)?)?)?")
_WESTERN_COMPACT_LENGTHS = (8, 12, 14)


def western_sure(raw: str) -> str | None:
    """``YYYY-MM-DD[ hh:mm:ss]`` of a western date that cannot be a ROC one (F8, D-807); None for anything else."""
    text = raw.strip()
    if text.isascii() and text.isdigit() and len(text) in _WESTERN_COMPACT_LENGTHS:
        parts: tuple[str | None, ...] = (text[:4], text[4:6], text[6:8], text[8:10] or None, text[10:12] or None,
                                         text[12:14] or None)  # fmt: skip
    elif m := _WESTERN_SURE.fullmatch(text):
        parts = m.groups()
    else:
        return None
    y, mo, d, h, mi, sec = parts
    try:
        day = date(int(str(y)), int(str(mo)), int(str(d)))
    except ValueError:
        return None
    clock = _clock(h, mi, sec)
    return None if clock is None else day.isoformat() + clock


# F6 (D-808): ICD-10-CM: a letter, a digit, then a digit or letter (the category), and up to four more after the dot
_ICD10CM_BARE = re.compile(r"[A-Z][0-9][0-9A-Z](?:[0-9A-Z]{1,4})?")
_ICD10CM_DOTTED = re.compile(r"[A-Z][0-9][0-9A-Z]\.[0-9A-Z]{1,4}")


def to_western(raw: str, calendar: str) -> str | None:
    """A date (or date and time) written in ``calendar`` as ``YYYY-MM-DD[ hh:mm:ss]``; None when ``raw`` is not a
    date of that calendar (D-589). Nothing is guessed: a western date in a ``roc`` column is None."""
    text = raw.strip()
    day: date | None = None
    clock: str | None = ""
    if calendar == "roc":
        if text.isascii() and text.isdigit():
            if len(text) not in _ROC_COMPACT_LENGTHS:
                return None
            d, t = text[:7], text[7:]
            if int(d[:-4]) < 1:
                return None
            day = tb_dates.minguo_date(int(d[:-4]), int(d[-4:-2]), int(d[-2:]))
            clock = _clock(t[:2], t[2:4], t[4:6] or None) if t else ""
        elif (m := _ROC_WRITTEN.fullmatch(text)) and int(m.group(1) or m.group(2)) >= 1:
            day = tb_dates.minguo_date(int(m.group(1) or m.group(2)), int(m.group(3)), int(m.group(4)))
            clock = _clock(m.group(5), m.group(6), m.group(7))
    elif calendar == "era":
        m = _ERA_WRITTEN.fullmatch(text)
        cell = tb_dates.CELL_ERA.match(m.group(1).strip()) if m else None
        if m and cell:
            got, inside = tb_dates.era_date(cell.group(1), cell.group(2), int(cell.group(3)), int(cell.group(4)))
            day = got if inside else None
            clock = _clock(m.group(2), m.group(3), m.group(4))
    if day is None or clock is None:
        return None
    return day.isoformat() + clock


def declared_and_unread(value: Any) -> tuple[str, str] | None:
    """``(calendar, the value as fed)`` when ``normalize`` could not read ``value`` in its declared calendar. A
    source value that only imitates the marker names no calendar of ours and is an ordinary value."""
    if isinstance(value, str) and value.startswith(_NOT_CALENDAR):
        calendar, _, raw = value[len(_NOT_CALENDAR) :].partition("\x00")
        if calendar in CALENDARS:
            return calendar, raw
    return None


def _refuse_declared(raw: Any) -> None:
    """``normalize`` could not read a value in its column's declared calendar: the row is refused here, where
    every refused row is counted."""
    unread = declared_and_unread(raw)
    if unread:
        raise MappingError(f"not a {unread[0]} calendar date {unread[1]!r}")


def _date_columns(resources: list[ResourceSpec], table: str) -> frozenset[str]:
    """The canonical columns the resources of ``table`` read as a date (an element's ``type``, a period's ends, a
    date bound of a condition)."""
    out: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            if x.get("type") in DATE_TYPES or x.get("builder") == "period" or "add_minutes" in x:
                out.update(x[k] for k in ("column", "start", "end") if isinstance(x.get(k), str))
            if ("date_before" in x or "date_from" in x) and isinstance(x.get("column"), str):
                out.add(x["column"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for r in resources:
        if r.table == table:
            walk(r.elements)
            walk(r.where)
    return frozenset(out)


class MappingError(ValueError):
    pass


class DateRangeError(MappingError):
    """A value that reads as a date outside ``EARLIEST_YEAR`` to today's year + ``LATEST_YEARS_AHEAD``."""


def _zone(path: Path, name: object) -> ZoneInfo:
    """A mapping states its source's zone (``tz``); it is the site's zone, and doctor compares it with ``TB_TZ``.
    A mapping without one is refused: there is no default zone (D-315)."""
    if not name:
        raise MappingError(f"{path}: no tz: state the source's IANA time zone (the site's site.tz, e.g. Asia/Tokyo)")
    try:
        return ZoneInfo(str(name))
    except Exception as exc:
        raise MappingError(f"{path}: tz {name!r} is not a valid IANA time zone") from exc


def resource_id(site_key: bytes, rtype: str, value: str) -> str:
    """Stable pseudonymous id for a non-patient resource (no source keys leave the adapter)."""
    return hmac.new(site_key, f"{rtype}|{value}".encode(), hashlib.sha256).hexdigest()[:32]


# full-width ASCII (U+FF01 to U+FF5E) and the ideographic space, to their half-width forms: what a Taiwanese or
# Japanese system writes for the same code. Not Unicode NFKC: that also turns ``㎎`` into ``mg``, ``①`` into ``1``
# and ``Ⅳ`` into ``IV``, which are other signs, not another width of the same code.
_HALF_WIDTH = {**{c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}, 0x3000: 0x20}
# what a code looks like when it is written into a report (D-580): printable ASCII with no blank inside, and no
# longer than this. Reason for the length: the longest code a look-up of this product is keyed by is JLAC10 (17
# characters); a site's own prefix or suffix fits in the rest. A longer value, or one with a blank or a letter of
# another script, is text someone typed into the code column and is counted, never written out.
CODE_MAX = 40
_CODE_SHAPE = re.compile(rf"[!-~]{{1,{CODE_MAX}}}")
NO_CODE, NOT_A_CODE = "(no code)", "(not a code)"


def fold_key(key: object) -> str:
    """A look-up key as a person reads it (D-580): no blanks around it, full-width letters and digits made
    half-width, lower case."""
    return ("" if key is None else str(key)).translate(_HALF_WIDTH).strip().lower()


KEY_JOIN = "|"  # F10 (D-809): the parts of a key of several columns, joined (``CBC|072``)


def join_key(row: Row, parts: list[str]) -> str:
    """The key of several columns of ``row``, or "" when a part is empty (never a key of one part)."""
    values = [str(row.get(k) or "").strip() for k in parts]
    return KEY_JOIN.join(values) if all(values) else ""


@dataclass
class Lookup:
    name: str
    key: str
    rows: dict[str, Row]
    _folded: dict[str, Row | None] | None = field(default=None, repr=False, compare=False)

    @classmethod
    def load(cls, name: str, path: Path, key: str | list[str]) -> Lookup:
        """``key``: a column, or (F10, D-809) a list of columns that together are the key (panel and item). A row of
        a list key is keyed by its parts joined with :data:`KEY_JOIN`, kept under the joined names as a column; a
        row that lacks a part has no key."""
        parts = [key] if isinstance(key, str) else list(key)
        if not isinstance(key, str) and (len(parts) < 2 or not all(isinstance(k, str) and k for k in parts)):
            raise MappingError(f"look-up {name}: a key of several columns names two or more columns")
        joined = KEY_JOIN.join(parts)
        rows: dict[str, Row] = {}
        with path.open(encoding="utf-8-sig", newline="") as fh:  # a look-up saved with a byte order mark reads too
            reader = csv.DictReader(fh)
            missing = [k for k in parts if k not in (reader.fieldnames or [])]
            if missing:
                raise MappingError(f"look-up {name}: {path.name} has no column {', '.join(missing)}")
            for r in reader:
                if isinstance(key, str):
                    rows[r[key]] = r
                    continue
                values = [str(r[k] or "").strip() for k in parts]
                if all(values):
                    r[joined] = KEY_JOIN.join(values)
                    rows[r[joined]] = r
        return cls(name, joined, rows)

    def find(self, key: object) -> Row | None:
        """The row of ``key`` (NEW-DIN-6, D-580): as written first; else by its folded form (:func:`fold_key`) when
        exactly one row of the table has it. Two rows that differ only by case, width or blanks are two codes of the
        site: folding matches neither (never a guess). An empty key has no row."""
        text = "" if key is None else str(key)
        hit = self.rows.get(text)
        if hit is not None or not text.strip():
            return hit
        if self._folded is None:
            folded: dict[str, Row | None] = {}
            for k, row in self.rows.items():
                fk = fold_key(k)
                folded[fk] = None if fk in folded else row
            self._folded = folded
        return self._folded.get(fold_key(text))


@dataclass
class ResourceSpec:
    type: str
    table: str
    id: dict[str, Any]
    elements: dict[str, Any]
    profile: Any = None
    where: list[dict[str, Any]] = field(default_factory=list)


def _by_day_links(path: Path, order: list[str], resources: list[ResourceSpec]) -> list[tuple[str, str, dict[str, Any]]]:
    """Each ``{ref: {type: T, by_day: {table, keys, day, their_day}}}`` of the mapping (F7, D-806), checked: the table
    exists, makes a ``T`` and is mapped before the table that links to it (its visits are known by then); ``keys``
    (the columns both tables hold: branch, patient) and both days are named."""
    found: list[tuple[str, str, dict[str, Any]]] = []

    def walk(x: Any, r: ResourceSpec) -> None:
        if isinstance(x, dict):
            ref = x.get("ref")
            if isinstance(ref, dict) and "by_day" in ref:
                spec, rtype = ref["by_day"], str(ref.get("type") or "")
                where = f"{path}: {r.type} from {r.table}: a link by day"
                if not isinstance(spec, dict) or spec.get("table") not in order:
                    raise MappingError(f"{where} names no table of the mapping")
                there = str(spec["table"])
                if not any(o.table == there and o.type == rtype for o in resources):
                    raise MappingError(f"{where}: the table {there} makes no {rtype}")
                keys = spec.get("keys")
                if not isinstance(keys, list) or not keys or not all(isinstance(k, str) and k for k in keys):
                    raise MappingError(f"{where} needs keys: the columns both tables hold (branch, patient)")
                if not str(spec.get("day") or "") or not str(spec.get("their_day") or ""):
                    raise MappingError(f"{where} needs day and their_day: the day column of each table")
                if order.index(there) >= order.index(r.table):
                    raise MappingError(f"{where}: the table {there} must be mapped before {r.table}")
                found.append((r.table, rtype, spec))
            for v in x.values():
                walk(v, r)
        elif isinstance(x, list):
            for v in x:
                walk(v, r)

    for r in resources:
        walk(r.elements, r)
    return found


@dataclass
class Mapping:
    name: str
    tz: ZoneInfo
    systems: dict[str, str]
    tables: dict[str, dict[str, Any]]
    lookups: dict[str, Lookup]
    resources: list[ResourceSpec]
    static: list[Resource]
    path: Path
    profiles: dict[str, str] = field(default_factory=dict)
    fhir_profiles: str = ""  # "jp-core": the ingest checks a sample against JP Core (D-137); "tw-core" (T-619a)
    # D-149: the site's declared unit per analyte (LOINC code -> UCUM) for a feed result that arrives without one
    unit_defaults: dict[str, str] = field(default_factory=dict)
    # NEW-STD-1 (D-586): what a site states once and conditions read as ``{param: name}`` (``icd9cm_before``)
    params: dict[str, str] = field(default_factory=dict)
    # NEW-DIN-9 (D-590): the site's own unit spellings, each the UCUM code it stands for (``萬/μL: 10*4/uL``)
    unit_spellings: dict[str, str] = field(default_factory=dict)
    # NEW-DIN-1 (D-589): per table, the date columns, the calendar a site declared for some; the placeholder dates
    date_columns: dict[str, frozenset[str]] = field(default_factory=dict)
    calendars: dict[str, dict[str, str]] = field(default_factory=dict)
    empty_dates: frozenset[str] = frozenset()
    # T-106b: ``<name>@<12 hex>``, the hash of the mapping file and the base it extends (a changed file, a new version)
    version: str = ""
    # F7 (D-806): each ``{ref: {by_day: ...}}``, as (the table that links, the resource type, its by_day spec)
    by_day: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    def read_whole(self) -> set[str]:
        """The tables read whole on a delta night (F7, D-806): a visit table a link by day looks up. An unchanged visit
        missing from the night's rows would make a day of two visits look like a day of one: a wrong link."""
        return {str(spec["table"]) for _, _, spec in self.by_day}

    # F8 (D-807): the western values read in a ``roc_or_western`` column, by (table, column): counts only
    western_read: Counter[tuple[str, str]] = field(default_factory=Counter)

    def read_as_western(self) -> dict[str, dict[str, int]]:
        """Per table and column, how many values a ``roc_or_western`` column read as western (F8, D-807)."""
        out: dict[str, dict[str, int]] = {}
        for (table, col), n in sorted(self.western_read.items()):
            out.setdefault(table, {})[col] = n
        return out

    @staticmethod
    def _plausible_of(lk: dict[str, Any]) -> tuple[float, float] | None:
        """A look-up row's own ``plausible_low`` / ``plausible_high``: both or neither, two finite numbers, low not
        over high. Anything else is a ``MappingError``."""
        low, high = (lk.get("plausible_low") or "").strip(), (lk.get("plausible_high") or "").strip()
        if not low and not high:
            return None
        try:
            span = float(low), float(high)
        except ValueError:
            span = float("nan"), float("nan")
        if not (math.isfinite(span[0]) and math.isfinite(span[1]) and span[0] <= span[1]):
            raise MappingError(
                f"the plausible range of {lk.get('local_code')!r} needs two numbers, low then high "
                "(plausible_low, plausible_high)"
            )
        return span

    @staticmethod
    def _unit_spellings(path: Path, doc: Any) -> dict[str, str]:
        """``unit_spellings: {<as the source writes it>: <UCUM code>}``. The code must be one the shared unit table
        knows, and a spelling the table already reads must not be given another meaning: the mapping does not
        load. The rule "a value only when both units are one UCUM code" (D-215) stands; the site adds spellings."""
        if doc is None:
            return {}
        if not isinstance(doc, dict):
            raise MappingError(f"{path}: unit_spellings is a map of a unit as the source writes it to its UCUM code")
        out: dict[str, str] = {}
        for spelling, code in doc.items():
            key, known = labvalue.written(spelling), labvalue.ucum(code)
            if not key or known is None:
                raise MappingError(f"{path}: unit_spellings {spelling!r}: {code!r} is not a UCUM code the box knows")
            if labvalue.ucum(spelling) not in (None, known):
                raise MappingError(f"{path}: unit_spellings {spelling!r} already means {labvalue.ucum(spelling)}")
            if out.get(key, known) != known:  # two spellings that fold to one cannot mean two units
                raise MappingError(f"{path}: unit_spellings {spelling!r} is declared twice, as {out[key]} and {known}")
            out[key] = known
        return out

    def concept_maps(self) -> list[tuple[str, str]]:
        """The reference maps this mapping asks for (D-593): ``(from system, to system)`` addresses of every
        ``mapped_coding`` element of its resources, overlays included, each once, in order. A load checks that they
        are loaded before it starts (``tb_common.refdata.has_map_or_none``): started before the reference pack is
        in, every such code would be published as "no entry"."""
        out: list[tuple[str, str]] = []
        for r in self.resources:
            for spec in r.elements.values():
                if isinstance(spec, dict) and spec.get("builder") == "mapped_coding":
                    pair = (self.systems[spec["from"]], self.systems[spec["to"]])
                    if pair not in out:
                        out.append(pair)
        return out

    def unit_as_code(self, unit: Any) -> Any:
        """The UCUM code of a site spelling (``unit_spellings``), else the unit as it came."""
        return self.unit_spellings.get(labvalue.written(unit), unit) if self.unit_spellings else unit

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or doc.get("version") != 1:
            raise MappingError(f"{path}: expected a mapping document with version: 1")
        return doc

    @classmethod
    def load(cls, path: Path) -> Mapping:
        doc = cls._read(path)
        digest = hashlib.sha256(path.read_bytes())
        lookup_dirs = {name: path.parent for name in (doc.get("lookups") or {})}
        if doc.get("extends"):
            from adapter.mapping.site import resolve_extends  # a site mapping extends the image's base (T-632)

            base_path = resolve_extends(path, str(doc["extends"]))
            if not base_path.exists():
                raise MappingError(f"{path}: extends {doc['extends']} not found")
            digest.update(base_path.read_bytes())
            base = cls._read(base_path)
            if base.get("extends"):
                raise MappingError(f"{base_path}: a base mapping cannot extend another one")
            site_tables = doc.get("tables") or {}
            merged = {**base, **{k: v for k, v in doc.items() if k != "extends"}}
            merged["systems"] = {**(base.get("systems") or {}), **(doc.get("systems") or {})}
            merged["params"] = {**(base.get("params") or {}), **(doc.get("params") or {})}
            if isinstance(base.get("unit_spellings"), dict) and isinstance(doc.get("unit_spellings") or {}, dict):
                merged["unit_spellings"] = {**base["unit_spellings"], **(doc.get("unit_spellings") or {})}  # D-590
            merged["lookups"] = {**(base.get("lookups") or {}), **(doc.get("lookups") or {})}
            lookup_dirs = {
                **{n: base_path.parent for n in (base.get("lookups") or {})},
                **{n: path.parent for n in (doc.get("lookups") or {})},
            }
            merged["tables"] = site_tables  # the site declares what it exports
            merged["resources"] = [r for r in base.get("resources") or [] if r["table"] in site_tables]
            merged["static"] = doc.get("static", base.get("static"))
            doc = merged
        for ov in doc.get("overlay") or []:
            hits = [r for r in doc.get("resources") or [] if r["type"] == ov["type"] and r["table"] == ov["table"]]
            if not hits and ov["table"] in (doc.get("tables") or {}):
                raise MappingError(f"{path}: overlay for {ov['type']}/{ov['table']} matches no resource")
            for r in hits:
                r["elements"] = {**(r.get("elements") or {}), **(ov.get("elements") or {})}
        lookups = {
            name: Lookup.load(name, lookup_dirs[name] / spec["file"], spec["key"])
            for name, spec in (doc.get("lookups") or {}).items()
        }
        resources = [
            ResourceSpec(
                type=r["type"],
                table=r["table"],
                id=r["id"],
                elements=r.get("elements") or {},
                profile=r.get("profile"),
                where=r.get("where") or [],
            )
            for r in doc.get("resources") or []
        ]
        for t, tspec in (doc.get("tables") or {}).items():  # F10 (D-809): a key column made of several
            for col, parts in ((tspec or {}).get("join") or {}).items():
                if not (isinstance(parts, list) and len(parts) >= 2 and all(isinstance(p, str) and p for p in parts)):
                    raise MappingError(f"{path}: {t}.join.{col}: a list of two or more columns")
        for r in resources:
            if r.table not in (doc.get("tables") or {}):
                raise MappingError(f"{path}: resource {r.type} uses undeclared table {r.table!r}")
            _known_codes_are_the_maps(path, r)
        by_day = _by_day_links(path, list(doc.get("tables") or {}), resources)
        for name, lk in lookups.items():  # D-590: a range stated badly is found now, not row by row at night
            for row in lk.rows.values():
                try:
                    cls._plausible_of(row)
                except MappingError as exc:
                    raise MappingError(f"{path}: look-up {name}: {exc}") from exc
                # D-596: a factor of 0 turns every result of its analyte into 0, a wrong result, not a missing one
                text = str(row.get("factor") or "1").strip()
                try:
                    # as a float too: 1e-400 is above zero as written and 0.0 in every result; 1e400 is infinite
                    good = Decimal(text).is_finite() and math.isfinite(float(text)) and float(text) > 0
                except (ArithmeticError, ValueError):
                    good = False
                if not good:
                    code = row.get(lk.key)
                    raise MappingError(
                        f"{path}: look-up {name}, row {code!r}: the factor {text!r} must be a number above 0"
                    )
        date_columns = {t: _date_columns(resources, t) for t in (doc.get("tables") or {})}
        calendars: dict[str, dict[str, str]] = {}
        for word in ("dates", "date", "calendars"):  # a declaration in the wrong place would be ignored without a word
            if word in doc:
                raise MappingError(f"{path}: {word} belongs on a table (tables.<table>.dates), not at the top")
        for t, tspec in (doc.get("tables") or {}).items():
            for word in ("date", "calendars", "calendar", "empty_dates"):
                if word in (tspec or {}):
                    raise MappingError(f"{path}: {t}.{word}: a table declares `dates`; `empty_dates` is at the top")
            if not isinstance((tspec or {}).get("dates") or {}, dict):
                raise MappingError(f"{path}: {t}.dates is a map of date column to calendar ({', '.join(CALENDARS)})")
            for col, cal in ((tspec or {}).get("dates") or {}).items():
                if cal not in CALENDARS:
                    raise MappingError(f"{path}: {t}.dates.{col}: the calendar is one of {', '.join(CALENDARS)}")
                if col not in date_columns[t]:
                    raise MappingError(f"{path}: {t}.dates.{col}: not a date column of a resource of {t}")
                calendars.setdefault(t, {})[str(col)] = str(cal)
        empty = doc.get("empty_dates", [])
        if not isinstance(empty, list) or not all(isinstance(x, str) and x.strip() for x in empty):
            raise MappingError(f"{path}: empty_dates is a list of placeholder dates as the source writes them")
        systems = doc.get("systems") or {}
        # D-536 (lane B): the lake reads ATC only under the ATC system's own name. A mapping that writes ATC codes
        # under an address of the site's own would pass every check and lose them from the lake's ATC column: a
        # drug-class exclusion would stop firing for that site, and nothing would say so. One spelling only: the
        # address is written into the feed as given, and a ruleset's value set compares it as written
        from lake.flatten import ATC_SYSTEM

        why = (
            f"ATC codes are written under {ATC_SYSTEM} (the ATC system's own address, spelled so); under another "
            "one the lake does not read them as ATC and a drug-class exclusion would not see them"
        )
        if "atc" in systems and systems["atc"] != ATC_SYSTEM:
            raise MappingError(
                f"{path}: systems.atc is {systems['atc']!r}: {why}. Leave systems.atc out, and give a hospital's "
                "own drug codes another name"
            )
        for r in resources:
            for element, spec in r.elements.items():
                if not isinstance(spec, dict) or spec.get("builder") != "coding" or spec.get("column") != "atc":
                    continue
                if systems.get(str(spec.get("system"))) != ATC_SYSTEM:
                    raise MappingError(
                        f"{path}: {r.type}.{element} writes column atc under system {spec.get('system')!r}: {why}. "
                        "Write the atc column under `system: atc`"
                    )
        for r in resources:  # D-689: a mapped coding takes only relations that say the code is the target
            for element, spec in r.elements.items():
                if not isinstance(spec, dict) or spec.get("builder") != "mapped_coding" or "accept" not in spec:
                    continue
                accept = spec["accept"]
                if not isinstance(accept, list) or not accept or not set(accept) <= MAPPED_RELATIONS:
                    raise MappingError(
                        f"{path}: {r.type}.{element}: accept is a list of {', '.join(sorted(MAPPED_RELATIONS))} "
                        f"(an inexact or related entry is a candidate, never the code), not {accept!r}"
                    )
        for r in resources:  # D-689: a mapped ATC only where the hospital's own ATC column is empty, and only in full
            atc_cols = sorted({
                str(sp.get("column"))
                for sp in r.elements.values()
                if isinstance(sp, dict) and sp.get("builder") == "coding"
                and systems.get(str(sp.get("system"))) == ATC_SYSTEM
            })  # fmt: skip
            for element, spec in r.elements.items():
                if not isinstance(spec, dict) or spec.get("builder") != "mapped_coding":
                    continue
                if "target" in spec and spec["target"] not in MAPPED_TARGETS:
                    raise MappingError(f"{path}: {r.type}.{element}: target is one of {', '.join(MAPPED_TARGETS)}")
                if systems.get(str(spec.get("to"))) != ATC_SYSTEM:
                    continue
                when = spec.get("when")
                guarded = (isinstance(when, dict) and when.get("not_empty") is False and len(atc_cols) <= 1
                           and (not atc_cols or when.get("column") == atc_cols[0]))  # fmt: skip
                if spec.get("target") != "atc5" or not guarded:
                    raise MappingError(
                        f"{path}: {r.type}.{element} maps a code to ATC: it needs `target: atc5` and `when: {{column: "
                        f"{atc_cols[0] if atc_cols else '<the ATC column>'}, not_empty: false}}`, the column the "
                        f"hospital's own ATC is written from ({', '.join(atc_cols) or 'none'}), so that the hospital's "
                        "ATC is never overridden"
                    )
        return cls(
            unit_spellings=cls._unit_spellings(path, doc.get("unit_spellings")),
            date_columns=date_columns,
            calendars=calendars,
            empty_dates=frozenset(x.strip() for x in empty),
            name=doc.get("name", path.stem),
            tz=_zone(path, doc.get("tz")),
            systems=doc.get("systems") or {},
            tables=doc.get("tables") or {},
            lookups=lookups,
            resources=resources,
            static=doc.get("static") or [],
            path=path,
            profiles={str(k): str(v or "") for k, v in (doc.get("profiles") or {}).items()},
            fhir_profiles=str(doc.get("fhir_profiles") or ""),
            unit_defaults={str(k): str(v) for k, v in (doc.get("unit_defaults") or {}).items()},
            params=cls._params(path, doc),
            version=f"{doc.get('name', path.stem)}@{digest.hexdigest()[:12]}",
            by_day=by_day,
        )

    @staticmethod
    def _params(path: Path, doc: dict[str, Any]) -> dict[str, str]:
        """The mapping's ``params`` (NEW-STD-1, D-586), checked when the mapping loads: each is a day written
        ``YYYY-MM-DD`` (a bound is compared as text, so ``2016/01/01`` or a blank would move every diagnosis to the
        wrong edition), and each is read by a condition (a misspelt name would switch its rule off silently)."""

        def used(node: Any) -> set[str]:
            if isinstance(node, dict):
                here = {str(v["param"]) for k, v in node.items()
                        if k in ("date_before", "date_from") and isinstance(v, dict) and "param" in v}  # fmt: skip
                return here.union(*(used(v) for v in node.values()))
            if isinstance(node, list):
                return set().union(*(used(v) for v in node))
            return set()

        out: dict[str, str] = {}
        read = used(doc.get("resources") or [])
        for name, value in (doc.get("params") or {}).items():
            text = "" if value is None else str(value)
            try:
                ok = len(text) == 10 and date.fromisoformat(text).isoformat() == text
            except ValueError:
                ok = False
            if not ok:
                raise MappingError(f"{path}: params.{name} must be a day written YYYY-MM-DD, not {text!r}")
            if str(name) not in read:
                raise MappingError(f"{path}: params.{name} is read by no condition of this mapping "
                                   f"(known: {', '.join(sorted(read)) or 'none'})")  # fmt: skip
            out[str(name)] = text
        return out

    def normalize(self, table: str, row: Row) -> Row:
        """Source row → canonical row: ``rename`` local columns, then translate ``values`` codes."""
        spec = self.tables.get(table) or {}
        rename: dict[str, str] = spec.get("rename") or {}
        out = {rename.get(k, k): v for k, v in row.items()} if rename else dict(row)
        for col, codes in (spec.get("values") or {}).items():
            v = out.get(col)
            table_codes = {str(k): c for k, c in codes.items()}  # YAML may load 1: M with an int key
            if v is None:
                continue
            if str(v) in table_codes:
                out[col] = table_codes[str(v)]
            elif str(v).strip() in table_codes:  # D-587: blanks around a site's code are not part of it
                out[col] = table_codes[str(v).strip()]
        for col, parts in (spec.get("join") or {}).items():  # F10 (D-809): one key column made of several
            out[col] = join_key(out, parts)
        calendars = self.calendars.get(table) or {}
        if calendars or self.empty_dates:  # D-589: a declared placeholder is empty; a declared calendar made western
            for col in self.date_columns.get(table, ()):
                text = "" if out.get(col) is None else str(out[col]).strip()
                if not text:
                    continue
                if text in self.empty_dates or _MIDNIGHT.sub("", text) in self.empty_dates:
                    out[col] = ""  # the placeholder, also when a date-time column adds its midnight
                elif calendars.get(col) == "roc_or_western":
                    # F8 (D-807): ROC read as ROC; a western date that no ROC form can be read as written, counted
                    western = to_western(text, "roc")
                    if western is None and (western := western_sure(text)) is not None:
                        self.western_read[(table, col)] += 1
                    out[col] = western if western is not None else f"{_NOT_CALENDAR}{calendars[col]}\x00{text}"
                elif calendars.get(col, "western") != "western":
                    western = to_western(text, calendars[col])
                    # not raised here: the row is refused where refused rows are counted (the date readers)
                    out[col] = western if western is not None else f"{_NOT_CALENDAR}{calendars[col]}\x00{text}"
        return out

    def source_column(self, table: str, canonical: str | None) -> str | None:
        """The local name of a canonical column (for source-side filters such as ``delta``)."""
        if canonical is None:
            return None
        rename: dict[str, str] = (self.tables.get(table) or {}).get("rename") or {}
        return next((local for local, canon in rename.items() if canon == canonical), canonical)


def _known_codes_are_the_maps(path: Path, r: ResourceSpec) -> None:
    """NEW-DIN-7 (D-587): a ``known:`` / ``unknown_to:`` list repeats the codes of the ``map:`` on the same column
    of the same resource. One changed without the other would drop, or mark unknown, every row of a code the map
    reads: the mapping does not load."""
    maps: dict[str, set[str]] = {}
    for expr in r.elements.values():
        if isinstance(expr, dict) and isinstance(expr.get("map"), dict) and isinstance(expr.get("column"), str):
            maps.setdefault(expr["column"], set()).update(str(k) for k in expr["map"])

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for word in ("known", "unknown_to"):
                col = x.get("column")
                if word in x and col in maps and {str(c) for c in x[word]} != maps[col]:
                    raise MappingError(
                        f"{path}: {r.type} from {r.table}: the {word} codes {sorted(str(c) for c in x[word])} of "
                        f"{col} are not the codes of the map on {col} {sorted(maps[col])}; a site's own codes go "
                        "in the table's values: map"
                    )
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(r.where)
    walk(r.elements)


# D-593: an all-numeric ICD-9-CM code, with its dot (three places, then one or two) or without (three to five)
#: D-689: the relations a ``mapped_coding`` element may accept (``accept:``): the map says the code IS the target
#: (``equivalent``, ``equal``) or belongs to it as to its class (``wider``: an NHI product in its ATC class). An
#: ``inexact`` or ``relatedto`` entry is a candidate, never the code (D-592)
MAPPED_RELATIONS = frozenset({"equivalent", "equal", "wider"})
#: D-689: the shape a mapped code must have to be written (``target:``). ``atc5``: a full ATC code (level 5, the
#: level of a drug value set). A coarser class from a map is not written: any ATC, however coarse, makes the row
#: "readable" to the coverage rule, and a level-5 inclusion would then answer "no" where it was unknown
MAPPED_TARGETS = {"atc5": re.compile(r"[A-Z]\d{2}[A-Z]{2}\d{2}")}

_ICD9_NUMERIC = re.compile(r"(\d{3})(?:\.(\d{1,2}))?|(\d{4,5})")


class Mapper:
    """Applies a :class:`Mapping` to source rows."""

    def __init__(
        self,
        mapping: Mapping,
        site_key: bytes,
        site_id: str,
        ingest_time: str | None = None,
        concept_map: Callable[[str, str], list[dict[str, Any]] | None] | None = None,
    ) -> None:
        # D-593: the reference data's map (code system, code → its rows), when the caller has it: the night and the
        # back-fill pass the box's own; without it ``mapped_coding`` maps nothing
        self.concept_map = concept_map
        self._mapped: dict[tuple[str, ...], str | None] = {}  # (from, to, code, accepted) → the one code, asked once
        self.mapped: Counter[tuple[str, str]] = Counter()  # D-689: rows that gained a mapped coding, by (table, map)
        self.m = mapping
        self.key = site_key
        self.site_id = site_id
        self.ingest_time = ingest_time  # a FHIR instant: set, every resource carries its row provenance (DATA-010)
        self.builders: dict[str, Callable[[ResourceSpec, Row, dict[str, Any]], Any]] = {
            "lab_value": self._b_lab_value,
            "coding": self._b_coding,
            "period": self._b_period,
            "mapped_coding": self._b_mapped_coding,
        }
        # NEW-DIN-6 (D-580): rows a resource's ``where`` dropped because the look-up has no row for their code,
        # by (source table, look-up, code as fed without its blanks): codes and counts, never a row
        self.unmapped: Counter[tuple[str, str, str]] = Counter()
        self._row_seen: set[tuple[str, str]] | None = None  # the row :meth:`map_table` is mapping, else None
        # F7 (D-806): the visits of each linked-to table by (its keys, its day) -> their ids, filled as it is mapped,
        # and what each link by day found, by (table, outcome): counts only
        self._visits: dict[tuple[str, str, tuple[str, ...], str], dict[tuple[str, ...], set[str]]] = {}
        for _, rtype, spec in mapping.by_day:
            self._visits.setdefault((str(spec["table"]), rtype, tuple(spec["keys"]), str(spec["their_day"])), {})
        self.links: Counter[tuple[str, str]] = Counter()
        self._made: set[tuple[str, str]] = set()  # (type, id) of each visit that became a record

    # ------------------------------------------------------------------ scalar conversion
    def _parse_dt(self, raw: str) -> datetime:
        """A source date-time. One that states its offset keeps it (the same instant, the same offset: T-616,
        STD-015); a naive one is in the mapping's ``tz``; a date alone is its midnight in ``tz``. A value that is
        not a western calendar date-time is refused on every form (DIN-001)."""
        _refuse_declared(raw)
        try:
            return self._read_dt(raw)
        except DateRangeError:
            raise
        except ValueError as exc:
            raise MappingError(f"unparseable datetime {raw!r}") from exc

    def _read_dt(self, raw: str) -> datetime:
        if _OFFSET_RE.search(raw.strip()):
            text = raw.strip()
            text = text[:-1] + "+00:00" if text[-1] in "zZ" else text
            return self._western(datetime.fromisoformat(text.replace(" ", "T", 1)), raw)
        text = raw.strip().replace("T", " ")
        compact = self._compact(text, raw)
        if compact is not None:
            return compact.replace(tzinfo=self.m.tz)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                got = datetime.strptime(text, fmt)
            except ValueError:
                continue
            return self._western(got, raw).replace(tzinfo=self.m.tz)
        timed = _WESTERN_CLOCK.fullmatch(text)
        if timed:  # DIN-014: a fraction of a second keeps the time; 24:00 or a minute 60 is no time (it was midnight)
            clock = _clock(timed.group(2), timed.group(3), timed.group(4))
            if clock is None:
                raise ValueError(f"no such time of day in {raw!r}")
            at = self._western(datetime.strptime(timed.group(1).replace("/", "-"), "%Y-%m-%d"), raw)
            hh, mm, ss = (int(x) for x in clock.split(":"))
            return at.replace(hour=hh, minute=mm, second=ss, tzinfo=self.m.tz)
        d = self._parse_date(raw)
        return datetime(d.year, d.month, d.day, tzinfo=self.m.tz)

    @staticmethod
    def _western(dt: datetime, raw: str) -> datetime:
        """``dt`` when its year can be a patient's; one message for every form and column type."""
        if not EARLIEST_YEAR <= dt.year <= date.today().year + LATEST_YEARS_AHEAD:
            raise DateRangeError(
                f"date {raw!r} is outside {EARLIEST_YEAR} to {LATEST_YEARS_AHEAD} years from now: "
                "not a western calendar date"
            )
        return dt

    @classmethod
    def _compact(cls, text: str, raw: str) -> datetime | None:
        """The value when it starts with digits and has no date separator. Digits only: 8, 12 or 14 of them
        (``_COMPACT_FORMS``). Digits and then something else: the run is 8, 12 or 14 digits and its date is read, as
        before this card (the time too when what follows 14 digits is a fraction of a second). None: not compact."""
        run = _DIGIT_RUN_RE.match(text)
        if run is None or "-" in text[: run.end() + 1] or "/" in text:
            return None
        digits, tail = run.group(), text[run.end() :]
        fmt = _COMPACT_FORMS.get(len(digits))
        if fmt is None:
            raise MappingError(f"unparseable date {raw!r}")
        if tail and not (len(digits) == 14 and _FRACTION_RE.fullmatch(tail)):
            digits, fmt = digits[:8], "%Y%m%d"
        try:
            got = datetime.strptime(digits, fmt)
        except ValueError as exc:
            raise MappingError(f"unparseable date {raw!r}") from exc
        return cls._western(got, raw)

    @classmethod
    def _parse_date(cls, raw: str) -> date:
        """A western calendar date. Anything else is refused (DIN-001): `strptime` takes a one-digit month, so the
        compact form on a Republic-of-China date (`1150501`) or a two-digit year (`640715`) used to give the year
        1150 or 6407 and the night passed. The compact form needs 8 digits (or the 12 or 14 of a date-time), and a
        year outside ``EARLIEST_YEAR`` to ``LATEST_YEARS_AHEAD`` years from now is not a patient's date."""
        _refuse_declared(raw)
        text = raw.strip()
        compact = cls._compact(text.replace("T", " "), raw)
        if compact is not None:
            return compact.date()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                got = datetime.strptime(text[:10], fmt)
            except ValueError:
                continue
            return cls._western(got, raw).date()
        raise MappingError(f"unparseable date {raw!r}")

    def convert(self, value: Any, typ: str | None) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and value.strip() == "":
            return None
        if typ in (None, "str"):
            return str(value)
        s = str(value)
        if typ == "int":
            return int(Decimal(s))
        if typ == "decimal":
            try:
                d = Decimal(s)
            except InvalidOperation as exc:
                raise MappingError(f"not a number: {s!r}") from exc
            return float(d)
        if typ == "date":
            return self._parse_date(s).isoformat()
        if typ in ("datetime", "instant"):
            return self._parse_dt(s).isoformat(timespec="seconds")
        if typ == "bool":
            return s.strip().lower() in ("1", "y", "yes", "true", "t")
        raise MappingError(f"unknown type {typ!r}")

    # ------------------------------------------------------------------ expressions
    def pid(self, row: Row, col: str) -> str:
        raw = row.get(col)
        if raw is None or str(raw).strip() == "":
            raise MappingError(f"empty patient key column {col!r}")
        return pid_for_mrn(self.key, str(raw))

    def hid(self, rtype: str, row: Row, col: str) -> str:
        return resource_id(self.key, rtype, str(row[col]))

    def lookup(self, spec: dict[str, Any], row: Row) -> Any:
        hit = self.m.lookups[spec["name"]].find(row.get(spec["key"]))
        if hit is None:
            return spec.get("default")
        return hit.get(spec["field"]) or spec.get("default")

    def template(self, text: str, row: Row, spec: ResourceSpec) -> str:
        def sub(mt: re.Match[str]) -> str:
            tok = mt.group(1)
            if tok.startswith("sys."):
                return self.m.systems[tok[4:]]
            if tok == "site_id":
                return self.site_id
            if tok.startswith("pid:"):
                return self.pid(row, tok[4:])
            if tok.startswith("hid:"):
                rtype, _, col = tok[4:].partition(":")
                return self.hid(rtype, row, col)
            val = row.get(tok)
            if val is None:
                raise MappingError(f"template column {tok!r} missing in table {spec.table}")
            return str(val)

        return _TOKEN_RE.sub(sub, text)

    def _day_of(self, raw: Any) -> str | None:
        if raw is None or str(raw).strip() == "":
            return None
        try:
            return self._parse_dt(str(raw)).date().isoformat()
        except (MappingError, ValueError):
            return None

    def _by_day(self, spec: dict[str, Any], rtype: str, row: Row, rs: ResourceSpec) -> str | None:
        """F7 (D-806): the one ``rtype`` the linked-to table holds for this row's keys and day; none when that day has
        several or none, each counted, never guessed."""
        keys = tuple(spec["keys"])
        want = (*(str(row.get(k) or "").strip() for k in keys), self._day_of(row.get(spec["day"])) or "")
        ids = self._visits.get((str(spec["table"]), rtype, keys, str(spec["their_day"])), {}).get(want, set())
        if any(not v for v in want) or not ids:
            self.links[(rs.table, "no_visit_that_day")] += 1
            return None
        if len(ids) > 1:
            self.links[(rs.table, "several_visits_that_day")] += 1
            return None
        rid = next(iter(ids))
        if (rtype, rid) not in self._made:  # the day's one visit was refused or left out: no record to point at
            self.links[(rs.table, "visit_not_mapped")] += 1
            return None
        self.links[(rs.table, "linked")] += 1
        return f"{rtype}/{rid}"

    def encounter_links(self) -> dict[str, dict[str, int]]:
        """What the links by day found, per table (F7, D-806): ``linked``, ``several_visits_that_day``,
        ``no_visit_that_day``, ``visit_not_mapped``. Counts only."""
        out: dict[str, dict[str, int]] = {}
        for (table, outcome), n in sorted(self.links.items()):
            out.setdefault(table, {})[outcome] = n
        return out

    def ref(self, spec: dict[str, Any], row: Row, rs: ResourceSpec) -> str | None:
        rtype = spec["type"]
        if "by_day" in spec:
            return self._by_day(spec["by_day"], rtype, row, rs)
        if "pid" in spec:
            return f"{rtype}/{self.pid(row, spec['pid'])}"
        col = spec.get("hid") or spec.get("column")
        assert col is not None
        raw = row.get(col)
        if raw is None or str(raw).strip() == "":
            return None
        if "hid" in spec:
            return f"{rtype}/{resource_id(self.key, rtype, str(raw))}"
        return f"{rtype}/{raw}"

    def value(self, expr: Any, row: Row, rs: ResourceSpec) -> Any:
        if not isinstance(expr, dict):
            return expr
        if "when" in expr and not self.cond(expr["when"], row):
            return None
        if "const" in expr:
            return expr["const"]
        if "builder" in expr:
            return self.builders[expr["builder"]](rs, row, expr)
        if "column" in expr:
            raw = row.get(expr["column"])
            if "map" in expr:
                key = "" if raw is None else str(raw)
                if key not in expr["map"]:
                    key = key.strip()  # a padded code is the same code (D-580)
                if key and key not in expr["map"] and "unmapped" in expr:
                    # D-275: a code the map does not know is not the empty default (a cancelled order must never
                    # become "active" because the map lacks the word). NEW-DIN-7 (D-587): and it is counted
                    self._note_unmapped(rs.table, f"column:{expr['column']}", key)
                    raw = expr["unmapped"]
                else:
                    raw = expr["map"].get(key, expr.get("default"))
            elif (raw is None or str(raw).strip() == "") and "default" in expr:
                raw = expr["default"]
            if "add_minutes" in expr and raw not in (None, ""):
                minutes = row.get(expr["add_minutes"]) if isinstance(expr["add_minutes"], str) else expr["add_minutes"]
                dt = self._parse_dt(str(raw)) + timedelta(minutes=int(minutes or 0))
                raw = dt.isoformat(sep=" ", timespec="seconds")  # an offset the source stated stays (STD-015)
            val = self.convert(raw, expr.get("type"))
            if val is not None and "factor" in expr:
                val = float(Decimal(str(val)) * Decimal(str(expr["factor"])))
            return val
        if "template" in expr:
            return self.template(expr["template"], row, rs)
        if "pid" in expr:
            return self.pid(row, expr["pid"])
        if "hid" in expr:
            return self.hid(rs.type, row, expr["hid"])
        if "ref" in expr:
            return self.ref(expr["ref"], row, rs)
        if "lookup" in expr:
            return self.lookup(expr["lookup"], row)
        if "base64" in expr:
            text = row.get(expr["base64"])
            return None if text is None else base64.b64encode(str(text).encode("utf-8")).decode("ascii")
        raise MappingError(f"unknown value expression {expr!r}")

    def _bound(self, value: Any) -> str | None:
        """A date bound of a condition: a day, or ``{param: name}`` (NEW-STD-1): the mapping's parameter of that
        name, None when the mapping sets none."""
        if isinstance(value, dict):
            got = self.m.params.get(str(value.get("param")))
            return str(got) if got else None
        return str(value)

    def cond(self, conds: Any, row: Row) -> bool:
        for c in conds if isinstance(conds, list) else [conds]:
            if "any" in c:  # NEW-STD-1: one of the lists holds
                if not any(self.cond(alt, row) for alt in c["any"]):
                    return False
                if not {"column", "lookup", "fhir_profiles"} & set(c):
                    continue  # ``any`` alone; with a column or a look-up beside it both must hold
            if "fhir_profiles" in c:  # T-619a: the profile set of the mapping (tw-core, jp-core), not a column
                if self.m.fhir_profiles != str(c["fhir_profiles"]):
                    return False
                if "column" not in c and "lookup" not in c:
                    continue
            if "lookup" in c:
                v: Any = self.lookup(c["lookup"], row)
            else:
                v = row.get(c["column"])
            sv = "" if v is None else str(v)
            if "not_empty" in c and bool(sv.strip()) != bool(c["not_empty"]):
                return False
            if "equals" in c and sv != str(c["equals"]):
                return False
            if "in" in c and sv not in [str(x) for x in c["in"]]:
                return False
            # NEW-DIN-7 (D-587): ``known``: blank, or one of the codes; ``unknown_to``: a code that is none of them
            if "known" in c and sv.strip() and sv.strip() not in [str(x) for x in c["known"]]:
                return False
            if "unknown_to" in c and (not sv.strip() or sv.strip() in [str(x) for x in c["unknown_to"]]):
                return False
            if "not_in" in c and sv in [str(x) for x in c["not_in"]]:
                return False
            if "date_before" in c or "date_from" in c:  # T-619a: an ISO date bound (a code edition by date)
                before = self._bound(c["date_before"]) if "date_before" in c else None
                since = self._bound(c["date_from"]) if "date_from" in c else None
                if "date_before" in c and before is None:
                    return False  # a parameter the mapping does not set: nothing is "before" it
                if before is not None or since is not None:
                    # a value that is there and cannot be read refuses the row (it used to answer "no" to both
                    # bounds, so the element was left out and nothing was counted)
                    day = self._parse_date(sv).isoformat() if sv.strip() else ""
                    if not day or (before is not None and day >= before):
                        return False
                    if since is not None and day < since:
                        return False
            if "numeric" in c:
                try:
                    float(sv)
                    is_num = True
                except ValueError:
                    is_num = False
                if is_num != bool(c["numeric"]):
                    return False
        return True

    # ------------------------------------------------------------------ builders
    @staticmethod
    def _plausible(lk: dict[str, Any]) -> tuple[float, float] | None:
        """The range a unit-less value of this look-up row may have, in the unit the look-up writes: the row's own
        ``plausible_low`` / ``plausible_high`` (the site's data), else the built-in one for its LOINC code."""
        own = Mapping._plausible_of(lk)
        if own is not None:
            return own
        loinc = lk.get("code") if lk.get("system") == "loinc" else None
        return labvalue.plausible_range(loinc, lk.get("ucum"))

    def _lab_code(self, lk: dict[str, Any], row: Row, args: dict[str, Any]) -> str:
        """The look-up's own spelling of the lab code (one count per analyte, not per spelling of its code)."""
        key = self.m.lookups[args["lookup"]].key
        return str(lk.get(key) or row.get(args["key"]) or "").strip()

    def _b_lab_value(self, rs: ResourceSpec, row: Row, args: dict[str, Any]) -> Any:
        """``value[x]`` from a lab result using the lookup's ucum/factor/value_type/answers columns. With
        ``unit_column`` the row's own unit is checked against the unit the lookup says the source reports (its
        ``source_unit`` column, else ``ucum`` when ``factor`` is 1): a row in another unit, or in a unit nobody can
        check, has no value (R-31, D-215, :func:`tb_common.labvalue.read`)."""
        lk = self.m.lookups[args["lookup"]].find(row.get(args["key"]))
        raw = row.get(args["column"])
        if lk is None or raw is None or str(raw).strip() == "":
            return None
        checked: labvalue.Reading | None = None
        if args.get("unit_column") and lk.get("value_type") != "coded":
            column = args["unit_column"]
            if column not in row:  # a declared unit column the source does not have: stop, never skip the check
                raise MappingError(f"{rs.type} from {rs.table}: unit_column {column!r} is not a column of the source")
            source_unit = lk.get("source_unit") or (lk.get("ucum") if Decimal(lk.get("factor") or "1") == 1 else None)
            loinc = lk.get("code") if lk.get("system") == "loinc" else None  # NEW-STD-4: IU/L as U/L for enzymes
            checked = labvalue.read(raw, self.m.unit_as_code(row[column]), source_unit, loinc)
            if checked.reason == labvalue.UNIT_MISMATCH:  # no value[x]: the engines read no value as unknown (D-130)
                self._note_unmapped(rs.table, "unit_mismatch", self._lab_code(lk, row, args))  # D-590
                return {
                    "dataAbsentReason": {
                        "coding": [{"system": DATA_ABSENT, "code": "error"}],
                        "text": labvalue.UNIT_MISMATCH,
                    },
                    "note": [{"text": f"{str(raw).strip()} {str(row[column] or '').strip()}"}],
                }
        if lk.get("value_type") == "coded":
            answers = dict(a.split(":", 1) for a in (lk.get("answers") or "").split(";") if ":" in a)
            # the site's own word first, then the shared ja / zh-TW / en table (陰性, 未檢出, Non-reactive; D-334)
            word = labvalue.answer_key(raw, answers)
            code = answers.get(word) if word else None
            if code is None:
                return {"valueString": str(raw)}
            loinc_answer, _, display = code.partition("|")
            return {
                "valueCodeableConcept": {
                    "coding": [{"system": self.m.systems["loinc"], "code": loinc_answer, "display": display or None}],
                    "text": str(raw),
                }
            }
        comparator: str | None = None
        if checked is not None:  # D-215: the unit-checked reading is labvalue's alone (no 1.5E1, no NaN)
            if checked.value is None:
                return {"valueString": str(raw)}
            num, comparator = Decimal(repr(checked.value)), checked.comparator
        else:
            try:
                num = Decimal(str(raw).strip())
            except InvalidOperation:
                # D-142 (review B-01): "75 H" is 75 with a flag, "<0.3" / "0.3未満" is censored (Quantity.comparator);
                # anything else stays text, which the screening engine reads as unknown, never as a failed test
                got = labvalue.parse(raw)
                if got is None:
                    return {"valueString": str(raw)}
                num, comparator = Decimal(repr(got[0])), got[1]
            if not num.is_finite():  # "NaN", "Infinity": not a result (D-215)
                return {"valueString": str(raw)}
        factor = Decimal(lk.get("factor") or "1")
        val = num * factor
        # D-596: the arithmetic comes before the plausibility check, so a number the mapping cannot compute (thirty
        # digits) has one outcome with and without a unit: the ``ArithmeticError`` that makes it a rejected row
        # (D-527). Without a unit it used to be called implausible and kept
        number: float | int = float(val) if val % 1 else int(val)
        # D-590 (DIN-017): a value that came with no unit is read in the look-up's unit (D-149) only when it can be
        # a value in that unit: else it stays text (unknown to the engines) and is counted
        column = args.get("unit_column")
        if not (column and str(row.get(column) or "").strip()):
            span = self._plausible(lk)
            if span is not None and not span[0] <= float(val) <= span[1]:
                self._note_unmapped(rs.table, "no_unit_implausible", self._lab_code(lk, row, args))
                # no value[x], as for a unit mismatch: a text value would be read back as a number by the lake
                return {
                    "dataAbsentReason": {
                        "coding": [{"system": DATA_ABSENT, "code": "error"}],
                        "text": labvalue.NO_UNIT_IMPLAUSIBLE,
                    },
                    "note": [{"text": str(raw).strip()}],
                }
        # NEW-STD-4 (D-585): the unit is stored as its UCUM code, never as the spelling the look-up was typed in
        # (``×10^3/μL``): the engines read the code, not the spellings of the feed
        unit = labvalue.ucum(lk.get("ucum")) or lk.get("ucum") or ""
        q: dict[str, Any] = {"value": number, "unit": unit}
        if comparator:
            q["comparator"] = comparator
        if unit:
            q["system"] = self.m.systems["ucum"]
            q["code"] = unit
        return {"valueQuantity": q}

    def _b_coding(self, rs: ResourceSpec, row: Row, args: dict[str, Any]) -> Any:
        """``dotted: icd10cm`` (F6, D-808): a code of the ICD-10-CM shape is written with its dot after the third
        character (``M109`` is ``M10.9``); a category of three has none. A code of another shape is copied as fed and
        counted (``shape:icd10cm``)."""
        code = row.get(args["column"])
        if code is None or str(code).strip() == "":
            return None
        text = str(code).strip()
        if args.get("dotted") == "icd10cm":
            bare = text.upper()
            if _ICD10CM_DOTTED.fullmatch(bare):
                text = bare
            elif _ICD10CM_BARE.fullmatch(bare):
                text = bare if len(bare) == 3 else f"{bare[:3]}.{bare[3:]}"
            else:
                self._note_unmapped(rs.table, "shape:icd10cm", text)
        coding: dict[str, Any] = {"system": self.m.systems[args["system"]], "code": text}
        if "display_column" in args and row.get(args["display_column"]):
            coding["display"] = str(row[args["display_column"]])
        return coding

    def _note_mapped(self, table: str, name: str) -> None:
        """One row that gained a mapped coding (D-689), once per source row and name."""
        at = ("mapped", name)
        if self._row_seen is None or at not in self._row_seen:
            self.mapped[(table, name)] += 1
            if self._row_seen is not None:
                self._row_seen.add(at)

    def mapped_summary(self) -> dict[str, dict[str, int]]:
        """``{table: {map: rows that gained its coding}}`` for the night's report (D-689): counts only."""
        out: dict[str, dict[str, int]] = {}
        for (table, name), n in sorted(self.mapped.items()):
            out.setdefault(table, {})[name] = n
        return out

    def _b_mapped_coding(self, rs: ResourceSpec, row: Row, args: dict[str, Any]) -> Any:
        """D-593: the coding of a column's code in another system (``from`` → ``to``, names of ``systems``), only
        when the reference data's map has exactly one row for the code into that system and the row says the two
        are the same (``equivalent`` / ``equal``). An approximate entry, alternatives, a combination or no entry
        give nothing, and the row is counted (``map:<from>-><to>``, the value as fed): never a guess.

        ``dotted: icd9``: only an all-numeric ICD-9-CM code is looked up, with its dot (``7140`` is ``714.0``). A
        code that starts with a letter is never looked up: ``E03.0`` and ``V12.5`` are codes of both editions, and
        a site that wrote ICD-10-CM in its ICD-9-CM years would get another disease's code.

        A map that could not be asked (``None``) is not "no entry": nothing is mapped, the row is counted under
        ``…:unavailable`` and the next row asks again. Without a ``concept_map`` nothing is mapped or counted."""
        raw = row.get(args["column"])
        if self.concept_map is None or raw is None or not str(raw).strip():
            return None
        fed = str(raw).strip().upper()
        name = f"map:{args['from']}->{args['to']}"
        code: str | None = fed
        if args.get("dotted") == "icd9":
            m = _ICD9_NUMERIC.fullmatch(fed)
            code = None if m is None else (m.group(1) + (f".{m.group(2)}" if m.group(2) else "") if m.group(1)
                                           else f"{m.group(3)[:3]}.{m.group(3)[3:]}")  # fmt: skip
        if code is None:
            self._note_unmapped(rs.table, name, fed)
            return None
        accept = tuple(args.get("accept") or ("equivalent", "equal"))  # D-689: ``wider`` only where an element says
        key = (str(args["from"]), str(args["to"]), code, *accept)
        if key not in self._mapped:
            target = self.m.systems[args["to"]]
            asked = self.concept_map(self.m.systems[args["from"]], code)
            if asked is None:
                self._note_unmapped(rs.table, f"{name}:unavailable", fed)
                return None
            rows = [t for t in asked if t.get("target_system") == target]
            answers = {(str(t.get("target_code") or ""), t.get("relation")) for t in rows}  # one answer given twice
            shape = MAPPED_TARGETS.get(str(args.get("target") or ""))
            hit_code, rel = next(iter(answers)) if len(answers) == 1 else ("", None)
            same = bool(hit_code) and rel in accept and (shape is None or shape.fullmatch(hit_code) is not None)
            self._mapped[key] = hit_code if same else None
        hit = self._mapped[key]
        if hit is None:
            self._note_unmapped(rs.table, name, fed)  # as fed, so the count's own filter sees what it was
            return None
        self._note_mapped(rs.table, name)
        # userSelected false: not the code the hospital recorded, the one the map says it is
        return {"system": self.m.systems[args["to"]], "code": hit, "userSelected": False}

    def _b_period(self, rs: ResourceSpec, row: Row, args: dict[str, Any]) -> Any:
        typ = args.get("type", "date")
        start = self.convert(row.get(args["start"]), typ)
        end = self.convert(row.get(args["end"]), typ) if args.get("end") else None
        if start is None and end is None:
            return None
        return {k: v for k, v in (("start", start), ("end", end)) if v is not None}

    # ------------------------------------------------------------------ assembly
    @staticmethod
    def set_path(res: Resource, path: str, value: Any) -> None:
        if value is None:
            return
        if path == "$merge":
            if not isinstance(value, dict):
                raise MappingError("$merge expects an object")
            res.update(value)
            return
        parts = path.split(".")
        cur: Any = res
        for i, part in enumerate(parts):
            m = _PATH_RE.fullmatch(part)
            if not m:
                raise MappingError(f"bad path segment {part!r} in {path!r}")
            name, idx = m.group(1), m.group(2)
            last = i == len(parts) - 1
            if idx is None:
                if last:
                    cur[name] = value
                else:
                    cur = cur.setdefault(name, {})
            else:
                lst = cur.setdefault(name, [])
                n = int(idx)
                while len(lst) <= n:
                    lst.append({})
                if last:
                    lst[n] = value
                else:
                    cur = lst[n]

    @staticmethod
    def prune(obj: Any) -> Any:
        if isinstance(obj, dict):
            out = {k: Mapper.prune(v) for k, v in obj.items()}
            return {k: v for k, v in out.items() if v not in (None, {}, [], "")}
        if isinstance(obj, list):
            items = [Mapper.prune(v) for v in obj]
            return [v for v in items if v not in (None, {}, [], "")]
        return obj

    def row_id(self, rs: ResourceSpec, row: Row) -> str:
        if "pid" in rs.id:
            return self.pid(row, rs.id["pid"])
        if "hid" in rs.id:
            return resource_id(self.key, rs.type, f"{row[rs.id['hid']]}{rs.id.get('suffix', '')}")
        if "column" in rs.id:
            return str(row[rs.id["column"]])
        raise MappingError(f"{rs.type}: id needs pid/hid/column")

    def tombstones(self, table: str, rows: Iterator[Row]) -> Iterator[tuple[str, str]]:
        """``(resource type, id)`` of every resource a deleted source row would have made (dataflow review P0-1).

        A deleted row is often a bare key, so ``where`` conditions and elements are not evaluated: each resource of
        the table whose id the row can give is a tombstone, and a tombstone for an id not in the snapshot is a no-op.
        A Patient is never tombstoned this way: removing a person is the opt-out path's job, not a feed delta's."""
        specs = [r for r in self.m.resources if r.table == table and r.type != "Patient"]
        for row in rows:
            for rs in specs:
                try:
                    yield rs.type, self.row_id(rs, row)
                except (KeyError, TypeError, ValueError):
                    continue

    def map_row(self, rs: ResourceSpec, row: Row) -> Resource | None:
        for v in row.values():  # D-589: an unread date of a declared calendar refuses the row, whoever reads it
            _refuse_declared(v)
        if rs.where and not self.cond(rs.where, row):
            self._count_unmapped(rs, row)
            return None
        res: Resource = {"resourceType": rs.type, "id": self.row_id(rs, row)}
        if rs.profile:
            prof = self.value(rs.profile, row, rs) if isinstance(rs.profile, dict) else rs.profile
            prof = self.m.profiles.get(str(prof), prof) if prof else prof
            if prof:
                res["meta"] = {"profile": [prof]}
        for path, expr in rs.elements.items():
            self.set_path(res, path, self.value(expr, row, rs))
        if self.ingest_time:
            meta = res.setdefault("meta", {})
            meta["source"] = f"{self.site_id}/{rs.table}#{self.row_hash(row)}"
            meta["lastUpdated"] = self.ingest_time
            meta["tag"] = [*(meta.get("tag") or []), {"system": MAPPING_VERSION, "code": self.m.version}]
        pruned: Resource = self.prune(res)
        return pruned

    def _note_unmapped(self, table: str, name: str, code: str) -> None:
        """One dropped or unknown code, once per source row and name (``self._row_seen`` is the row's set while
        :meth:`map_table` maps it; a caller of :meth:`map_row` alone counts every call)."""
        at = (name, code)
        if self._row_seen is None or at not in self._row_seen:
            self.unmapped[(table, *at)] += 1
            if self._row_seen is not None:
                self._row_seen.add(at)

    def _count_unmapped(self, rs: ResourceSpec, row: Row) -> None:
        """Count the row a ``where`` dropped when the reason is a code nobody knows: a ``{lookup: ..., not_empty:
        true}`` condition whose look-up gives nothing for the row's key (D-580), or a ``{column: ..., known:
        [...]}`` condition whose column holds another code (NEW-DIN-7, D-587)."""
        for c in rs.where if isinstance(rs.where, list) else [rs.where]:
            if not isinstance(c, dict):
                continue
            spec = c.get("lookup")
            if spec and c.get("not_empty") and self.lookup(spec, row) in (None, ""):
                code = row.get(spec["key"])
                self._note_unmapped(rs.table, str(spec["name"]), "" if code is None else str(code).strip())
            elif "known" in c and "column" in c:
                raw = row.get(c["column"])
                code = "" if raw is None else str(raw).strip()
                if code and code not in [str(x) for x in c["known"]]:
                    self._note_unmapped(rs.table, f"column:{c['column']}", code)

    def unmapped_by_code(self, chart_pattern: str | None = None) -> dict[str, dict[str, dict[str, int]]]:
        """``{table: {look-up: {code: rows}}}``, the largest count first: every code, none cut (OD-10). Only what
        looks like a code is written out (``_CODE_SHAPE``, and not the site's chart-number pattern): a value with a
        blank, a name or a number of a patient that a mis-mapped column put where the code belongs is counted under
        ``NOT_A_CODE``, an empty one under ``NO_CODE``. Nothing identifying reaches a report."""
        chart = re.compile(chart_pattern) if chart_pattern else None
        counts: Counter[tuple[str, str, str]] = Counter()
        for (table, name, code), n in self.unmapped.items():
            if not code:
                code = NO_CODE
            elif not _CODE_SHAPE.fullmatch(code) or (chart is not None and chart.fullmatch(code)):
                code = NOT_A_CODE
            counts[(table, name, code)] += n
        out: dict[str, dict[str, dict[str, int]]] = {}
        for (table, name, code), n in sorted(counts.items(), key=lambda kv: (kv[0][:2], -kv[1], kv[0][2])):
            out.setdefault(table, {}).setdefault(name, {})[code] = n
        return out

    def unmapped_summary(self) -> dict[str, dict[str, dict[str, int]]]:
        """``{table: {look-up: {"rows": dropped rows, "codes": distinct values}}}`` for the night's report."""
        rows: Counter[tuple[str, str]] = Counter()
        codes: Counter[tuple[str, str]] = Counter()
        for (table, name, _code), n in self.unmapped.items():
            rows[(table, name)] += n
            codes[(table, name)] += 1
        out: dict[str, dict[str, dict[str, int]]] = {}
        for table, name in sorted(rows):
            out.setdefault(table, {})[name] = {"rows": rows[(table, name)], "codes": codes[(table, name)]}
        return out

    def row_hash(self, row: Row) -> str:
        """The source row's fingerprint: an HMAC under the site key of its canonical JSON (24 hex)."""
        body = json.dumps(row, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
        return hmac.new(self.key, body, hashlib.sha256).hexdigest()[:24]

    def _index_visit(self, table: str, rs: ResourceSpec, row: Row) -> str:
        """F7 (D-806): every visit row read, under its keys and its day, mapped or not: a day of two visits stays a
        day of two when one is refused or left out. Its id ("" when not indexed); one without an id still counts."""
        hit = [(k, i) for k, i in self._visits.items() if k[0] == table and k[1] == rs.type]
        if not hit:
            return ""
        try:
            rid = self.row_id(rs, row)
        except (KeyError, MappingError):
            rid = ""
        for (_, _, keys, their_day), index in hit:
            key = (*(str(row.get(k) or "").strip() for k in keys), self._day_of(row.get(their_day)) or "")
            if all(key):
                index.setdefault(key, set()).add(rid or f"\x00{len(index)}:{sum(map(len, index.values()))}")
        return rid

    def map_table(self, table: str, rows: Iterator[Row]) -> Iterator[Resource]:
        specs = [r for r in self.m.resources if r.table == table]
        try:
            for row in rows:
                self._row_seen = set()
                for rs in specs:
                    rid = self._index_visit(table, rs, row)  # before mapping: a visit refused or left out counts
                    res = self.map_row(rs, row)
                    if res is not None:
                        if rid:
                            self._made.add((rs.type, rid))
                        yield res
        finally:
            self._row_seen = None

    def static_resources(self) -> list[Resource]:
        out: list[Resource] = []
        for res in self.m.static:
            text = yaml.safe_dump(res, allow_unicode=True)
            text = _TOKEN_RE.sub(
                lambda mt: (
                    self.m.systems[mt.group(1)[4:]]
                    if mt.group(1).startswith("sys.")
                    else self.site_id
                    if mt.group(1) == "site_id"
                    else mt.group(0)
                ),
                text,
            )
            out.append(yaml.safe_load(text))
        return out
