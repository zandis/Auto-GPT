"""Red of lane G's frozen-commit run (#639, 2026-11-16): ``ir_extract`` refused by the gateway (``upstream_failed``,
compiler HTTP 422) 11 times, on long protocols, and the refused calls were not in the trace store (D-911).

* **The limit.** One call carried the whole protocol, and the prompt caps its answer at ``max_tokens`` (8,192): at up
  to about 330 tokens a criterion (its concept candidates and synonyms), a protocol past about 25 lines was cut off,
  and the gateway refuses a malformed answer as ``upstream_failed``. The prompt also has to fit the model's context.
* **Now.** The compiler sends the protocol in parts of :func:`lines_per_part` lines (an answer that fits three
  quarters of the cap), split at a section boundary where it can be, a line never apart from the lines under it, and
  joins the answers in order. (qualify's longest-prompt check cannot carry it: it measures the judge's context and
  sends through the judge's role, which the gateway refuses for ``ir_extract``, a role and model class of its own.)
* **A refused call leaves a trace** with its reason; its prompt is kept only when the call was cleared for a model and
  failed there, never for a refusal of the call itself.

Synthetic protocols; a recording model client; the gateway in-process with a scripted model server.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from criteria_compiler import service
from criteria_compiler.service import (
    ANSWER_SHARE,
    TOKENS_PER_CRITERION,
    extraction_parts,
    lines_per_part,
)
from tb_common.llm import LlmResult, load_prompt


def _protocol(n_inc: int, n_exc: int) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = [{"text": f"Inclusion line {i}", "kind": "inclusion"} for i in range(n_inc)]
    lines.append({"text": "Any of the following:", "kind": "exclusion"})
    lead = len(lines) - 1
    lines += [{"text": f"Sub-item {i}", "kind": "exclusion", "parent": lead} for i in range(4)]
    lines += [{"text": f"Exclusion line {i}", "kind": "exclusion"} for i in range(n_exc)]
    return lines


def test_a_part_answers_inside_the_prompts_cap() -> None:
    cap = int(load_prompt("ir_extract").meta.max_tokens)
    n = lines_per_part()
    assert n >= 1 and n * TOKENS_PER_CRITERION <= cap * ANSWER_SHARE
    assert lines_per_part(2048) < n  # a smaller cap, smaller parts


def test_the_parts_cover_every_line_in_order_and_keep_a_lead_in_with_its_items() -> None:
    lines = _protocol(20, 30)
    parts = extraction_parts(lines, 15)
    covered = [i for start, part in parts for i in range(start, start + len(part))]
    assert covered == list(range(len(lines)))  # every line once, in order
    assert all(len(p) <= 15 for _, p in parts)
    lead = next(i for i, ln in enumerate(lines) if ln["text"] == "Any of the following:")
    holder = next((s, p) for s, p in parts if s <= lead < s + len(p))
    s, p = holder
    assert all(s <= lead + k < s + len(p) for k in range(5))  # the lead-in and its four items, one part
    for k in range(1, 5):
        assert p[lead - s + k]["parent"] == lead - s  # rebased inside the part
    assert any(p[0]["kind"] == "exclusion" and s > 0 for s, p in parts)  # a section boundary started a part


class _Model:
    def __init__(self, short: int | None = None) -> None:
        self.parts: list[int] = []
        self.short = short

    def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> LlmResult:
        lines = variables["criteria"]
        self.parts.append(len(lines))
        n = len(lines) - (1 if self.short == len(self.parts) else 0)
        crit = [{"kind": ln["kind"], "class": "human", "text": ln["text"], "human_question": "?", "concept_candidates": []}
                for ln in lines[:n]]  # fmt: skip
        return LlmResult({"criteria": crit}, prompt_id, 3, "m", "local", "i", "o", 1, 1, 1)


def _compiler(model: _Model) -> Any:
    comp = object.__new__(service.Compiler)
    comp.d = type("D", (), {"llm": model, "mrn_regex": None})()
    return comp


def test_a_long_protocol_is_asked_in_parts_and_the_answers_join_in_order() -> None:
    lines = _protocol(30, 40)
    model = _Model()
    out, _guard, unread = _compiler(model)._extract("J", "T", "en", lines)
    assert len(model.parts) > 1 and max(model.parts) <= lines_per_part() and sum(model.parts) == len(lines)
    assert [c.text for c in out.criteria] == [ln["text"] for ln in lines] and not unread
    short = _compiler(_Model())._extract("J", "T", "en", _protocol(3, 3))[0]
    assert len(short.criteria) == 3 + 5 + 3  # a protocol that fits: one call, as before


# ------------------------------------------------------------------------------------------- the refused call's trace
class _Traces:
    def __init__(self) -> None:
        self.written: list[dict[str, Any]] = []

    def write(self, trace: dict[str, Any]) -> str:
        self.written.append(trace)
        return str(trace["call_id"])


@pytest.mark.nodb
def test_a_refused_call_leaves_a_trace_with_its_reason(tmp_path: Path) -> None:
    from tests.unit.test_gateway import H, _judge_body
    from tests.unit.test_gateway_one_role_one_model import JUDGE_HOST, _gw, _vllm

    http, _log = _vllm({JUDGE_HOST: "timeout"})
    gw = _gw(tmp_path, http)
    traces = _Traces()
    gw.traces = traces  # type: ignore[assignment]
    res = gw.chat(H(Data_Class="D3"), _judge_body())
    assert res.body["error"]["code"] == "upstream_failed"
    [t] = traces.written
    assert t["span"] == "refusal" and t["attributes"]["tb.refusal"] == "upstream_failed"
    assert t["call_id"] == res.body["error"]["call_id"] and t["prompt"] and t["sc"] is True
    assert t["attributes"]["tb.upstream_kinds"] == ["timeout"]
    refused = _gw(tmp_path / "b", _vllm({})[0])
    before = _Traces()
    refused.traces = before  # type: ignore[assignment]
    res = refused.chat(H(Data_Class="D9"), _judge_body())  # refused before any model: no prompt kept
    [t] = before.written
    assert res.status == 403 and t["prompt"] is None and t["attributes"]["tb.refusal"] == res.body["error"]["code"]
