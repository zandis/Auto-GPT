"""Seconds of an APPROVE job's named steps (card H-45, the fix (1) of H-41's approve profile).

H-41 (``docs/plan/measurements/approve-profile-2026-11-19.md``) found about 53 s of each launch-P3 approval in steps
no record names. The compiler's ``Compiler.approve`` and the orchestrator's APPROVE scenario now time their steps on
the monotonic clock and the job's ``metrics.step_seconds`` holds them: step name to seconds, numbers only, the names
fixed here (:data:`APPROVE_STEPS`). The steps of a run plus ``orch.unaccounted`` (and ``orch.earlier_runs`` when the
job ran before a restart) add up to the job's ``metrics.wall_seconds``.

A step is timed by laps: :meth:`StepClock.mark` starts a lap, :meth:`StepClock.lap` gives the time since the last
mark (or lap) to a step and starts the next lap. Code between a lap and the next mark belongs to no step and is left
to the remainder. Nothing here does I/O, logs or holds text beyond the fixed step names.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

#: the compiler's steps inside ``Compiler.approve`` (services/criteria_compiler/service.py)
COMPILER_STEPS: tuple[str, ...] = (
    "compiler.draft_read",  # the draft branch found, and its equivalence report read
    "compiler.refresh_installed",  # the installed terminology tables read again (E-TERM-3)
    "compiler.audit_confirmed",  # the ai.confirmed audit records, one per decided criterion with model calls
    "compiler.apply_decisions",  # the reviewer's decisions applied to the criteria
    "compiler.extract_edits",  # edited criterion text extracted again (an edit round only)
    "compiler.build_artifacts",  # CQL generation and the CQL-to-ELM translation
    "compiler.equivalence",  # the equivalence gate run again, or the compile's report enforced
    "compiler.checks",  # flags, blocking, terminology stamp and site lists, the manifest
    "compiler.files",  # the ruleset's files assembled
    "compiler.fhir_load",  # the FHIR libraries built (FHIRHelpers read from the jar) and loaded with the value sets
    "compiler.repo_write",  # the rulesets repository: the draft branch written (the rulesets volume)
    "compiler.repo_tag",  # the rulesets repository: the version tagged
    "compiler.repo_promote",  # the rulesets repository: the tag promoted to release
    "compiler.package",  # the review package of a further round
    "compiler.audit_done",  # the approve.done / approve.needs_review / approve.max_rounds audit record
    "compiler.unaccounted",  # the rest of Compiler.approve
)

#: the orchestrator's steps of the APPROVE job around the compiler (services/orchestrator/scenarios/approve.py,
#: services/orchestrator/core.py)
ORCH_STEPS: tuple[str, ...] = (
    "orch.target",  # the ruleset and version found, the job updated, the approved ruleset looked for
    "orch.resume_awaiting",  # the jobs waiting for this version resumed
    "orch.state",  # the job's state set to compiling (its record and audit line)
    "orch.read_workbook",  # the review workbook read from the object store
    "orch.parse_review",  # the workbook parsed
    "orch.compiler_transport",  # the HTTP round trip to the compiler less the compiler's own approve
    "orch.compiler_call",  # the whole compiler call, when the compiler gave no steps (it failed)
    "orch.publish",  # the approved manifest stored, hashed and audited
    "orch.review_delivery",  # the next review round's mail assembled
    "orch.fail_awaiting",  # the waiting jobs failed (rejected, or out of rounds)
    "orch.deliver",  # the job's mail sent
    "orch.earlier_runs",  # wall seconds of runs before a restart (metrics.wall_seconds carried in)
    "orch.unaccounted",  # the rest of the job's wall time
)

APPROVE_STEPS: tuple[str, ...] = ORCH_STEPS + COMPILER_STEPS

_ROUND = 4


class StepClock:
    """Lap timer on :func:`time.perf_counter`; :attr:`seconds` maps a fixed step name to its seconds."""

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self._mark = self.started
        self.seconds: dict[str, float] = {}

    def mark(self) -> None:
        self._mark = time.perf_counter()

    def since_mark(self) -> float:
        return time.perf_counter() - self._mark

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.add(name, now - self._mark)
        self._mark = now

    def add(self, name: str, seconds: float) -> None:
        self.seconds[name] = self.seconds.get(name, 0.0) + float(seconds)

    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    def closed(
        self, rest: str, total: float | None = None, extra: Mapping[str, float] | None = None
    ) -> dict[str, float]:
        """The steps, with ``extra`` added to them, and ``rest`` = ``total`` (default: the time since the clock
        started) less the named steps. Changes nothing on the clock: calling it twice gives the same steps."""
        total = self.elapsed() if total is None else total
        named = dict(self.seconds)
        for k, v in (extra or {}).items():
            named[k] = named.get(k, 0.0) + float(v)
        out = {k: round(v, _ROUND) for k, v in named.items()}
        out[rest] = round(total - sum(named.values()) + named.get(rest, 0.0), _ROUND)
        return out


def numbers_only(steps: Mapping[str, object] | None) -> dict[str, float]:
    """The known step names with numeric seconds from a stored record; anything else is dropped."""
    out: dict[str, float] = {}
    for k, v in (steps or {}).items():
        if k in APPROVE_STEPS and isinstance(v, int | float) and not isinstance(v, bool):
            out[k] = float(v)
    return out
