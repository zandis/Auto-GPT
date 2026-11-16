"""G4 of the integrator's second review of the P1b run (#639, 2026-11-16): four protocols (NCT00974064, NCT01181232,
NCT01745731, NCT02378311) failed at ir_extract with "gateway refused ir_extract: upstream_failed": a part of 12-15
lines could not be written within the gateway's 180 s read timeout, and the refusal was never retried.

* A part the gateway gave up on is asked again in halves (at most two halvings deep); its lines' answers come back
  whole. A model that is down, a prompt too long, any other refusal, or a single line fails as before.
* A part is sized by time too: no more lines than the model writes within the read timeout.

Stand-in model; synthetic protocol lines.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from criteria_compiler import service
from criteria_compiler.service import CompileFailed, Compiler, lines_per_part, too_slow
from tb_common.llm import LlmError, LlmModelFault, LlmPromptTooLong


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
    comp = _comp(7, LlmError("gateway refused ir_extract: upstream_failed"), asked)
    out = comp._ask_in_halves("J", "T", "en", _lines(15), SimpleNamespace(), "")  # type: ignore[arg-type]
    assert [a["text"] for a in out] == [f"line {i}" for i in range(15)]
    assert asked[0] == 15 and sum(n for n in asked if n <= 7) == 15  # the answered parts hold every line once


def test_halving_stops_two_levels_deep() -> None:
    asked: list[int] = []
    comp = _comp(1, LlmError("gateway refused ir_extract: upstream_failed"), asked)
    with pytest.raises(CompileFailed):
        comp._ask_in_halves("J", "T", "en", _lines(16), SimpleNamespace(), "")  # type: ignore[arg-type]
    assert len(asked) <= 1 + 2 + 4


@pytest.mark.parametrize(
    "error",
    [LlmModelFault("gateway refused ir_extract: upstream_down", "upstream_down"),
     LlmPromptTooLong("gateway refused ir_extract: prompt_too_long"), LlmError("gateway refused ir_extract: phi")],
)  # fmt: skip
def test_any_other_failure_fails_as_before(error: Exception) -> None:
    asked: list[int] = []
    comp = _comp(0, error, asked)
    with pytest.raises(CompileFailed):
        comp._ask_in_halves("J", "T", "en", _lines(10), SimpleNamespace(), "")  # type: ignore[arg-type]
    assert asked == [10] and not too_slow(error)


def test_a_part_is_sized_by_time_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_EXTRACT_TOKENS_PER_S", raising=False)
    assert lines_per_part(8192, read_s=180) == int(180 * service.EXTRACT_TOKENS_PER_S * service.TIME_SHARE) // 400
    assert lines_per_part(8192, read_s=180) < 12  # the run's parts of 12-15 lines ran past 180 s
    assert lines_per_part(8192, read_s=10_000) == int(8192 * 0.75) // 400  # the answer cap, when time is no limit
    monkeypatch.setenv("TB_EXTRACT_TOKENS_PER_S", "1")
    assert lines_per_part(8192, read_s=180) == 1
