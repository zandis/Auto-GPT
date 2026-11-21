"""Criterion model v3 in the cascade, step 1 (D-1263; plan 10 card 10A-5; review 15, B16-1 and its decision 1).

A ruleset's criterion file that says ``ir_version`` 3.0.0 is a criterion of model v3 (``Ruleset.v3``). S1 evaluates
the structured ones here; a v1 ruleset has none and this stage does nothing, so its answers are what they were.

**One window convention.** A v3 window hangs on an anchor: the index date as in v1, the study's planned start for
this patient, the screening date, or an event of the patient's own record (the first or the last). The criterion is
lowered to the v1 criterion with index-relative windows (``tb_contracts.criterion_ir.index_form``) and the compiled
SQL of the existing generator is run with the index date set to the anchor's date. So the interval is the existing
one, ``[anchor + from_days, anchor + to_days]`` with both ends inside, on the local calendar date of the record
(D-17), and every rule of S1 (an undated record, a unit that cannot be read, a proposed fact, a code system no row
carries) applies unchanged, by the same code (``_Run._s1_outcome``).

**An anchor nobody gave is no answer.** The planned start and the screening date come from the caller
(``CascadeConfig.anchors``); with none for a patient, with no event in the record, or with a matching event that has
no date, the answer is unknown (``anchor_date_unknown``), never a guessed date.

**A window that reaches past the day of the run** (a planned start next week) is answered from the records only
where a later record cannot change the answer: a record that already meets it and stays inside the window. Anything
else is unknown (``verify_at_anchor``), never "met" and never "not met" (spec v4 §6.2.4, DM-07).

**Device and allergy** atoms: no lake table holds either kind for any source, so such a criterion answers unknown
with ``not_in_source``.

**A medication window is answered from the order's date** (the existing record rule). Where a matching order
carries a therapy period that reaches the window (an end after its order date, a supply, a start of its own), the
order date does not say when the last dose was: the answer is unknown (``order_dates_missing``) and no date is
computed (the period-aware medication atom is step 2, card 10A-6).

**The flip date** of a criterion a patient passes or fails by the records: the first day after the anchor's date on
which, with the records as they are, the answer would change (the first day a washout is over, the first day a
result is too old). It is found by running the same SQL at the days a dated record enters or leaves a window, never
by a second calculation, and only for windows on the index date, the planned start or the screening date whose
atoms are records or values in a window. What is found is kept on the outcome with its kind (``Outcome.flip``):
``answer_changes`` (index date: from that run day the answer is the opposite one), ``window_empties`` (the answer
becomes open because nothing is in the window any more), ``earliest_anchor`` and ``anchor_window_empties`` (the
same two for a planned start or a screening date: the earliest such date, not a day to re-check on), and
``search_stopped`` (the bound below was reached and no date is known). Only ``answer_changes`` is a date to
re-check on, and only it is stored (``Outcome.flip_date``, the answer store). Nothing is found: when the answer that
day is open for a record that cannot be placed or read (an undated record, a unit), beside a record dated after the
day of the run, when the change would fall on or before the day of the run, when the criterion holds an age, a
score or a duration, for an event anchor, and for a v1 criterion.

**Cost.** One lake query per distinct day per batch of patients. At most ``MAX_DAYS`` days are tried per patient
and criterion and at most ``MAX_RUN_DAYS`` distinct days per run, soonest first; a search cut short says so
(``search_stopped``, counted in S1's stage detail as ``flip_bound_hit``).

"The day of the run" is ``CascadeConfig.run_date`` in every index mode.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.semantics import CompileError, Kind, atoms, kind, window
from criteria_compiler.terminology.mapper import SYSTEMS, ValueSets
from pydantic import ValidationError
from tb_common.reasons import Reason
from tb_contracts import Atom, BoolExpr, CriterionIR
from tb_contracts.criterion_ir import Atom as AtomV3
from tb_contracts.criterion_ir import NotStep1, index_form, sourceless_domains

from matching.cascade.model import Outcome
from matching.stored_scores import apply_rows

log = logging.getLogger(__name__)

#: an offset in days that puts a window where no record is dated (about 2,700 years before the index date): what
#: the compiled SQL answers there is what the undated records alone say
NO_DAY = -1_000_000
#: an offset in days that puts a window's end after every record
EVER = 1_000_000
#: how many days one patient's criterion is tried on for its flip date, soonest first
MAX_DAYS = 64
#: how many distinct days one run's flip-date search asks the lake about, soonest first (one query each per batch)
MAX_RUN_DAYS = 366
#: the medication orders that carry a therapy period beside their order date: an end, or a start of its own. A
#: written-out constant; the patients are a parameter
MED_PERIODS = (
    'SELECT pid, mid, atc, nhi_code, authored, start, "end" FROM medication WHERE pid = ANY(?) '
    'AND ("end" IS NOT NULL OR (start IS NOT NULL AND authored IS NOT NULL AND start <> authored))'
)
_YJ = re.compile(r"[0-9]{7}[A-Z][0-9A-Z]{4}")  # a YJ code, whose first seven characters are its ingredient stem
GIVEN_ANCHORS = ("planned_start", "screening")
_FLIP_KINDS = (Kind.PRESENCE, Kind.OBS_VALUE)
_GROWS = {Kind.PRESENCE: (None, "any", "count>="), Kind.OBS_VALUE: (None, "any", "count>=")}


@dataclass(frozen=True)
class Form:
    """One structured v3 criterion as the engine runs it: its v1 form with index-relative windows, and the anchor
    whose date is the index date of the run."""

    cx: CriterionIR
    anchor: str  # index | planned_start | screening | event
    event: AtomV3 | None = None
    pick: str | None = None

    @property
    def id(self) -> str:
        return self.cx.id


def _pseudo(ruleset: str, n: int, logic: dict[str, Any]) -> CriterionIR:
    cid = f"V3-{n // 1000}-INC-{n % 1000:03d}"  # any number of them fits the criterion id's pattern
    doc = {"id": cid, "ruleset": ruleset, "kind": "inclusion", "class": "structured", "text": "-"}
    return CriterionIR.model_validate({**doc, "logic": logic})


def _dates(evidence: Any) -> list[date]:
    """The dates of the ``record|yyyy-mm-dd`` items of a compiled evidence string, in order."""
    out: list[date] = []
    for item in str(evidence or "").split(";"):
        day = item.rsplit("|", 1)[-1] if "|" in item else ""
        try:
            out.append(date.fromisoformat(day))
        except ValueError:
            continue
    return sorted(out)


def _only_grows(expr: Atom | BoolExpr) -> bool:
    """Whether a TRUE of ``expr`` stays TRUE whatever is recorded later: no negation, and every atom is an age or
    a sex, or counts records (or values) that meet it."""
    if isinstance(expr, BoolExpr):
        return expr.op != "not" and all(_only_grows(a) for a in expr.args)
    k = kind(expr)
    return k is Kind.DEMOGRAPHIC or (k in _GROWS and expr.quantifier in _GROWS[k])


def _definite(o: Outcome | None) -> bool | None:
    """True for a "not met" that excludes, False for a "met" with nothing open, None for anything else."""
    if o is None:
        return None
    if o.hard:  # only a "not met" that may exclude is hard (``Outcome.hard``)
        return True
    if o.status == "pass" and o.unknown_kind is None:
        return False
    return None


#: S1's reasons for an answer left open because no record is in the window (``_Run._s1_coded``)
_NOTHING_IN_WINDOW = ("no value in the window", "unknown_kept", "no record (CAS-11: missing → unknown)")


def _emptied(o: Outcome) -> bool:
    """An answer left open only because nothing is in the window: no record is named and S1 says so."""
    return o.unknown_kind == "data_gap" and not o.evidence and o.reason in _NOTHING_IN_WINDOW


class AnchorError(ValueError):
    """``CascadeConfig.anchors`` holds something that is not a calendar date, or an anchor the caller cannot give."""


def check_anchors(anchors: Any) -> None:
    """A given anchor is a ``date`` and nothing else: a ``datetime`` beside a ``date`` cannot be compared with it,
    and a string would silently read as "not given". Refused before the run reads a patient."""
    for pid, given in (anchors or {}).items():
        for name, day in (given or {}).items():
            if name not in GIVEN_ANCHORS:
                raise AnchorError(f"anchors of {pid!r}: {name!r} is not one of {', '.join(GIVEN_ANCHORS)}")
            if type(day) is not date:
                raise AnchorError(f"anchors of {pid!r}: {name} is a {type(day).__name__}, not a date")


class V3Stage:
    """The v3 criteria of one cascade run. ``run`` is the engine's ``_Run``."""

    def __init__(self, run: Any) -> None:
        self.run = run
        check_anchors(run.cfg.anchors)
        self.today: date = run.cfg.run_date  # the day of the run, in every index mode
        self.flip_bound_hit = 0  # patient-criterion pairs whose flip-date search was cut short
        self.forms: dict[str, Form] = {}
        self.sourceless: dict[str, list[str]] = {}
        self.left: dict[str, str] = {}  # criterion id -> the kind of refusal that leaves it to a person
        self._vs: ValueSets | None = None
        rs = run.rs
        for c in rs.active():
            ir = rs.v3.get(c.id)
            if ir is None or ir.kind not in ("inclusion", "exclusion") or ir.class_ != "structured":
                continue
            missing = sourceless_domains(ir)
            if missing:
                self.sourceless[c.id] = missing
                continue
            try:
                doc, (anchor, event, pick) = index_form(ir)
                form = Form(CriterionIR.model_validate(doc), anchor, event, pick)
                if event is not None:
                    self._event_logic(event, NO_DAY)
                    if self._valuesets().families(str(event.valueset)):
                        # a record of the family outside the list could be the first or the last event (D-113)
                        raise NotStep1(f"{c.id}: the event's value set stands for a code family; a person decides")
                self._sql([form.cx])
            except (NotStep1, CompileError, ValidationError) as exc:
                self.left[c.id] = type(exc).__name__  # the kind of refusal, never the error's text (D-700)
                continue
            self.forms[c.id] = form

    def __bool__(self) -> bool:
        return bool(self.forms or self.sourceless)

    def criteria(self) -> list[CriterionIR]:
        """The v1 forms S1's record checks (coverage, carried systems, kinds of record, proposed facts) also read."""
        return [f.cx for f in self.forms.values()]

    def _query(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        """The stage's one way to the lake. No handler: a failure of the lake stops the run, as S1's own query."""
        rows: list[dict[str, Any]] = self.run.lake.query(sql, params, self.run.cfg.snapshot).to_pylist()
        return rows

    # ------------------------------------------------------------------------------------------- the compiled SQL
    def _valuesets(self) -> ValueSets:
        if self._vs is None:
            # the ruleset's own value sets only: the SQL generator reads their codes, families and stems, and the
            # matching service does not read the loaded terminology tables
            self._vs = ValueSets(self.run.rs.id, self.run.rs.valuesets, None)
        return self._vs

    def _sql(self, crit: list[CriterionIR]) -> str:
        return SqlGenerator(self.run.rs.id, self.run.rs.version, self._valuesets()).render(crit)

    def _rows(self, crit: list[CriterionIR], need: dict[date, set[str]]) -> dict[tuple[str, date], dict[str, Any]]:
        """The compiled SQL of ``crit`` for each day's patients: ``(pid, day) -> row``."""
        from matching.cascade.engine import patients_per_query

        out: dict[tuple[str, date], dict[str, Any]] = {}
        if not crit or not need:
            return out
        run = self.run
        sql = self._sql(crit)
        for day in sorted(need):
            pids = sorted(need[day])
            size = patients_per_query(run.lake, len(pids), 1, run.cfg.s1_rows)
            for start in range(0, len(pids), size):
                for row in self._query(sql, [[day.isoformat()], pids[start : start + size]]):
                    out[(str(row["pid"]), row["index_date"])] = row
        return out

    # ------------------------------------------------------------------------------------------- anchors
    @staticmethod
    def _event_logic(event: AtomV3, offset: int | None) -> dict[str, Any]:
        """The event atom as a plain record atom: with its own window (``offset`` None), or with a window where no
        record is dated."""
        d = event.model_dump(mode="json", by_alias=True, exclude_unset=True)
        extra = sorted(set(d) - {"id", "domain", "valueset", "quantifier", "window", "clinical_status"})
        if extra or d.get("quantifier") not in (None, "any") or not d.get("valueset"):
            raise NotStep1(f"event atom {event.id}: an event is a record of a value set, counted once")
        logic = {k: v for k, v in d.items() if k in ("domain", "valueset", "clinical_status")}
        if offset is not None:
            logic["window"] = {"from_days": offset, "to_days": offset}
        elif "window" in d:
            logic["window"] = {k: v for k, v in d["window"].items() if k in ("from_days", "to_days")}
        return logic

    def _event_dates(self, scope: list[Any]) -> dict[tuple[str, str], date | None]:
        """``(criterion id, pid) -> the event's date``: the first or the last dated event up to the patient's index
        date; None with no event, with an answer the SQL leaves open, or with a matching event that has no date."""
        forms = [f for f in self.forms.values() if f.anchor == "event" and f.event is not None]
        out: dict[tuple[str, str], date | None] = {}
        if not forms:
            return out
        crit: list[CriterionIR] = []
        for n, f in enumerate(forms):
            assert f.event is not None
            crit.append(_pseudo(self.run.rs.id, 2 * n, self._event_logic(f.event, None)))
            crit.append(_pseudo(self.run.rs.id, 2 * n + 1, self._event_logic(f.event, NO_DAY)))
        need: dict[date, set[str]] = {}
        for t in scope:
            need.setdefault(t.index_date, set()).add(t.pid)
        rows = self._rows(crit, need)
        for n, f in enumerate(forms):
            assert f.event is not None
            dated, undated = crit[2 * n].id, crit[2 * n + 1].id
            # the event as "no such record": what a fact a person has not confirmed yet (D-135) could change
            absent = _pseudo(self.run.rs.id, 0, {**self._event_logic(f.event, None), "quantifier": "none"})
            for t in scope:
                row = rows.get((t.pid, t.index_date))
                days = _dates(row.get(f"E_{dated}")) if row and row.get(f"C_{dated}") is True else []
                # FALSE where no record is dated: no undated record of the event either
                clean = row is not None and row.get(f"C_{undated}") is False
                # a proposed or suspected event is no anchor, and beside one the first or the last cannot be told
                if clean and self.run.proposed.refs(absent, t.pid, t.index_date, True):
                    clean = False
                out[(f.id, t.pid)] = (days[0] if f.pick == "first" else days[-1]) if days and clean else None
        return out

    def _anchor_dates(self, scope: list[Any]) -> dict[tuple[str, str], date | None]:
        given = self.run.cfg.anchors or {}
        events = self._event_dates(scope)
        out: dict[tuple[str, str], date | None] = {}
        for f in self.forms.values():
            for t in scope:
                if f.anchor == "index":
                    out[(f.id, t.pid)] = t.index_date
                elif f.anchor == "event":
                    out[(f.id, t.pid)] = events.get((f.id, t.pid))
                else:
                    out[(f.id, t.pid)] = (given.get(t.pid) or {}).get(f.anchor)  # a date (``check_anchors``)
        return out

    # ------------------------------------------------------------------------------------------- the answers
    def _unknown(self, cid: str, reason: Reason, evidence: list[dict[str, Any]] | None = None) -> Outcome:
        """An unknown the way S1 gives one: an exclusion left unknown keeps the patient (D-18)."""
        status = "pass" if self.run.crit[cid].kind == "exclusion" else "unknown"
        return Outcome(cid, status, "S1", unknown_kind="data_gap", evidence=evidence or [], reason=reason.value)  # type: ignore[arg-type]

    def _at_anchor(self, f: Form, out: Outcome, value: Any, anchor: date) -> Outcome:
        """A window that reaches past the day of the run, on any anchor, is answered only by a record that already
        meets it and stays (DM-07): never by the absence of one, and never by a record dated after the day of the
        run, which is an entry error or a plan and not a fact yet."""
        if _definite(out) is None:
            return out
        ends = [window(a).to_days for a in atoms(f.cx.logic) if kind(a) is not Kind.DEMOGRAPHIC]
        if not ends or anchor + timedelta(days=max(ends)) <= self.today:
            return out
        if value is True and _only_grows(f.cx.logic):
            dated = [date.fromisoformat(e["date"]) for e in out.evidence if e.get("date")]
            one = isinstance(f.cx.logic, Atom) and f.cx.logic.quantifier in (None, "any")
            if all(d <= self.today for d in dated) or (one and any(d <= self.today for d in dated)):
                return out
        return self._unknown(f.id, Reason.VERIFY_AT_ANCHOR, out.evidence)

    # ------------------------------------------------------------------------------------------- medication periods
    def _med_atoms(self, f: Form) -> list[Atom]:
        """The windowed medication record atoms of ``f``: what a washout is written with."""
        return [
            a
            for a in atoms(f.cx.logic)
            if a.domain == "medication" and a.window is not None and kind(a) is Kind.PRESENCE
        ]

    def _med_match(self, a: Atom, row: dict[str, Any]) -> bool:
        """Whether a medication row is of the atom's value set: a listed ATC or product code, a code of a listed
        family, or a YJ code of a listed ingredient stem (what the SQL generator matches)."""
        vs, name = self._valuesets(), str(a.valueset)
        atc, nhi = str(row.get("atc") or ""), str(row.get("nhi_code") or "")
        by = {SYSTEMS["atc"]: atc, SYSTEMS["nhi_drug"]: nhi}
        if any(by.get(system) == code for system, code in vs.codes(name) if code):
            return True
        if any(by.get(system, "").startswith(prefix) for system, prefix in vs.families(name) if by.get(system)):
            return True
        return bool(_YJ.fullmatch(nhi)) and nhi[:7] in vs.yj_stems(name)

    def _periods(self, forms: list[Form], scope: list[Any]) -> dict[str, list[dict[str, Any]]]:
        """``pid -> the medication orders that carry a therapy period``, read once when a form has a washout."""
        out: dict[str, list[dict[str, Any]]] = {}
        if not scope or not any(self._med_atoms(f) for f in forms):
            return out
        for row in self._query(MED_PERIODS, [sorted(t.pid for t in scope)]):
            authored, start, end = row.get("authored"), row.get("start"), row.get("end")
            if (end is not None and (authored is None or end > authored)) or (end is None and start != authored):
                out.setdefault(str(row["pid"]), []).append(row)
        return out

    def _period_in_window(self, f: Form, rows: list[dict[str, Any]], anchor: date) -> list[str]:
        """The orders of ``rows`` whose therapy period reaches a medication window of ``f`` at ``anchor``: for these
        the order date the SQL reads does not say when the last dose was."""
        hit: list[str] = []
        for a in self._med_atoms(f):
            w = window(a)
            lo = date.min if w.from_days is None else anchor + timedelta(days=w.from_days)
            hi = anchor + timedelta(days=w.to_days)
            for row in rows:
                if not self._med_match(a, row):
                    continue
                known = [d for d in (row.get("authored"), row.get("start")) if d is not None]
                first = min(known) if known else date.min
                last = row.get("end") or date.max  # a start of its own and no end: it may still be running
                if last >= lo and first <= hi and str(row["mid"]) not in hit:
                    hit.append(str(row["mid"]))
        return sorted(hit)

    def evaluate(self, applied: list[str]) -> int:
        """Give every patient in scope an outcome on each v3 criterion S1's own SQL did not answer, then the
        medication-period rule, the flip dates and S1's exclusion. ``applied``: the criteria the ruleset's SQL
        answered, in order. The number of criteria answered here."""
        run = self.run
        scope = [t for t in run.traces.values() if t.in_scope]
        for cid in self.sourceless:
            for t in scope:
                t.outcomes[cid] = self._unknown(cid, Reason.NOT_IN_SOURCE)
        anchors = self._anchor_dates(scope)
        mine = [f for f in self.forms.values() if f.id not in applied]
        need: dict[date, set[str]] = {}
        for f in mine:
            for t in scope:
                day = anchors[(f.id, t.pid)]
                if day is not None:
                    need.setdefault(day, set()).add(t.pid)
        crit = [f.cx for f in mine]
        rows = self._rows(crit, need)
        table = list(rows.values())
        apply_rows(table, crit, run.cfg.stored, run.cfg.snapshot, getattr(run.rs.manifest, "derived_pins", None))
        for f in mine:
            for t in scope:
                day = anchors[(f.id, t.pid)]
                if day is None:
                    t.outcomes[f.id] = self._unknown(f.id, Reason.ANCHOR_DATE_UNKNOWN)
                    continue
                row = rows.get((t.pid, day))
                if row is None:  # deceased or not yet born at the anchor's date by the records: a person looks
                    t.outcomes[f.id] = self._unknown(f.id, Reason.CHECK_DATES)
                    continue
                out = run._s1_outcome(f.cx, row)
                out = self._at_anchor(f, out, row.get(f"C_{f.id}"), day)
                if f.anchor != "index":
                    out.anchor = {"kind": f.anchor, "date": day.isoformat()}
                t.outcomes[f.id] = out
        # a washout answered from an order's date while the order's therapy period reaches the window: no answer
        periods = self._periods(list(self.forms.values()), scope)
        lineage = f"snapshot:{run.cfg.snapshot or ''}"
        for f in self.forms.values():
            for t in scope:
                day, got = anchors[(f.id, t.pid)], periods.get(t.pid)
                if day is None or not got or f.id not in t.outcomes:
                    continue
                mids = self._period_in_window(f, got, day)
                if mids:
                    ev = [{"source": "lake", "record": m, "date": None, "lineage": lineage,
                           "index_date": day.isoformat()} for m in mids[:20]]  # fmt: skip
                    was = t.outcomes[f.id]
                    t.outcomes[f.id] = self._unknown(f.id, Reason.ORDER_DATES_MISSING, ev)
                    t.outcomes[f.id].anchor = was.anchor
        self._flips(scope, anchors)
        mine_order = [c.id for c in run.rs.active() if c.id in self.forms]
        for t in scope:
            if t.exit_stage == "S1" and t.exit_criterion in self.forms and not t.outcomes[t.exit_criterion].hard:
                t.exit_stage = t.exit_criterion = None  # S1's own SQL excluded on an answer this stage took back
            if t.exit_stage is None:
                first = next((c for c in [*applied, *mine_order] if c in t.outcomes and t.outcomes[c].hard), None)
                if first:
                    run.exclude(t, "S1", first)
        return len(mine) + len(self.sourceless)

    # ------------------------------------------------------------------------------------------- flip dates
    def _flips(self, scope: list[Any], anchors: dict[tuple[str, str], date | None]) -> None:
        run = self.run
        forms = [
            f
            for f in self.forms.values()
            if f.anchor != "event" and all(kind(a) in _FLIP_KINDS for a in atoms(f.cx.logic))
        ]
        if not forms:
            return
        # every dated record of each windowed atom, whatever its date: the days it enters and leaves the window
        seen: list[tuple[Form, Atom, CriterionIR]] = []
        for f in forms:
            for a in atoms(f.cx.logic):
                logic = {"domain": a.domain, "valueset": a.valueset, "window": {"to_days": EVER}}
                seen.append((f, a, _pseudo(run.rs.id, len(seen), logic)))
        open_: list[tuple[Form, Any, date, bool]] = []  # form, trace, anchor day, excludes now
        for f in forms:
            for t in scope:
                day, now = anchors[(f.id, t.pid)], _definite(t.outcomes.get(f.id))
                if day is not None and now is not None:
                    open_.append((f, t, day, now))
        if not open_:
            return
        need: dict[date, set[str]] = {}
        for _f, t, _day, _now in open_:
            need.setdefault(t.index_date, set()).add(t.pid)
        records = self._rows([p for _f, _a, p in seen], need)
        days: dict[tuple[str, str], list[date]] = {}
        cut: set[tuple[str, str]] = set()  # the pairs whose search is cut short by a bound
        need = {}
        for f, t, day, _now in open_:
            row = records.get((t.pid, t.index_date)) or {}
            cand: set[date] = set()
            ahead = False  # a record dated after the day of the run: an entry error or a plan, not a fact yet
            for g, a, p in seen:
                if g is not f:
                    continue
                w = window(a)
                for d in _dates(row.get(f"E_{p.id}")):
                    ahead = ahead or d > self.today
                    cand.add(d - timedelta(days=w.to_days))
                    if w.from_days is not None:
                        cand.add(d - timedelta(days=w.from_days) + timedelta(days=1))
            # no date is computed beside a record dated ahead; at most MAX_DAYS days are tried, soonest first
            every = [] if ahead else sorted(c for c in cand if c > day)
            days[(f.id, t.pid)] = every[:MAX_DAYS]
            if len(every) > MAX_DAYS:
                cut.add((f.id, t.pid))
        # at most MAX_RUN_DAYS distinct days are asked of the lake in one run, the soonest: each pair keeps the
        # days among them, which are its own soonest, so the first change found is still the first
        asked = set(sorted({c for cs in days.values() for c in cs})[:MAX_RUN_DAYS])
        for f, t, day, _now in open_:
            kept = [c for c in days[(f.id, t.pid)] if c in asked]
            if len(kept) < len(days[(f.id, t.pid)]):
                cut.add((f.id, t.pid))
            days[(f.id, t.pid)] = kept
            for c in (day, *kept):
                need.setdefault(c, set()).add(t.pid)
        rows = self._rows([f.cx for f in forms], need)
        for f, t, day, now in open_:
            col = f"C_{f.id}"
            at = rows.get((t.pid, day))
            value = at.get(col) if at else None
            # the fresh SQL must give the answer the outcome states: an exclusion excludes on TRUE, an inclusion on
            # FALSE; otherwise something else decided the outcome and no date is computed from it
            if not isinstance(value, bool) or value is not (now if f.cx.kind == "exclusion" else not now):
                continue
            out = t.outcomes[f.id]
            for c in days[(f.id, t.pid)]:
                nxt = rows.get((t.pid, c))
                later = nxt.get(col) if nxt else None
                if later is value:
                    continue
                # the first change. It is kept when the answer that day is the opposite one, or open only because
                # nothing is in the window any more (a result too old); never when it is open for a record that
                # cannot be placed or read (an undated one, a unit, a proposed fact). A change on or before the day
                # of the run (an anchor in the past) is not a change to come: none
                then = run._s1_outcome(f.cx, nxt) if nxt and c > self.today else None
                opposite = then is not None and _definite(then) is (not now)
                if then is not None and (opposite or _emptied(then)):
                    on_index = f.anchor == "index"
                    if opposite:
                        name = "answer_changes" if on_index else "earliest_anchor"
                    else:
                        name = "window_empties" if on_index else "anchor_window_empties"
                    out.flip = {"date": c.isoformat(), "kind": name}
                    if name == "answer_changes":  # the one kind that is a day to re-check on: the one stored
                        out.flip_date = c.isoformat()
                break
            else:
                if (f.id, t.pid) in cut:  # every day tried gave the same answer and days were left untried
                    out.flip = {"kind": "search_stopped", "tried": str(len(days[(f.id, t.pid)]))}
                    self.flip_bound_hit += 1


__all__ = [
    "EVER",
    "GIVEN_ANCHORS",
    "MAX_DAYS",
    "MAX_RUN_DAYS",
    "MED_PERIODS",
    "NO_DAY",
    "AnchorError",
    "Form",
    "V3Stage",
    "check_anchors",
]
