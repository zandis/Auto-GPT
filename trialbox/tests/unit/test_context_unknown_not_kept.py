"""Deep review 2026-11-13 (screening, SCR-18): one failed context lookup does not size a whole run's excerpts.

``LlmClient.context_tokens`` kept an unknown context (the gateway's ``GET /v1/models`` failed once) for its whole
TTL of 300 s. Every judge prompt sized in that time used the small default excerpt budget, so which notes the models
read, and so the tier of a patient, depended on whether one request failed. A known context is still kept.
"""

from __future__ import annotations

from typing import Any

from tb_common.llm import LlmClient


class FlakyGateway:
    def __init__(self, answers: list[Any]) -> None:
        self.answers = list(answers)
        self.asked = 0

    def context(self) -> Any:
        self.asked += 1
        return self.answers.pop(0) if self.answers else 32768


def _client(gw: FlakyGateway) -> LlmClient:
    return LlmClient("http://gateway.invalid/v1", "judge", gateway=gw)


def test_an_unknown_context_is_asked_again_at_the_next_call() -> None:
    gw = FlakyGateway([None, 32768])
    c = _client(gw)
    assert c.context_tokens() is None  # the gateway could not tell: the caller keeps its own default, this once
    assert c.context_tokens() == 32768 and gw.asked == 2


def test_a_known_context_is_kept_for_the_ttl() -> None:
    gw = FlakyGateway([16384, 99999])
    c = _client(gw)
    assert c.context_tokens() == 16384 and c.context_tokens() == 16384 and gw.asked == 1
