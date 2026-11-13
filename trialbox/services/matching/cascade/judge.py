"""S3 judge and S4 second opinion through ``tb-gateway`` (spec v4 §4.5 S3/S4, CAS-3, CAS-5, CAS-16; §8.2 ENG-04).

The cascade never talks to a model endpoint: :class:`GatewayJudge` renders the registered ``judge`` prompt, sends it
with :class:`tb_llm.GatewayClient` and its labels (data class, study, purpose, context of use, role, prompt@version,
step), and parses the schema-constrained answer. Any client with the same ``judge`` method can be injected (tests use
the in-process gateway in front of ``llm_stub``).

:func:`verify_span` is the CAS-16 check: the quote must sit, character for character, inside one excerpt that is
dated inside the criterion window. A judgement whose span does not verify is ``insufficient`` and counts as
``unknown:uncertain``.

The answer is validated against the prompt's output schema here too, as ``tb_common.llm`` does on the SCREEN path
(T-608, D-445; review LLM-022): an answer outside it is ``unknown`` (``refused: schema_invalid``), its verdict unread.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Protocol

from tb_common.pair import Vote, combine, needs_verifier, served_keys
from tb_common.quotes import quote_in, quote_key
from tb_llm.budget import estimate_tokens

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
    prompt: str = ""  # id@version from the prompt registry (D-300)
    prompt_sha: str = ""  # the registry's sha256 of that text
    tokens_in: int = 0
    tokens_out: int = 0
    refused: str | None = None  # gateway refusal code: the pair stays unknown, never excluded
    opinions: list[dict[str, Any]] = field(default_factory=list)  # both answers when the checks disagree (D-120)


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


#: the fields of an excerpt a model is shown (D-644; ``orchestrator.scenarios.evaluate`` sends the same three)
SHOWN = ("date", "note_type", "text")


@dataclass
class GatewayJudge:
    """The production judge path: ``libs/tb_llm`` → ``tb-gateway`` (the only route to a model, LLM-1)."""

    client: Any  # tb_llm.GatewayClient
    prompt_id: str = JUDGE_PROMPT
    calls: int = 0
    refusals: list[str] = field(default_factory=list)
    # T-689 (D-456, F-04): a call the model did not answer (an outage, a restart, a full queue) waits and is sent
    # again within this judge's allowance for the run (TB_LLM_OUTAGE_WAIT_S); used up, the run stops
    # (tb_llm.outage.OutageExhausted) instead of writing the rest as unknown. None: the allowance of the environment
    outage: Any = None  # tb_llm.outage.OutageBudget

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
        from tb_contracts import inline_schema, load_schema, null_absent, schema_errors
        from tb_llm import CallLabels, GatewayDown, GatewayRefused, json_schema_format
        from tb_llm.outage import MODEL_FAULTS, OutageBudget, wait_and_retry

        if self.outage is None:
            self.outage = OutageBudget()

        def fault_of(exc: BaseException) -> tuple[str, float | None] | None:
            if isinstance(exc, GatewayRefused) and exc.reason in MODEL_FAULTS:
                return exc.reason, exc.retry_after
            return ("unreachable", None) if isinstance(exc, GatewayDown) else None

        p = load_prompt(self.prompt_id)
        prompt = f"{p.meta.id}@{p.meta.version}"
        body_vars = {
            "criterion_text": criterion_text,
            "note_question": note_question,
            "index_date": index_date.isoformat(),
            # D-644: what a model reads of an excerpt, as NoteJudge sends it. Never the record's id (``did``): an
            # identifier has no place in a prompt, and a hex id holds digit runs the PHI tripwire refuses
            "excerpts": [{k: e.get(k) for k in SHOWN} for e in excerpts],
        }
        labels = CallLabels(
            data_class=data_class,
            purpose=purpose,
            study_id=study_id,
            context_of_use="s3_note_judgement" if role == "judge" else "s4_second_opinion",
            role=role,
            prompt=prompt,
            step_id=step_id,
            prompt_sha=p.sha256,
        )
        self.calls += 1
        try:
            res = wait_and_retry(
                lambda: self.client.chat(
                    render(p, body_vars),
                    labels,
                    response_format=json_schema_format(p.meta.id, inline_schema(p.meta.output_schema)),
                    max_tokens=p.meta.max_tokens,
                ),
                self.outage,
                role,
                fault_of,
            )
        except GatewayRefused as exc:
            self.refusals.append(exc.reason)
            reason = f"gateway refused: {exc.reason}"
            return JudgeReply(
                "unknown", 0.0, None, None, reason, prompt=prompt, prompt_sha=p.sha256, refused=exc.reason
            )
        schema = p.meta.output_schema
        data = null_absent(load_schema(schema), res.data) if isinstance(res.data, dict) else None
        if not isinstance(data, dict) or schema_errors(schema, data):
            # LLM-022: a reply outside the judge schema is no answer; it never reaches the verdict (fails safe)
            self.refusals.append("schema_invalid")
            return JudgeReply(
                "unknown",
                0.0,
                None,
                None,
                "the answer is outside the judge schema",
                call_id=res.call_id,
                build_sha=res.build_sha,
                prompt=prompt,
                prompt_sha=p.sha256,
                tokens_in=res.tokens_in,
                tokens_out=res.tokens_out,
                refused="schema_invalid",
            )
        return JudgeReply(
            verdict=str(data.get("verdict", "unknown")),
            confidence=float(data.get("confidence") or 0.0),
            quote=data.get("quote"),
            quote_date=None if data.get("quote_date") is None else str(data.get("quote_date")),
            reason=str(data.get("reason") or ""),
            call_id=res.call_id,
            build_sha=res.build_sha,
            prompt=prompt,
            prompt_sha=p.sha256,
            tokens_in=res.tokens_in,
            tokens_out=res.tokens_out,
        )


@dataclass
class AgreementJudge:
    """Two-model judge (the recommended DGX Spark configuration: judge build + verifier build behind one gateway).

    Every S3 question goes to ``primary``; a decided answer (``pass`` / ``fail``) is then put to ``verifier`` with the
    same role and inputs. The primary's answer stands only when the verifier gives the same verdict; any disagreement,
    abstention or refusal by the verifier becomes ``unknown`` ("judge/verifier disagree"), which the cascade maps to
    ``potential:uncertain``. So a criterion blocks a patient only when both models say so (unknown never excludes,
    SAFE-13); the S4 second opinion goes to the verifier as before. Costs one extra call per decided S3 answer."""

    primary: Any  # JudgeClient
    verifier: Any  # JudgeClient
    disagreements: int = 0

    def judge(self, *, role: str, **kw: Any) -> JudgeReply:
        if role != "judge":
            reply: JudgeReply = self.verifier.judge(role=role, **kw)
            return reply
        first: JudgeReply = self.primary.judge(role=role, **kw)
        if not needs_verifier(_vote(first)):
            return first
        second: JudgeReply = self.verifier.judge(role=role, **kw)
        answered = second
        mismatch = (first.prompt, first.prompt_sha) != (second.prompt, second.prompt_sha)
        if mismatch:
            # D-300: the pair agrees only on one registered prompt text; two texts are not two opinions on one question
            second = replace(second, verdict="unknown", confidence=0.0)  # combine() -> unknown (disagree)
        d = combine(_vote(first), _vote(second))  # the one two-model rule (tb_common.pair, D-118)
        if d.disagreement:
            self.disagreements += 1
        if d.verdict == first.verdict:
            return replace(first, confidence=d.confidence)
        return JudgeReply(
            "unknown",
            0.0,
            None,
            None,
            d.reason or "",
            call_id=first.call_id,
            build_sha=first.build_sha,
            prompt=first.prompt,
            prompt_sha=first.prompt_sha,
            tokens_in=first.tokens_in + second.tokens_in,
            tokens_out=first.tokens_out + second.tokens_out,
            refused=second.refused,
            opinions=[_opinion("judge", first), _opinion("verifier", answered, mismatch)] if d.disagreement else [],
        )


def _opinion(role: str, r: JudgeReply, prompt_mismatch: bool = False) -> dict[str, Any]:
    o = {"role": role, "verdict": r.verdict, "quote": r.quote, "quote_date": r.quote_date}
    if prompt_mismatch:  # D-300: why this answer did not count (the reason code stays "disagree", tb_common.reasons)
        o["prompt_mismatch"] = f"{r.prompt} sha256 {r.prompt_sha[:12]}"
    return o


def _vote(r: JudgeReply) -> Vote:
    """A cascade reply as a vote: a refusal counts as a model that did not answer (never an agreement)."""
    if r.refused:
        return Vote("unknown", 0.0, "model_down")
    return Vote(r.verdict, r.confidence, None, served_keys(build=r.build_sha))  # one build twice: one model (D-276)


def norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sentence_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(norm(text).encode("utf-8")).hexdigest()


def verify_span(reply: JudgeReply, excerpts: list[dict[str, Any]], lo: date, hi: date) -> dict[str, Any] | None:
    """CAS-16: the verified span (excerpt id, offsets, date, sentence hash) or None when it does not verify."""
    if not reply.quote:
        return None
    q = quote_key(reply.quote)  # stray spaces next to CJK characters do not count (tb_common.quotes)
    for ex in excerpts:
        raw = str(ex.get("text", ""))
        text = quote_key(raw)
        start = text.find(q)
        if start < 0 or not quote_in(reply.quote, raw):  # D-641: never across a cut of the excerpt, never the mark
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
    """What a judge call is counted as against the night's token budget: the one estimate of the product
    (:func:`tb_llm.budget.estimate_tokens`; D-645: this had a count of its own that took full-width punctuation
    and digits as a quarter token) of each excerpt's text, plus 300 for the prompt."""
    return 300 + sum(estimate_tokens(str(ex.get("text", ""))) for ex in excerpts)


__all__ = ["GatewayJudge", "JudgeClient", "JudgeReply", "expected_tokens", "norm", "sentence_hash", "verify_span"]
