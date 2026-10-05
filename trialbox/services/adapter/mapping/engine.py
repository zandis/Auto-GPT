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
``tz`` and emitted with offset. ``when`` (element) / ``where`` (resource) filter on columns or lookups.

Site mappings (onboarding kit, D-84) usually ``extends`` a shared profile mapping (e.g. ``tw_core/demo_his.yaml``)
and only declare their ``tables``: each table's ``rename`` (local column → canonical column) and ``values``
(canonical column → {local code: canonical code}) are applied to every source row before the shared resource
definitions run; ``key`` / ``delta`` / ``identity`` name canonical columns. Resources of tables the site does not
declare are dropped; lookups resolve relative to the file that declares them.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from tb_common.crypto import pid_for_mrn

Row = dict[str, Any]
Resource = dict[str, Any]

_PATH_RE = re.compile(r"([A-Za-z_$][A-Za-z0-9_$]*)(?:\[(\d+)\])?")
_TOKEN_RE = re.compile(r"\{([^{}]+)\}")


class MappingError(ValueError):
    pass


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

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or doc.get("version") != 1:
            raise MappingError(f"{path}: expected a mapping document with version: 1")
        return doc

    @classmethod
    def load(cls, path: Path) -> Mapping:
        doc = cls._read(path)
        lookup_dirs = {name: path.parent for name in (doc.get("lookups") or {})}
        if doc.get("extends"):
            base_path = Path(doc["extends"])
            base_path = base_path if base_path.is_absolute() else (path.parent / base_path).resolve()
            if not base_path.exists():
                raise MappingError(f"{path}: extends {doc['extends']} not found")
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
            tz=ZoneInfo(doc.get("tz", "Asia/Taipei")),
            systems=doc.get("systems") or {},
            tables=doc.get("tables") or {},
            lookups=lookups,
            resources=resources,
            static=doc.get("static") or [],
            path=path,
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

    def __init__(self, mapping: Mapping, site_key: bytes, site_id: str) -> None:
        self.m = mapping
        self.key = site_key
        self.site_id = site_id
        self.builders: dict[str, Callable[[ResourceSpec, Row, dict[str, Any]], Any]] = {
            "lab_value": self._b_lab_value,
            "coding": self._b_coding,
            "period": self._b_period,
        }

    # ------------------------------------------------------------------ scalar conversion
    def _parse_dt(self, raw: str) -> datetime:
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
                raw = expr["map"].get(key, expr.get("default"))
            elif (raw is None or str(raw).strip() == "") and "default" in expr:
                raw = expr["default"]
            if "add_minutes" in expr and raw not in (None, ""):
                minutes = row.get(expr["add_minutes"]) if isinstance(expr["add_minutes"], str) else expr["add_minutes"]
                dt = self._parse_dt(str(raw)) + timedelta(minutes=int(minutes or 0))
                raw = dt.strftime("%Y-%m-%d %H:%M:%S")
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
        """``value[x]`` from a lab result using the lookup's ucum/factor/value_type/answers columns."""
        lk = self.m.lookups[args["lookup"]].rows.get(str(row.get(args["key"], "")))
        raw = row.get(args["column"])
        if lk is None or raw is None or str(raw).strip() == "":
            return None
        if lk.get("value_type") == "coded":
            answers = dict(a.split(":", 1) for a in (lk.get("answers") or "").split(";") if ":" in a)
            code = answers.get(str(raw).strip().upper())
            if code is None:
                return {"valueString": str(raw)}
            loinc_answer, _, display = code.partition("|")
            return {
                "valueCodeableConcept": {
                    "coding": [{"system": self.m.systems["loinc"], "code": loinc_answer, "display": display or None}],
                    "text": str(raw),
                }
            }
        try:
            num = Decimal(str(raw).strip())
        except InvalidOperation:
            return {"valueString": str(raw)}
        factor = Decimal(lk.get("factor") or "1")
        val = num * factor
        unit = lk.get("ucum") or ""
        q: dict[str, Any] = {"value": float(val) if val % 1 else int(val), "unit": unit}
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

    def map_row(self, rs: ResourceSpec, row: Row) -> Resource | None:
        if rs.where and not self.cond(rs.where, row):
            return None
        res: Resource = {"resourceType": rs.type}
        if "pid" in rs.id:
            res["id"] = self.pid(row, rs.id["pid"])
        elif "hid" in rs.id:
            res["id"] = resource_id(self.key, rs.type, f"{row[rs.id['hid']]}{rs.id.get('suffix', '')}")
        elif "column" in rs.id:
            res["id"] = str(row[rs.id["column"]])
        else:
            raise MappingError(f"{rs.type}: id needs pid/hid/column")
        if rs.profile:
            prof = self.value(rs.profile, row, rs) if isinstance(rs.profile, dict) else rs.profile
            if prof:
                res["meta"] = {"profile": [prof]}
        for path, expr in rs.elements.items():
            self.set_path(res, path, self.value(expr, row, rs))
        pruned: Resource = self.prune(res)
        return pruned

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
