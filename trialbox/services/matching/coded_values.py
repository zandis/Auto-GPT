"""The coded records behind an answer, as a person checks them (card T-514, D-362, review UX-008).

A criterion answered from the coded records carried only the record ids (``resource_refs``): the patient page showed
"met · coded records" with nothing to check, and the not-matched list "1 record". This module reads, beside the
approved SQL and after it has answered, the records those ids name on the same lake snapshot and puts on the
evidence what a person checks against the chart: the record's own value and unit, its date and its code
(``Evidence.coded``, latest first, at most three). It is display only:

* nothing here changes a verdict, a tier or a reason; matching never reads ``coded`` back;
* the value is the record's own number in the record's own unit, as stored (a censored result keeps its
  comparator, ``<0.3``), never a converted number, so what the page shows is what the chart shows (STD-001);
* a criterion on age or sex has no record: its value is the age in complete years on the run date, or the sex, from
  the patient row;
* a coded answer with no record behind it (nothing carries the criterion's codes, or nothing meets its limits) gets an
  empty list, so the page can say so in words: no met or not met row without a value or a quote;
* a record the lake does not hold (a site fact, a note) is left out; a failing lake read leaves every row as it was.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableSequence
from datetime import date
from typing import Any, Protocol

from criteria_compiler.terminology.mapper import SYSTEMS
from tb_contracts import Atom, BoolExpr, CodedValue, CriterionIR, CriterionVerdict, Evidence

SHOWN = 3  # records shown per criterion: the latest first
DOMAINS = ("observation", "condition", "medication", "procedure", "report", "encounter", "claim")

# one row per record id: the record's own value, unit, date and code; $1 pids, $2 record ids, $3 to $5 the ATC, NHI
# drug and department code systems
SQL = """
SELECT 'observation' AS domain, oid AS rid, code, system, CAST(effective AS DATE) AS d, value_num, unit, value_code,
       value_cmp
FROM observation WHERE list_contains(CAST($1 AS VARCHAR[]), pid) AND list_contains(CAST($2 AS VARCHAR[]), oid)
UNION ALL
SELECT 'condition', cid, code, system, coalesce(onset, recorded), NULL, NULL, NULL, NULL
FROM condition WHERE list_contains(CAST($1 AS VARCHAR[]), pid) AND list_contains(CAST($2 AS VARCHAR[]), cid)
UNION ALL
SELECT 'medication', mid, coalesce(nullif(atc, ''), nhi_code),
       CASE WHEN coalesce(atc, '') <> '' THEN CAST($3 AS VARCHAR) ELSE CAST($4 AS VARCHAR) END, authored,
       NULL, NULL, NULL, NULL
FROM medication WHERE list_contains(CAST($1 AS VARCHAR[]), pid) AND list_contains(CAST($2 AS VARCHAR[]), mid)
UNION ALL
SELECT 'procedure', prid, code, system, performed, NULL, NULL, NULL, NULL
FROM procedure WHERE list_contains(CAST($1 AS VARCHAR[]), pid) AND list_contains(CAST($2 AS VARCHAR[]), prid)
UNION ALL
SELECT 'report', rid, code, system, effective, NULL, NULL, NULL, NULL
FROM report WHERE list_contains(CAST($1 AS VARCHAR[]), pid) AND list_contains(CAST($2 AS VARCHAR[]), rid)
UNION ALL
SELECT 'encounter', eid, dept, CAST($5 AS VARCHAR), CAST(start AS DATE), NULL, NULL, NULL, NULL
FROM encounter WHERE list_contains(CAST($1 AS VARCHAR[]), pid) AND list_contains(CAST($2 AS VARCHAR[]), eid)
UNION ALL
SELECT 'claim', kid, product, CAST($4 AS VARCHAR), created, NULL, NULL, NULL, NULL
FROM claim WHERE list_contains(CAST($1 AS VARCHAR[]), pid) AND list_contains(CAST($2 AS VARCHAR[]), kid)
"""
CODE_SYSTEMS = (SYSTEMS["atc"], SYSTEMS["nhi_drug"], SYSTEMS["department"])
PATIENTS = "SELECT pid, birth_date, sex FROM patient WHERE list_contains(CAST($1 AS VARCHAR[]), pid)"


class _Lake(Protocol):
    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any: ...


def record_id(ref: str) -> str:
    """``Observation/o-1|2026-09-12`` (the v1 engine) or ``o-1`` (the cascade) → ``o-1``."""
    return ref.split("|", 1)[0].rsplit("/", 1)[-1]


def atoms(expr: Atom | BoolExpr | None) -> list[Atom]:
    if expr is None:
        return []
    if isinstance(expr, BoolExpr):
        return [a for x in expr.args for a in atoms(x)]
    return [expr]


def age_on(birth: date, day: date) -> int:
    """Complete years on ``day`` (the compiled SQL's age, ``criteria_compiler.semantics``)."""
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def _wanted(v: CriterionVerdict) -> list[str]:
    """The record ids of a coded answer, in the engine's order (oldest first); a note's document is not one."""
    ev = v.evidence
    if ev is None or ev.quote:
        return []
    return [record_id(r) for r in ev.resource_refs or [] if not r.startswith("DocumentReference/")]


def _demographic(c: CriterionIR | None) -> tuple[bool, bool]:
    """(age, sex): which demographic values the criterion's logic reads."""
    found = [a for a in atoms(c.logic if c is not None else None) if a.domain == "demographic"]
    return any(a.age is not None for a in found), any(a.sex is not None for a in found)


def _value(row: Mapping[str, Any]) -> CodedValue:
    d = row.get("d")
    num = row.get("value_num")
    return CodedValue(
        record=str(row["rid"]),
        domain=str(row["domain"]),
        code=str(row["code"]) if row.get("code") else None,
        system=str(row["system"]) if row.get("system") else None,
        date=d.isoformat() if isinstance(d, date) else (str(d)[:10] if d else None),
        value=float(num) if num is not None else None,
        unit=str(row["unit"]) if row.get("unit") else None,
        value_code=str(row["value_code"]) if row.get("value_code") else None,
        comparator=str(row["value_cmp"]) if row.get("value_cmp") else None,
    )


def attach(
    lake: _Lake,
    criteria: Iterable[CriterionIR],
    verdicts: Mapping[str, MutableSequence[CriterionVerdict]],
    run_date: date,
    snapshot: str | None,
) -> int:
    """Put the coded values on every coded answer of ``verdicts`` (``{pid: [CriterionVerdict]}``, changed in place).
    Returns how many answers got one. Two lake reads for the whole run; a failing read changes nothing."""
    by_id = {c.id: c for c in criteria}
    want: dict[str, set[str]] = {}
    people: set[str] = set()
    for pid, vs in verdicts.items():
        for v in vs:
            ids = _wanted(v)
            if ids:
                want.setdefault(pid, set()).update(ids)
            elif v.verdict in ("pass", "fail") and any(_demographic(by_id.get(v.id))):
                people.add(pid)
    rows: dict[tuple[str, str], CodedValue] = {}
    pats: dict[str, Mapping[str, Any]] = {}
    try:
        if want:
            rids = sorted({r for s in want.values() for r in s})
            for r in lake.query(SQL, [sorted(want), rids, *CODE_SYSTEMS], snapshot).to_pylist():
                rows.setdefault((str(r["domain"]), str(r["rid"])), _value(r))
        if people:
            pats = {str(r["pid"]): r for r in lake.query(PATIENTS, [sorted(people)], snapshot).to_pylist()}
    except Exception:  # display only: an older snapshot without a table, a lake that is down; the answers stand
        return 0
    found: dict[str, list[CodedValue]] = {}
    for (_, rid), cv in rows.items():
        found.setdefault(rid, []).append(cv)
    n = 0
    for pid, vs in verdicts.items():
        for i, v in enumerate(vs):
            c = by_id.get(v.id)
            doms = {a.domain for a in atoms(c.logic if c is not None else None)} or set(DOMAINS)
            shown: list[CodedValue] = []
            for rid in reversed(_wanted(v)):  # latest first
                hits = found.get(rid) or []
                hit = next((x for x in hits if x.domain in doms), hits[0] if hits else None)
                if hit is not None and hit not in shown:
                    shown.append(hit)
                if len(shown) == SHOWN:
                    break
            if not shown and pid in pats and v.verdict in ("pass", "fail"):
                shown = demographic_values(c, pats[pid], run_date)
            if not shown and none_behind(c, v):  # looked: no record behind a coded answer (the page says so)
                vs[i] = _with(v, [])
            elif shown:
                vs[i] = _with(v, shown)
                n += 1
    return n


def _with(v: CriterionVerdict, coded: list[CodedValue]) -> CriterionVerdict:
    ev = v.evidence or Evidence(resource_refs=[])
    return v.model_copy(update={"evidence": ev.model_copy(update={"coded": coded})})


def none_behind(c: CriterionIR | None, v: CriterionVerdict) -> bool:
    """A met or not met answer of a coded criterion with no record behind it: no record carries the criterion's codes
    (an exclusion with no such record, an inclusion not met for lack of one) or none meets its limits. Not an age or
    sex criterion (its value is the patient row's)."""
    ev = v.evidence
    return (
        c is not None
        and c.class_ == "structured"
        and v.verdict in ("pass", "fail")
        and not _wanted(v)
        and not (ev is not None and ev.quote)
        and not any(_demographic(c))
    )


def demographic_values(c: CriterionIR | None, patient: Mapping[str, Any], run_date: date) -> list[CodedValue]:
    """The age on the run date and the sex, for a criterion that reads them; nothing the patient row lacks."""
    age, sex = _demographic(c)
    out: list[CodedValue] = []
    birth = patient.get("birth_date")
    if age and isinstance(birth, date):
        out.append(CodedValue(record="patient", domain="demographic", code="age", date=run_date.isoformat(),
                              value=float(age_on(birth, run_date))))  # fmt: skip
    if sex and patient.get("sex"):
        out.append(CodedValue(record="patient", domain="demographic", code="sex", value_code=str(patient["sex"])))
    return out
