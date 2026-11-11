"""Screening reads the stored derived rows (D-442, the rest of D-190; CR-066).

The derive batch (:func:`tb_common.derived_store.run_batch`) writes every stored score of a lake snapshot as a row
with its provenance, and keeps the derived-vs-documented conflicts. The approved SQL still computes the score from
the same component rows (the engines agree, D-275), and this module is the other half, beside it as
:mod:`matching.proposed` is: for every criterion on a stored score whose answer is decided (TRUE or FALSE), the
stored row of record must stand behind it. When it does not, the answer becomes unknown ("needs information"), never
a new decided answer:

* no finished derive batch of the snapshot being screened, a batch run under other definitions than the box
  computes now, or a batch that failed for this patient: ``derived_not_stored``;
* no current stored row in the atom's window, a row of another definition version or text than the ruleset pinned at
  approval (``derived_pins``), or a row anchored on another visit than the engine's: ``derived_not_stored``;
* a stored row with no value: its own reason (``derived_unit``, ``derived_adult_only``, ...);
* a stored row with an open derived-vs-documented conflict: ``derived_vs_documented``;
* a single-score criterion whose comparison gives another answer on the stored value (the value a person kept when
  they chose the documented one, else the computed one): ``derived_vs_documented`` when the value is the documented
  one, else ``derived_not_stored``.

A criterion that is already unknown stays as it is. ``das28`` (ESR at a visit with an ESR, else CRP) reads the stored
DAS28-ESR row when that row used an ESR, else the DAS28-CRP row. BMI, BASDAI and ASDAS have no stored rows: the SQL
alone decides them, as before.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from criteria_compiler.semantics import atoms, window
from tb_common import scores
from tb_common.derived_store import STORED, Batch, Latest
from tb_contracts import Atom, CriterionIR

NOT_STORED = "derived_not_stored"
VS_DOCUMENTED = "derived_vs_documented"


class Store(Protocol):
    def batch(self, snapshot: str) -> Batch | None: ...

    def latest_many(self, pids: list[str], score: str, lo: date | None, hi: date) -> dict[str, Latest]: ...


def stored_scores(score: str | None) -> tuple[str, ...]:
    """The stored scores that stand behind a criterion's score (``egfr`` is CKD-EPI 2021; ``das28`` either variant);
    empty for a score with no stored rows."""
    return tuple(s for s in scores.FOLLOWS.get(score or "", ()) if s in STORED)


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


@dataclass
class StoredScores:
    """The stored rows behind the score criteria of one screening (one snapshot, one index date)."""

    batch: Batch | None
    pins: Mapping[str, Any]
    # (stored score, window) -> {pid: Latest}
    rows: dict[tuple[str, int | None, int], dict[str, Latest]] = field(default_factory=dict)

    @classmethod
    def for_criteria(
        cls,
        store: Store,
        criteria: Iterable[CriterionIR],
        pids: Iterable[str],
        snapshot: str | None,
        index_date: date,
        pins: Mapping[str, Any] | None = None,
    ) -> StoredScores:
        crit = [c for c in criteria if c.logic is not None]
        wanted = {(s, window(a)) for c in crit for a in atoms(c.logic) for s in stored_scores(a.derived)}
        batch = store.batch(snapshot) if snapshot and wanted else None
        out = cls(batch if batch is not None and batch.current() else None, dict(pins or {}))
        if out.batch is None:
            return out
        scope = sorted(set(pids))
        for s, w in sorted(wanted, key=lambda x: (x[0], x[1].from_days or 0, x[1].to_days)):
            lo = None if w.from_days is None else index_date + timedelta(days=w.from_days)
            hi = index_date + timedelta(days=w.to_days)
            out.rows[(s, w.from_days, w.to_days)] = store.latest_many(scope, s, lo, hi)
        return out

    def _row(self, a: Atom, pid: str) -> Latest | None:
        w = window(a)
        got = [self.rows.get((s, w.from_days, w.to_days), {}).get(pid) for s in stored_scores(a.derived)]
        if a.derived == "das28":
            esr, crp = got
            used_esr = esr is not None and any(i.get("component") == "esr" for i in esr.inputs)
            return esr if used_esr else crp
        return got[0]

    def _pin_holds(self, row: Latest, score: str) -> bool:
        raw = self.pins.get(score)
        if raw is None:  # approved before D-442: nothing pinned, the box's current definitions
            return True
        pin = scores.pin_fields(raw)
        return row.def_version == pin.get("def_version") and row.def_sha == pin.get("sha256")

    def check(self, c: CriterionIR, pid: str, value: bool | None, refs: list[str]) -> str | None:
        """The reason the decided answer ``value`` of ``c`` does not stand on the stored rows, or None (it stands,
        or it was unknown already, or ``c`` reads no stored score). ``refs``: the SQL's evidence, ``oid|date``."""
        if value is None or c.logic is None:
            return None
        score_atoms = [a for a in atoms(c.logic) if stored_scores(a.derived)]
        if not score_atoms:
            return None
        if self.batch is None or pid in self.batch.failed_pids:
            return NOT_STORED
        oids = {r.split("|", 1)[0] for r in refs}
        for a in score_atoms:
            row = self._row(a, pid)
            if row is None or row.row_id is None:
                return NOT_STORED
            score = (row.def_version or "").split("@", 1)[0]
            engine = next((s for s in stored_scores(a.derived) if scores.ENGINE[s] == score), None)
            if engine is None or not self._pin_holds(row, engine):
                return NOT_STORED
            if row.value is None:
                return (row.reason or NOT_STORED).split(":", 1)[0]
            if row.anchor_oid not in oids:  # the engine's visit is not the stored row's
                return NOT_STORED
        if len(score_atoms) == 1 and c.logic is score_atoms[0]:
            a = score_atoms[0]
            row = self._row(a, pid)
            assert row is not None and row.value is not None
            got = compare(a, row.value)
            if got is not None and got != value:
                return VS_DOCUMENTED if row.source == "documented" else NOT_STORED
        return None
