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


def test_tokenize_on_a_read_only_proxy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    import sys

    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path))
    # A fresh interpreter exercises the first import made by an authenticated request.
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
from unittest.mock import patch
from tests.unit.test_model_guard import KEY, _call, _start, _Upstream
from model_guard import Guard, make_handler
with patch("tempfile.gettempdir", side_effect=FileNotFoundError):
    upstream = _start(_Upstream)
    proxy = _start(make_handler(Guard(KEY, {"llm-service": upstream.server_address})))
    assert _call(proxy.server_port, "GET", "/healthz", key=None) == 200
    assert _call(proxy.server_port, "POST", "/tokenize", body=b'{"prompt":"hello"}') == 200
    assert _Upstream.seen[-1][1] == "/tokenize"
    assert _call(proxy.server_port, "POST", "/tokenize", body=b'{"prompt":42}') == 422
    assert len(_Upstream.seen) == 1
""",
        ],
        check=True,
    )
    record = json.loads(next(tmp_path.glob("*.jsonl")).read_text())
    assert record["detail"] == {"purpose": "tokenize", "reason": "output_invalid"}


def test_guard_only_spans_keep_their_offsets() -> None:
    from guard import Guard

    note = "Pt: Robin Example. Gout."
    spans = Guard().detect(note)
    assert spans and note[spans[0].start : spans[0].end] == "Robin Example"
    shown = prepare_output("chart_text", "model", {"text": note})["text"]
    assert "Robin" not in shown and "Example" not in shown
    assert len(note) == len(shown) and shown.index("Gout") == note.index("Gout")


def test_unregistered_schema_name_is_refused() -> None:
    from tb_contracts import inline_schema

    fmt = {"type": "json_schema", "json_schema": {"name": "Robin-Example", "schema": inline_schema("llm_judge_output")}}
    with pytest.raises(OutputRefused, match="output_identifier_refused"):
        prepare_output("chat", "model", {"messages": [{"role": "user", "content": "hello"}], "response_format": fmt})


@pytest.mark.parametrize("field", ["name", "code"])
def test_identifying_form_keys_refuse_the_form(field: str) -> None:
    item = {"name": "Pt: Robin Example"} if field == "name" else {"choices": [{"code": "Pt: Robin Example"}]}
    with pytest.raises(OutputRefused, match="output_identifier_refused"):
        prepare_output("crf_prefill", "model", {"item": item, "notes": []})


def test_chart_section_provenance_takes_precedence_over_local_note_type() -> None:
    rows = [
        {"note_type": "Robin-Example", "section_heading": "", "text": "Referral."},
        {"note_type": "chart", "section_heading": "Family history", "text": "Breast cancer."},
    ]
    shown = prepare_output("judge", "model", {"excerpts": rows})["excerpts"]
    assert [e["note_type"] for e in shown] == ["chart", "Family history"]
    assert "Robin" not in str(shown)


def test_guard_failure_withholds_a_clean_note(monkeypatch: pytest.MonkeyPatch) -> None:
    from guard import Guard

    def unavailable(self: Guard, text: str) -> None:
        raise RuntimeError(text)

    monkeypatch.setattr(Guard, "detect", unavailable)
    with pytest.raises(OutputRefused, match="analysis_unavailable"):
        prepare_output("embedding", "model", {"texts": ["Gout."]})


def test_form_refusal_message_is_available_in_each_console_language() -> None:
    from console import i18n_edc
    from tb_common.output_gate import IDENTIFIER_MESSAGE

    key = "edc.err.output_identifier_refused"
    assert {"en": i18n_edc.EN[key], "zh-TW": i18n_edc.ZH[key], "ja": i18n_edc.JA[key]} == IDENTIFIER_MESSAGE
    assert len(set(IDENTIFIER_MESSAGE.values())) == 3


@pytest.mark.parametrize(
    "data",
    [
        {"model": "Robin-Example"},
        {"provider": {"order": ["Robin-Example"]}},
        {"provider": {"order": [], "quantizations": ["Robin-Example"]}},
    ],
)
def test_caller_cannot_make_a_routing_identifier_public(data: dict[str, Any]) -> None:
    with pytest.raises(OutputRefused, match="output_identifier_refused"):
        prepare_output("dispatch", "model", data)
