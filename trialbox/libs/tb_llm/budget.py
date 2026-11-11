"""Prompt budgets from the model's context (T-603; deep review LLM-015, LLM-016, LLM-018).

The gateway knows each build's context (``context_length`` in ``models/registry.yaml``: 32,768 on the RTX PRO 6000,
16,384 on the Spark, 8,192 on the RTX 5090) and returns it per alias in ``GET /v1/models``. Callers size what they
put in a prompt from it — note excerpts, the full record, an uploaded chart — and the answer budget of a retry, and
the gateway refuses a request whose estimate is over the context before it reaches a model (``prompt_too_long``).

The count is an **estimate**, not the model's tokenizer (the judge and the verifier tokenise differently): a CJK
character is one token, other text four characters per token, rounded up, plus a few tokens per message. Callers
plan with :data:`SAFETY` of the context so that a tokenizer that counts more than the estimate still fits; the
gateway refuses only what the plain estimate puts over the context, and a server that still answers "too long"
gives ``prompt_too_long`` too (T-601).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

# share of the context a caller plans with: the rest is room for a tokenizer that counts more than the estimate
SAFETY = 0.85
# an answer budget below this is not worth sending: the call is refused as too long instead
MIN_ANSWER_TOKENS = 256
# tokens a chat template adds around each message (role markers); generous for the models in the registry
MESSAGE_OVERHEAD = 8
# the truncation retry never asks for more than this, whatever the context (stress test 2026-10-25)
RETRY_CEILING = 16384


def _cjk(ch: str) -> bool:
    return "　" <= ch <= "鿿" or "豈" <= ch <= "﫿" or "＀" <= ch <= "￯" or "가" <= ch <= "힯"


def estimate_tokens(text: str) -> int:
    """CJK characters (and full-width forms, Hangul) one token each; other text four characters per token, rounded
    up; plus one."""
    cjk = sum(1 for ch in text if _cjk(ch))
    return cjk + (len(text) - cjk + 3) // 4 + 1


def _content(m: Any) -> str:
    c = m.get("content") if isinstance(m, Mapping) else None
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(str(x.get("text", "")) for x in c if isinstance(x, Mapping))
    return ""


def estimate_messages(messages: Iterable[Any]) -> int:
    """The estimated prompt size of a chat request's ``messages``."""
    return sum(estimate_tokens(_content(m)) + MESSAGE_OVERHEAD for m in messages)


def excerpt_tokens(excerpt: Mapping[str, Any]) -> int:
    """What one excerpt adds to a prompt that renders its excerpts as pretty JSON (the judge, ``tojson_pretty``):
    its date, note type and text, JSON-escaped, plus the separators."""
    shown = {k: excerpt.get(k) for k in ("date", "note_type", "text")}
    return estimate_tokens(json.dumps(shown, ensure_ascii=False, indent=1, sort_keys=True)) + 2


def text_budget(context: int, fixed_tokens: int, max_tokens: int) -> int:
    """Tokens left for the variable part of a prompt (excerpts, a chart) on a model with ``context`` tokens, when the
    rest of the prompt is ``fixed_tokens`` and the answer may take ``max_tokens``. Never negative."""
    return max(0, int(context * SAFETY) - fixed_tokens - max_tokens)


def answer_room(context: int, prompt_tokens: int) -> int:
    """The largest ``max_tokens`` a caller should ask for with a prompt of ``prompt_tokens``. May be negative."""
    return int(context * SAFETY) - prompt_tokens


def retry_max_tokens(context: int | None, prompt_tokens: int, first: int) -> int | None:
    """``max_tokens`` for the one retry after an answer cut off at ``first`` tokens: four times as much, at most
    :data:`RETRY_CEILING` and, with a known context, at most what fits beside the prompt (LLM-018: a retry of 16,384
    on an 8k or 16k model was the server's HTTP 400). None when no larger budget fits: the retry would be cut off
    the same way, so it is not sent."""
    want = min(4 * max(1, first), RETRY_CEILING)
    if context:
        want = min(want, answer_room(context, prompt_tokens))
    return want if want > first else None


def over_context(context: int | None, prompt_tokens: int, max_tokens: int | None) -> bool:
    """Whether a request is over the context by the plain estimate (the gateway's check before dispatch)."""
    if not context:
        return False
    return prompt_tokens + int(max_tokens or 0) > context


__all__ = [
    "MESSAGE_OVERHEAD",
    "MIN_ANSWER_TOKENS",
    "RETRY_CEILING",
    "SAFETY",
    "answer_room",
    "estimate_messages",
    "estimate_tokens",
    "excerpt_tokens",
    "over_context",
    "retry_max_tokens",
    "text_budget",
]
