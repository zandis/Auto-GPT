"""Card H-40 (lane H, 2026-11-19): wasted model calls counted in a stored run's traces.

``tools.public_accuracy.waste`` reads ``work/raw-traces.json`` and flags calls cut at the answer cap, looping, outside
the prompt's schema, and timed out. The traces here are made up, in the records' real shape: synthetic text, no
patient data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.public_accuracy import waste

pytestmark = pytest.mark.nodb

GOOD_JUDGE = json.dumps({"verdict": "pass", "reason": "made-up reason", "quote": "made-up quote",
                         "quote_date": "2026-01-02", "confidence": 0.9})  # fmt: skip
LOOPED_JUDGE = '{"verdict": "unknown", "reason": "made-up", "quote": "' + "\r  " * 300


def _trace(alias: str, prompt: str, output: Any, *, span: str = "chat", kinds: list[str] | None = None,
           repair: bool = False) -> dict[str, Any]:  # fmt: skip
    attrs: dict[str, Any] = {"tb.model_alias": alias, "tb.prompt": prompt, "tb.cache": "miss"}
    if span == "refusal":
        attrs |= {"tb.refusal": "upstream_failed", "tb.upstream_kinds": kinds or []}
    msgs = [{"role": "user", "content": "made-up question"}]
    if repair:
        msgs += [{"role": "assistant", "content": "earlier answer"}, {"role": "user", "content": "again"}]
    return {"call_id": "c", "span": span, "sc": False, "attributes": attrs, "prompt": msgs, "output": output,
            "ts": "2026-11-19T00:00:00+00:00"}  # fmt: skip


def _set(root: Path, traces: list[dict[str, Any]]) -> Path:
    d = root / "made"
    (d / "built" / "gold").mkdir(parents=True)
    (d / "work").mkdir(parents=True)
    (d / "built" / "gold" / "ids.json").write_text(json.dumps({"set": "made"}), encoding="utf-8")
    (d / "work" / "raw-traces.json").write_text(json.dumps({"since": "x", "calls": len(traces), "traces": traces}),
                                                encoding="utf-8")  # fmt: skip
    return d


def test_longest_repeat_finds_a_back_to_back_block_and_not_a_list() -> None:
    assert waste.longest_repeat("ab" * 50)[1] >= 50
    assert waste.is_loop(waste.longest_repeat("x " + "\r  " * 40))
    # a JSON list of different items repeats its keys, never one block back to back
    items = json.dumps([{"text": f"made-up line {i}", "kind": "inclusion"} for i in range(30)])
    assert not waste.is_loop(waste.longest_repeat(items))


def test_cut_is_a_text_that_stops_before_its_json_closes() -> None:
    assert waste.cut('{"a": "b')
    assert waste.cut(LOOPED_JUDGE)
    assert not waste.cut('{"a": 1}')
    assert not waste.cut('{"a": 1} trailing')  # not JSON, but the parser did not run off the end


def test_counts_per_model_with_timeouts_repairs_and_the_schema(tmp_path: Path) -> None:
    d = _set(tmp_path, [
        _trace("j-workhorse", "judge@5", GOOD_JUDGE),
        _trace("j-workhorse", "judge@5", json.dumps({"verdict": "maybe"}), repair=True),  # outside the schema
        _trace("v-verifier", "judge@5", LOOPED_JUDGE),
        _trace("j-workhorse", "ir_extract@4", None, span="refusal", kinds=["timeout"]),
    ])  # fmt: skip
    r = waste.waste([d], tmp_path / "scratch")
    by = r["sets"]["made"]["by_model"]
    j, v = by["j-workhorse"], by["v-verifier"]
    assert (j["calls"], j["timeout"], j["repair"], j["outside_schema"], j.get("loop", 0)) == (3, 1, 1, 1, 0)
    assert (v["calls"], v["cut"], v["loop"], v["outside_schema"], v["flagged"]) == (1, 1, 1, 1, 1)
    assert v["token_share_flagged"] == 1.0
    assert by["j-workhorse judge@5"]["answered"] == 2
    assert all(v[f"loop_{a}x{b}"] == 1 for a, b in waste.GRID)
    assert "j-workhorse" in waste.render(r)


def test_main_writes_json_and_refuses_a_full_scratch(tmp_path: Path) -> None:
    d = _set(tmp_path, [_trace("j-workhorse", "judge@5", GOOD_JUDGE)])
    out = tmp_path / "w.json"
    assert waste.main([str(d), "--json", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["sets"]["made"]["by_model"]["j-workhorse"]["flagged"] == 0
    full = tmp_path / "full"
    full.mkdir()
    (full / "x").write_text("x", encoding="utf-8")
    assert waste.main([str(d), "--scratch", str(full)]) == 2
