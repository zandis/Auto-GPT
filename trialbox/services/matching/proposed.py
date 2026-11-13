"""The one rule of site set-up (D-131, D-135): a proposed fact can only send a patient to "needs information".

A fact the model read from a chart (``sitesetup.charts``) is *proposed* until a coordinator confirms or corrects it.
It lives in the lake's ``site_fact`` table only (``lake.flatten``): the compiled SQL never reads that table, so a
proposed fact can never count as met and can never exclude. This module is the other half of the rule. Beside the
approved SQL (unchanged, as for D-130's unknown code systems), for every criterion whose answer is decided (TRUE or
FALSE) it asks: could a proposed fact of this patient change the answer? If so, the answer becomes ``unknown`` with
the reason ``proposed_fact`` and the facts as evidence, so the patient goes to "needs information" and a person
looks. Once a coordinator confirms the fact, it is a coded record like any other and counts (and may exclude).

A suspected diagnosis (D-142: SS-MIX2 PRB-13 疑い, FHIR ``verificationStatus`` provisional or differential) follows
the same rule: the lake lists it in ``site_fact`` with basis ``suspected`` and keeps it out of ``condition``, and the
reason is ``suspected_diagnosis``. "肺癌の疑い" never makes "history of malignancy" true.

Whether a fact *could* change an answer, per atom of the criterion's logic:

* a condition or medication present (``any``, ``count>=``, a duration): a fact makes it truer, so it matters when
  the answer is FALSE; under ``not`` or with ``none`` it makes it falser, so it matters when the answer is TRUE;
* a value (a lab, a derived value such as eGFR, the age from a birth date, the sex): a new value can move the answer
  either way, so it matters whenever the answer is decided.

A fact matters to an atom when it is of the atom's domain, its code is in the atom's ValueSet (or a family of it),
or it has no code at all, and its date is in the atom's window (an undated fact always counts). A criterion that is
already unknown stays unknown.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from criteria_compiler.semantics import Kind, kind, window
from criteria_compiler.terminology.mapper import FAMILY_EXT
from tb_contracts import Atom, BoolExpr, CriterionIR

PROPOSED_FACT = "proposed_fact"
SUSPECTED_DIAGNOSIS = "suspected_diagnosis"  # D-142: a diagnosis recorded as suspected (疑い, provisional)
SQL = """
SELECT fid, pid, domain, coalesce(code, '') AS code, coalesce(system, '') AS system, d, basis
FROM site_fact
WHERE basis IN ('proposed', 'suspected')
  AND (CAST($1 AS VARCHAR[]) IS NULL OR list_contains(CAST($1 AS VARCHAR[]), pid))
ORDER BY pid, fid
"""
#: is there a ``site_fact`` table (or view) in the snapshot: one row, one number
TABLE_SQL = (
    "SELECT (SELECT count(*) FROM duckdb_tables() WHERE lower(table_name) = 'site_fact') + "
    "(SELECT count(*) FROM duckdb_views() WHERE lower(view_name) = 'site_fact') AS n"
)
DEMOGRAPHIC_CODES = {"birth_date": "age", "sex": "sex"}


class _Lake(Protocol):
    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any: ...


def _no_site_facts(lake: _Lake, snapshot: str | None) -> bool:
    """After a query of ``site_fact`` failed: True only when the lake answers that the snapshot has no such table
    (it was built before step 5b and holds no site fact). Asked of the lake, not read out of the failure's text
    (NEW-TRUST-6, D-649): an error's text is whatever its author put in it. Anything but one row with the number
    0, and a failure of the question itself, is False: the caller's failure then stops the run (D-127, F-04: a list
    must never silently drop the rule)."""
    try:
        rows = lake.query(TABLE_SQL, [], snapshot).to_pylist()
    except Exception:
        return False
    return len(rows) == 1 and type(rows[0].get("n")) is int and rows[0]["n"] == 0


def _site_fact_rows(lake: _Lake, sql: str, params: list[Any], snapshot: str | None) -> list[dict[str, Any]] | None:
    """The rows of a query of ``site_fact``; None when the snapshot has no such table (:func:`_no_site_facts`); any
    other failure is raised.

    With no snapshot named, a failed query and the question after it would each read "current", which can move in
    between (the review of D-649). So after a failure the lake is asked once which snapshot is current, and the
    query is put again, and then the question, to that name. A stand-in that cannot name its snapshot is asked the
    question as it was asked the query."""
    try:
        return list(lake.query(sql, params, snapshot).to_pylist())
    except Exception:
        name = snapshot
        current = getattr(lake, "snapshot", None)
        if name is None and callable(current):
            name = current()
            if name is None:
                raise
            try:
                return list(lake.query(sql, params, name).to_pylist())
            except Exception:
                if _no_site_facts(lake, name):
                    return None
                raise
        if _no_site_facts(lake, name):
            return None
        raise


@dataclass(frozen=True)
class FactRow:
    fid: str
    domain: str
    code: str
    system: str
    d: date | None
    basis: str = "proposed"


def signed_atoms(expr: Atom | BoolExpr, positive: bool = True) -> list[tuple[Atom, str]]:
    """Every atom with the direction a new fact pushes the criterion: ``+`` (truer), ``-`` (falser), ``±``."""
    if isinstance(expr, BoolExpr):
        flip = expr.op == "not"
        return [x for a in expr.args for x in signed_atoms(a, positive != flip)]
    try:
        k = kind(expr)
    except ValueError:
        return [(expr, "±")]
    if k in (Kind.DEMOGRAPHIC, Kind.OBS_VALUE, Kind.DERIVED):
        return [(expr, "±")]
    base = "-" if k is Kind.PRESENCE and (expr.quantifier or "any") == "none" else "+"
    if not positive:
        base = "-" if base == "+" else "+"
    return [(expr, base)]


def _vs_codes(vs: Mapping[str, Any] | None) -> tuple[set[str], list[str]]:
    codes: set[str] = set()
    for inc in ((vs or {}).get("compose") or {}).get("include") or []:
        codes |= {str(c.get("code")) for c in inc.get("concept") or [] if c.get("code")}
    fams = []
    for ext in (vs or {}).get("extension") or []:
        if ext.get("url") == FAMILY_EXT and "|" in str(ext.get("valueString", "")):
            fams.append(str(ext["valueString"]).rsplit("|", 1)[1])
    return codes, fams


@dataclass
class Proposed:
    """Per patient, the proposed facts of one lake snapshot."""

    rows: dict[str, list[FactRow]] = field(default_factory=dict)
    valuesets: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        lake: _Lake,
        pids: Iterable[str] | None,
        snapshot: str | None,
        valuesets: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> Proposed:
        scope = None if pids is None else sorted(set(pids))
        if scope is not None and not scope:
            return cls(valuesets=valuesets or {})
        # a snapshot built before step 5b has no site_fact table: it holds no proposed fact. Any other failure
        # stops the run (D-127, F-04): a list must never silently drop the rule.
        found = _site_fact_rows(lake, SQL, [scope], snapshot)
        if found is None:
            return cls(valuesets=valuesets or {})
        out: dict[str, list[FactRow]] = {}
        for r in found:
            out.setdefault(str(r["pid"]), []).append(
                FactRow(
                    str(r["fid"]),
                    str(r["domain"]),
                    str(r["code"] or ""),
                    str(r["system"] or ""),
                    r["d"],
                    str(r.get("basis") or "proposed"),
                )
            )
        return cls(out, valuesets or {})

    @classmethod
    def for_criteria(
        cls,
        lake: _Lake,
        criteria: Iterable[CriterionIR],
        pids: Iterable[str] | None,
        snapshot: str | None,
        valuesets: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> Proposed:
        if not any(c.logic is not None for c in criteria):
            return cls(valuesets=valuesets or {})
        return cls.load(lake, pids, snapshot, valuesets)

    def patients(self) -> set[str]:
        return set(self.rows)

    def _matters(self, a: Atom, f: FactRow, index_date: date) -> bool:
        if a.domain == "demographic":
            if f.domain != "demographic":
                return False
            return (f.code == "birth_date" and a.age is not None) or (f.code == "sex" and a.sex is not None)
        if a.derived is not None and f.domain == "demographic":
            return True  # eGFR and the like use the age and the sex
        if f.domain != a.domain:
            return False
        if f.code and a.valueset not in ("", "NONE"):
            codes, fams = _vs_codes(self.valuesets.get(a.valueset))
            if (codes or fams) and f.code not in codes and not any(f.code.startswith(p) for p in fams):
                return False
        if f.d is None:
            return True
        try:
            w = window(a)
        except ValueError:
            return True
        lo = None if w.from_days is None else index_date + timedelta(days=w.from_days)
        hi = index_date + timedelta(days=w.to_days)
        return not (f.d > hi or (lo is not None and f.d < lo))

    def refs(self, c: CriterionIR, pid: str, index_date: date, value: bool | None) -> list[str]:
        """``fid|yyyy-mm-dd`` of the proposed facts that could change the decided answer ``value`` of criterion
        ``c``'s logic at ``index_date``. Empty: the answer stands (or it was already unknown)."""
        rows = self.rows.get(pid)
        if not rows or value is None or c.logic is None:
            return []
        out: list[str] = []
        for a, sign in signed_atoms(c.logic):
            if not (sign == "±" or (sign == "+" and value is False) or (sign == "-" and value is True)):
                continue
            for f in rows:
                if self._matters(a, f, index_date):
                    ref = f"{f.fid}|{f.d.isoformat()}" if f.d else f.fid
                    if ref not in out:
                        out.append(ref)
        return out

    def reason(self, pid: str, refs: list[str]) -> str:
        """The reason code for ``refs``: ``suspected_diagnosis`` when every one is a suspected diagnosis (D-142),
        else ``proposed_fact``."""
        ids = {r.split("|")[0] for r in refs}
        bases = {f.basis for f in self.rows.get(pid, []) if f.fid in ids}
        return SUSPECTED_DIAGNOSIS if bases == {"suspected"} else PROPOSED_FACT


BASIS_SQL = "SELECT DISTINCT pid, basis FROM site_fact WHERE basis IN ('proposed', 'confirmed') ORDER BY pid, basis"


def site_basis(lake: _Lake, snapshot: str | None) -> tuple[set[str], set[str]]:
    """``(patients with a confirmed fact, patients with a proposed fact)`` of one snapshot (empty for a snapshot
    built before step 5b, which has no site facts)."""
    rows = _site_fact_rows(lake, BASIS_SQL, [], snapshot)
    if rows is None:
        return set(), set()
    confirmed = {str(r["pid"]) for r in rows if r["basis"] == "confirmed"}
    proposed = {str(r["pid"]) for r in rows if r["basis"] == "proposed"}
    return confirmed, proposed


__all__ = [
    "PROPOSED_FACT",
    "SQL",
    "SUSPECTED_DIAGNOSIS",
    "TABLE_SQL",
    "FactRow",
    "Proposed",
    "signed_atoms",
    "site_basis",
]
