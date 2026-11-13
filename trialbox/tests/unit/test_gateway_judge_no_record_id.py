"""The cascade's gateway judge sends no record id to a model (D-644).

``GatewayJudge.judge`` passed the cascade's excerpts whole, and each carries ``did``: the document's id, a keyed
hash written in hex. So the id was rendered into the judge prompt. A record id has no place in a model prompt, and
a hex string holds digit runs: twelve digits read as an ID number, "0" and nine digits as a phone number. The PHI
tripwire then refused the call: 100 of 960 judge prompts on the scale kit's dense synthetic hospital, 0 of 960
without the id (measured 2026-11-13; 5 of 85 and 1 of 17 in the runs that reported it). The orchestrator's own
judge (``NoteJudge``) already sent the three fields a model needs.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

from gateway.core import _content_text
from guard.guard import Guard
from matching.cascade.judge import GatewayJudge
from tb_llm.outage import OutageBudget

# ids shaped as the lake's (32 hex characters), each holding a run the tripwire reads as an identifier
PHONE_LIKE = "a3f0912345678bc41d09e77a2f61c0de"  # "0" + nine digits
ID_LIKE = "7be420198812345ccc19f0a2d3e4b5a6"  # twelve digits in a row


class _Client:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    def chat(self, messages: Any, labels: Any, **kw: Any) -> Any:
        self.sent.append(messages)
        answer = {"verdict": "unknown", "confidence": 0.0, "quote": None, "quote_date": None, "reason": "stand-in"}
        return SimpleNamespace(data=answer, call_id="c1", build_sha="b", tokens_in=1, tokens_out=1)


def _ask(excerpts: list[dict[str, Any]]) -> str:
    client = _Client()
    GatewayJudge(client, outage=OutageBudget()).judge(
        role="judge",
        criterion_text="History of gout flares.",
        note_question="Do the notes document a gout flare?",
        index_date=date(2026, 10, 5),
        excerpts=excerpts,
        study_id="GZQO",
        data_class="D0",
        step_id="test",
        purpose="feasibility",
    )
    return _content_text(client.sent[0])


EXCERPTS = [
    {"date": "2026-09-01", "note_type": "progress", "text": "右第一MTP関節の急性痛風発作。", "did": PHONE_LIKE},
    {"date": "2026-08-01", "note_type": "progress", "text": "Colchicine given.", "did": ID_LIKE, "extra": "x"},
]


def test_the_prompt_holds_the_three_fields_of_an_excerpt_and_no_record_id() -> None:
    text = _ask(EXCERPTS)
    assert "右第一MTP関節の急性痛風発作。" in text and "Colchicine given." in text and "2026-09-01" in text
    assert PHONE_LIKE not in text and ID_LIKE not in text and '"did"' not in text and '"extra"' not in text


def test_the_tripwire_does_not_refuse_a_call_for_its_record_ids() -> None:
    guard = Guard(r"^\d{8}$")
    assert guard.tripwire(PHONE_LIKE).hit and guard.tripwire(ID_LIKE).hit  # the ids alone are what it refuses
    assert not guard.tripwire(_ask(EXCERPTS)).hit


def test_the_callers_excerpts_keep_their_id_for_the_quote_check() -> None:
    """The id stays on the caller's side: ``verify_span`` reads it from the excerpts it is given."""
    before = [dict(e) for e in EXCERPTS]
    _ask(EXCERPTS)
    assert before == EXCERPTS
