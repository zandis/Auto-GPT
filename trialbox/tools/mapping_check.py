"""Check a site mapping against a real HIS export before the first nightly run (SPEC §12 phase 9; D-84).

For every table of the mapping: reads up to ``--rows`` source rows (after the table's ``rename`` / ``values``), and
reports

* **missing columns** — canonical columns the resource definitions read that the source does not provide;
* **unmapped codes** — lab codes missing from the lab lookup, values outside an element's ``map`` (they fall back to
  the element default), values outside the table's ``values`` maps;
* **structural errors** — produced resources that fail the FHIR R4B models or miss SPEC §3.1 required elements.

Exit status 1 when a column is missing or a resource is structurally invalid; unmapped codes are warnings for the
lab / HIS team.

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
COLUMN_KEYS = ("column", "pid", "hid", "display_column", "start", "end", "add_minutes", "base64")


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


def check(mapping_path: Path, source_kind: str, where: str, rows: int = 500) -> dict[str, Any]:
    from adapter.mapping.engine import Mapper, Mapping
    from adapter.pipeline import make_source
    from adapter.validate.validator import StructuralValidator

    m = Mapping.load(mapping_path)
    src = make_source(source_kind, where)
    mapper = Mapper(m, b"mapping-check-key-0123456789abcdef", "CHECK")
    report: dict[str, Any] = {"mapping": str(mapping_path), "tables": {}, "missing_columns": 0, "invalid": 0}
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
        if missing:
            report["tables"][table] = t
            continue
        resources = list(mapper.map_table(table, iter(got)))
        res = validator.validate(resources)
        t["resources"] = len(resources)
        t["structural_errors"] = res.messages[:10]
        report["invalid"] += res.errors
        report["tables"][table] = t
    report["passed"] = report["missing_columns"] == 0 and report["invalid"] == 0
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mapping", type=Path, required=True)
    ap.add_argument("--source", choices=["csv", "cgrd_sql"], default="csv")
    ap.add_argument("--path", help="export directory (csv)")
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
            if t.get("note"):
                line += f"  ({t['note']})"
            print(line)
        print(
            f"{'PASSED' if rep['passed'] else 'FAILED'}: {rep['missing_columns']} missing columns, "
            f"{rep['invalid']} invalid resources"
        )
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
