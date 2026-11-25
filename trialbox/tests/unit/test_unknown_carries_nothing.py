"""INT-S-C: an ``unknown`` verdict carries no confidence, no quote and no quote date.

The judge's placeholder reply (verdict ``unknown``, a filler quote, the date ``0000-01-01``, confidence 1.0) became a
valid ``unknown`` after the date was nulled, and kept confidence 1.0 and the filler quote down to the candidate list
and the investigator's workbook ("confidence 1.00" beside an answer nobody gave). The reply is normalised where it is
accepted (the generic model client, the cascade's gateway judge, the note judge's ``postprocess``) and again where a
verdict is built, so a stored or printed ``unknown`` never has a confidence. A decided answer (pass, fail) is unchanged.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from matching.cascade.judge import GatewayJudge
from matching.cascade.model import Outcome
from openpyxl import load_workbook
from orchestrator.scenarios.evaluate import NoteJudge, NoteResult, note_verdict, postprocess
from orchestrator.scenarios.screen_cascade import OrchestratorJudge, verdict_of
from tb_common.llm import LlmClient, unknown_carries_nothing
from tb_common.ruleset import Ruleset
from tb_contracts import CandidateRow, CriterionVerdict, Evidence

from tests.judge_kit import ScriptedModel, note_criterion
from tests.unit.test_judge_sentinel_date import KW, RUN_REPLY, _Client

ROOT = Path(__file__).resolve().parents[2]
CRIT = note_criterion("T-EXC-01", "exclusion", "No gout flare", "Does the patient have a gout flare?")
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
NOTE_EXC = next(c.id for c in GZQO.active() if c.class_ == "note" and c.kind == "exclusion")
EXCERPTS = [{"did": "D1", "text": "Acute gout flare of the right toe.", "date": "2026-10-01"}]
QUESTION = ("No gout flare", "Does the patient have a gout flare?", date(2026, 10, 5), EXCERPTS)


def test_the_helper_clears_an_unknown_and_leaves_a_decided_answer() -> None:
    cleared = unknown_carries_nothing(dict(RUN_REPLY, certainty="affirmed", experiencer="patient", time="current"))
    assert cleared["quote"] is None and cleared["quote_date"] is None and cleared["confidence"] == 0.0
    assert (cleared["certainty"], cleared["experiencer"], cleared["time"]) == (None, None, None)
    assert cleared["reason"] == RUN_REPLY["reason"]  # the reason code stays
    decided = {"verdict": "pass", "quote": "q", "quote_date": "2026-10-01", "confidence": 0.9}
    assert unknown_carries_nothing(decided) == decided


class _Http:
    """The model endpoint: one chat-completions answer carrying ``RUN_REPLY``."""

    def post(self, url: str, **kw: Any) -> httpx.Response:
        import json

        body = {"choices": [{"message": {"content": json.dumps(RUN_REPLY)}, "finish_reason": "stop"}], "model": "m"}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    get = post


def test_the_generic_client_accepts_the_placeholder_reply_as_an_unknown_with_nothing() -> None:
    llm = LlmClient("http://stub/v1", "m")
    llm.http = _Http()  # type: ignore[assignment]
    res = llm.chat_json(
        "judge", {"criterion_text": "c", "note_question": "q", "index_date": "2026-10-05", "excerpts": []}
    )
    assert res.data["verdict"] == "unknown"
    assert (res.data["quote"], res.data["quote_date"], res.data["confidence"]) == (None, None, 0.0), res.data


def test_the_cascades_gateway_judge_accepts_it_as_an_unknown_with_nothing() -> None:
    r = GatewayJudge(_Client(RUN_REPLY)).judge(**KW)
    assert r.verdict == "unknown" and r.refused is None
    assert (r.quote, r.quote_date, r.confidence) == (None, None, 0.0), r


def test_the_note_judges_postprocess_accepts_it_as_an_unknown_with_nothing() -> None:
    r = postprocess(RUN_REPLY, EXCERPTS)
    assert r.predicate == "unknown"
    assert (r.quote, r.quote_date, r.confidence) == (None, None, 0.0), r


def test_the_note_judge_and_the_orchestrator_judge_hand_on_an_unknown_with_nothing() -> None:
    model = ScriptedModel("judge-a", lambda v: dict(RUN_REPLY))
    r = NoteJudge(None, model).judge_excerpts(*QUESTION)  # type: ignore[arg-type]
    assert (r.predicate, r.quote, r.quote_date, r.confidence) == ("unknown", None, None, 0.0), r
    reply = OrchestratorJudge(None, model).judge(  # type: ignore[arg-type]
        role="judge", criterion_text=QUESTION[0], note_question=QUESTION[1], index_date=QUESTION[2],
        excerpts=EXCERPTS, study_id="S", data_class="D0", step_id="s", purpose="screening",
    )  # fmt: skip
    assert (reply.verdict, reply.quote, reply.quote_date, reply.confidence) == ("unknown", None, None, 0.0), reply


def test_the_v1_verdict_of_an_unknown_has_no_confidence_even_from_a_stale_result() -> None:
    v = note_verdict(CRIT, NoteResult("unknown", 1.0, "unknown", "0000-01-01", "abstained"))
    assert v.verdict == "unknown"
    assert v.evidence is not None and v.evidence.confidence is None, v


def test_the_cascade_verdict_of_an_unknown_has_no_confidence() -> None:
    o = Outcome(
        "T-EXC-01", "unknown", "S3", unknown_kind="uncertain", evidence=[{"confidence": 1.0}], reason="abstained"
    )
    v = verdict_of(o)
    assert v.evidence is not None and v.evidence.confidence is None, v


def test_a_decided_answer_keeps_its_confidence() -> None:
    o = Outcome("T-EXC-01", "pass", "S3", evidence=[{"confidence": 0.9}], reason="stated")
    assert verdict_of(o).evidence.confidence == 0.9  # type: ignore[union-attr]
    inc = note_criterion("T-INC-01", "inclusion", "Gout flare", "Does the patient have a gout flare?")
    r = note_verdict(inc, NoteResult("pass", 0.9, "Acute gout flare of the right toe.", "2026-10-01", "note"))
    assert r.verdict == "pass"
    assert r.evidence is not None and r.evidence.confidence == 0.9


def test_the_workbook_never_prints_a_confidence_for_an_unknown() -> None:
    from orchestrator.reports import candidate_xlsx

    from tests.unit.test_feas_unit import META

    stale = CriterionVerdict(  # a row stored before this card
        id=NOTE_EXC, verdict="unknown", evidence=Evidence(reason="abstained", confidence=1.0, quote="unknown")
    )
    decided = CriterionVerdict(
        id=NOTE_EXC,
        verdict="pass",
        evidence=Evidence(reason="note", confidence=0.9, quote="q", quote_date="2026-10-01"),
    )
    rows = [CandidateRow(pid="P1", tier="review", criteria=[stale], actions=[]),
            CandidateRow(pid="P2", tier="review", criteria=[decided], actions=[])]  # fmt: skip
    ws = load_workbook(io.BytesIO(candidate_xlsx.render(rows, GZQO, META, {}, {})))["candidates"]
    col = [c.value for c in ws[1]].index(f"C_{NOTE_EXC}") + 1
    cells = {r[1].value: r[col - 1] for r in ws.iter_rows(min_row=2) if r[1].value in ("P1", "P2")}
    assert cells["P1"].value == "unknown"
    stale_note, decided_note = cells["P1"].comment, cells["P2"].comment
    assert "confidence" not in (stale_note.text if stale_note else "")
    assert decided_note is not None and "confidence 0.90" in decided_note.text


@pytest.mark.parametrize("quote", ["unknown", None, "Acute gout flare of the right toe."])
@pytest.mark.parametrize("conf", [0.0, 0.4, 1.0])
def test_invariant_no_unknown_the_judge_path_builds_has_a_confidence(quote: str | None, conf: float) -> None:
    """Whatever an ``unknown`` reply holds, every verdict built from it has no confidence and an abstention no quote."""
    reply = {"verdict": "unknown", "reason": "r", "quote": quote, "quote_date": "0000-01-01", "confidence": conf}
    r = postprocess(reply, EXCERPTS)
    v1 = note_verdict(CRIT, r)
    assert v1.verdict == "unknown" and v1.evidence is not None
    assert v1.evidence.confidence is None and v1.evidence.quote is None and v1.evidence.quote_date is None
    o = Outcome("T-EXC-01", "unknown", "S3", unknown_kind="uncertain", evidence=[{"confidence": r.confidence}])
    assert verdict_of(o).evidence.confidence is None  # type: ignore[union-attr]
