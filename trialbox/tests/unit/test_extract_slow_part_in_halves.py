"""G4 of the integrator's second review of the P1b run (#639, 2026-11-16): four protocols (NCT00974064, NCT01181232,
NCT01745731, NCT02378311) failed at ir_extract with "gateway refused ir_extract: upstream_failed": a part of 12-15
lines could not be written within the gateway's 180 s read timeout, and the refusal was never retried.

* A part the gateway gave up on (``LlmUpstreamFailed``: its ``upstream_failed``, or the endpoint's read timeout) is
  asked again in halves (at most two halvings deep); its lines' answers come back whole. A model that is down, a prompt too long, any other refusal, or a single line fails as before.
* A part is sized by time too: no more lines than the model writes within the read timeout.

Stand-in model; synthetic protocol lines.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from criteria_compiler import service
from criteria_compiler.service import CompileFailed, Compiler, lines_per_part
from tb_common.llm import LlmError, LlmModelFault, LlmPromptTooLong, LlmUpstreamFailed


def _lines(n: int) -> list[dict[str, Any]]:
    return [{"text": f"line {i}", "kind": "inclusion", "parent": None} for i in range(n)]


def _comp(fails_over: int, error: Exception, asked: list[int]) -> Compiler:
    comp = Compiler(SimpleNamespace())  # type: ignore[arg-type]

    def ask(job_id: str, ruleset: str, language: str, part: list[dict[str, Any]], guard: Any, where: str) -> list[Any]:
        asked.append(len(part))
        if len(part) > fails_over:
            raise CompileFailed("ir_extract", "the model did not return usable criteria") from error
        return [{"text": ln["text"]} for ln in part]

    comp._ask_extract = ask  # type: ignore[method-assign]
    return comp


def test_a_part_the_gateway_gave_up_on_is_asked_in_halves() -> None:
    asked: list[int] = []
    comp = _comp(7, LlmUpstreamFailed("gateway refused ir_extract: upstream_failed"), asked)
    out = comp._ask_in_halves("J", "T", "en", _lines(15), SimpleNamespace(), "")  # type: ignore[arg-type]
    assert [a["text"] for a in out] == [f"line {i}" for i in range(15)]
    assert asked[0] == 15 and sum(n for n in asked if n <= 7) == 15  # the answered parts hold every line once


def test_halving_stops_two_levels_deep() -> None:
    asked: list[int] = []
    comp = _comp(1, LlmUpstreamFailed("gateway refused ir_extract: upstream_failed"), asked)
    with pytest.raises(CompileFailed):
        comp._ask_in_halves("J", "T", "en", _lines(16), SimpleNamespace(), "")  # type: ignore[arg-type]
    assert len(asked) <= 1 + 2 + 4


@pytest.mark.parametrize(
    "error",
    [LlmModelFault("gateway refused ir_extract: upstream_down", "upstream_down"),
     LlmPromptTooLong("gateway refused ir_extract: prompt_too_long"), LlmError("gateway refused ir_extract: phi"),
     LlmError("text that says upstream_failed")],  # an error's words decide nothing
)  # fmt: skip
def test_any_other_failure_fails_as_before(error: Exception) -> None:
    asked: list[int] = []
    comp = _comp(0, error, asked)
    with pytest.raises(CompileFailed):
        comp._ask_in_halves("J", "T", "en", _lines(10), SimpleNamespace(), "")  # type: ignore[arg-type]
    assert asked == [10]  # decided by the error's type (D-651), never its text


def test_a_part_is_sized_by_time_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_EXTRACT_RATE_PER_S", raising=False)
    assert lines_per_part(8192, read_s=180) == int(180 * service.EXTRACT_TOKENS_PER_S * service.TIME_SHARE) // 400
    assert lines_per_part(8192, read_s=180) < 12  # the run's parts of 12-15 lines ran past 180 s
    assert lines_per_part(8192, read_s=10_000) == int(8192 * 0.75) // 400  # the answer cap, when time is no limit
    monkeypatch.setenv("TB_EXTRACT_RATE_PER_S", "1")
    assert lines_per_part(8192, read_s=180) == 1


def test_the_gateways_upstream_failed_is_raised_as_its_own_type() -> None:
    from tb_common.llm import LlmClient
    from tb_llm import GatewayRefused

    class _Gateway:
        def complete(self, req: Any, labels: Any) -> Any:
            raise GatewayRefused("upstream_failed", 502, "the model did not answer in time")

    client = LlmClient("http://unused/v1", "m")
    client.gateway = _Gateway()
    with pytest.raises(LlmUpstreamFailed):
        client.chat_json("ir_extract", {"ruleset": "T", "language": "en", "criteria": []})
