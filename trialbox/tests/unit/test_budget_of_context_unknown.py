"""Deep review 2026-11-13 (screening, SCR-18, the part left for lane A2): one failed context lookup no longer sizes a
whole run's excerpts, and a run that could not tell its context says so.

``engine.budget_of`` asked the judge for the excerpt budget of a criterion once and kept the answer for the run. When
the judge could not tell (a failed ``GET /v1/models``), it kept the 2,500-token default instead: with a context of
about 30,000 tokens every later patient got another excerpt set, other ``left_out`` counts and so other tiers. Now an
unknown budget is used for that prompt only and asked again next time; a told one is kept. The criteria a run sized
on the default are listed in its metrics and in the manifest's cascade block (``context_unknown``). Synthetic
ruleset, no model.
"""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

from matching.cascade.engine import EXCERPT_TOKENS, CascadeConfig, _Run
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
IDX = date(2026, 10, 5)


class Judge:
    """Cannot tell the context ``unknown`` times, then tells 9,000."""

    def __init__(self, unknown: int) -> None:
        self.unknown = unknown
        self.asked = 0
        self._lock = threading.Lock()

    def excerpt_budget(self, c: object, index_date: date) -> int | None:
        with self._lock:
            self.asked += 1
            return None if self.asked <= self.unknown else 9_000


def _run(judge: Judge) -> _Run:
    rs = Ruleset.load(ROOT / "rulesets" / "GOUT-COH")
    return _Run(None, rs, CascadeConfig(study_id="S-1", run_date=IDX), judge, None)  # type: ignore[arg-type]


def test_an_unknown_context_is_asked_again_and_a_told_one_is_kept() -> None:
    judge = Judge(unknown=1)
    run = _run(judge)
    c = run.rs.active()[0]
    assert run.budget_of(c, IDX) == EXCERPT_TOKENS  # this prompt only
    assert run.budget_of(c, IDX) == 9_000  # asked again: the context is known now
    assert run.budget_of(c, IDX) == 9_000 and judge.asked == 2  # kept once told
    assert run.metrics.context_unknown == [c.id]  # the run says it sized a prompt on the default


def test_a_run_that_could_tell_lists_nothing() -> None:
    run = _run(Judge(unknown=0))
    c = run.rs.active()[0]
    assert run.budget_of(c, IDX) == 9_000
    assert run.metrics.context_unknown == []


def test_each_criterion_is_listed_once_in_a_run_that_never_could_tell() -> None:
    judge = Judge(unknown=10**6)
    run = _run(judge)
    cs = run.rs.active()[:2]
    threads = [threading.Thread(target=lambda c=c: [run.budget_of(c, IDX) for _ in range(20)]) for c in cs * 4]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(run.metrics.context_unknown) == sorted(c.id for c in cs)
    assert judge.asked == 20 * len(threads)  # never kept: asked every time


def test_the_manifest_block_carries_the_list() -> None:
    from matching.cascade.engine import CascadeResult

    run = _run(Judge(unknown=1))
    c = run.rs.active()[0]
    run.budget_of(c, IDX)
    res = CascadeResult(
        study_id="S-1", ruleset=run.rs.id, ruleset_version=run.rs.version, semantics=run.semantics,
        ir_hash=run.ir_hash, criterion_hashes=run.hashes, index_dates=[IDX], traces={}, stages=[],
        metrics=run.metrics, queue=[], final_list=[], applied=[], note_criteria=[c.id], human_criteria=[],
    )  # fmt: skip
    assert res.manifest_block()["context_unknown"] == [c.id]
