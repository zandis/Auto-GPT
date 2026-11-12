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
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
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


class MappingError(ValueError):
    pass


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


@dataclass
class Lookup:
    name: str
    key: str
    rows: dict[str, Row]

    @classmethod
    def load(cls, name: str, path: Path, key: str) -> Lookup:
        with path.open(encoding="utf-8", newline="") as fh:
            rows = {r[key]: r for r in csv.DictReader(fh)}
        return cls(name, key, rows)


@dataclass
class ResourceSpec:
    type: str
    table: str
    id: dict[str, Any]
    elements: dict[str, Any]
    profile: Any = None
    where: list[dict[str, Any]] = field(default_factory=list)


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
    # T-106b: ``<name>@<12 hex>``, the hash of the mapping file and the base it extends (a changed file, a new version)
    version: str = ""

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
        for r in resources:
            if r.table not in (doc.get("tables") or {}):
                raise MappingError(f"{path}: resource {r.type} uses undeclared table {r.table!r}")
        return cls(
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
            version=f"{doc.get('name', path.stem)}@{digest.hexdigest()[:12]}",
        )

    def normalize(self, table: str, row: Row) -> Row:
        """Source row → canonical row: ``rename`` local columns, then translate ``values`` codes."""
        spec = self.tables.get(table) or {}
        rename: dict[str, str] = spec.get("rename") or {}
        out = {rename.get(k, k): v for k, v in row.items()} if rename else dict(row)
        for col, codes in (spec.get("values") or {}).items():
            v = out.get(col)
            table_codes = {str(k): c for k, c in codes.items()}  # YAML may load 1: M with an int key
            if v is not None and str(v) in table_codes:
                out[col] = table_codes[str(v)]
        return out

    def source_column(self, table: str, canonical: str | None) -> str | None:
        """The local name of a canonical column (for source-side filters such as ``delta``)."""
        if canonical is None:
            return None
        rename: dict[str, str] = (self.tables.get(table) or {}).get("rename") or {}
        return next((local for local, canon in rename.items() if canon == canonical), canonical)


class Mapper:
    """Applies a :class:`Mapping` to source rows."""

    def __init__(self, mapping: Mapping, site_key: bytes, site_id: str, ingest_time: str | None = None) -> None:
        self.m = mapping
        self.key = site_key
        self.site_id = site_id
        self.ingest_time = ingest_time  # a FHIR instant: set, every resource carries its row provenance (DATA-010)
        self.builders: dict[str, Callable[[ResourceSpec, Row, dict[str, Any]], Any]] = {
            "lab_value": self._b_lab_value,
            "coding": self._b_coding,
            "period": self._b_period,
        }

    # ------------------------------------------------------------------ scalar conversion
    def _parse_dt(self, raw: str) -> datetime:
        """A source date-time. One that states its offset keeps it (the same instant, the same offset: T-616,
        STD-015); a naive one is in the mapping's ``tz``; a date alone is its midnight in ``tz``."""
        if _OFFSET_RE.search(raw.strip()):
            text = raw.strip()
            text = text[:-1] + "+00:00" if text[-1] in "zZ" else text
            try:
                return datetime.fromisoformat(text.replace(" ", "T", 1))
            except ValueError as exc:
                raise MappingError(f"unparseable datetime {raw!r}") from exc
        raw = raw.strip().replace("T", " ")
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y%m%d%H%M%S",
        ):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=self.m.tz)
            except ValueError:
                continue
        try:
            d = self._parse_date(raw)
        except MappingError as exc:
            raise MappingError(f"unparseable datetime {raw!r}") from exc
        return datetime(d.year, d.month, d.day, tzinfo=self.m.tz)

    @staticmethod
    def _parse_date(raw: str) -> date:
        raw = raw.strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(raw[:10] if "-" in raw or "/" in raw else raw[:8], fmt).date()
            except ValueError:
                continue
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
        lk = self.m.lookups[spec["name"]]
        hit = lk.rows.get(str(row.get(spec["key"], "")))
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

    def ref(self, spec: dict[str, Any], row: Row, rs: ResourceSpec) -> str | None:
        rtype = spec["type"]
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
                if key.strip() and key not in expr["map"] and "unmapped" in expr:
                    # D-275: a code the map does not know is not the empty default (a cancelled order must never
                    # become "active" because the map lacks the word)
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

    def cond(self, conds: Any, row: Row) -> bool:
        for c in conds if isinstance(conds, list) else [conds]:
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
            if "not_in" in c and sv in [str(x) for x in c["not_in"]]:
                return False
            if "date_before" in c or "date_from" in c:  # T-619a: an ISO date bound (a code edition by date)
                try:
                    day = self._parse_date(sv).isoformat() if sv.strip() else ""
                except MappingError:
                    day = ""
                if not day or ("date_before" in c and day >= str(c["date_before"])):
                    return False
                if "date_from" in c and day < str(c["date_from"]):
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
    def _b_lab_value(self, rs: ResourceSpec, row: Row, args: dict[str, Any]) -> Any:
        """``value[x]`` from a lab result using the lookup's ucum/factor/value_type/answers columns. With
        ``unit_column`` the row's own unit is checked against the unit the lookup says the source reports (its
        ``source_unit`` column, else ``ucum`` when ``factor`` is 1): a row in another unit, or in a unit nobody can
        check, has no value (R-31, D-215, :func:`tb_common.labvalue.read`)."""
        lk = self.m.lookups[args["lookup"]].rows.get(str(row.get(args["key"], "")))
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
            checked = labvalue.read(raw, row[column], source_unit, loinc)
            if checked.reason == labvalue.UNIT_MISMATCH:  # no value[x]: the engines read no value as unknown (D-130)
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
        unit = lk.get("ucum") or ""
        q: dict[str, Any] = {"value": float(val) if val % 1 else int(val), "unit": unit}
        if comparator:
            q["comparator"] = comparator
        if unit:
            q["system"] = self.m.systems["ucum"]
            q["code"] = unit
        return {"valueQuantity": q}

    def _b_coding(self, rs: ResourceSpec, row: Row, args: dict[str, Any]) -> Any:
        code = row.get(args["column"])
        if code is None or str(code).strip() == "":
            return None
        coding: dict[str, Any] = {"system": self.m.systems[args["system"]], "code": str(code).strip()}
        if "display_column" in args and row.get(args["display_column"]):
            coding["display"] = str(row[args["display_column"]])
        return coding

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
        if rs.where and not self.cond(rs.where, row):
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

    def row_hash(self, row: Row) -> str:
        """The source row's fingerprint: an HMAC under the site key of its canonical JSON (24 hex)."""
        body = json.dumps(row, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
        return hmac.new(self.key, body, hashlib.sha256).hexdigest()[:24]

    def map_table(self, table: str, rows: Iterator[Row]) -> Iterator[Resource]:
        specs = [r for r in self.m.resources if r.table == table]
        for row in rows:
            for rs in specs:
                res = self.map_row(rs, row)
                if res is not None:
                    yield res

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
