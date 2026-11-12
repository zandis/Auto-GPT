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
    python tools/mapping_check.py --mapping ... --source cgrd_sql --dsn-env HIS_DSN

**A real source (T-731, D-588).** ``--share <file>`` writes the one report that may leave the site: shapes of dates
(never a date), codes that look like codes, unit spellings, counts of repeated keys and of refused rows; no row
value. With it the terminal shows only what the file holds. ``--columns-only`` reads no row: which mapped columns
each table has. ``--day`` (or ``--since`` / ``--until``) reads one window of the change-time column; ``--rows`` is
the most rows read from a table (0: no limit). The connection string comes from the environment variable
``--dsn-env`` names and is never printed.

    python tools/mapping_check.py --mapping <site>.yaml --source cgrd_sql --dsn-env HIS_DSN \
        --columns-only --share columns.json
    python tools/mapping_check.py --mapping <site>.yaml --source cgrd_sql --dsn-env HIS_DSN \
        --day 2026-11-10 --rows 20000 --share day.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import date, timedelta
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
        hit = lk.find(code)
        if hit is None or hit.get("value_type") == "coded" or str(row.get(args["column"]) or "").strip() == "":
            continue
        seen[(code, str(row.get(col) or "").strip() if col else "")] += 1
    out: list[dict[str, Any]] = []
    for (code, unit), n in sorted(seen.items()):
        hit = lk.find(code) or {}
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
        hit = lk.find(code)
        raw = str(row.get(args["column"]) or "").strip()
        if hit is not None and hit.get("value_type") == "coded" and raw:
            seen[(code, raw)] += 1
    out: list[dict[str, Any]] = []
    for (code, raw), n in sorted(seen.items()):
        answers = dict(a.split(":", 1) for a in ((lk.find(code) or {}).get("answers") or "").split(";") if ":" in a)
        key = labvalue.answer_key(raw, answers)
        if key is not None:
            how = "site answer" if raw.upper() in answers else "shared table"
            read = f"{key} ({how})"
        elif labvalue.presence(raw) == labvalue.UNSETTLED:
            read = "unknown (unsettled on purpose)"
        else:
            read = "unknown (not recognised: stays text)"
        out.append({"code": code, "loinc": _loinc(lk.find(code) or {}), "raw": raw, "rows": n, "read": read})
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


def _scan() -> Any:
    """Text → whether the repository's data scan knows its kind (a chart number, a phone, an id, a name by a
    date). The share report is not written without it."""
    if str(ROOT) not in sys.path:  # run as ``python tools/mapping_check.py``: the package's parent is not there
        sys.path.append(str(ROOT))
    from tools import data_scan

    patterns = data_scan.load_patterns()
    allow = data_scan.Allow({}, [])
    return lambda text: bool(data_scan.scan_text(text, "share", patterns, allow))


def _wanted(m: Any, table: str, tspec: dict[str, Any], specs: list[Any]) -> tuple[set[str], set[str], list[str]]:
    """(canonical columns without which nothing is built, the optional ones, the local names of all of them)."""
    need: set[str] = set()  # without these no resource (or no patient link) can be built
    optional: set[str] = set()  # element columns: a missing one only omits that element
    for spec in specs:
        need |= referenced_columns(spec.id) | referenced_columns(spec.where) | _patient_columns(spec.elements)
        optional |= referenced_columns(spec.elements)
        if isinstance(spec.profile, dict):
            optional |= referenced_columns(spec.profile)
    need.add(str(tspec.get("key", "")))
    need.discard("")
    canon = need | optional | set((tspec.get("identity") or {}).values()) | set(tspec.get("values") or {})
    if tspec.get("delta"):
        canon.add(str(tspec["delta"]))
    local = {c: loc for loc, c in (tspec.get("rename") or {}).items()}
    return need, optional, sorted({local.get(c, c) for c in canon})


def columns_only(mapping_path: Path, source_kind: str, where: str) -> dict[str, Any]:
    """Which mapped columns each table or view of a SQL source has, and the database's type of the date columns.
    No row is read (T-731)."""
    from adapter.mapping import sharereport
    from adapter.mapping.engine import Mapping
    from adapter.pipeline import make_source

    if source_kind != "cgrd_sql":
        raise SystemExit("--columns-only reads a SQL source (--source cgrd_sql)")
    m = Mapping.load(mapping_path)
    src: Any = make_source(source_kind, where)
    rep: dict[str, Any] = {"report": "columns", "mapping": mapping_path.name, "dialect": src.engine.dialect.name,
                           "tables": {}, "missing_columns": 0}  # fmt: skip
    for table, tspec in m.tables.items():
        specs = [r for r in m.resources if r.table == table]
        need, optional, wanted = _wanted(m, table, tspec, specs)
        t: dict[str, Any] = {"source": tspec["source"]}
        try:
            have = src.columns(tspec["source"])
        except Exception as exc:
            t["cannot_be_read"] = type(exc).__name__
            rep["missing_columns"] += len(need)
            rep["tables"][table] = t
            continue
        low = {c.lower() for c in have}
        rename = tspec.get("rename") or {}
        canon_have = {rename.get(loc, loc) for loc in wanted if loc.lower() in low}
        t["columns_in_table"] = len(have)
        t["missing_columns"] = sorted(need - canon_have)
        t["absent_optional"] = sorted(optional - need - canon_have)
        t["mapped_names_not_in_table"] = sorted(loc for loc in wanted if loc.lower() not in low)
        t["names_differ_in_case_only"] = sorted(loc for loc in wanted if loc.lower() in low and loc not in have)
        types = {k.lower(): v for k, v in src.column_types(tspec["source"]).items()}
        local = {c: loc for loc, c in rename.items()}
        dates = sharereport.date_columns(specs)
        if tspec.get("delta"):
            dates.setdefault(str(tspec["delta"]), "change time")
        t["date_column_types"] = {
            c: types.get(local.get(c, c).lower(), "not told") for c in sorted(dates) if c in canon_have
        }
        rep["missing_columns"] += len(t["missing_columns"])
        rep["tables"][table] = t
    rep["passed"] = rep["missing_columns"] == 0
    return rep


def check(
    mapping_path: Path,
    source_kind: str,
    where: str,
    rows: int = 500,
    since: str | None = None,
    until: str | None = None,
    chart_pattern: str | None = None,
    min_patients: int | None = None,
) -> dict[str, Any]:
    from adapter.mapping import sharereport
    from adapter.mapping.engine import Mapper, Mapping
    from adapter.pipeline import make_source
    from adapter.validate.validator import StructuralValidator

    m = Mapping.load(mapping_path)
    src: Any = make_source(source_kind, where)
    if until and source_kind != "cgrd_sql":
        raise SystemExit("--day and --until read a SQL source (--source cgrd_sql)")
    if until and not since:
        raise SystemExit("--until needs --since (or give --day)")
    mapper = Mapper(m, b"mapping-check-key-0123456789abcdef", "CHECK")
    net = sharereport.Net(_scan(), chart_pattern, min_patients or sharereport.MIN_PATIENTS)
    report: dict[str, Any] = {"mapping": str(mapping_path), "tables": {}, "missing_columns": 0, "invalid": 0}
    report["rejected"] = 0
    report["source"] = source_kind
    report["window"] = {"since": since, "until": until}
    report["rows_limit"] = rows
    report["unit_default_conflicts"] = unit_default_conflicts(m)
    validator = StructuralValidator()
    for table, tspec in m.tables.items():
        specs = [r for r in m.resources if r.table == table]
        need, optional, wanted = _wanted(m, table, tspec, specs)
        got = []
        cut = False
        delta = tspec.get("delta") if (since or until) else None
        local_delta = {c: loc for loc, c in (tspec.get("rename") or {}).items()}.get(delta, delta) if delta else None
        if source_kind == "cgrd_sql":  # only the columns the mapping names, only the window asked for (D-588)
            feed = src.rows(table, tspec["source"], local_delta, since, until=until, columns=wanted)
        else:
            feed = src.rows(table, tspec["source"], local_delta, since)
        try:
            for i, row in enumerate(feed):
                if rows and i >= rows:
                    cut = True
                    break
                got.append(m.normalize(table, row) if hasattr(m, "normalize") else row)
        except Exception as exc:
            if source_kind != "cgrd_sql":
                raise
            # the error's text may hold the connection or a value: its kind only
            bad = {"source": tspec["source"], "rows_read": 0, "cannot_be_read": type(exc).__name__}
            report["tables"][table] = bad
            report["missing_columns"] += len(need)
            continue
        t: dict[str, Any] = {"source": tspec["source"], "rows_read": len(got), "cut_at_rows_limit": cut}
        if source_kind == "cgrd_sql":
            have = src.columns(tspec["source"])
            low = {c.lower() for c in have}
            # the night finds a column by its exact name: one that differs in case only is missing for it
            t["names_differ_in_case_only"] = sorted(c for c in wanted if c.lower() in low and c not in have)
            report["missing_columns"] += len(t["names_differ_in_case_only"])
            if local_delta and local_delta.lower() not in low:
                delta = "the change-time column is not in the table: it was read whole"
        if since or until:
            t["window_on"] = delta or "no change-time column: the table was read whole"
        pcol = next(iter(sorted(_patient_columns_all(specs))), None) or str(tspec.get("key") or "")

        def who_has(rows_: list[dict[str, Any]], pcol: str = pcol) -> int:
            """How many patients these rows are of (a table with no patient link: how many keys)."""
            return len({str(r.get(pcol) or "").strip() for r in rows_})

        # the second net learns what identifies somebody in these rows: the whole patient table, and every column
        # the mapping uses as a patient link or an identity
        who = {*_patient_columns_all(specs), *(tspec.get("identity") or {}).values()}
        net.learn(got, None if table == "patient" else who)
        if not got:
            t["note"] = "no rows (table not exported?)"
            report["tables"][table] = t
            continue
        dates = sharereport.date_columns(specs)
        t["date_shapes"] = sharereport.date_shapes(mapper, got, dates)
        if tspec.get("key"):
            day = next((c for c in dates if any(c in r for r in got)), None)
            t["repeated_keys"] = sharereport.repeated_keys(got, str(tspec["key"]), day)
        present: set[str] = set().union(*(row.keys() for row in got))
        missing = sorted(need - present)
        t["missing_columns"] = missing
        t["absent_optional"] = sorted(optional - need - present)
        report["missing_columns"] += len(missing)
        unmapped: Counter[str] = Counter()
        outside: dict[tuple[str, str], list[dict[str, Any]]] = {}  # (column or look-up, value) → its rows
        for col, mp in (tspec.get("values") or {}).items():
            for row in got:
                v = row.get(col)
                if v not in (None, "") and str(v) not in {str(x) for x in mp.values()}:
                    unmapped[f"{col}={v}"] += 1
                    outside.setdefault((f"values:{col}", str(v)), []).append(row)
        for spec in specs:
            for expr in spec.elements.values():
                if isinstance(expr, dict) and "map" in expr and "column" in expr:
                    for row in got:
                        v = row.get(expr["column"])
                        if v not in (None, "") and str(v) not in {str(k) for k in expr["map"]}:
                            unmapped[f"{expr['column']}={v}"] += 1
                            outside.setdefault((f"map:{expr['column']}", str(v)), []).append(row)
        if "lab" in m.lookups and table == "lab":
            lk = m.lookups["lab"]
            for row in got:
                code = row.get(lk.key)
                if code not in (None, "") and lk.find(code) is None:  # as the night reads it (D-580)
                    unmapped[f"lab {lk.key}={code} (not in lookup)"] += 1
                    outside.setdefault(("lookup:lab", str(code)), []).append(row)
        t["unmapped_codes"] = dict(unmapped.most_common(20))
        t["outside"] = [[name, value, len(rs), who_has(rs)] for (name, value), rs in sorted(outside.items())]
        args = lab_value_args(m, table)
        if args is not None and args.get("lookup") in m.lookups:
            t["unit_pairs"] = unit_pairs(m, args, got)
            ucol = args.get("unit_column")
            for pair in t["unit_pairs"]:  # how many patients have the pair: the share report's small-cell rule
                pair["patients"] = who_has([
                    r for r in got
                    if str(r.get(args["key"]) or "") == pair["code"]
                    and (str(r.get(ucol) or "").strip() if ucol else "") == pair["row_unit"]
                ])  # fmt: skip
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
        resources, rejected = sharereport.map_rows(mapper, table, got)  # a refused row is counted, as at night
        t["rejected"] = dict(sorted(rejected.items()))
        report["rejected"] += sum(rejected.values())
        res = validator.validate(resources)
        t["resources"] = len(resources)
        t["structural_errors"] = res.messages[:10]
        report["invalid"] += res.errors
        report["tables"][table] = t
    # a row the mapping refuses is a row the night loses: the check does not pass over it (it used to stop there)
    report["passed"] = (
        report["missing_columns"] == 0
        and report["invalid"] == 0
        and report["rejected"] == 0
        and not report["unit_default_conflicts"]
    )
    report["share"] = share(report, mapper, net)
    return report


def _patient_columns_all(specs: list[Any]) -> set[str]:
    out: set[str] = set()
    for spec in specs:
        out |= _patient_columns(spec.elements)
    return out


# what a table's share report takes as it stands: names of the mapping, counts, shapes (safe by their kind)
SHARED_AS_IS = (
    *("source", "rows_read", "cannot_be_read", "cut_at_rows_limit", "window_on", "note", "missing_columns"),
    *("absent_optional", "date_shapes", "repeated_keys", "resources", "unknown_code_system"),
)


def share(report: dict[str, Any], mapper: Any, net: Any) -> dict[str, Any]:
    """The report that may leave the site (D-588): built field by field from what is safe by its kind, then swept
    by the second net. No row value is copied into it."""
    from adapter.mapping import sharereport

    counted = mapper.unmapped_summary()
    out: dict[str, Any] = {
        "report": "share",
        "mapping": Path(report["mapping"]).name,
        "source": report["source"],
        "window": report["window"],
        "rows_limit": report["rows_limit"],
        "passed": report["passed"],
        "missing_columns": report["missing_columns"],
        "invalid_resources": report["invalid"],
        "rejected_rows": report["rejected"],
        "min_patients": net.min_patients,
        "unit_default_conflicts": len(report["unit_default_conflicts"]),
        "tables": {},
    }
    for table, t in report["tables"].items():
        s: dict[str, Any] = {k: t[k] for k in SHARED_AS_IS if k in t}
        if "rejected" in t:
            s["rejected_rows"] = dict(t["rejected"])  # reasons in the engine's own words (``scrub_reason``)
        if "structural_errors" in t:
            s["structural_errors"] = len(t["structural_errors"])
        if "names_differ_in_case_only" in t:
            s["names_differ_in_case_only"] = [net.text(c) for c in t["names_differ_in_case_only"]]
        names: dict[str, list[tuple[Any, int, int]]] = {}
        for name, value, n, patients in t.get("outside") or []:
            names.setdefault(name, []).append((value, n, patients))
        if "outside" in t:
            s["outside_the_map"] = {name: net.codes(items) for name, items in sorted(names.items())}
            # dropped or unknown at mapping time (D-580): how many rows and distinct codes, by look-up or column
            s["unmapped_dropped_or_unknown"] = counted.get(table) or {}
        if "unit_pairs" in t:
            s["unit_pairs"] = [
                {"code": net.code(p["code"], p["patients"], known=True), "loinc": p["loinc"],
                 "row_unit": net.unit(p["row_unit"], p["patients"]),
                 "lookup_unit": p["lookup_unit"], "rows": p["rows"], "read": p["read"],
                 "factor": None if p.get("factor") is None else str(p["factor"])}
                for p in t["unit_pairs"]
            ]  # fmt: skip
        if "qualitative_values" in t:
            s["qualitative_values"] = [
                {"code": net.code(q["code"], 0, known=True), "loinc": q["loinc"], "rows": q["rows"], "read": q["read"],
                 "raw": net.text(q["raw"]) if "not recognised" not in q["read"] else sharereport.shape(q["raw"])}
                for q in t["qualitative_values"]
            ]  # fmt: skip
        out["tables"][table] = s
    own = {str(k) for k in report["tables"]} | set(SHARED_AS_IS)
    for t in report["tables"].values():
        own |= {str(c) for k in ("missing_columns", "absent_optional") for c in t.get(k) or []}
        own |= {str(c) for c in t.get("date_shapes") or {}} | {str(t.get("source") or "")}
    out = net.sweep(out, own)
    out["withheld"] = net.withheld
    return dict(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mapping", type=Path, required=True)
    ap.add_argument("--source", choices=["csv", "cgrd_sql", "ssmix2"], default="csv")
    ap.add_argument("--path", help="export directory (csv) or storage root (ssmix2)")
    ap.add_argument("--dsn", help="SQLAlchemy DSN (cgrd_sql): a test database only; a real one goes by --dsn-env")
    ap.add_argument("--dsn-env", help="the environment variable that holds the SQLAlchemy DSN (never printed)")
    ap.add_argument("--rows", type=int, default=500, help="the most rows read from a table (0: no limit)")
    ap.add_argument("--day", help="read the rows changed on this day (YYYY-MM-DD) of each table's change-time column")
    ap.add_argument("--since", help="read rows changed from this time on (YYYY-MM-DD[ HH:MM:SS])")
    ap.add_argument("--until", help="with --since: and before this time")
    ap.add_argument("--chart-pattern", help="the site's chart number pattern: a code that matches is not written out")
    ap.add_argument("--min-patients", type=int, help="a code is written to the share report when this many have it (5)")
    ap.add_argument("--columns-only", action="store_true", help="read no row: which mapped columns each table has")
    ap.add_argument("--share", type=Path, help="write the report that may leave the site, and print only that")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    where = args.path or args.dsn or ""
    if args.dsn_env:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.dsn_env):  # the string itself was given: not echoed
            raise SystemExit("--dsn-env takes the name of an environment variable, not the connection string")
        where = os.environ.get(args.dsn_env, "")
        if not where:
            raise SystemExit(f"the environment variable {args.dsn_env} is not set")
    if args.until and not args.since:
        raise SystemExit("--until needs --since (or give --day)")
    since, until = args.since, args.until
    if args.day:
        day = date.fromisoformat(args.day)
        since, until = f"{day.isoformat()} 00:00:00", f"{(day + timedelta(days=1)).isoformat()} 00:00:00"
    if args.columns_only:
        rep = columns_only(args.mapping, args.source, where)
        text = json.dumps(rep, ensure_ascii=False, indent=1)
        if args.share:
            args.share.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0 if rep["passed"] else 1
    rep = check(args.mapping, args.source, where, args.rows, since, until, args.chart_pattern, args.min_patients)
    if args.share:
        text = json.dumps(rep["share"], ensure_ascii=False, indent=1)
        args.share.write_text(text + "\n", encoding="utf-8")
        print(text)
        print(f"Send back only this file: {args.share}")
        return 0 if rep["passed"] else 1
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        for table, t in rep["tables"].items():
            line = f"{table:13s} {t['rows_read']:>5} rows"
            if t.get("cannot_be_read"):
                print(f"{line}  CANNOT BE READ ({t['cannot_be_read']})")
                continue
            if t.get("missing_columns"):
                line += f"  MISSING {', '.join(t['missing_columns'])}"
            elif "resources" in t:
                line += f"  → {t['resources']} resources, {len(t['structural_errors'])} structural errors"
                if t.get("rejected"):
                    line += f", {sum(t['rejected'].values())} rows refused ({'; '.join(sorted(t['rejected']))})"
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
            f"{rep['invalid']} invalid resources, {rep['rejected']} rows refused"
        )
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
