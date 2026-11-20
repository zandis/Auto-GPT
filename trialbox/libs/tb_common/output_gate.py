"""Construct the clinical payload a named output may receive."""

from __future__ import annotations

import copy
import logging
import math
import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, NoReturn

from tb_common import phi_guard
from tb_common.audit_writer import open_audit

_PURPOSES = frozenset(
    {
        "judge",
        "chart_facts",
        "crf_prefill",
        "chat",
        "embedding",
        "chart_text",
        "ie_locate",
        "draft_doc",
        "tokenize",
        "completion",
        "dispatch",
    }
)
_LANGUAGE = {"en": "English", "ja": "Japanese", "zh-TW": "Traditional Chinese"}


class OutputRefused(ValueError):
    """A stable, text-free reason, suitable for a caller's failure record."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _refuse(purpose: str, reason: str) -> NoReturn:
    detail = {"purpose": purpose if purpose in _PURPOSES else "unknown", "reason": reason}
    try:
        open_audit().append("llm.output_refused", detail=detail)
    except Exception:
        logging.getLogger(__name__).error("llm.output_refused", extra=detail)
    raise OutputRefused(reason)


class _Invalid(ValueError):
    pass


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _Invalid
    return value


def _list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise _Invalid
    return value


def _text(value: object, mrn: str | None) -> str:
    if not isinstance(value, str):
        raise _Invalid
    masked = phi_guard.mask_note(value, mrn)
    if not isinstance(masked, str) or len(masked) != len(value):
        raise RuntimeError
    return masked


def _fields(row: dict[str, Any], keys: tuple[str, ...], mrn: str | None) -> dict[str, Any]:
    return {key: _text(row[key], mrn) for key in keys if key in row}


def _judge(data: Mapping[str, object], mrn: str | None) -> dict[str, Any]:
    out = _fields(dict(data), ("criterion_text", "note_question", "index_date"), mrn)
    excerpts = []
    for value in _list(data.get("excerpts")):
        row = _object(value)
        excerpt = _fields(
            {k: v for k, v in row.items() if v is not None},
            ("date", "note_type", "text", "same_text_first_written"),
            mrn,
        )
        if "same_text_copies" in row:
            if type(row["same_text_copies"]) is not int:
                raise _Invalid
            excerpt["same_text_copies"] = row["same_text_copies"]
        excerpts.append(excerpt)
    return {**out, "excerpts": excerpts}


def _prefill(data: Mapping[str, object], mrn: str | None) -> dict[str, Any]:
    row = _object(data.get("item"))
    item = _fields(row, ("name", "label", "kind", "question"), mrn)
    item["choices"] = [_fields(_object(c), ("code", "label"), mrn) for c in _list(row.get("choices", []))]
    notes = [
        {"id": f"n{i}", **_fields(_object(n), ("date", "type", "text"), mrn)}
        for i, n in enumerate(_list(data.get("notes")), 1)
    ]
    return {"item": item, "notes": notes}


@lru_cache(maxsize=1)
def _schema_hashes() -> frozenset[str | None]:
    from tb_llm.prompt_registry import default_registry, schema_sha

    return frozenset(e.schema_sha256 for e in default_registry().entries()) | {
        schema_sha({}),
        schema_sha({"type": "object"}),
    }


def _public_schema(schema: dict[str, Any]) -> bool:
    """The two public evaluation prompts allow a numeric evidence cap, with an optional reasoning field."""
    props = schema.get("properties")
    if not isinstance(props, dict) or not isinstance(props.get("evidence"), dict):
        return False
    evidence: dict[str, Any] = {"type": "array", "items": {"type": "integer"}}
    if "maxItems" in props["evidence"]:
        cap = props["evidence"]["maxItems"]
        if type(cap) is not int or cap < 0:
            return False
        evidence["maxItems"] = cap
    fields = {"label": {"type": "string"}, "evidence": evidence}
    required = ["label", "evidence"]
    if "reasoning" in props:
        fields["reasoning"] = {"type": "string", "maxLength": 1200}
        required = ["reasoning", "evidence", "label"]
    return schema == {"type": "object", "properties": fields, "required": required, "additionalProperties": False}


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_./:+-]{0,180}", value):
        raise _Invalid
    return value


def _format(value: object) -> dict[str, Any]:
    from tb_llm.prompt_registry import schema_sha

    fmt = _object(value)
    if fmt.get("type") not in ("json_object", "json_schema", "text"):
        raise _Invalid
    out = {"type": fmt["type"]}
    if "json_schema" in fmt:
        spec = _object(fmt["json_schema"])
        schema = copy.deepcopy(_object(spec.get("schema")))
        if schema_sha(schema) not in _schema_hashes() and not _public_schema(schema):
            raise _Invalid
        permitted: dict[str, Any] = {"schema": schema}
        if "name" in spec:
            permitted["name"] = _identifier(spec["name"])
        if "strict" in spec:
            if type(spec["strict"]) is not bool:
                raise _Invalid
            permitted["strict"] = spec["strict"]
        out["json_schema"] = permitted
    return out


def _message(value: object, mrn: str | None) -> dict[str, Any]:
    row = _object(value)
    if row.get("role") not in ("user", "system", "assistant", "developer"):
        raise _Invalid
    content = row.get("content")
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            if _object(part).get("type") != "text" or not isinstance(part.get("text"), str):
                raise _Invalid
            texts.append(part["text"])
        # The backend concatenates text parts. A caller can place the name and its label in different parts.
        joined = _text("".join(texts), mrn)
        parts = []
        offset = 0
        for text in texts:
            single = _text(text, mrn)
            combined = joined[offset : offset + len(text)]
            safe = "".join(a if b != phi_guard.MASK_CHAR else b for a, b in zip(single, combined, strict=True))
            parts.append({"type": "text", "text": safe})
            offset += len(text)
        return {"role": row["role"], "content": parts}
    return {"role": row["role"], "content": _text(content, mrn)}


def _chat(data: Mapping[str, object], mrn: str | None, purpose: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if purpose != "completion" and "messages" in data:
        out["messages"] = [_message(m, mrn) for m in _list(data["messages"])]
    if purpose in ("completion", "tokenize") and "prompt" in data:
        prompt = data["prompt"]
        out["prompt"] = [_text(p, mrn) for p in prompt] if isinstance(prompt, list) else _text(prompt, mrn)
    if purpose == "tokenize" and "add_generation_prompt" in data:
        if type(data["add_generation_prompt"]) is not bool:
            raise _Invalid
        out["add_generation_prompt"] = data["add_generation_prompt"]
    if purpose == "dispatch" and "provider" in data:
        pin = _object(data["provider"])
        provider: dict[str, Any] = {
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
            "order": [_identifier(v) for v in _list(pin.get("order"))],
        }
        if "quantizations" in pin:
            provider["quantizations"] = [_identifier(v) for v in _list(pin["quantizations"])]
        out["provider"] = provider
    if "model" in data:
        out["model"] = _identifier(data["model"])
    for key in ("max_tokens", "max_completion_tokens", "seed"):
        if key in data:
            if type(data[key]) is not int:
                raise _Invalid
            out[key] = data[key]
    for key in ("temperature", "top_p"):
        if key in data:
            n = data[key]
            if not isinstance(n, int | float) or isinstance(n, bool) or not math.isfinite(n):
                raise _Invalid
            out[key] = n
    if "response_format" in data:
        out["response_format"] = _format(data["response_format"])
    for key in ("reasoning", "reasoning_effort"):
        if key in data:
            effort = _object(data[key]).get("effort") if key == "reasoning" else data[key]
            if effort not in ("none", "minimal", "low", "medium", "high", "xhigh"):
                raise _Invalid
            out[key] = {"effort": effort} if key == "reasoning" else effort
    return out


def prepare_output(
    purpose: str, destination: str, data: Mapping[str, object], *, mrn_regex: str | None = None
) -> dict[str, Any]:
    """Project a fresh payload. Every released free-text leaf must complete the installed note/name analysis."""
    if destination != "model" or purpose not in _PURPOSES:
        _refuse(purpose, "output_not_permitted")
    try:
        if not isinstance(data, Mapping):
            raise _Invalid
        mrn = mrn_regex or phi_guard.site_mrn_regex()
        if purpose == "ie_locate":
            return {"sections": [_fields(_object(s), ("title", "text"), mrn) for s in _list(data.get("sections"))]}
        if purpose == "draft_doc":
            keys = (
                "diagnosis",
                "diagnosis_date",
                "dmards",
                "das28_latest",
                "das28_latest_date",
                "das28_previous",
                "tb_screening",
                "hbv_screening",
                "approval_end",
            )
            return {"facts": _fields(_object(data.get("facts")), keys, mrn)}
        if purpose == "chart_text":
            return {"text": _text(data.get("text"), mrn)}
        if purpose == "judge":
            return _judge(data, mrn)
        if purpose == "chart_facts":
            lang = data.get("language")
            if not isinstance(lang, str) or lang not in _LANGUAGE:
                raise _Invalid
            return {"language": lang, "language_name": _LANGUAGE[lang], "text": _text(data.get("text"), mrn)}
        if purpose == "crf_prefill":
            return _prefill(data, mrn)
        if purpose == "embedding":
            return {"texts": [_text(v, mrn) for v in _list(data.get("texts"))]}
        return _chat(data, mrn, purpose)
    except _Invalid:
        reason = "output_invalid"
    except Exception:
        reason = "analysis_unavailable"
    # Outside the handler so exception chaining cannot copy clinical text into a traceback.
    _refuse(purpose, reason)
