"""Two-model judge: a criterion blocks only when the judge and the verifier builds agree (S1-14, SAFE-13).

The cascade's :class:`AgreementJudge` and the bake-off's recorded-answer rule :func:`agreement_rows` implement the
same rule; disagreement abstains, and an abstention is never an exclusion (SAFE-13). No network.
"""

from __future__ import annotations

from typing import Any

import pytest
from matching.cascade.judge import AgreementJudge, JudgeReply

from tools import bakeoff_live


class Fixed:
    def __init__(self, verdict: str, refused: str | None = None) -> None:
        self.verdict, self.refused = verdict, refused
        self.roles: list[str] = []

    def judge(self, *, role: str, **_: Any) -> JudgeReply:
        self.roles.append(role)
        return JudgeReply(self.verdict, 0.9, "q", None, "r", call_id="c", build_sha="s", refused=self.refused)


KW: dict[str, Any] = {"criterion_text": "x", "note_question": "x?", "excerpts": []}


@pytest.mark.req("S1-14", "SAFE-13")
def test_agreement_judge_blocks_only_on_agreement() -> None:
    a, b = Fixed("fail"), Fixed("fail")
    assert AgreementJudge(a, b).judge(role="judge", **KW).verdict == "fail" and b.roles == ["judge"]
    j = AgreementJudge(Fixed("fail"), Fixed("pass"))
    out = j.judge(role="judge", **KW)
    assert out.verdict == "unknown" and "disagree" in out.reason and j.disagreements == 1
    refused = AgreementJudge(Fixed("pass"), Fixed("unknown", refused="phi_tripwire")).judge(role="judge", **KW)
    assert refused.verdict == "unknown" and "phi_tripwire" in refused.reason
    abstain, never = Fixed("unknown"), Fixed("fail")
    assert AgreementJudge(abstain, never).judge(role="judge", **KW).verdict == "unknown" and never.roles == []
    p, v = Fixed("pass"), Fixed("fail")
    assert AgreementJudge(p, v).judge(role="second_opinion", **KW).verdict == "fail"  # S4 goes to the verifier
    assert p.roles == [] and v.roles == ["second_opinion"]


def _row(i: str, pred: str, cost: float) -> bakeoff_live.Row:
    r = bakeoff_live.Row("x", "en", i, "exclusion", "not excluded", "not excluded", pred=pred, valid=True)
    r.cost_usd, r.latency_s, r.call_id = cost, 1.0, "c"
    return r


@pytest.mark.req("S1-14", "SAFE-13")
def test_agreement_rows_on_recorded_answers() -> None:
    judge = [_row("1", "excluded", 0.01), _row("2", "excluded", 0.01), _row("3", "not excluded", 0.01)]
    verifier = [_row("1", "excluded", 0.02), _row("2", "not excluded", 0.02), _row("3", "excluded", 0.02)]
    out = {r.annotation_id: r for r in bakeoff_live.agreement_rows(judge, verifier)}
    assert out["1"].pred == "excluded" and out["1"].cost_usd == pytest.approx(0.03)  # both block
    assert out["2"].pred == "not enough information"  # judge blocks, verifier does not: abstain
    assert out["3"].pred == "not excluded" and out["3"].cost_usd == pytest.approx(0.01)  # verifier not consulted
    assert all(r.build_id == "agree:x+x" for r in out.values())
