"""The decision context (T-708, D-477; review 2026-11-12 ``decision.md`` AD-1, root cause R2).

Six paths decide or count patients (SCREEN v1, the cascade, MICROBATCH, NAV, CASE, FEAS/COHORT). Only the snapshot
was handed to all of them (the pin of D-383); the opt-out register, consent, the note-block decision and "today"
were read by each scenario with its own call and its own rule. This module is the one place a path reads them:

* **the snapshot and the run date**: the job's pinned lake (``ctx.services.lake``) and ``ctx.today()``;
* **the opt-out register**: one function (:func:`tb_common.optout.opted_out`, with the surviving pseudonym of a
  merged chart), as it stood when the job was received for who is looked at (:meth:`DecisionContext.register`),
  and as it stands now before anything is published or stored (:meth:`DecisionContext.register_now`);
* **consent**: one rule (:func:`tb_common.optout.registry_state`: the patient's latest statement on or before the
  day decides; an undated statement is the oldest; one entered in error is none; ties of a day fail closed), as of
  the run date on the pinned snapshot (:meth:`DecisionContext.consent`);
* **the ruleset and its pins**: the approved version in force on the job's run date (:meth:`ruleset`) and what it
  pins (:meth:`pins`);
* **whether a note answer may exclude** on this job (:meth:`note_block`): decided on the first call for a pair and
  only ever withdrawn after that, never granted again;
* **the confidence threshold** (:meth:`threshold`).

``tests/unit/test_decision_context_lint.py`` fails on ``opted_out(``, ``FROM consent`` or a read of the note-block
decision outside this module (and the library functions it calls).

A scenario gets it as ``ctx.decision``; :func:`decision_of` also serves a stand-in context of a test (one object
per context either way). Code outside a job (a route, a timer) uses :func:`register_now`.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from tb_common import optout as _optout  # by module: a test that replaces the register's reader is honoured
from tb_common.optout import RegistryState
from tb_common.ruleset import Ruleset

from orchestrator.clients import StepFailed

if TYPE_CHECKING:
    from orchestrator.scenarios.evaluate import NoteJudge

#: the reason the cascade gives a patient whose latest statement refuses research use (shown on the excluded page)
REFUSED_REASON = "research-use opt-out (FHIR Consent rejected)"
#: the action of a patient whose latest statement denies contact: never on a list (D-441)
NO_CONTACT_ACTION = "contact: deny (FHIR Consent) — never listed"

log = logging.getLogger("orchestrator.decision")


@dataclass(frozen=True)
class NoteBlock:
    """Whether a confident note "not met" may exclude a patient on this job (D-95, D-97, D-276), the policy in
    force and why."""

    may_block: bool
    policy: str
    reason: str
    code: str = ""  # the reason's code (``evaluate.NOTE_BLOCK_CODES``, or ``ok``): what a page words the refusal by


def register_now() -> frozenset[str]:
    """The opt-out register as it stands now (with merged charts), for code outside a job: a route, a timer, an
    export. Raises when the register does not answer (D-127: fail closed). Code of another service calls
    ``tb_common.optout.register_now``, the same read."""
    return _optout.register_now()


def note_block_of(judge: NoteJudge | None, ctx: Any = None) -> NoteBlock:
    """The note-block decision for ``judge``: the job's (``ctx``), or, for a caller with no job (a tool, a test of
    the evaluator), the rule applied now."""
    if ctx is not None:
        return decision_of(ctx).note_block(judge)
    from orchestrator.scenarios.evaluate import note_block_why

    return NoteBlock(*note_block_why(judge))


def configured_note_block() -> str:
    """The configured policy (``TB_NOTE_BLOCK``), before a run's pair is looked at."""
    from orchestrator.scenarios.evaluate import note_block_policy

    return note_block_policy()


class DecisionContext:
    """What one job reads to decide. Built once per job (``ctx.decision``)."""

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx
        self._at_receipt: frozenset[str] | None = None
        self._consent: dict[tuple[str | None, str], RegistryState | None] = {}
        self._note_block: dict[tuple[int, int], NoteBlock] = {}

    # ------------------------------------------------------------------------------------ the snapshot, the date
    @property
    def lake(self) -> Any:
        """The job's lake, pinned to one snapshot (D-383); None on a box (or a stand-in context) without one."""
        return getattr(getattr(self._ctx, "services", None), "lake", None)

    def snapshot(self) -> str | None:
        """The job's snapshot (the first call pins it)."""
        snap = self.lake.snapshot() if self.lake is not None else None
        return str(snap) if snap else None

    @property
    def run_date(self) -> date:
        """The job's run date: fixed when the job starts, so a run across midnight and a re-run use one date. A
        context with no job clock (code that counts outside a job) reads today in the site's zone."""
        today = getattr(self._ctx, "today", None)
        if callable(today):
            return today()  # type: ignore[no-any-return]
        from tb_common.timeutil import today as site_today

        return site_today(self._ctx.cfg.env.tz)

    # ------------------------------------------------------------------------------------ the opt-out register
    def register(self) -> frozenset[str]:
        """Who was opted out when the job was received (D-147; a re-run of an old job stays byte-identical, D-82)."""
        if self._at_receipt is None:
            job = getattr(self._ctx, "job", None)  # no job (code that counts outside one): the register now
            self._at_receipt = (
                _optout.opted_out(as_of=job.received_at.isoformat()) if job is not None else _optout.opted_out()
            )
        return self._at_receipt

    def register_now(self) -> frozenset[str]:
        """Who is opted out now (D-441): read again before a run publishes or stores anything."""
        return register_now()

    def drop(self, pids: Iterable[str], event: str, **detail: Any) -> frozenset[str]:
        """The ones of ``pids`` on the register at the job's receipt; the removal is audited by count under
        ``event`` (who opted out is itself private)."""
        gone = frozenset(self.register() & set(pids))
        if gone:
            self._audit(event, {"removed": len(gone), **detail, "register": "optout"})
        return gone

    def drop_now(self, pids: Iterable[str], event: str, **detail: Any) -> frozenset[str]:
        """The ones of ``pids`` on the register as it stands now; audited by count under ``event``."""
        want = set(pids)
        gone = frozenset(self.register_now() & want) if want else frozenset()
        if gone:
            self._audit(event, {"removed": len(gone), **detail, "register": "optout"})
        return gone

    # ------------------------------------------------------------------------------------ consent
    def consent(self, day: date | None = None, snapshot: str | None = None) -> RegistryState | None:
        """What the hospital's registry says per patient as of ``day`` (the run date) on the job's snapshot, by the
        one rule. None: the lake has no consent table (the registry was never ingested), on a DEV or TEST box; on
        a PRODUCTION box that stops the job (D-654). Any other failure raises (D-127)."""
        if self.lake is None:
            return None  # no lake: no registry was ingested
        key = (snapshot, (day or self.run_date).isoformat())
        if key not in self._consent:
            try:
                self._consent[key] = _optout.registry_state(self.lake, snapshot, key[1])
            except _optout.NoRegistryTable as exc:
                # D-654: a PRODUCTION box and a snapshot without a consent table. The job stops with the sentence
                # (a general error would show only "Internal error"), at the step it is in; nothing is cached, the
                # next read asks again. Logged here: a step failure is not logged where the job ends
                step = str(getattr(getattr(self._ctx, "job", None), "state", "") or "running")
                log.error("job stopped at %s: the lake snapshot has no consent table (D-654)", step)
                raise StepFailed(step, str(exc)) from exc
        return self._consent[key]

    def refused(self) -> frozenset[str]:
        """Patients whose latest statement refuses research use: never screened, counted or listed."""
        state = self.consent()
        return state.refused if state is not None else frozenset()

    def no_contact(self) -> frozenset[str]:
        """Patients whose latest statement denies contact: never on a list (they stay in counts, D-441)."""
        state = self.consent()
        return state.no_contact if state is not None else frozenset()

    def off_lists(self, pids: Iterable[str], event: str, **detail: Any) -> frozenset[str]:
        """The ones of ``pids`` that may be on no list of this job: on the register at the job's receipt, refused,
        or contact denied. Audited by count under ``event``."""
        want = set(pids)
        reg = frozenset(self.register() & want)
        said = frozenset((self.refused() | self.no_contact()) & want)
        if reg or said:
            self._audit(event, {"removed": len(reg | said), **detail, "register": "optout", "consent": len(said - reg)})
        return reg | said

    def consent_off_lists(self, pids: Iterable[str], event: str, **detail: Any) -> frozenset[str]:
        """The ones of ``pids`` whose latest statement refuses research use or denies contact (the register was
        applied by the caller). Audited by count under ``event``."""
        said = frozenset((self.refused() | self.no_contact()) & set(pids))
        if said:
            self._audit(event, {"removed": len(said), **detail, "register": "consent"})
        return said

    def uncounted(self) -> frozenset[str]:
        """Who a count leaves out (OD-8): the register at the job's receipt and the patients who refused research
        use. A patient who only denies contact is counted."""
        return self.register() | self.refused()

    def contactable(self, index: date, snapshot: str | None = None) -> set[str] | None:
        """Patients whose latest statement on or before ``index`` is an active consent that allows contact (COHORT's
        ``n_contactable``); None when the lake has no consent table."""
        state = self.consent(index, snapshot)
        return None if state is None else set(state.contactable)

    # ------------------------------------------------------------------------------------ the threshold
    def threshold(self, rs: Ruleset) -> float:
        """The confidence a note answer needs to count (the ruleset's, else the site's, else 0.75)."""
        m, s = rs.manifest, self._ctx.cfg.settings
        if m.thresholds and m.thresholds.tier_high_confidence is not None:
            return float(m.thresholds.tier_high_confidence)
        if s.thresholds and s.thresholds.tier_high_confidence is not None:
            return float(s.thresholds.tier_high_confidence)
        return 0.75

    # ------------------------------------------------------------------------------------ the note-block decision
    def note_block(self, judge: NoteJudge | None) -> NoteBlock:
        """Whether a note answer may exclude on this job, for this judge's pair of models. Decided on the first
        call; a later call can only withdraw it (the canary gate shut, note reading held), never grant it again, so
        one job never excludes under two decisions."""
        from orchestrator.scenarios.evaluate import note_block_why

        key = (id(getattr(judge, "llm", None)), id(getattr(judge, "verifier", None)))
        now = NoteBlock(*note_block_why(judge))
        first = self._note_block.get(key)
        if first is None or (first.may_block and not now.may_block):
            self._note_block[key] = first = now
        return first

    def _audit(self, event: str, detail: dict[str, Any]) -> None:
        job = self._ctx.job
        self._ctx.orch.audit.append(event, job_id=job.job_id, ruleset=job.ruleset, detail=detail)


def decision_of(ctx: Any) -> DecisionContext:
    """The context's :class:`DecisionContext`: ``ctx.decision`` of a real job context, and one made (and kept, where
    the object allows it) for a stand-in context of a test."""
    got = getattr(ctx, "decision", None)
    if isinstance(got, DecisionContext):
        return got
    made = DecisionContext(ctx)
    with contextlib.suppress(AttributeError, TypeError):
        ctx.decision = made
    return made
