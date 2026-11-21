"""Construct the clinical payload a named output may receive."""

from __future__ import annotations

import copy
import json
import math
import os
import re
from collections.abc import Collection, Mapping
from functools import lru_cache
from typing import Any, NoReturn

from tb_common import phi_guard

_PURPOSES = frozenset(
    {
        "assist",
        "judge",
        "chart_facts",
        "crf_prefill",
        "chat",
        "gateway_chat",
        "embedding",
        "embedding_pairs",
        "chart_text",
        "indexed_note",
        "chart_excerpts",
        "ie_locate",
        "draft_doc",
        "tokenize",
        "completion",
        "dispatch",
        "prompt_headers",
    }
)
_LANGUAGE = {"en": "English", "ja": "Japanese", "zh-TW": "Traditional Chinese"}


IDENTIFIER_REFUSAL = "output_identifier_refused"
IDENTIFIER_MESSAGE = {
    "en": "Model input was withheld. Use an approved identifier that can be sent unchanged.",
    "zh-TW": "已停止傳送模型輸入。請使用經核准且可原樣傳送的識別碼。",
    "ja": "モデルへの入力を保留しました。そのまま送信できる承認済みの識別子を使用してください。",
}


def identifier_message(language: str | None) -> str:
    from tb_common.wording import lang_of

    return IDENTIFIER_MESSAGE[lang_of(language)]


class OutputRefused(ValueError):
    """A stable, text-free reason, suitable for a caller's failure record."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    @property
    def status(self) -> int:
        return 503 if self.reason == AUDIT_UNAVAILABLE else 422

    def message(self, language: str | None = None) -> str:
        if self.reason == AUDIT_UNAVAILABLE:
            from tb_common.wording import lang_of

            return AUDIT_MESSAGE[lang_of(language)]
        return identifier_message(language) if self.reason == IDENTIFIER_REFUSAL else self.reason


AUDIT_UNAVAILABLE = "output_audit_unavailable"
AUDIT_MESSAGE = {
    "en": "Model input was withheld. The audit service is unavailable.",
    "zh-TW": "已停止傳送模型輸入。稽核服務目前無法使用。",
    "ja": "モデルへの入力を保留しました。監査サービスを利用できません。",
}
PROXY_PURPOSES = frozenset({"prompt_headers", "chat", "completion", "tokenize"})
REFUSAL_REASONS = frozenset({IDENTIFIER_REFUSAL, "output_invalid", "analysis_unavailable", "output_not_permitted"})
REFUSAL_PATH = "/internal/model-refusals"


def _refuse(purpose: str, reason: str) -> NoReturn:
    detail = {"purpose": purpose if purpose in _PURPOSES else "unknown", "reason": reason}
    try:
        if os.environ.get("TB_SERVICE_NAME") == "model-guard" and os.environ.get("TB_GATEWAY_URL"):
            import httpx
            from model_guard import key_of

            url = os.environ["TB_GATEWAY_URL"].removesuffix("/v1").rstrip("/")
            with httpx.Client(trust_env=False, timeout=5) as client:
                receipt = client.post(
                    f"{url}{REFUSAL_PATH}/{detail['purpose']}/{reason}",
                    headers={"Authorization": f"Bearer {key_of(os.environ)}"},
                )
                if receipt.status_code != 204:
                    raise RuntimeError
        else:
            from tb_common.audit_writer import open_audit

            open_audit().append("llm.output_refused", detail=detail)
    except Exception:
        reason = AUDIT_UNAVAILABLE
    raise OutputRefused(reason)


class _UnsafeIdentifier(ValueError):
    pass


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


# The stored note-mask version treated a capitalized word after "Patient:"
# as a name, including a clinical negation. Such notes need a versioned reindex.
_OLD_INDEX_NEGATION = re.compile(rf"\b(?:Patient|PATIENT):[ \t]{{0,3}}(?=[A-Z])(?:{phi_guard.CLINICAL_NEGATION})")
_POLARITY_AFTER_LABEL = re.compile(r"\b(?:Pt|Patient)\s*[:：]\s*(No|Not|Never|Denies|Without)\b", re.I)


def _text(value: object, mrn: str | None) -> str:
    if not isinstance(value, str):
        raise _Invalid
    masked = phi_guard.mask_note(value, mrn)
    if not isinstance(masked, str) or len(masked) != len(value):
        raise RuntimeError
    # Analyse the original text. Masking one recogniser's hit first can hide another's context.
    from guard import Guard

    spans = Guard(mrn).detect(value)
    if not isinstance(spans, list):
        raise RuntimeError
    if not spans:
        return masked
    chars = list(masked)
    for span in spans:
        if not 0 <= span.start < span.end <= len(chars):
            raise RuntimeError
        for i in range(span.start, span.end):
            if not value[i].isspace():
                chars[i] = phi_guard.MASK_CHAR
    result = "".join(chars)
    for cue in _POLARITY_AFTER_LABEL.finditer(value):
        if result[cue.start(1) : cue.end(1)] != cue[1]:
            # Ambiguous subject/name. Do not release a finding with reversed polarity.
            raise _UnsafeIdentifier
    return result


_JSON_ESCAPE = re.compile(r'\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4})')


def _message_text(value: object, mrn: str | None) -> str:
    raw = _text(value, mrn)
    if not isinstance(value, str) or "\\" not in value:
        return raw
    # A template or an SDK may already have JSON-escaped the note. Map each decoded
    # character back to its wire range so existing escapes and whitespace survive.
    decoded: list[str] = []
    offsets: list[int] = []
    pos = 0
    for match in _JSON_ESCAPE.finditer(value):
        decoded.extend(value[pos : match.start()])
        offsets.extend(range(pos, match.start()))
        decoded.append(json.loads('"' + match[0] + '"'))
        offsets.append(match.start())
        pos = match.end()
    if not offsets:
        return raw
    decoded.extend(value[pos:])
    offsets.extend(range(pos, len(value) + 1))
    plain = "".join(decoded)
    checked = _text(plain, mrn)
    chars = list(raw)
    for i, (before, after) in enumerate(zip(plain, checked, strict=True)):
        if before != after:
            start, end = offsets[i : i + 2]
            chars[start:end] = phi_guard.MASK_CHAR * (end - start)
    return "".join(chars)


def _unchanged(value: object, mrn: str | None) -> str:
    safe = _text(value, mrn)
    if safe != value:
        raise _UnsafeIdentifier
    return safe


def _fields(row: dict[str, Any], keys: tuple[str, ...], mrn: str | None) -> dict[str, Any]:
    return {key: _text(row[key], mrn) for key in keys if key in row}


def _judge(data: Mapping[str, object], mrn: str | None, *, uploaded: bool) -> dict[str, Any]:
    out = _fields(dict(data), ("criterion_text", "note_question", "index_date"), mrn)
    excerpts = []
    for value in _list(data.get("excerpts")):
        row = _object(value)
        if uploaded or "section_heading" in row:
            # Uploaded charts keep a filename-derived type for local records. Only a document heading may travel.
            heading = row.get("section_heading", "")
            if not isinstance(heading, str):
                raise _Invalid
            row = {**row, "note_type": "chart" if heading == "" else heading}
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
    item: dict[str, Any] = _fields(row, ("label", "question"), mrn)
    for key in ("name", "kind"):
        if key in row:
            item[key] = _unchanged(row[key], mrn)
    choices = []
    for choice in _list(row.get("choices", [])):
        option = _object(choice)
        shown = _fields(option, ("label",), mrn)
        if "code" in option:
            shown["code"] = _unchanged(option["code"], mrn)
        choices.append(shown)
    item["choices"] = choices
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


def _identifier(value: object, mrn: str | None) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_./:+-]{0,180}", value):
        raise _Invalid
    return _unchanged(value, mrn)


def _prompt_headers(data: Mapping[str, object], mrn: str | None) -> dict[str, str]:
    from tb_llm.prompt_registry import default_registry

    if "X-TB-Prompt-Id" not in data:
        if "X-TB-Prompt-Version" in data or "X-TB-Prompt-Sha" in data:
            raise _UnsafeIdentifier
        return {}
    registry = default_registry()
    pid = _unchanged(data["X-TB-Prompt-Id"], mrn)
    versions = registry.versions(pid)
    if not versions and pid not in {"mlbench_judge", "trialgpt_criterion"}:
        raise _UnsafeIdentifier
    out = {"X-TB-Prompt-Id": pid}
    if "X-TB-Prompt-Version" in data:
        version = _unchanged(data["X-TB-Prompt-Version"], mrn)
        if version not in {str(v) for v in versions or [1]}:
            raise _UnsafeIdentifier
        out["X-TB-Prompt-Version"] = version
        if "X-TB-Prompt-Sha" in data:
            if not versions or data["X-TB-Prompt-Sha"] != registry.entry(pid, int(version)).sha256:
                raise _UnsafeIdentifier
            out["X-TB-Prompt-Sha"] = registry.entry(pid, int(version)).sha256
    elif "X-TB-Prompt-Sha" in data:
        raise _UnsafeIdentifier
    return out


def _format(value: object, mrn: str | None) -> dict[str, Any]:
    from tb_llm.prompt_registry import default_registry, schema_sha

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
            # Registry prompt IDs and the fixed short aliases used by the evaluation and intake clients.
            name = _unchanged(spec["name"], mrn)
            if name not in {"ir", "j", "x"} and not default_registry().versions(name):
                raise _UnsafeIdentifier
            permitted["name"] = name
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
        joined = _message_text("".join(texts), mrn)
        parts = []
        offset = 0
        for text in texts:
            single = _message_text(text, mrn)
            combined = joined[offset : offset + len(text)]
            safe = "".join(a if b != phi_guard.MASK_CHAR else b for a, b in zip(single, combined, strict=True))
            parts.append({"type": "text", "text": safe})
            offset += len(text)
        return {"role": row["role"], "content": parts}
    return {"role": row["role"], "content": _message_text(content, mrn)}


def _chat(
    data: Mapping[str, object],
    mrn: str | None,
    purpose: str,
    model_names: Collection[str],
    provider_route: Mapping[str, object] | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if purpose != "completion" and "messages" in data:
        out["messages"] = [_message(m, mrn) for m in _list(data["messages"])]
    if purpose in ("completion", "tokenize") and "prompt" in data:
        prompt = data["prompt"]
        out["prompt"] = (
            [_message_text(p, mrn) for p in prompt] if isinstance(prompt, list) else _message_text(prompt, mrn)
        )
    if purpose == "tokenize" and "add_generation_prompt" in data:
        if type(data["add_generation_prompt"]) is not bool:
            raise _Invalid
        out["add_generation_prompt"] = data["add_generation_prompt"]
    if purpose == "dispatch" and "provider" in data:
        pin = _object(data["provider"])
        if provider_route is None or pin != provider_route:
            raise _UnsafeIdentifier
        provider: dict[str, Any] = {
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
            "order": [_identifier(v, mrn) for v in _list(pin.get("order"))],
        }
        if "quantizations" in pin:
            provider["quantizations"] = [_identifier(v, mrn) for v in _list(pin["quantizations"])]
        out["provider"] = provider
    if "model" in data:
        model = _identifier(data["model"], mrn)
        if model not in model_names:
            if purpose != "gateway_chat":
                raise _UnsafeIdentifier
            # An SDK caller can also select an alias published by the site's registry.
            from registry.registry import Registry

            if model not in Registry.from_env().aliases:
                raise _UnsafeIdentifier
        out["model"] = model
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
        out["response_format"] = _format(data["response_format"], mrn)
    for key in ("reasoning", "reasoning_effort"):
        if key in data:
            effort = _object(data[key]).get("effort") if key == "reasoning" else data[key]
            if effort not in ("none", "minimal", "low", "medium", "high", "xhigh"):
                raise _Invalid
            out[key] = {"effort": effort} if key == "reasoning" else effort
    return out


def prepare_output(
    purpose: str,
    destination: str,
    data: Mapping[str, object],
    *,
    mrn_regex: str | None = None,
    model_names: Collection[str] = (),
    provider_route: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Project a fresh payload. Routing names and the provider pin come from configuration outside the request."""
    if destination != "model" or purpose not in _PURPOSES:
        _refuse(purpose, "output_not_permitted")
    try:
        if not isinstance(data, Mapping):
            raise _Invalid
        from tb_common.config import get_config

        mrn = get_config().settings.mrn_regex
        if mrn_regex and mrn_regex != mrn:
            mrn = f"(?:{mrn.strip('^$')}|{mrn_regex.strip('^$')})" if mrn else mrn_regex
        if purpose == "prompt_headers":
            return _prompt_headers(data, mrn)
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
        if purpose == "indexed_note":
            # Persisted vectors use a SHA of each chunk under the original note mask.
            # A stronger projection that changes that text needs a versioned reindex.
            value = data.get("text")
            safe = _text(value, mrn)
            if (
                not isinstance(value, str)
                or _OLD_INDEX_NEGATION.search(value)
                or safe != phi_guard.mask_note(value, mrn_regex)
            ):
                raise _UnsafeIdentifier
            return {"text": safe}
        if purpose == "chart_text":
            return {"text": _text(data.get("text"), mrn)}
        if purpose in ("judge", "chart_excerpts"):
            return _judge(data, mrn, uploaded=purpose == "chart_excerpts")
        if purpose in ("assist", "chart_facts"):
            lang = data.get("language")
            if not isinstance(lang, str) or lang not in _LANGUAGE:
                raise _Invalid
            if purpose == "assist":
                return {
                    "language": lang,
                    "language_name": _LANGUAGE[lang],
                    **_fields(dict(data), ("question", "draft"), mrn),
                    "points": [_text(point, mrn) for point in _list(data.get("points"))],
                }
            return {"language": lang, "language_name": _LANGUAGE[lang], "text": _text(data.get("text"), mrn)}
        if purpose == "crf_prefill":
            return _prefill(data, mrn)
        if purpose == "embedding_pairs":
            pairs = []
            for pair in _list(data.get("pairs")):
                if len(_list(pair)) != 2:
                    raise _Invalid
                pairs.append([_text(v, mrn) for v in pair])
            return {"pairs": pairs}
        if purpose == "embedding":
            return {"texts": [_text(v, mrn) for v in _list(data.get("texts"))]}
        return _chat(data, mrn, purpose, model_names, provider_route)
    except _UnsafeIdentifier:
        reason = IDENTIFIER_REFUSAL
    except _Invalid:
        reason = "output_invalid"
    except Exception:
        reason = "analysis_unavailable"
    # Outside the handler so exception chaining cannot copy clinical text into a traceback.
    _refuse(purpose, reason)
