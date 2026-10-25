"""S3 judge and S4 second opinion through ``tb-gateway`` (spec v4 §4.5 S3/S4, CAS-3, CAS-5, CAS-16; §8.2 ENG-04).

The cascade never talks to a model endpoint: :class:`GatewayJudge` renders the registered ``judge`` prompt, sends it
with :class:`tb_llm.GatewayClient` and its labels (data class, study, purpose, context of use, role, prompt@version,
step), and parses the schema-constrained answer. Any client with the same ``judge`` method can be injected (tests use
the in-process gateway in front of ``llm_stub``).

:func:`verify_span` is the CAS-16 check: the quote must sit, character for character, inside one excerpt that is
dated inside the criterion window. A judgement whose span does not verify is ``insufficient`` and counts as
``unknown:uncertain``.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

JUDGE_PROMPT = "judge"


@dataclass(frozen=True)
class JudgeReply:
    verdict: str  # answer to the note question: pass (yes) | fail (no) | unknown
    confidence: float
    quote: str | None
    quote_date: str | None
    reason: str
    call_id: str = ""
    build_sha: str = ""
    prompt: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    refused: str | None = None  # gateway refusal code: the pair stays unknown, never excluded


class JudgeClient(Protocol):
    def judge(
        self,
        *,
        role: str,
        criterion_text: str,
        note_question: str,
        index_date: date,
        excerpts: list[dict[str, Any]],
        study_id: str,
        data_class: str,
        step_id: str,
        purpose: str,
    ) -> JudgeReply: ...


@dataclass
class GatewayJudge:
    """The production judge path: ``libs/tb_llm`` → ``tb-gateway`` (the only route to a model, LLM-1)."""

    client: Any  # tb_llm.GatewayClient
    prompt_id: str = JUDGE_PROMPT
    calls: int = 0
    refusals: list[str] = field(default_factory=list)

    def judge(
        self,
        *,
        role: str,
        criterion_text: str,
        note_question: str,
        index_date: date,
        excerpts: list[dict[str, Any]],
        study_id: str,
        data_class: str,
        step_id: str,
        purpose: str,
    ) -> JudgeReply:
        from tb_common.llm import load_prompt, render
        from tb_contracts import inline_schema
        from tb_llm import CallLabels, GatewayRefused, json_schema_format

        p = load_prompt(self.prompt_id)
        prompt = f"{p.meta.id}@{p.meta.version}"
        body_vars = {
            "criterion_text": criterion_text,
            "note_question": note_question,
            "index_date": index_date.isoformat(),
            "excerpts": excerpts,
        }
        labels = CallLabels(
            data_class=data_class,
            purpose=purpose,
            study_id=study_id,
            context_of_use="s3_note_judgement" if role == "judge" else "s4_second_opinion",
            role=role,
            prompt=prompt,
            step_id=step_id,
        )
        self.calls += 1
        try:
            res = self.client.chat(
                render(p, body_vars),
                labels,
                response_format=json_schema_format(p.meta.id, inline_schema(p.meta.output_schema)),
                max_tokens=p.meta.max_tokens,
            )
        except GatewayRefused as exc:
            self.refusals.append(exc.reason)
            reason = f"gateway refused: {exc.reason}"
            return JudgeReply("unknown", 0.0, None, None, reason, prompt=prompt, refused=exc.reason)
        data = res.data if isinstance(res.data, dict) else {}
        return JudgeReply(
            verdict=str(data.get("verdict", "unknown")),
            confidence=float(data.get("confidence") or 0.0),
            quote=data.get("quote"),
            quote_date=None if data.get("quote_date") is None else str(data.get("quote_date")),
            reason=str(data.get("reason") or ""),
            call_id=res.call_id,
            build_sha=res.build_sha,
            prompt=prompt,
            tokens_in=res.tokens_in,
            tokens_out=res.tokens_out,
        )


def norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sentence_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(norm(text).encode("utf-8")).hexdigest()


def verify_span(reply: JudgeReply, excerpts: list[dict[str, Any]], lo: date, hi: date) -> dict[str, Any] | None:
    """CAS-16: the verified span (excerpt id, offsets, date, sentence hash) or None when it does not verify."""
    if not reply.quote:
        return None
    q = norm(reply.quote)
    for ex in excerpts:
        text = norm(str(ex.get("text", "")))
        start = text.find(q)
        if start < 0:
            continue
        d = date.fromisoformat(str(ex["date"])[:10])
        if not lo <= d <= hi:
            continue
        if reply.quote_date and reply.quote_date[:10] != d.isoformat():
            continue
        return {
            "did": ex.get("did"),
            "start": start,
            "end": start + len(q),
            "date": d.isoformat(),
            "sentence_hash": sentence_hash(q),
            "quote": reply.quote,
        }
    return None


def expected_tokens(excerpts: list[dict[str, Any]]) -> int:
    """Conservative token estimate (CJK ~1 token per character, Latin ~4 characters per token) plus the prompt."""
    n = 300
    for ex in excerpts:
        t = str(ex.get("text", ""))
        cjk = sum(1 for ch in t if "　" <= ch <= "鿿")
        n += cjk + (len(t) - cjk) // 4 + 1
    return n


__all__ = ["GatewayJudge", "JudgeClient", "JudgeReply", "expected_tokens", "norm", "sentence_hash", "verify_span"]
