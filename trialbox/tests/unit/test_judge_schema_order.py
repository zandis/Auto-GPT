"""The judge's output schema ends with ``confidence`` (found on the card, 8 Nov: vLLM 0.32 guided JSON with both on-card
models ended the answer after ``confidence``; with ``reason`` required after it they padded whitespace to max_tokens,
every call was truncated and retried at 4x the tokens, and the verifier never answered on real notes)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_confidence_is_the_last_property_a_guided_decoder_writes() -> None:
    s = json.loads((ROOT / "schemas" / "llm_judge_output.schema.json").read_text(encoding="utf-8"))
    props = list(s["properties"])
    assert props[-1] == "confidence" and props.index("reason") < props.index("confidence")
    assert s["required"] == props  # every property required (strict mode), in the same order
