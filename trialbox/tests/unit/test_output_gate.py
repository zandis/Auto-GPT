"""The model output policy constructs a new value, or audits one fixed refusal reason."""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

import pytest
from tb_common import phi_guard
from tb_common.output_gate import OutputRefused, prepare_output

pytestmark = pytest.mark.nodb


def test_gate_projects_nested_excerpts_without_changing_its_input() -> None:
    row = {
        "text": "Patient name: Robin Example. Gout.",
        "date": "2026-01-01",
        "note_type": "Dr. Robin Example",
        "same_text_copies": 2,
        "did": "source-id",
        "debug": {"nested": ["do not release"]},
    }
    out = prepare_output("judge", "model", {"excerpts": [row], "debug": row})
    assert set(out) == {"excerpts"}
    shown = out["excerpts"][0]
    assert set(shown) == {"date", "note_type", "text", "same_text_copies"}
    assert "Robin" not in str(out) and "Gout" in shown["text"] and shown["same_text_copies"] == 2
    assert "Robin" in str(row["text"])


def test_chat_projects_every_part_and_discards_unknown_fields() -> None:
    hidden = {"nested": ["never release"]}
    part = {"type": "text", "text": "姓名：陳美華，痛風。", "image": hidden}
    req = {
        "messages": [{"role": "user", "content": [part], "debug": hidden}],
        "unused": hidden,
        "response_format": {
            "type": "json_schema",
            "extra": hidden,
            "json_schema": {"name": "judge", "strict": True, "schema": {}, "extra": hidden},
        },
    }
    out = prepare_output("chat", "model", req)
    assert "never release" not in str(out) and "陳美華" not in str(out)
    assert "痛風" in str(out) and req["messages"][0]["content"][0] == part  # type: ignore[index]


@pytest.mark.parametrize(
    ("purpose", "dest", "data"),
    [
        ("unknown clinical string", "model", {}),
        ("judge", "unknown clinical string", {}),
        ("judge", "model", {"excerpts": [{"text": {"nested": ["unknown clinical string"]}}]}),
        ("judge", "model", {"excerpts": [{"same_text_copies": True}]}),
        ("chat", "model", {"messages": [{"role": "user", "content": [{"type": "image_url"}]}]}),
        (
            "chat",
            "model",
            {
                "messages": [],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"schema": {"type": "object", "description": "unknown clinical string"}},
                },
            },
        ),
        ("chat", "model", {"messages": [], "max_tokens": True}),
    ],
)
def test_refusals_audit_only_closed_values(
    purpose: str, dest: str, data: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path))
    with pytest.raises(OutputRefused):
        prepare_output(purpose, dest, data)
    record = json.loads(next(tmp_path.glob("*.jsonl")).read_text())
    assert record["event"] == "llm.output_refused"
    assert set(record["detail"]) == {"purpose", "reason"}
    assert "unknown clinical string" not in str(record)


@pytest.mark.parametrize("failure", ["missing", "raised", "invalid"])
def test_analyser_failure_withholds_even_its_exception_context(
    failure: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    text = "synthetic withheld text"
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path))

    def broken(*args: Any) -> Any:
        if failure == "raised":
            raise RuntimeError(text)
        return None

    monkeypatch.setattr(phi_guard, "mask_note", None if failure == "missing" else broken)
    with pytest.raises(OutputRefused, match="analysis_unavailable") as err:
        prepare_output("chart_text", "model", {"text": text})
    assert text not in "".join(traceback.format_exception(err.value))
    assert text not in next(tmp_path.glob("*.jsonl")).read_text()


def test_one_name_split_between_message_parts_is_masked() -> None:
    parts = [{"type": "text", "text": t} for t in ("Patient name: ", "Robin ", "Example. Gout.")]
    result = prepare_output("chat", "model", {"messages": [{"role": "user", "content": parts}]})
    text = "".join(p["text"] for p in result["messages"][0]["content"])
    assert "Robin" not in text and "Example" not in text and "Gout" in text


def test_prefill_builds_references_and_drops_hidden_note_content() -> None:
    notes = [{"id": "unlabelled-source-id", "text": "Gout", "subject": {"name": "hidden"}}]
    result = prepare_output("crf_prefill", "model", {"item": {"name": "observation"}, "notes": notes})
    assert result["notes"] == [{"id": "n1", "text": "Gout"}]
