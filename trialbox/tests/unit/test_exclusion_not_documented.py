"""An exclusion the notes do not mention: "not documented in the notes" (BENCH-2 §2, integrator ruling 2026-11-28).

On the EXCLUSION side only, a judge that read the notes and found nothing to quote is labelled ``not_documented``
("not documented in the notes") instead of ``abstained``. It is a label and a sort key, never a tier change: the
answer stays ``unknown`` (an unknown exclusion keeps the patient, D-18), and the tier is the one ``abstained`` gives.
On the inclusion side absence stays unknown and ``abstained`` (never "not met"). The worklists put a patient whose only
open items are undocumented exclusions below the fully decided and above the ones with real unknowns.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from console.studies import worklist_sorted
from orchestrator.scenarios.evaluate import NoteJudge, note_verdict, tier
from tb_common.llm import LlmResult
from tb_common.reasons import LABELS
from tb_contracts import CriterionIR

from tests.judge_kit import ruleset

TEXT = "Routine visit. Blood pressure stable."
EXCERPTS = [{"date": "2026-01-10", "note_type": "progress", "text": TEXT, "did": "D1"}]
IDX = date(2026, 2, 1)
_n = 0


class Model:
    def __init__(self, verdict: str, quote: str | None = None) -> None:
        global _n
        _n += 1
        self.model, self.verdict, self.quote = f"m{_n}", verdict, quote

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        data = {"verdict": self.verdict, "reason": "r", "confidence": 0.0, "quote": self.quote,
                "quote_date": "2026-01-10" if self.quote else None, "certainty": "possible" if self.quote else None,
                "experiencer": None, "time": None}  # fmt: skip
        return LlmResult(data, prompt_id, 6, self.model, "local", "i" * 64, "o" * 64, 100, 20, 1)


def crit(kind: str) -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": f"T-{kind[:3].upper()}-01", "ruleset": "T", "text": "Known HIV infection", "kind": kind,
         "class": "note", "note_question": "Does the patient have HIV infection?",
         "logic": {"domain": "condition", "valueset": "VS_T"}}
    )  # fmt: skip


def verdict(kind: str, quote: str | None = None) -> Any:
    c = crit(kind)
    nj = NoteJudge(lake=None, llm=Model("unknown", quote), verifier=Model("unknown"))  # type: ignore[arg-type]
    r = nj.judge_excerpts(c.text, c.note_question or c.text, IDX, EXCERPTS, demote=True)
    return c, note_verdict(c, r, pair=True)


def test_an_unmentioned_exclusion_reads_not_documented_and_keeps_its_tier() -> None:
    c, v = verdict("exclusion")
    assert v.verdict == "unknown" and v.evidence.reason == "not_documented"
    rs = ruleset([c])
    same = v.model_copy(update={"evidence": v.evidence.model_copy(update={"reason": "abstained"})})
    assert tier(rs, [v], 0.75, note_block=True) == tier(rs, [same], 0.75, note_block=True)
    assert tier(rs, [v], 0.75, note_block=True)[0] != "excluded"
    assert LABELS["not_documented"]["en"] == "not documented in the notes"


@pytest.mark.parametrize(("kind", "quote"), [("inclusion", None), ("exclusion", TEXT)])
def test_inclusion_absence_and_an_unsure_quote_stay_abstained(kind: str, quote: str | None) -> None:
    _, v = verdict(kind, quote)
    assert v.verdict == "unknown" and v.evidence.reason == "abstained"


def test_the_worklists_sort_undocumented_exclusions_between_decided_and_open() -> None:
    nd = {"evidence": {"reason": "not_documented"}}
    open_ = {"evidence": {"reason": "abstained"}}
    rows = [{"pid": p, "visit": None, "visit_text": "", "tier": "review", "criteria": c,
             "fit": SimpleNamespace(open=[x for x in c if x is not None])}
            for p, c in (("a-open", [open_]), ("b-nd", [nd]), ("c-done", []))]  # fmt: skip
    assert [r["pid"] for r in worklist_sorted(rows, "all")] == ["c-done", "b-nd", "a-open"]  # not the pseudonym order
    assert len(worklist_sorted(rows, "all")) == 3  # nobody leaves the list
