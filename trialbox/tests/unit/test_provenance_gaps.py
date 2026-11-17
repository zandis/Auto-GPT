"""D-989 step 1 (the gap-closing, before the index): a model's answer names the build and the prompt text behind it.

* SCREEN's judge reply carried the model's *name* as its ``build_sha`` and no ``prompt_sha``; it now carries the
  build that answered ("" on a direct call) and the registry's sha256 of the prompt text.
* The cascade's evidence meta keeps ``prompt_sha`` beside ``call_id``, ``build_sha`` and ``prompt``.
* The ``llm.call`` audit event records ``build_sha`` (the gateway's event already did) and ``call_id``, which the
  result carries too: the gateway's id, or on a direct call one derived from the answer (a re-run keeps it).
* SCREEN's reply names that call id; it was a prefix of the answer's hash.
* Each extracted criterion names the call it came from (IR 1.3.0 ``provenance.calls``): the part's call, the
  retry's for a line asked again, each half's for a part asked in halves (D-981), none for a line left to a person.

Synthetic excerpts; no patient data."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from criteria_compiler import service
from criteria_compiler.service import CompileFailed, Compiler, with_calls
from matching.cascade.judge import JudgeReply
from orchestrator.scenarios.screen_cascade import OrchestratorJudge
from tb_common.llm import LlmResult, LlmUpstreamFailed
from tb_contracts import CriterionIR, validate
from tb_contracts.criterion_ir import downgrade_to_v1, upgrade_v1

from tests.unit.test_criterion_ir_v3 import IR_FILES
from tests.unit.test_ir_extract_aligned import LINES, _crit, _Model
from tests.unit.test_llm_client import _client
from tests.unit.test_safety_properties import SPAN, _ir, _run_for_map
from tests.unit.test_screen_cascade import FakeLlm, _ask, _res


def test_screens_reply_names_the_build_and_the_prompt_text_never_the_models_name() -> None:
    res = replace(_res("pass"), build_sha="sha256:b1d", prompt_sha="f" * 64)
    r = _ask(OrchestratorJudge(None, FakeLlm([res])))  # type: ignore[arg-type]
    assert r.build_sha == "sha256:b1d" and r.prompt_sha == "f" * 64 and r.prompt == "judge@4"


def test_a_direct_call_has_no_build_and_says_so() -> None:
    r = _ask(OrchestratorJudge(None, FakeLlm([_res("pass")])))  # type: ignore[arg-type]
    assert r.build_sha == "" and r.build_sha != "m"  # "m" is the result's model name


def test_the_cascades_evidence_keeps_the_prompt_text_hash() -> None:
    c = _ir("N-INC-09", "inclusion", "note", {"domain": "condition", "valueset": "VS_X"}, text="Gout",
            note_question="Gout?")  # fmt: skip
    reply = JudgeReply("pass", 0.95, str(SPAN["quote"]), None, "r", call_id="c1", build_sha="b1", prompt="judge@4",
                       prompt_sha="p" * 64)  # fmt: skip
    o = _run_for_map(True)._map(c, reply, SPAN, "S3")
    meta = next(e for e in o.evidence if "call_id" in e)
    assert (meta["call_id"], meta["build_sha"], meta["prompt"], meta["prompt_sha"]) == ("c1", "b1", "judge@4", "p" * 64)


def test_the_llm_call_event_records_the_build_and_the_call(tmp_path: Path) -> None:
    excerpt = {"date": "2026-10-01", "note_type": "progress", "text": "Gout flare noted."}
    res = _client(tmp_path).chat_json("judge", {"criterion_text": "x", "note_question": "Gout flare?",
                                                "index_date": "2026-10-05", "excerpts": [excerpt]})  # fmt: skip
    line = json.loads(next(tmp_path.glob("*.jsonl")).read_text().splitlines()[0])
    assert line["event"] == "llm.call" and "build_sha" in line["detail"] and "prompt_sha" in line["detail"]
    assert res.call_id == line["detail"]["call_id"] == f"direct-{res.output_sha[:16]}"


def test_screens_reply_names_the_call() -> None:
    r = _ask(OrchestratorJudge(None, FakeLlm([replace(_res("pass"), call_id="gw-7")])))  # type: ignore[arg-type]
    assert r.call_id == "gw-7"


# ---------------------------------------------------------------------------------------- the extraction's pointers
def _extract_with_calls(*script: Any) -> tuple[dict[int, str], dict[int, list[str]]]:
    """``_extract`` over the aligned test's four lines; each call answers under its own id (c1, c2, ...)."""
    model = _Model(*script)
    n = iter(range(1, 99))

    def chat_json(prompt_id: str, variables: dict[str, Any], **kw: Any) -> LlmResult:
        return replace(_Model.chat_json(model, prompt_id, variables, **kw), call_id=f"c{next(n)}")

    model.chat_json = chat_json  # type: ignore[method-assign]
    comp = object.__new__(service.Compiler)
    comp.d = type("D", (), {"llm": model, "mrn_regex": None})()
    _out, _guard, unread, calls = comp._extract("J", "T", "en", LINES)
    return unread, calls


def test_each_extracted_line_names_its_call() -> None:
    assert _extract_with_calls() == ({}, {0: ["c1"], 1: ["c1"], 2: ["c1"], 3: ["c1"]})


def test_a_line_asked_again_names_the_second_call_and_a_persons_line_names_none() -> None:
    unread, calls = _extract_with_calls(lambda ls: [_crit(x) for x in ls if x["text"] != "Signed consent"],
                                        lambda ls: [_crit(x) for x in ls if x["text"] != "Signed consent"])  # fmt: skip
    assert unread == {1: "not_extracted"} and calls == {0: ["c1"], 2: ["c1"], 3: ["c1"]}
    unread, calls = _extract_with_calls(lambda ls: [_crit(x) for x in ls if x["text"] != "Active tuberculosis"])
    assert unread == {} and calls == {0: ["c1"], 1: ["c1"], 2: ["c2"], 3: ["c1"]}


def test_the_halves_keep_their_own_calls() -> None:
    comp = Compiler(SimpleNamespace())  # type: ignore[arg-type]
    seen = iter(range(1, 99))

    def ask(job_id: str, ruleset: str, language: str, part: list[dict[str, Any]], guard: Any, where: str) -> Any:
        if len(part) > 2:
            raise CompileFailed("ir_extract", "x") from LlmUpstreamFailed("gateway refused ir_extract: upstream_failed")
        cid = f"h{next(seen)}"
        return service._Answers([{"text": ln["text"]} for ln in part], [cid] * len(part))

    comp._ask_extract = ask  # type: ignore[method-assign]
    lines = [{"text": f"line {i}", "kind": "inclusion", "parent": None} for i in range(4)]
    out = comp._ask_in_halves("J", "T", "en", lines, SimpleNamespace(), "")  # type: ignore[arg-type]
    assert out.calls == ["h1", "h1", "h2", "h2"]


def test_the_ir_carries_the_calls_through_v3_and_back() -> None:
    c = CriterionIR.model_validate(json.loads(IR_FILES[0].read_text("utf-8")))
    (got,) = with_calls([c], {0: ["c1", "c2"]})
    assert got.provenance is not None and got.provenance.calls == ["c1", "c2"]
    v1 = got.model_dump(mode="json", by_alias=True, exclude_unset=True)
    validate("criterion_ir", v1)
    assert downgrade_to_v1(upgrade_v1(v1)) == v1
    assert with_calls([c], {}) == [c]  # a person's line: no model, no field
