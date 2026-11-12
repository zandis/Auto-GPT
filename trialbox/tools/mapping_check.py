"""Check a site mapping against a real HIS export before the first nightly run (SPEC §12 phase 9; D-84).

For every table of the mapping: reads up to ``--rows`` source rows (after the table's ``rename`` / ``values``), and
reports

* **missing columns** — canonical columns the resource definitions read that the source does not provide;
* **unmapped codes** — lab codes missing from the lab lookup, values outside an element's ``map`` (they fall back to
  the element default), values outside the table's ``values`` maps;
* **structural errors** — produced resources that fail the FHIR R4B models or miss SPEC §3.1 required elements;
* **unit pairs** (D-334, STD-001) — every (lab code, row unit) pair of a quantity result and how it is read: the
  lookup's unit, no unit (read in the lookup's unit), or a mismatch that leaves the row without a value; for a
  mismatch, the tested factor from ``tb_common.labvalue.conversion`` the lookup's ``source_unit`` / ``factor`` could
  declare, or "no tested factor";
* **qualitative values** (D-334, STD-022) — every distinct raw text of a coded result and what it reads as: the
  site's own answer, the shared ja / zh-TW / en table, unsettled, or not recognised (stays text, unknown);
* **unit defaults** — a ``unit_defaults`` line that is not the lab lookup's unit for the same LOINC code.

Exit status 1 when a column is missing, a resource is structurally invalid or a unit default contradicts the lookup;
unmapped codes, unit mismatches and unread qualitative values are warnings for the lab / HIS team.

    python tools/mapping_check.py --mapping services/adapter/mapping/tw_core/<site>.yaml --source csv --path <dir>
    python tools/mapping_check.py --mapping ... --source cgrd_sql --dsn "$HIS_DSN"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services"):
    sys.path.insert(0, str(ROOT / _p))

_TOKEN = re.compile(r"\{([A-Za-z_][\w.]*)\}")
COLUMN_KEYS = ("column", "pid", "hid", "display_column", "start", "end", "add_minutes", "base64", "unit_column")
UNREADABLE = {"diagnosis": "icd10", "medication": "atc"}  # the column whose absence makes a row unreadable (D-130)


def referenced_columns(spec: Any) -> set[str]:
    """Canonical column names an element / id / where expression reads."""
    out: set[str] = set()
    if isinstance(spec, dict):
        for k, v in spec.items():
            if k in COLUMN_KEYS and isinstance(v, str):
                out.add(v)
            elif k == "template" and isinstance(v, str):
                out |= {t for t in _TOKEN.findall(v) if not t.startswith("sys.") and t != "site_id"}
            elif k == "lookup" and isinstance(v, dict) and isinstance(v.get("key"), str):
                out.add(v["key"])
            elif k == "key" and isinstance(v, str) and "lookup" in spec:  # lab_value builder: key = column
                out.add(v)
            else:
                out |= referenced_columns(v)
    elif isinstance(spec, list):
        for x in spec:
            out |= referenced_columns(x)
    return out


def _patient_columns(elements: dict[str, Any]) -> set[str]:
    """The column of every ``ref: {type: Patient, pid: …}`` (the subject link is mandatory)."""
    out: set[str] = set()
    for expr in elements.values():
        ref = expr.get("ref") if isinstance(expr, dict) else None
        if isinstance(ref, dict) and ref.get("type") == "Patient" and isinstance(ref.get("pid"), str):
            out.add(ref["pid"])
    return out


def lab_value_args(m: Any, table: str) -> dict[str, Any] | None:
    """The ``lab_value`` builder's arguments on a resource of ``table`` (lookup, key, column, unit_column), or None."""
    for spec in m.resources:
        if spec.table != table:
            continue
        for expr in spec.elements.values():
            if isinstance(expr, dict) and expr.get("builder") == "lab_value":
                return dict(expr)
    return None


def _loinc(lk_row: dict[str, Any]) -> str | None:
    return str(lk_row.get("code") or "") or None if lk_row.get("system") == "loinc" else None


def unit_pairs(m: Any, args: dict[str, Any], got: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every (lab code, row unit) pair of a quantity result, how the adapter reads it, and for a mismatch the tested
    factor that would turn the row's unit into the unit the lookup expects (D-334)."""
    from decimal import Decimal

    from tb_common import labvalue

    lk = m.lookups[args["lookup"]]
    col = args.get("unit_column")
    seen: Counter[tuple[str, str]] = Counter()
    for row in got:
        code = str(row.get(args["key"]) or "")
        hit = lk.rows.get(code)
        if hit is None or hit.get("value_type") == "coded" or str(row.get(args["column"]) or "").strip() == "":
            continue
        seen[(code, str(row.get(col) or "").strip() if col else "")] += 1
    out: list[dict[str, Any]] = []
    for (code, unit), n in sorted(seen.items()):
        hit = lk.rows[code]
        factor = Decimal(hit.get("factor") or "1")
        expected = hit.get("source_unit") or (hit.get("ucum") if factor == 1 else None)
        item: dict[str, Any] = {
            "code": code,
            "loinc": _loinc(hit),
            "row_unit": unit,
            "lookup_unit": expected,
            "rows": n,
        }
        agree = labvalue.units_agree(unit, expected, _loinc(hit) or None) if col else None
        if agree is None:
            item["read"] = "no unit: read in the lookup's unit" if col else "not checked: no unit_column"
        elif agree:
            item["read"] = "same unit"
        else:
            item["read"] = "unit_mismatch: no value"
            to = hit.get("ucum") or expected  # the unit the lookup writes
            k = labvalue.conversion(unit, to, _loinc(hit)) if to else None
            item["factor"] = k
            item["proposal"] = (
                f"if {code} is reported in {unit}: source_unit {unit}, factor {k} (then ucum {to})"
                if k is not None
                else "no tested factor: the lab team fixes the export or the lookup"
            )
        out.append(item)
    return out


def qualitative_values(m: Any, args: dict[str, Any], got: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every distinct raw text of a coded result and what it reads as (D-334, STD-022)."""
    from tb_common import labvalue

    lk = m.lookups[args["lookup"]]
    seen: Counter[tuple[str, str]] = Counter()
    for row in got:
        code = str(row.get(args["key"]) or "")
        hit = lk.rows.get(code)
        raw = str(row.get(args["column"]) or "").strip()
        if hit is not None and hit.get("value_type") == "coded" and raw:
            seen[(code, raw)] += 1
    out: list[dict[str, Any]] = []
    for (code, raw), n in sorted(seen.items()):
        answers = dict(a.split(":", 1) for a in (lk.rows[code].get("answers") or "").split(";") if ":" in a)
        key = labvalue.answer_key(raw, answers)
        if key is not None:
            how = "site answer" if raw.upper() in answers else "shared table"
            read = f"{key} ({how})"
        elif labvalue.presence(raw) == labvalue.UNSETTLED:
            read = "unknown (unsettled on purpose)"
        else:
            read = "unknown (not recognised: stays text)"
        out.append({"code": code, "loinc": _loinc(lk.rows[code]), "raw": raw, "rows": n, "read": read})
    return out


def unit_default_conflicts(m: Any) -> list[str]:
    """``unit_defaults`` lines that are not the lab lookup's ``ucum`` for the same LOINC code (D-149, D-334)."""
    from tb_common import labvalue

    out: list[str] = []
    lk = m.lookups.get("lab")
    if lk is None:
        return out
    for row in lk.rows.values():
        loinc, unit = _loinc(row), row.get("ucum") or ""
        default = m.unit_defaults.get(loinc or "")
        if default is not None and unit and labvalue.ucum(default) != labvalue.ucum(unit):
            out.append(f"unit_defaults {loinc}: {default} but the lab lookup writes {unit} ({row.get('local_code')})")
    return sorted(set(out))


def check(mapping_path: Path, source_kind: str, where: str, rows: int = 500) -> dict[str, Any]:
    from adapter.mapping.engine import Mapper, Mapping
    from adapter.pipeline import make_source
    from adapter.validate.validator import StructuralValidator

    m = Mapping.load(mapping_path)
    src = make_source(source_kind, where)
    mapper = Mapper(m, b"mapping-check-key-0123456789abcdef", "CHECK")
    report: dict[str, Any] = {"mapping": str(mapping_path), "tables": {}, "missing_columns": 0, "invalid": 0}
    report["unit_default_conflicts"] = unit_default_conflicts(m)
    validator = StructuralValidator()
    for table, tspec in m.tables.items():
        specs = [r for r in m.resources if r.table == table]
        need: set[str] = set()  # without these no resource (or no patient link) can be built
        optional: set[str] = set()  # element columns: a missing one only omits that element
        for spec in specs:
            need |= referenced_columns(spec.id) | referenced_columns(spec.where) | _patient_columns(spec.elements)
            optional |= referenced_columns(spec.elements)
            if isinstance(spec.profile, dict):
                optional |= referenced_columns(spec.profile)
        need.add(str(tspec.get("key", "")))
        need.discard("")
        got = []
        for i, row in enumerate(src.rows(table, tspec["source"], None, None)):
            if i >= rows:
                break
            got.append(m.normalize(table, row) if hasattr(m, "normalize") else row)
        t: dict[str, Any] = {"source": tspec["source"], "rows_read": len(got)}
        if not got:
            t["note"] = "no rows (table not exported?)"
            report["tables"][table] = t
            continue
        present: set[str] = set().union(*(row.keys() for row in got))
        missing = sorted(need - present)
        t["missing_columns"] = missing
        t["absent_optional"] = sorted(optional - need - present)
        report["missing_columns"] += len(missing)
        unmapped: Counter[str] = Counter()
        for col, mp in (tspec.get("values") or {}).items():
            for row in got:
                v = row.get(col)
                if v not in (None, "") and str(v) not in {str(x) for x in mp.values()}:
                    unmapped[f"{col}={v}"] += 1
        for spec in specs:
            for expr in spec.elements.values():
                if isinstance(expr, dict) and "map" in expr and "column" in expr:
                    for row in got:
                        v = row.get(expr["column"])
                        if v not in (None, "") and str(v) not in {str(k) for k in expr["map"]}:
                            unmapped[f"{expr['column']}={v}"] += 1
        if "lab" in m.lookups and table == "lab":
            lk = m.lookups["lab"]
            for row in got:
                code = row.get(lk.key)
                if code not in (None, "") and str(code) not in lk.rows:
                    unmapped[f"lab {lk.key}={code} (not in lookup)"] += 1
        t["unmapped_codes"] = dict(unmapped.most_common(20))
        args = lab_value_args(m, table)
        if args is not None and args.get("lookup") in m.lookups:
            t["unit_pairs"] = unit_pairs(m, args, got)
            t["qualitative_values"] = qualitative_values(m, args, got)
        # D-130 (review F-10): diagnoses without an ICD-10 code and medicines without ATC reach the lake in a code
        # system no ValueSet reads; screening keeps those patients unknown, so the site should know the share now
        col = UNREADABLE.get(table)
        if col:
            n_bad = sum(1 for row in got if not str(row.get(col) or "").strip())
            t["unknown_code_system"] = {"rows": n_bad, "share": round(n_bad / len(got), 3)}
        if missing:
            report["tables"][table] = t
            continue
        resources = list(mapper.map_table(table, iter(got)))
        res = validator.validate(resources)
        t["resources"] = len(resources)
        t["structural_errors"] = res.messages[:10]
        report["invalid"] += res.errors
        report["tables"][table] = t
    report["passed"] = (
        report["missing_columns"] == 0 and report["invalid"] == 0 and not report["unit_default_conflicts"]
    )
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mapping", type=Path, required=True)
    ap.add_argument("--source", choices=["csv", "cgrd_sql", "ssmix2"], default="csv")
    ap.add_argument("--path", help="export directory (csv) or storage root (ssmix2)")
    ap.add_argument("--dsn", help="SQLAlchemy DSN (cgrd_sql)")
    ap.add_argument("--rows", type=int, default=500)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = check(args.mapping, args.source, args.path or args.dsn or "", args.rows)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        for table, t in rep["tables"].items():
            line = f"{table:13s} {t['rows_read']:>5} rows"
            if t.get("missing_columns"):
                line += f"  MISSING {', '.join(t['missing_columns'])}"
            elif "resources" in t:
                line += f"  → {t['resources']} resources, {len(t['structural_errors'])} structural errors"
            if t.get("absent_optional"):
                line += f"  (optional, not provided: {', '.join(t['absent_optional'])})"
            if t.get("unmapped_codes"):
                line += f"  unmapped: {', '.join(f'{k} ×{v}' for k, v in t['unmapped_codes'].items())}"
            if (t.get("unknown_code_system") or {}).get("rows"):
                u = t["unknown_code_system"]
                line += f"  unknown code system: {u['rows']} rows ({u['share']:.1%})"
            if t.get("note"):
                line += f"  ({t['note']})"
            print(line)
            for p in t.get("unit_pairs") or []:
                if p["read"] != "same unit":
                    extra = f"  {p['proposal']}" if p.get("proposal") else ""
                    pair = f"{p['code']} [{p['row_unit'] or '-'}] vs {p['lookup_unit']}"
                    print(f"    unit  {pair}: {p['read']} ×{p['rows']}{extra}")
            for q in t.get("qualitative_values") or []:
                print(f"    value {q['code']} {q['raw']!r}: {q['read']} ×{q['rows']}")
        for c in rep["unit_default_conflicts"]:
            print(f"UNIT DEFAULT {c}")
        print(
            f"{'PASSED' if rep['passed'] else 'FAILED'}: {rep['missing_columns']} missing columns, "
            f"{rep['invalid']} invalid resources"
        )
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
