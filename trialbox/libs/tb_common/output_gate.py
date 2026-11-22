"""Construct the clinical payload a named output may receive.

Gate 5 (``docs/plan/gates/gate-5.md``): :func:`prepare_output` is the one function for every exit. For a model call
it projects a fresh, masked payload. For the other exits (:data:`EXITS`: mail, downloads, the support bundle,
exports) it reads the bytes in every decoding a receiver could apply and refuses them if a patient identifier
survives in any; what it releases is a :class:`Released`, which only it makes and which an exit turns back into
bytes with :func:`leave`."""

from __future__ import annotations

import base64
import binascii
import copy
import email
import gzip
import hashlib
import hmac
import html
import io
import json
import math
import os
import quopri
import re
import secrets
import tarfile
import unicodedata
import urllib.parse
import zipfile
from collections.abc import Collection, Iterator, Mapping
from email import policy as email_policy
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, NoReturn, final, overload

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
#: where a refusal is audited when no ``TB_AUDIT_DIR`` names the service's folder (None: ``open_audit``'s own default)
AUDIT_DIRECTORY: Path | None = None
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

            directory = None if os.environ.get("TB_AUDIT_DIR") else AUDIT_DIRECTORY
            open_audit(directory).append("llm.output_refused", detail=detail)
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
        return _still_clear(masked, mrn, value)
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
    return _still_clear(result, mrn, value)


def _still_clear(masked: str, mrn: str | None, value: str) -> str:
    """Gate 5: what the recognisers left must hold no identifier a receiver could read (a name with no label, a
    pseudonym), and the text must hold none in an encoded form (percent, base64, entities, escapes: the recognisers
    read only the plain form, and mask parts of an encoded one). Such a text is withheld, not sent half masked."""
    _site_mrn, domains = _site()
    mrns = [mrn] if mrn else []
    if any(_kinds(view, mrns, domains) for view in _views(masked)):
        raise _UnsafeIdentifier
    if any(_kinds(view, mrns, domains) for view in _views(value, fold=False)[1:]):
        raise _UnsafeIdentifier
    if any(_pseudonym(view) for view in _views(value)):  # the recognisers never mask one; they can halve one
        raise _UnsafeIdentifier
    return masked


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


@overload
def prepare_output(
    purpose: str,
    destination: Literal["model"],
    data: Mapping[str, object],
    *,
    mrn_regex: str | None = None,
    model_names: Collection[str] = (),
    provider_route: Mapping[str, object] | None = None,
) -> dict[str, Any]: ...


@overload
def prepare_output(
    purpose: str,
    destination: Literal["mail", "download", "support", "export"],
    data: Mapping[str, object],
    *,
    mrn_regex: str | None = None,
    model_names: Collection[str] = (),
    provider_route: Mapping[str, object] | None = None,
) -> Released: ...


@overload
def prepare_output(
    purpose: str,
    destination: str,
    data: Mapping[str, object],
    *,
    mrn_regex: str | None = None,
    model_names: Collection[str] = (),
    provider_route: Mapping[str, object] | None = None,
) -> dict[str, Any] | Released: ...


def prepare_output(
    purpose: str,
    destination: str,
    data: Mapping[str, object],
    *,
    mrn_regex: str | None = None,
    model_names: Collection[str] = (),
    provider_route: Mapping[str, object] | None = None,
) -> dict[str, Any] | Released:
    """Project a fresh payload. Routing names and the provider pin come from configuration outside the request.

    For an exit other than the model (:data:`EXITS`) ``data`` is ``{"bytes": ...}`` or ``{"text": ...}`` with an
    optional ``"name"`` (a file or member name, read too); the result is a :class:`Released` or a refusal."""
    if destination in EXIT_PURPOSES:
        return _release(purpose, destination, data, mrn_regex)
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


# ------------------------------------------------------------------------------------------------ the other exits
#: Every exit of the box and what crosses it (gate 5). A new exit is added here and given a road in the cross-path
#: test (``tests/gate5_kit.py``), which fails for an exit it has no road for.
EXITS: dict[str, str] = {
    "model": "a model call: the projected payload above (the gateway is the one model exit)",
    "mail": "a message as handed to the mail transport: its subject, every part and every attachment",
    "download": "a file a signed-in person downloads from the console or the orchestrator",
    "support": "a member of the support bundle, its name and its content",
    "export": "a package or report made for use off the box (the sponsor pack, a deliverable)",
}
#: each exit's purposes, and the identifier kinds a purpose lets leave as they are
EXIT_PURPOSES: dict[str, dict[str, frozenset[str]]] = {
    "mail": {"mail_message": frozenset()},
    "download": {"aggregate_file": frozenset(), "pseudonymised_file": frozenset({"pseudonym"})},
    "support": {"bundle_member": frozenset()},
    "export": {"aggregate_file": frozenset()},
}
#: the kinds of identifier an exit looks for, in every decoding of what would leave
IDENTIFIER_KINDS = frozenset({"name", "chart", "phone", "email", "national_id", "pseudonym"})
NOT_RELEASED = "output_not_released"
_SEAL_KEY = secrets.token_bytes(32)  # per process: a Released cannot be carried to, or made in, another process


@final
class Released:
    """Bytes the gate read and released for one exit and purpose. Only :func:`prepare_output` makes one (the
    constructor refuses), and :func:`leave` checks its seal, so bytes swapped in afterwards do not pass."""

    __slots__ = ("_seal", "data", "exit", "name", "purpose")
    exit: str
    purpose: str
    name: str
    data: bytes
    _seal: bytes

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("only prepare_output makes a Released")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("a Released is read-only")

    def __repr__(self) -> str:  # never the bytes
        return f"Released({self.exit}, {self.purpose}, {len(self.data)} bytes)"


def _seal_of(exit_name: str, purpose: str, name: str, data: bytes) -> bytes:
    head = "\0".join((exit_name, purpose, name)).encode("utf-8")
    return hmac.new(_SEAL_KEY, head + b"\0" + hashlib.sha256(data).digest(), hashlib.sha256).digest()


def _mint(exit_name: str, purpose: str, name: str, data: bytes) -> Released:
    out = object.__new__(Released)
    for key, value in (("exit", exit_name), ("purpose", purpose), ("name", name), ("data", data)):
        object.__setattr__(out, key, value)
    object.__setattr__(out, "_seal", _seal_of(exit_name, purpose, name, data))
    return out


def leave(released: object, exit_name: str) -> bytes:
    """The bytes an exit may write or send: the last call before its write. Anything the gate did not release for
    this exit (raw bytes or text, a Released for another exit, one whose bytes were replaced) is
    :class:`OutputRefused` with ``output_not_released``, and the exit writes nothing."""
    if (
        type(released) is not Released
        or released.exit != exit_name
        or not hmac.compare_digest(
            released._seal, _seal_of(released.exit, released.purpose, released.name, released.data)
        )
    ):
        raise OutputRefused(NOT_RELEASED)
    return released.data


def _release(purpose: str, exit_name: str, data: Mapping[str, object], mrn_regex: str | None) -> Released:
    permitted = EXIT_PURPOSES[exit_name].get(purpose)
    if permitted is None:
        raise OutputRefused("output_not_permitted")
    try:
        if not isinstance(data, Mapping):
            raise _Invalid
        name = data.get("name", "")
        raw = data["bytes"] if "bytes" in data else data.get("text")
        if not isinstance(name, str) or not isinstance(raw, bytes | str):
            raise _Invalid
        payload = raw.encode("utf-8") if isinstance(raw, str) else raw
        found = identifiers_in(payload, name, mrn_regex=mrn_regex) - permitted
    except _Invalid:
        reason = "output_invalid"
    except Exception:
        reason = "analysis_unavailable"
    else:
        if not found:
            return _mint(exit_name, purpose, name, payload)
        reason = IDENTIFIER_REFUSAL
    # Outside the handler so exception chaining cannot copy what was refused into a traceback.
    raise OutputRefused(reason)


def _site() -> tuple[str, tuple[str, ...]]:
    """The site's chart-number pattern and internal mail domains; the contract's default pattern when no site
    configuration can be read (a tool run without one), so a chart number is never let through for want of it."""
    try:
        from tb_common.config import get_config

        settings = get_config().settings
        return str(settings.mrn_regex), tuple(str(d).lower() for d in settings.internal_domains)
    except Exception:
        return r"^\d{8}$", ()


def identifiers_in(data: bytes, name: str = "", *, mrn_regex: str | None = None) -> set[str]:
    """The kinds of patient identifier (:data:`IDENTIFIER_KINDS`) in ``data`` and ``name``, read the way a receiver
    could read them: inside gzip, zip, tar, PDF and MIME containers, and through every layer of percent, base64,
    quoted-printable, HTML entity and backslash escape, with zero-width characters and soft hyphens removed and
    full-width forms folded. Kinds only, never a value."""
    site_mrn, domains = _site()
    mrns = [m for m in (site_mrn, mrn_regex) if m]
    kinds: set[str] = set()
    for text in [name, *_receiver_texts(data, 0)]:
        for view in _views(text):
            kinds |= _kinds(view, mrns, domains)
    return kinds


_MAX_DEPTH = 4
_MAX_INFLATE = 256 * 2**20


def _receiver_texts(data: bytes, depth: int) -> Iterator[str]:
    """Every text a receiver could get from ``data``: the bytes as text, and what each container holds."""
    if depth < _MAX_DEPTH:
        if data[:2] == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as fh:
                yield from _receiver_texts(fh.read(_MAX_INFLATE), depth + 1)
        elif data[:4] == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    yield info.filename
                    member = zf.read(info)
                    if info.filename.endswith((".xml", ".rels")):  # an office file shows its text, not its markup
                        member = re.sub(rb"<[^>]*>", b" ", member)
                    yield from _receiver_texts(member, depth + 1)
        elif data[:5] == b"%PDF-":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            yield "\n".join(str(v) for v in (reader.metadata or {}).values())
            for page in reader.pages:
                yield page.extract_text() or ""
        elif len(data) >= 512 and _is_tar(data):
            with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                for entry in tar.getmembers():
                    yield entry.name
                    stream = tar.extractfile(entry)
                    if stream is not None:
                        yield from _receiver_texts(stream.read(), depth + 1)
        elif _MIME_HEAD.match(data):
            # what a mail client shows: the parts decoded (the raw form is boundaries, routing and transfer codes)
            yield from _mime_texts(data, depth)
            return
    yield data.decode("utf-8", errors="replace")


def _is_tar(data: bytes) -> bool:
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            return bool(tar.getmembers())
    except (tarfile.TarError, OSError, EOFError, ValueError):
        return False


_MIME_HEAD = re.compile(rb"(?:[A-Za-z][A-Za-z0-9-]*:[^\r\n]*\r?\n(?:[ \t][^\r\n]*\r?\n)*)+\r?\n")
#: headers that route a message, not its content (an address of the box or of a recipient)
_ROUTING_HEADERS = {"from", "to", "cc", "bcc", "reply-to", "sender", "return-path", "message-id", "date"}


def _mime_texts(data: bytes, depth: int) -> Iterator[str]:
    message = email.message_from_bytes(data, policy=email_policy.default)
    for part in message.walk():
        for key, value in part.items():
            if key.lower() not in _ROUTING_HEADERS:
                yield f"{key}: {value}"
        filename = part.get_filename()
        if filename:
            yield filename
        if not part.is_multipart():
            body = part.get_payload(decode=True)
            if isinstance(body, bytes):
                yield from _receiver_texts(body, depth + 1)


_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e\u034f\u2061\u2062\u2063"))
_MAX_VIEWS = 96
_MAX_LAYERS = 8


def _views(text: str, *, fold: bool = True) -> list[str]:
    """``text`` and every decoding of it, layer on layer (at most eight layers): what a receiver could read."""
    seen = {text}
    order = [text]
    frontier = [text]
    for _ in range(_MAX_LAYERS):
        found: list[str] = []
        for current in frontier:
            for decoded in _decode_once(current, fold=fold):
                if decoded not in seen and len(seen) < _MAX_VIEWS:
                    seen.add(decoded)
                    order.append(decoded)
                    found.append(decoded)
        frontier = found
        if not frontier:
            break
    return order


_BACKSLASH = re.compile(r"(?:\\x[0-9A-Fa-f]{2})+|\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8}|\\/")
_QP = re.compile(r"=(?:[0-9A-Fa-f]{2}|\r?\n)")
_B64_RUN = re.compile(r"[A-Za-z0-9+/_-]{8,}={0,2}")


def _decode_once(text: str, *, fold: bool = True) -> list[str]:
    """One layer of each decoding; ``fold``: also the text with zero-width characters out and widths folded."""
    out = [unicodedata.normalize("NFKC", text.translate(_ZERO_WIDTH))] if fold else []
    if "%" in text:
        out += [urllib.parse.unquote(text, errors="replace"), urllib.parse.unquote_plus(text, errors="replace")]
    if "&" in text:
        out.append(html.unescape(text))
    if "\\" in text:
        out.append(_unescape_backslash(text))
    if _QP.search(text):
        soft = re.sub(r"=\r?\n", "", text)
        out.append(quopri.decodestring(soft.encode("utf-8")).decode("utf-8", errors="replace"))
    if _B64_RUN.search(text):
        out.append(_B64_RUN.sub(_b64_text, text))
    return [o for o in out if o != text]


def _unescape_backslash(text: str) -> str:
    def one(m: re.Match[str]) -> str:
        s = m.group(0)
        if s == "\\/":
            return "/"
        if s.startswith("\\x"):
            return bytes.fromhex(s.replace("\\x", "")).decode("utf-8", errors="replace")
        return chr(int(s[2:], 16))

    joined = _BACKSLASH.sub(one, text)
    return joined.encode("utf-16", "surrogatepass").decode("utf-16", errors="replace")


def _b64_text(m: re.Match[str]) -> str:
    """A base64 or base64url run decoded, when it decodes to text; else the run as it is."""
    run = m.group(0).rstrip("=")
    try:
        raw = base64.b64decode(run.replace("-", "+").replace("_", "/") + "=" * (-len(run) % 4), validate=True)
        text = raw.decode("utf-8")
    except (binascii.Error, ValueError):
        return m.group(0)
    if not text or sum(c.isprintable() or c in "\n\r\t" for c in text) < 0.9 * len(text):
        return m.group(0)
    return text


# A pseudonym (a keyed hash of a chart number): 32 hex digits, or a longer run that is not a whole digest of 40 or 64
_HEX_RUN = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])")
# names with no label (review 2026-11-22 R22-23): after a word for the patient, or a Japanese surname with its
# given name, or an English name followed by an age and a sex
_PATIENT_WORDS = r"(?:患者|病人|病患|個案|受試者|被験者|案主)"
_CJK_GIVEN = "[一-鿿぀-ヿ]"
_JP_FAMILY = "|".join(sorted(phi_guard.JP_SURNAMES, key=len, reverse=True))
_ROC_FAMILY = (
    "|".join(sorted(phi_guard.ROC_COMPOUND, key=len, reverse=True))
    + "|["
    + "".join(sorted(phi_guard.ROC_SURNAMES))
    + "]"
)
_NUMBER_SIGN = r"(?:n°|N°|No\.|#|№)"  # a number sign a record puts before an entry (Patient n° ..., 患者#...)
_LATIN_WORD = r"[A-Z][a-z\u00e0-\u024f\u0300-\u036f]+"  # a capital, then letters (accents too)
_NAME_NO_LABEL = re.compile(
    rf"{_PATIENT_WORDS}(?:は|が|の|を|に|、|，|,|:|：|/|\s){{0,2}}{_NUMBER_SIGN}?(?:{_JP_FAMILY}|{_ROC_FAMILY}){_CJK_GIVEN}{{1,3}}"
    rf"|(?:{_JP_FAMILY}){_CJK_GIVEN}{{1,3}}(?=[。、，,．./\s)）」』]|さん|様|氏|$)"
    rf"|(?:姓名|氏名|名前|病人姓名|患者名)\s*[:：]?\s*(?:{_JP_FAMILY}|{_ROC_FAMILY}){_CJK_GIVEN}{{1,3}}"
    rf"|\b(?:[Pp]atient|Pt\.?|Mrs?\.?|Ms\.?|Miss|[Nn]ame\s*:)(?:[\s/]+|[\s/]*{_NUMBER_SIGN}[\s/]*)"
    rf"(?!{phi_guard.CLINICAL_NEGATION}){_LATIN_WORD}"
    rf"(?:[ \t]+{_LATIN_WORD})+"
    rf"|\b{_LATIN_WORD}[ \t]+{_LATIN_WORD},[ \t]*\d{{1,3}}[ \t]?(?:[MF]|y/?o|yo)\b"
)
_TWELVE = re.compile(r"(?<![0-9.])(\d{4})[ \-.]?(\d{4})[ \-.]?(\d{4})(?![0-9]|\.[0-9])")
# an e-mail address is a patient's when a label or a patient word stands before it on its line (a staff or sponsor
# address in a message is not; the site's own domains never are)
_EMAIL_CONTEXT = re.compile(
    rf"(?i)(?:e-?mail|mail|メール(?:アドレス)?|電子郵件|電郵|信箱|郵箱|連絡先|聯絡|contact|{_PATIENT_WORDS}|patient)"
)
_SCAN_KINDS = {
    "name": "name",
    "mrn": "chart",
    "phone": "phone",
    "taiwan_id": "national_id",
    "id_number": "national_id",
}


def _pseudonym(view: str) -> bool:
    return any(len(m.group(0)) not in (40, 64) and re.search("[0-9]", m.group(0)) for m in _HEX_RUN.finditer(view))


_ID_LABEL = re.compile(r"(?i)(?:\bid\b|my\s*number|マイナンバー|個人番号|身分|national|identity)[^\n]{0,12}$")


def _id_like(view: str, m: re.Match[str]) -> bool:
    """Twelve digits are an individual number when written in its groups (1234 5678 9012) or after an ID label: a
    plain count or byte size that happens to carry the check digit is not one."""
    return m.group(0) != "".join(m.groups()) or bool(_ID_LABEL.search(view[max(0, m.start() - 24) : m.start()]))


def _my_number(digits: str) -> bool:
    """A Japanese individual number: twelve digits whose last is the check digit of the first eleven."""
    body = [int(c) for c in digits[:11]][::-1]
    total = sum(p * (n + 1 if n <= 6 else n - 5) for n, p in enumerate(body, 1))
    rest = total % 11
    return int(digits[11]) == (0 if rest <= 1 else 11 - rest)


def _kinds(view: str, mrns: list[str], domains: tuple[str, ...]) -> set[str]:
    kinds: set[str] = set()
    for mrn in mrns:
        kinds |= {_SCAN_KINDS[k] for k, _ in phi_guard.scan(view, mrn).findings if k in _SCAN_KINDS}
        # also between slashes, dots or dashes (a path, a file name): the recognisers leave those for dates
        if re.search(rf"(?<![0-9A-Za-z])(?:{mrn.strip('^$')})(?![0-9A-Za-z])", view):
            kinds.add("chart")
    for m in phi_guard.EMAIL.finditer(view):
        domain = m.group(0).rsplit("@", 1)[-1].lower()
        line = view[view.rfind("\n", 0, m.start()) + 1 : m.start()]
        if not any(domain == d or domain.endswith("." + d) for d in domains) and _EMAIL_CONTEXT.search(line):
            kinds.add("email")
    if _pseudonym(view):
        kinds.add("pseudonym")
    if _NAME_NO_LABEL.search(view):
        kinds.add("name")
    if any(_my_number("".join(m.groups())) and _id_like(view, m) for m in _TWELVE.finditer(view)):
        kinds.add("national_id")
    return kinds
