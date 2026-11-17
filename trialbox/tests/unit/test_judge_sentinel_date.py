"""G8 of the integrator's second review of the P1b run (#639, 2026-11-16), D-958: on NCT00277680 the judge answered
"unknown" with ``quote_date: "0000-01-01"`` (its way of saying it has none) on the attempt and the retry; the schema's
``format: date`` refused the reply, it counted as no answer, and one failure of 7 checks is above the share, so the
whole SCREEN job failed. The run's raw traces hold four such replies (``judge@5``).

* A quote date that is no real date is null: the reply is an answer ("unknown"), not a reply outside the schema.
* A real date, and a reply truly outside the schema, are unchanged; so is the share rule (a model that is down still
  fails a job: ``test_screen_cascade``, ``test_gateway_one_role_one_model``, ``test_gateway_no_fallback``).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from matching.cascade.judge import GatewayJudge
from tb_common.llm import no_sentinel_date


class _Res:
    def __init__(self, data: Any) -> None:
        self.data, self.call_id, self.build_sha, self.tokens_in, self.tokens_out = data, "c1", "b", 1, 1


class _Client:
    def __init__(self, data: Any) -> None:
        self.data = data

    def chat(self, *a: Any, **kw: Any) -> _Res:
        return _Res(self.data)


KW: dict[str, Any] = {"role": "judge", "criterion_text": "No contraindications against laparoscopic surgery",
                      "note_question": "Does the patient have contraindications against laparoscopic surgery?",
                      "index_date": date(2026, 10, 5), "excerpts": [], "study_id": "S-1", "data_class": "D0",
                      "step_id": "s", "purpose": "screening"}  # fmt: skip
RUN_REPLY = {"verdict": "unknown", "reason": "The provided excerpts do not mention any contraindications against "
             "laparoscopic surgery for the patient.", "quote": "unknown", "quote_date": "0000-01-01",
             "confidence": 1.0}  # fmt: skip


def test_the_runs_sentinel_reply_is_an_answer() -> None:
    r = GatewayJudge(_Client(RUN_REPLY)).judge(**KW)
    assert r.verdict == "unknown" and r.refused is None and r.quote_date is None, r


@pytest.mark.parametrize("qd", ["0000-01-01", "0001-01-01", "1899-12-31", "unknown", "2026-13-45", ""])
def test_a_date_that_is_no_real_date_is_null(qd: str) -> None:
    assert no_sentinel_date({"quote_date": qd})["quote_date"] is None


def test_a_real_date_and_a_reply_outside_the_schema_are_unchanged() -> None:
    assert no_sentinel_date({"quote_date": "2026-10-01"})["quote_date"] == "2026-10-01"
    r = GatewayJudge(_Client({"verdict": "PASS!", "confidence": 0.9, "quote_date": "0000-01-01"})).judge(**KW)
    assert r.verdict == "unknown" and r.refused == "schema_invalid"
