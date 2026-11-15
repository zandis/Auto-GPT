"""The code systems a site's data carries (F11 of the first look at a real export, D-795).

A coded criterion matches its value set's codes against the rows of one domain. When no row of that domain is coded
in any system the value set lists (a site with no ATC on any table, drugs only as NHI claim lines; no LOINC; a WHO
ICD-10 value set against ICD-10-CM diagnoses), the compiled SQL answers FALSE for every patient: a silent "absent".
This module reads, once per run and from the same lake snapshot, which systems each domain's rows carry, and names a
criterion's atoms whose value set has none of them. The runtime then turns the answer such an atom could have changed
into unknown with the reason ``code_system_not_carried``: a FALSE where a record would have made the atom truer, a TRUE
where it would have made it falser ("none"). The approved SQL is unchanged, as with D-130 (``matching.coverage``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from criteria_compiler.semantics import Kind, kind
from criteria_compiler.terminology.mapper import SYSTEMS, YJ_STEM
from tb_common.reasons import Reason
from tb_contracts import Atom, BoolExpr, CriterionIR

NOT_CARRIED = Reason.CODE_SYSTEM_NOT_CARRIED.value

_CODED = "coalesce(code, '') <> '' AND coalesce(system, '') <> ''"


def _has(domain: str, system: str, table: str, col: str) -> str:
    return f"SELECT '{domain}', '{system}' WHERE EXISTS (SELECT 1 FROM {table} WHERE coalesce({col}, '') <> '')"


# the systems each domain's rows carry, the columns the compiled SQL matches (compile_sql.generator.PRESENCE)
_TABLES = ("condition", "procedure", "report", "observation")
SQL = "\nUNION ALL ".join(
    [f"SELECT DISTINCT '{t}' AS domain, system FROM {t} WHERE {_CODED}" for t in _TABLES]
    + [
        _has("medication", SYSTEMS["atc"], "medication", "atc"),
        _has("medication", SYSTEMS["nhi_drug"], "medication", "nhi_code"),
        _has("medication", YJ_STEM, "medication", "nhi_code"),
        _has("encounter", SYSTEMS["department"], "encounter", "dept"),
        _has("claim", SYSTEMS["nhi_drug"], "claim", "product"),
    ]
)
DOMAINS = ("condition", "procedure", "report", "observation", "medication", "encounter", "claim")


class _Lake(Protocol):
    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any: ...


def _atoms(expr: Atom | BoolExpr, positive: bool = True) -> list[tuple[Atom, bool]]:
    """The presence and medication-duration atoms, each with whether a matching record makes the criterion truer."""
    if isinstance(expr, BoolExpr):
        flip = expr.op == "not"
        return [x for a in expr.args for x in _atoms(a, positive != flip)]
    if expr.domain not in DOMAINS or not expr.valueset or expr.valueset == "NONE":
        return []
    try:
        k = kind(expr)
    except ValueError:
        return []
    if k is Kind.MED_DURATION:
        return [(expr, positive)]
    if k is Kind.PRESENCE:
        return [(expr, positive != ((expr.quantifier or "any") == "none"))]
    return []


def _systems(vs: Mapping[str, Any] | None) -> set[str]:
    return {str(i["system"]) for i in ((vs or {}).get("compose") or {}).get("include") or [] if i.get("system")}


@dataclass(frozen=True)
class Carried:
    """Per domain, the code systems the snapshot's rows carry; empty (not read): no check."""

    systems: dict[str, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, lake: _Lake, snapshot: str | None) -> Carried:
        out: dict[str, set[str]] = {d: set() for d in DOMAINS}
        for r in lake.query(SQL, None, snapshot).to_pylist():
            out[str(r["domain"])].add(str(r["system"]))
        return cls({d: frozenset(s) for d, s in out.items()})

    @classmethod
    def for_criteria(cls, lake: _Lake, criteria: list[CriterionIR], snapshot: str | None) -> Carried:
        """Read only when a criterion has a coded atom (no lake query otherwise)."""
        if not any(c.logic is not None and _atoms(c.logic) for c in criteria):
            return cls()
        return cls.load(lake, snapshot)

    def missing(self, c: CriterionIR, valuesets: Mapping[str, Mapping[str, Any]] | None) -> tuple[list[str], list[str]]:
        """``domain: system`` of the atoms whose value set has no system the domain carries: those a record would
        make truer, and those it would make falser."""
        if not self.systems or c.logic is None:
            return [], []
        truer: list[str] = []
        falser: list[str] = []
        for atom, up in _atoms(c.logic):
            listed = _systems((valuesets or {}).get(str(atom.valueset)))
            if not listed or listed & self.systems.get(atom.domain, frozenset()):
                continue
            label = f"{atom.domain}: {', '.join(sorted(listed))}"
            side = truer if up else falser
            if label not in side:
                side.append(label)
        return truer, falser

    def doubt(self, c: CriterionIR, valuesets: Mapping[str, Mapping[str, Any]] | None, value: bool | None) -> list[str]:
        """The missing systems that leave ``value`` unsettled: a FALSE a record could have made TRUE, or a TRUE it
        could have made FALSE. Empty: the answer stands."""
        if value is None:
            return []
        truer, falser = self.missing(c, valuesets)
        return truer if value is False else falser


__all__ = ["DOMAINS", "NOT_CARRIED", "SQL", "Carried"]
