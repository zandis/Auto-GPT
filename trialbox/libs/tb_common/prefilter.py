"""The pre-filter record of a nightly screening job and the per-study per-night report built from it (10E-12, D-1259).

The nightly screening (MICROBATCH) filters patients in stages before the model judges any. Each job, when it
finishes, writes one **pre-filter record** into its own metrics (``JobMetrics.prefilter``, beside
``patients_scoped``): how many patients the job had in scope and at which stage each left, each patient once.
Counts only; the patient ids used to count them live in the job's memory and are never stored. A job with no record
(one from before the record, any other job) has no funnel: the job page shows nothing for it.

The counting (lane H's ruling on PR #639, 2026-11-19):

* **Unit:** within one job, each patient once, at their **last** evaluation in the job (a pool row re-checked and
  then screened again in the same job counts once, at the screen). The night (the jobs of a study that share a
  ``run_date``) is the **sum** of its jobs' records: a record holds no ids, so a patient two jobs of one study looked
  at on the same night is counted by each. The night's figures are sums of per-job counts, not distinct patients
  (the page says so when the night has more than one job; D-1259).
* **Stages that add up** (each patient in exactly one): ``opted_out`` (on the opt-out register, a refusal of
  research use or of contact, or not at the index date: not in the snapshot, deceased or not yet born);
  ``not_due`` (in scope, not looked at by this run's cadence); ``carried`` (due, left by the night budget);
  ``coded_excluded``; ``no_model`` (past the coded filter, not listed, no note read by the model);
  ``model_not_listed`` (the model read their notes, not listed); ``listed``. ``in_scope`` is their sum.
* The re-check rows are in the funnel (as ``screen.stage_funnel`` counts them).
* **The invariant:** ``in_scope`` is the sum of the stages (:func:`adds_up`). The job refuses to write a record that
  does not add up; a stored one that does not is a fault: not summed, not shown (:attr:`NightFunnel.faults`).
* Exact counts on internal console pages (D-99); anything mailed or exported goes through :func:`publishable`
  (``funnel_drops_publishable``: complementary suppression). This card mails and exports nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from tb_contracts import NightOpen, OpenReason, PrefilterRecord

from tb_common import open_reasons
from tb_common.reasons import Reason
from tb_common.smallcell import funnel_drops_publishable

#: the drops, in the funnel's order; ``listed`` is what is left at the end
STAGES = ("opted_out", "not_due", "carried", "coded_excluded", "no_model", "model_not_listed", "listed")
#: stages a patient reaches by being evaluated (the others are reached without an evaluation)
EVALUATED = ("opted_out", "coded_excluded", "no_model", "model_not_listed", "listed")
#: the evaluated stages whose patients passed the coded filter: the ones the open reasons and coded-complete count
SURVIVORS = ("no_model", "model_not_listed", "listed")
#: an evaluation that found the patient not at the index date (D-118, D-142)
NOT_AT_INDEX = (Reason.NOT_IN_SNAPSHOT.value, Reason.CHECK_DATES.value)
LISTED = ("high", "review")


def not_at_index(verdicts: Iterable[Any]) -> bool:
    """Every answer of the evaluation is "unknown" because the patient is not in the snapshot, or is deceased or not
    yet born on the index date (``evaluate.not_in_snapshot``)."""
    vs = list(verdicts)
    return bool(vs) and all(
        v.verdict == "unknown" and v.evidence is not None and v.evidence.reason in NOT_AT_INDEX for v in vs
    )


def evaluated_stage(*, consent_out: bool, at_index: bool, coded_fail: bool, listed: bool, model_read: bool) -> str:
    """The stage an evaluated patient left at, in the funnel's order."""
    if consent_out or not at_index:
        return "opted_out"
    if coded_fail:
        return "coded_excluded"
    if listed:
        return "listed"
    return "model_not_listed" if model_read else "no_model"


class Tally:
    """One job's patients by stage, each once: an evaluation always replaces what was said of the patient before
    (the last evaluation stands, the later of two evaluations included); a stage reached without an evaluation
    replaces only another such stage (a patient re-checked and then carried by the excluded patients' budget was
    evaluated tonight: the re-check stands). Ids stay in memory; :meth:`record` gives counts."""

    def __init__(self) -> None:
        self._stage: dict[str, str] = {}
        self._done: set[str] = set()
        self._facts: dict[str, open_reasons.Facts] = {}

    def passed(self, pids: Iterable[str], stage: str) -> None:
        if stage in EVALUATED and stage != "opted_out":
            raise ValueError(f"{stage} is reached by an evaluation")
        for p in pids:
            if p not in self._done:
                self._stage[p] = stage

    def evaluated(self, pid: str, stage: str, facts: open_reasons.Facts | None = None) -> None:
        """``facts``: the evaluation's open criteria and coded-complete flag (F17 5a, 5b); the last evaluation's
        stand, like its stage."""
        if stage not in EVALUATED:
            raise ValueError(f"{stage} is not reached by an evaluation")
        self._stage[pid] = stage
        self._done.add(pid)
        if facts is None:
            self._facts.pop(pid, None)
        else:
            self._facts[pid] = facts

    def counts(self) -> dict[str, int]:
        out = dict.fromkeys(STAGES, 0)
        for s in self._stage.values():
            out[s] += 1
        return out

    def record(self, trigger: str) -> PrefilterRecord:
        c = self.counts()
        rec = PrefilterRecord(trigger=trigger, in_scope=sum(c.values()), **c)  # type: ignore[arg-type]
        if not adds_up(rec):  # by construction it does; a record that does not is never written
            raise ValueError("the pre-filter record does not add up")
        return rec

    def night_open(self) -> NightOpen:
        """The open criteria and the coded-complete count of the patients past the coded filter (counts only)."""
        done, rows = open_reasons.tally(f for p, f in self._facts.items() if self._stage.get(p) in SURVIVORS)
        return NightOpen(coded_complete=done, open_reasons=[OpenReason(**r) for r in rows])


def adds_up(rec: Any) -> bool:
    """The invariant of every record: ``in_scope`` is the sum of the stages (``listed`` the last of them)."""
    return int(rec.in_scope) == sum(int(getattr(rec, s)) for s in STAGES)


@dataclass(frozen=True)
class NightFunnel:
    """One study's night: the stage counts summed over the night's records (sums of per-job counts, not distinct
    patients), the funnel's remaining counts (``remaining[0]`` is in scope, ``remaining[-1]`` listed), how many jobs
    it sums, and how many of the night's records did not add up (``faults``: left out of the sums; a reader shows no
    funnel while there is one)."""

    ruleset: str
    run_date: date
    jobs: int
    drops: dict[str, int]
    remaining: list[int]
    faults: int = 0
    coded_complete: int | None = None  # None: no job of the night wrote night_open
    open_reasons: tuple[tuple[str, str, str, int], ...] = ()  # (criterion, reason, where, patients), summed

    @property
    def in_scope(self) -> int:
        return self.remaining[0]

    @property
    def listed(self) -> int:
        return self.remaining[-1]


def remaining_of(drops: Mapping[str, int]) -> list[int]:
    """In scope, then what is left after each drop in order; the last is ``listed``."""
    left = sum(int(drops.get(s, 0)) for s in STAGES)
    out = [left]
    for s in STAGES[:-1]:
        left -= int(drops.get(s, 0))
        out.append(left)
    return out


def night_funnel(jobs: Iterable[Any], ruleset: str, run_date: date) -> NightFunnel | None:
    """The per-study per-night report: the pre-filter records of the finished MICROBATCH jobs of ``ruleset`` whose
    ``run_date`` is ``run_date``, summed (a sum of per-job counts). None when the night has no such record (no job,
    or only jobs that wrote none): no funnel, never a funnel of zeros. A record that does not add up is a fault,
    counted in ``faults`` and left out of the sums."""
    rid = (ruleset or "").strip().upper()
    drops = dict.fromkeys(STAGES, 0)
    n = faults = 0
    done: int | None = None
    opens: dict[tuple[str, str, str], int] = {}
    for j in jobs:
        if getattr(j, "type", None) != "MICROBATCH" or getattr(j, "state", None) != "done":
            continue
        if (getattr(j, "ruleset", None) or "").strip().upper() != rid or getattr(j, "run_date", None) != run_date:
            continue
        rec = getattr(getattr(j, "metrics", None), "prefilter", None)
        if rec is None:
            continue
        if not adds_up(rec):
            faults += 1
            continue
        n += 1
        for s in STAGES:
            drops[s] += int(getattr(rec, s))
        no = getattr(getattr(j, "metrics", None), "night_open", None)
        if no is not None:
            done = (done or 0) + int(no.coded_complete)
            for o in no.open_reasons:
                k = (o.criterion, o.reason, o.where)
                opens[k] = opens.get(k, 0) + int(o.count)
    if not n and not faults:
        return None
    rows = tuple((*k, v) for k, v in sorted(opens.items()))
    return NightFunnel(rid, run_date, n, drops, remaining_of(drops), faults, done, rows)


def publishable(f: NightFunnel, threshold: int = 5) -> list[bool]:
    """For anything mailed or exported (none in this card): which drops may be shown, by complementary suppression
    over the funnel's remaining counts (D-467 rule 5). Index 0 (in scope) has no drop."""
    return funnel_drops_publishable(f.remaining, threshold)
