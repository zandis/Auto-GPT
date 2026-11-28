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
import json
import unicodedata
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Protocol

from tb_common.llm import no_sentinel_date
from tb_common.pair import Vote, combine, needs_verifier, served_keys
from tb_common.quotes import as_in, quote_key
from tb_llm import budget
from tb_llm.budget import estimate_tokens

from matching.inferred import sentence_of
from matching.note_answer import affirms

JUDGE_PROMPT = "judge"


@dataclass(frozen=True)
class Asking:
    """Who and what a judge question is about, beside the prompt (D-908, the owner's D-519): set by the cascade
    around each question so a model client below it (the judged-pair store of SCREEN) can key and erase an answer by
    the patient's pseudonym, the criterion's canonical hash and the window. ``audit``: a question of an audit sample
    (CAS-8's stratified draw), which is always asked live and never stored."""

    pid: str
    criterion_hash: str
    window: tuple[str, str]
    audit: bool = False
    role: str = "judge"  # the cascade's role: S3 ``judge`` or S4 ``second_opinion``
    question: str = ""  # :func:`question_digest` of what the models are shown: only that call is the question


#: the question being asked in this thread (None outside the cascade's judge calls)
ASKING: ContextVar[Asking | None] = ContextVar("tb_cascade_asking", default=None)


def call_context(
    role: str, pid: str, criterion_hash: str, window: tuple[str, str], question: str, audit: bool = False
) -> dict[str, Any]:
    """H-16: what ``tb_common.llm.CALL_CONTEXT`` writes beside a judge call (``llm.call``'s ``asking``): the stage
    (S3 for the judge, S4 for the second opinion), the context of use the cascade's gateway client labels it with, the
    role, the patient's pseudonym, the criterion's canonical hash, the window and the question digest, with whether
    it is an audit sample. With the call's prompt, schema and build beside it, the judged-pair key can be computed
    offline (lane H's H-18 review). Ids and hashes only."""
    stage = "S3" if role == "judge" else "S4"
    return {
        "stage": stage,
        "context_of_use": "s3_note_judgement" if stage == "S3" else "s4_second_opinion",
        "role": role,
        "pid": pid,
        "criterion_hash": criterion_hash,
        "window": list(window),
        "question": question,
        "audit": audit,
    }


def question_digest(criterion_text: str, note_question: str, index_date: str, excerpts: list[dict[str, Any]]) -> str:
    """The sha256 of a note question as the models see it: the criterion's wording, the note question, the index
    date and the excerpts' shown fields. A model call below the cascade whose variables give another digest (a wake
    check's canary case, any other prompt) is not the cascade's question (D-908)."""
    body = json.dumps(
        [criterion_text, note_question, index_date, [{k: e.get(k) for k in SHOWN} for e in excerpts]],
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


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
    calls: tuple[str, ...] = ()  # D-989: every model call the answer rests on; () = this reply's own call_id
    # L3 (#639 7107834329): the record's sentences of the pair's other quote, read by the one rule of what a note
    # answer may do (``matching.note_answer``) beside the span's own; never published
    sentence: str = ""
    # round 5 (#639 7115208555): the model said the quote affirms the condition, the patient's, now (judge v6's
    # certainty, experiencer and time: ``note_answer.affirms``); in a pair, both models said it
    affirmed: bool = False
    qualification: str = ""  # SAFE-1 A1: "unqualified" when a model behind the answer holds no record
    # BENCH-2 §2: on a disagreement, the judge's own answer (never affirmed); the engine takes it only where it keeps
    kept: JudgeReply | None = None

    @property
    def all_calls(self) -> tuple[str, ...]:
        """The model calls behind this answer, once each (D-989): the pair's two, or the reply's own call."""
        return tuple(dict.fromkeys(self.calls or ((self.call_id,) if self.call_id else ())))


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


#: the fields of an excerpt a model is shown (D-644, D-941: ``tb_llm.budget.shown``, as every path sends them)
SHOWN = budget.SHOWN


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
        from tb_llm.outage import OutageBudget, refusal_fault, wait_and_retry

        if self.outage is None:
            self.outage = OutageBudget()

        def fault_of(exc: BaseException) -> tuple[str, float | None] | None:
            if isinstance(exc, GatewayRefused) and (fault := refusal_fault(exc.reason, exc.upstream_kinds)):
                return fault, exc.retry_after  # walk step 5: a timeout of the gateway's is waited for too
            return ("unreachable", None) if isinstance(exc, GatewayDown) else None

        p = load_prompt(self.prompt_id)
        prompt = f"{p.meta.id}@{p.meta.version}"
        body_vars = {
            "criterion_text": criterion_text,
            "note_question": note_question,
            "index_date": index_date.isoformat(),
            # D-644: what a model reads of an excerpt, as NoteJudge sends it. Never the record's id (``did``): an
            # identifier has no place in a prompt, and a hex id holds digit runs the PHI tripwire refuses
            "excerpts": [budget.shown(e) for e in excerpts],
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
        data = no_sentinel_date(data) if isinstance(data, dict) else data
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
                qualification=res.qualification,
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
            qualification=res.qualification,
            prompt=prompt,
            prompt_sha=p.sha256,
            tokens_in=res.tokens_in,
            tokens_out=res.tokens_out,
            affirmed=affirms(data),  # an abstention never excludes, whatever it says
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
        texts = [str(ex.get("text", "")) for ex in kw.get("excerpts") or []]
        found = next((f for t in texts if (f := as_in(str(second.quote or ""), t))), None) if second.quote else None
        if mismatch:
            # D-300: the pair agrees only on one registered prompt text; two texts are not two opinions on one question
            second = replace(second, verdict="unknown", confidence=0.0)  # combine() -> unknown (disagree)
        elif needs_verifier(_vote(second)) and found is None:  # a decided answer
            # M1 (#639 7115208555): the verifier's quote must be in the record too, as v1's ``postprocess`` checks it;
            # a decided answer on a quote that is not there, or on none, is the verifier's "unknown"
            second = replace(second, verdict="unknown", confidence=0.0)  # combine() -> unknown (disagree)
        d = combine(_vote(first), _vote(second))  # the one two-model rule (tb_common.pair, D-118)
        if d.disagreement:
            self.disagreements += 1
        calls = first.all_calls + second.all_calls  # D-989: the verifier's call counts too
        qualification = first.qualification or second.qualification  # SAFE-1 A1: either model unqualified
        if d.verdict == first.verdict:
            # L3: the verifier's quote is read too, in its sentence of the excerpts (never published); M1: it was found
            other = next((x for t in texts if found and (x := sentence_of(found, t))), str(found or ""))
            # round 5: the exclusion stands only when both models said the quote affirms it
            return replace(first, confidence=d.confidence, calls=calls, sentence=other,
                           affirmed=first.affirmed and second.affirmed, qualification=qualification)  # fmt: skip
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
            calls=calls,
            qualification=qualification,
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
    for ex in excerpts:
        raw = str(ex.get("text", ""))
        # D-641: never across a cut of the excerpt, never the mark; one enclosing 「」 or "" dropped (#639 7113069462)
        quote = as_in(reply.quote, raw)
        if quote is None:
            continue
        q = quote_key(quote)  # stray spaces next to CJK characters do not count (tb_common.quotes)
        text = quote_key(raw)
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
            "quote": quote,
            # R22-16: the record's sentence the quote lies in, for the one rule of what a note answer may do
            # (``matching.note_answer``); ``engine._map`` reads it and takes it out, so it is never published
            "sentence": sentence_of(quote, raw),
        }
    return None


def expected_tokens(excerpts: list[dict[str, Any]]) -> int:
    """What a judge call is counted as against the night's token budget: the one estimate of the product
    (:func:`tb_llm.budget.estimate_tokens`; D-645: this had a count of its own that took full-width punctuation
    and digits as a quarter token) of each excerpt's text, plus 300 for the prompt."""
    return 300 + sum(estimate_tokens(str(ex.get("text", ""))) for ex in excerpts)


__all__ = ["GatewayJudge", "JudgeClient", "JudgeReply", "expected_tokens", "norm", "sentence_hash", "verify_span"]
