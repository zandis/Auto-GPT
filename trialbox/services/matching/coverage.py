"""Code-system coverage: records in a code system the mapping does not know (review F-10, D-130).

A structured inclusion that is FALSE is a hard exclusion for every shipped ruleset (v1 semantics), outside the
two-model rule. D-113 made a code inside a grouper's family but outside its list ``unknown``. This module covers the
other silent case: a diagnosis or a medicine whose code is in no system the mapping knows, so no ValueSet can ever
match it, e.g.

* a local 保険病名 with no ICD-10 alternate and no row in ``byomei_to_icd10.csv`` (the SS-MIX2 reader then leaves
  the code empty), WHO ICD-10 or ICD-9-CM under its own URI, a free-text diagnosis;
* a medicine without an ATC code (a YJ or local drug code the lookup does not hold).

Such a row cannot answer the criterion either way. For a patient who has one in the window of a positive condition or
medication atom of an inclusion, a FALSE from the compiled SQL means "not found among the codes we can read", not
"absent": the runtime turns it into ``unknown`` with the reason ``unknown_code_system`` and the rows as evidence, so a
person looks instead of the patient being dropped. The approved SQL stays byte for byte as approved (the check runs
beside it, on the same lake snapshot); exclusions are untouched (FALSE keeps the patient anyway).

Known systems: diagnoses coded in ICD-10-CM or in any system the ruleset's condition ValueSets use; medicines with
an ATC code (every medication ValueSet is built from ATC classes, D-122).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from criteria_compiler.semantics import Kind, kind, window
from tb_contracts import Atom, BoolExpr, CriterionIR

ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
DOMAINS = ("condition", "medication")
UNKNOWN_CODE_SYSTEM = "unknown_code_system"

# rows of the two domains whose code no ValueSet can read; $1 pids (NULL = every patient), $2 known diagnosis systems
SQL = """
SELECT pid, 'condition' AS domain, cid AS rid, coalesce(onset, recorded) AS d, coalesce(system, '') AS system
FROM condition
WHERE (CAST($1 AS VARCHAR[]) IS NULL OR list_contains(CAST($1 AS VARCHAR[]), pid))
  AND (coalesce(code, '') = '' OR coalesce(system, '') = '' OR NOT list_contains(CAST($2 AS VARCHAR[]), system))
UNION ALL
SELECT pid, 'medication' AS domain, mid AS rid, authored AS d, '' AS system
FROM medication
WHERE (CAST($1 AS VARCHAR[]) IS NULL OR list_contains(CAST($1 AS VARCHAR[]), pid))
  AND coalesce(atc, '') = ''
ORDER BY pid, domain, d, rid
"""


class _Lake(Protocol):
    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any: ...


@dataclass(frozen=True)
class GapRow:
    domain: str
    rid: str
    d: date | None
    system: str


def known_systems(valuesets: Mapping[str, Mapping[str, Any]] | None) -> list[str]:
    """ICD-10-CM plus every system a ValueSet of the ruleset lists (only condition rows are checked against it)."""
    out = {ICD10CM}
    for vs in (valuesets or {}).values():
        for inc in ((vs or {}).get("compose") or {}).get("include") or []:
            if inc.get("system"):
                out.add(str(inc["system"]))
    return sorted(out)


def positive_atoms(expr: Atom | BoolExpr, positive: bool = True) -> list[Atom]:
    """Condition / medication atoms that a matching record makes truer (not under ``not``, quantifier not ``none``):
    the atoms whose FALSE can mean "the record is there, coded in a system nobody can read"."""
    if isinstance(expr, BoolExpr):
        flip = expr.op == "not"
        return [a for x in expr.args for a in positive_atoms(x, positive != flip)]
    if expr.domain not in DOMAINS:
        return []
    try:
        k = kind(expr)
    except ValueError:
        return []
    if k is Kind.MED_DURATION or (k is Kind.PRESENCE and (expr.quantifier or "any") != "none"):
        return [expr] if positive else []
    return []


def applies(c: CriterionIR) -> bool:
    """The criterion is an inclusion with at least one positive condition / medication atom."""
    return c.kind == "inclusion" and c.logic is not None and bool(positive_atoms(c.logic))


@dataclass
class Coverage:
    """Per patient, the rows in an unknown code system (both domains), from one lake snapshot."""

    rows: dict[str, list[GapRow]] = field(default_factory=dict)

    @classmethod
    def load(
        cls, lake: _Lake, pids: Iterable[str] | None, snapshot: str | None, known: Iterable[str] = (ICD10CM,)
    ) -> Coverage:
        scope = None if pids is None else sorted(set(pids))
        if scope is not None and not scope:
            return cls()
        table = lake.query(SQL, [scope, sorted(set(known))], snapshot)
        out: dict[str, list[GapRow]] = {}
        for r in table.to_pylist():
            out.setdefault(str(r["pid"]), []).append(
                GapRow(str(r["domain"]), str(r["rid"]), r["d"], str(r["system"] or ""))
            )
        return cls(out)

    @classmethod
    def for_criteria(
        cls,
        lake: _Lake,
        criteria: Iterable[CriterionIR],
        pids: Iterable[str] | None,
        snapshot: str | None,
        valuesets: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> Coverage:
        """Loaded only when an inclusion can be affected (no lake query otherwise)."""
        if not any(applies(c) for c in criteria):
            return cls()
        return cls.load(lake, pids, snapshot, known_systems(valuesets))

    def patients(self, domain: str) -> set[str]:
        return {pid for pid, rows in self.rows.items() if any(r.domain == domain for r in rows)}

    def refs(self, c: CriterionIR, pid: str, index_date: date) -> list[str]:
        """``rid|yyyy-mm-dd`` of the unknown-system rows that could have answered a positive atom of inclusion ``c``
        at ``index_date`` (in the atom's window; an undated row counts). Empty: the FALSE stands."""
        rows = self.rows.get(pid)
        if not rows or not applies(c):
            return []
        out: list[str] = []
        for a in positive_atoms(c.logic):
            w = window(a)
            lo = None if w.from_days is None else index_date + timedelta(days=w.from_days)
            hi = index_date + timedelta(days=w.to_days)
            for r in rows:
                if r.domain != a.domain:
                    continue
                if r.d is not None and (r.d > hi or (lo is not None and r.d < lo)):
                    continue
                ref = f"{r.rid}|{r.d.isoformat()}" if r.d else r.rid
                if ref not in out:
                    out.append(ref)
        return out


def unknown_system_counts(rows: Iterable[Any]) -> int:
    """Patients on a candidate list with a criterion left unknown for an unknown code system (S3, the SCREEN report)."""
    n = 0
    for r in rows:
        crits = r.get("criteria") if isinstance(r, Mapping) else getattr(r, "criteria", None)
        for v in crits or []:
            ev = v.get("evidence") if isinstance(v, Mapping) else getattr(v, "evidence", None)
            reason = (ev or {}).get("reason") if isinstance(ev, Mapping) else getattr(ev, "reason", None)
            if reason == UNKNOWN_CODE_SYSTEM:
                n += 1
                break
    return n


__all__ = [
    "DOMAINS",
    "ICD10CM",
    "SQL",
    "UNKNOWN_CODE_SYSTEM",
    "Coverage",
    "GapRow",
    "applies",
    "known_systems",
    "positive_atoms",
    "unknown_system_counts",
]
