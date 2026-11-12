"""Screening reads the stored derived rows (D-442, the rest of D-190; CR-066), behind one audited flag.

The flag ``derived.stored_read`` (:func:`tb_common.derived_store.stored_read`, default off) decides for every path
alike: off, no path reads the store; on, every path that decides a score criterion applies :func:`apply_rows` to the
approved SQL's rows before it reads them (the v1 engine and the cascade's S1, so SCREEN, MICROBATCH of both kinds,
NAV, CASE and COHORT). One function on the SQL's own rows: the same patient on the same snapshot gets the same answer
whatever path asks.

The approved SQL still computes the score from the same component rows (the engines agree, D-275). This module only
ever takes a decided answer away, never decides one. For a criterion on a stored score (CDAI, SDAI, DAS28, eGFR) whose
answer is decided, the stored row of record must support it:

* the rows are read as they stood when the snapshot's first derive batch finished (``batch_run.finished_at``), so a
  re-run of a job reads what the job read; no finished batch, a batch under other definitions than the ruleset pinned
  (or, unpinned, than the box computes now), or a batch that failed for this patient: ``derived_not_stored``;
* a score atom's stored value is unknown when there is no row in the atom's window, the row is of another definition
  than pinned, it is anchored on another visit than the SQL used, or it has no value (``derived_unit``, ...);
  an open derived-vs-documented conflict is ``derived_vs_documented``. One age rule (the index date's): a row with no
  value because the patient was under 18 at the creatinine's date is ``derived_not_stored`` when the SQL decided
  (the patient is 18 at the index date), never ``derived_adult_only``;
* the criterion's logic is then evaluated in three values with each score atom at its stored comparison and every
  other atom free: the SQL's answer stands when some value of the other atoms gives it. So ``eGFR < 30 OR dialysis``
  with dialysis true and no creatinine stands, and ``NOT eGFR < 30`` with a stored eGFR of 20 does not. When it does
  not stand, the reason is the first unknown score atom's, else ``derived_vs_documented`` when a stored value is one
  a person kept, else ``derived_not_stored``.

BMI, BASDAI and ASDAS have no stored rows: the SQL alone decides them, as before. ``das28`` (ESR at a visit with an
ESR, else CRP) reads the stored DAS28-ESR row when that row used an ESR, else the DAS28-CRP row.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from criteria_compiler.semantics import atoms, window
from tb_common import derived, scores
from tb_common.derived_store import STORED, Batch, Latest
from tb_contracts import Atom, BoolExpr, CriterionIR

NOT_STORED = derived.NOT_STORED
VS_DOCUMENTED = derived.VS_DOCUMENTED
MAX_FREE = 8  # other atoms enumerated in the three-valued check (2^8 assignments at most)


class Store(Protocol):
    def batch(self, snapshot: str) -> Batch | None: ...

    def latest_many(
        self, pids: list[str], score: str, lo: date | None, hi: date, as_of: str | None = None
    ) -> dict[str, Latest]: ...


def stored_scores(score: str | None) -> tuple[str, ...]:
    """The stored scores that stand behind a criterion's score (``egfr`` is CKD-EPI 2021; ``das28`` either variant);
    empty for a score with no stored rows."""
    return tuple(s for s in scores.FOLLOWS.get(score or "", ()) if s in STORED)


def stored_scores_of(c: CriterionIR) -> bool:
    """Whether criterion ``c`` decides on a stored score."""
    return c.logic is not None and any(stored_scores(a.derived) for a in atoms(c.logic))


def compare(atom: Atom, value: float) -> bool | None:
    """The atom's comparison on a number (None when the atom compares nothing numeric)."""
    v = atom.value
    if v is None or v.op is None or v.num is None:
        return None
    if v.op == "between":
        return v.num2 is not None and v.num <= value <= v.num2
    return {
        ">": value > v.num,
        ">=": value >= v.num,
        "<": value < v.num,
        "<=": value <= v.num,
        "=": value == v.num,
    }.get(v.op)


def kleene(expr: Atom | BoolExpr, val: Mapping[int, bool | None]) -> bool | None:
    """Three-valued value of a criterion's logic, each atom's value by ``id(atom)``."""
    if isinstance(expr, Atom):
        return val.get(id(expr))
    parts = [kleene(a, val) for a in expr.args]
    if expr.op == "not":
        return None if parts[0] is None else not parts[0]
    if expr.op == "and":
        return False if False in parts else None if None in parts else True
    return True if True in parts else None if None in parts else False


@dataclass
class StoredScores:
    """The stored rows behind the score criteria of one screening (one snapshot, its index dates)."""

    batch: Batch | None
    pins: Mapping[str, Any]
    # (stored score, window from, window to, index date) -> {pid: Latest}
    rows: dict[tuple[str, int | None, int, date], dict[str, Latest]] = field(default_factory=dict)

    @classmethod
    def for_criteria(
        cls,
        store: Store,
        criteria: Iterable[CriterionIR],
        pids: Iterable[str],
        snapshot: str | None,
        index_dates: date | Iterable[date],
        pins: Mapping[str, Any] | None = None,
    ) -> StoredScores:
        crit = [c for c in criteria if c.logic is not None]
        wanted = {(s, window(a)) for c in crit for a in atoms(c.logic) for s in stored_scores(a.derived)}
        batch = store.batch(snapshot) if snapshot and wanted else None
        out = cls(batch if batch is not None and batch.holds(pins) else None, dict(pins or {}))
        if out.batch is None:
            return out
        days = [index_dates] if isinstance(index_dates, date) else sorted(set(index_dates))
        scope = sorted(set(pids))
        for s, w in sorted(wanted, key=lambda x: (x[0], x[1].from_days or 0, x[1].to_days)):
            for day in days:
                lo = None if w.from_days is None else day + timedelta(days=w.from_days)
                hi = day + timedelta(days=w.to_days)
                got = store.latest_many(scope, s, lo, hi, out.batch.finished_at or None)
                out.rows[(s, w.from_days, w.to_days, day)] = got
        return out

    def _row(self, a: Atom, pid: str, day: date) -> Latest | None:
        w = window(a)
        got = [self.rows.get((s, w.from_days, w.to_days, day), {}).get(pid) for s in stored_scores(a.derived)]
        if a.derived == "das28":
            esr, crp = got
            used_esr = esr is not None and any(i.get("component") == "esr" for i in esr.inputs)
            return esr if used_esr else crp
        return got[0]

    def _pin_holds(self, row: Latest, score: str) -> bool:
        raw = self.pins.get(score)
        if raw is None:  # approved before D-442: nothing pinned, the box's current definitions
            d = scores.definition(score)
            return bool(row.def_version == d["def_version"] and row.def_sha == d["sha256"])
        pin = scores.pin_fields(raw)
        return row.def_version == pin.get("def_version") and row.def_sha == pin.get("sha256")

    def _atom(self, a: Atom, pid: str, day: date, oids: set[str]) -> tuple[bool | None, str | None, bool]:
        """(the atom's stored truth or None, the reason it is None, whether the value is a documented one)."""
        row = self._row(a, pid, day)
        if row is None or row.row_id is None:
            return None, NOT_STORED, False
        score = (row.def_version or "").split("@", 1)[0]
        engine = next((s for s in stored_scores(a.derived) if scores.ENGINE[s] == score), None)
        if engine is None or not self._pin_holds(row, engine):
            return None, NOT_STORED, False
        if row.value is None:
            why = (row.reason or NOT_STORED).split(":", 1)[0]
            # one age rule: the SQL decided, so the patient is an adult at the index date; a row computed under 18 at
            # the creatinine's date is not this answer's row
            return None, NOT_STORED if why == derived.ADULT_ONLY else why, False
        if row.anchor_oid not in oids:  # the engine's visit is not the stored row's
            return None, NOT_STORED, False
        got = compare(a, row.value)
        return (True if got is None else got), None, row.source == "documented"

    def check(
        self, c: CriterionIR, pid: str, value: bool | None, refs: list[str], day: date | None = None
    ) -> str | None:
        """The reason the decided answer ``value`` of ``c`` at ``day`` does not stand on the stored rows, or None (it
        stands, or it was unknown already, or ``c`` reads no stored score). ``refs``: the SQL's evidence,
        ``oid|date``. ``day``: the index date (the first one read when None)."""
        if value is None or c.logic is None:
            return None
        score_atoms = [a for a in atoms(c.logic) if stored_scores(a.derived)]
        if not score_atoms:
            return None
        if self.batch is None or pid in self.batch.failed_pids:
            return NOT_STORED
        if day is None:
            day = next((k[3] for k in self.rows), date.min)
        oids = {r.split("|", 1)[0] for r in refs}
        val: dict[int, bool | None] = {}
        first_why: str | None = None
        documented = False
        for a in score_atoms:
            truth, why, doc = self._atom(a, pid, day, oids)
            val[id(a)] = truth
            first_why = first_why or why
            documented = documented or doc
        free = [a for a in atoms(c.logic) if id(a) not in val]
        if len(free) > MAX_FREE:  # too many to enumerate: only an unknown score atom decides
            return first_why
        for combo in itertools.product((True, False), repeat=len(free)):
            if kleene(c.logic, {**val, **{id(a): b for a, b in zip(free, combo, strict=True)}}) is value:
                return None
        if first_why is not None:
            return first_why
        return VS_DOCUMENTED if documented else NOT_STORED


def apply_rows(
    rows: list[dict[str, Any]],
    criteria: Iterable[CriterionIR],
    store: Store | None,
    snapshot: str | None,
    pins: Mapping[str, Any] | None = None,
) -> StoredScores | None:
    """The one place a path reads the store (D-442): each row of the approved SQL (``pid``, ``index_date``,
    ``C_<id>``, ``E_<id>``) whose decided score answer does not stand becomes ``C_<id>`` NULL with the reason first in
    ``E_<id>``, which every path then reads as it reads a score with no value. ``store`` None (the flag off): nothing
    changes. Returns what was read (None when nothing)."""
    crit = [c for c in criteria if stored_scores_of(c)]
    if store is None or not crit or not rows:
        return None
    days = {r["index_date"] for r in rows}
    held = StoredScores.for_criteria(store, crit, {str(r["pid"]) for r in rows}, snapshot, days, pins)
    for r in rows:
        for c in crit:
            key = f"C_{c.id}"
            if key not in r:
                continue
            refs = [x for x in str(r.get(f"E_{c.id}") or "").split(";") if x]
            why = held.check(c, str(r["pid"]), r[key], refs, r["index_date"])
            if why is not None:
                r[key] = None
                r[f"E_{c.id}"] = ";".join([f"{why}:stored", *refs])
    return held


def unverified(criteria: Iterable[CriterionIR], store: Store | None, snapshot: str | None) -> bool:
    """The list header's line (D-442): the flag is on, the criteria read stored scores and the snapshot has no
    finished derive batch, so every score answer reads as needing information."""
    if store is None or not any(stored_scores_of(c) for c in criteria):
        return False
    return not snapshot or store.batch(snapshot) is None
