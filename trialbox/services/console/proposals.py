"""Web requests as exact grammar lines (FR-UX-10: two ways to say everything).

Every console action becomes the exact line a user would put in an e-mail subject (``FEAS GZQO lookback=36``,
``APPROVE GZQO-DEMO version=1.0.0``). The line is parsed by the same deterministic parser as the mail gateway
(``tb_common.subject``) and becomes the same ``JobCreate``. Free text never runs anything: an exact line typed in the
box runs without a model; anything else goes to ``classify_intent`` through ``tb-gateway`` (caller
``converse-native``: the console hosts the native engine's single-turn proposal step for the web channel), which
returns a typed intent; the console renders the proposed line and the administrator confirms it. The free text
itself is not stored or echoed back (FR-UX-9); the audit keeps its SHA-256.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

from channels.base import ClassifiedIntent
from channels.grammar import GrammarError, parse_line
from tb_common.subject import Subject, SubjectError, parse_subject
from tb_contracts import JobCreate

# study codes and look-back periods written in the text itself: a small model often drops them, above all next to CJK
# characters ("GZQO試験", "過去三年"); they fill only fields the model left empty, and the administrator confirms
_STUDY = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{2,7}(?:-[A-Z0-9]{1,8})?)(?![A-Za-z0-9])")
_NOT_STUDY = frozenset({"FEAS", "SCREEN", "STATUS", "CANCEL", "APPROVE", "NAV", "COHORT", "OK", "PDF", "DOCX", "CRC"})
_CJK_NUM = {"一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_LOOKBACK = re.compile(
    r"(\d{1,3}|[一二兩两三四五六七八九十])\s*(?:(months?|個月|个月|か月|ヶ月|カ月)|(years?|yrs?|年))", re.I
)

# a malformed line that reads like a sentence ("FEAS for GZQO or RA-BIO?") goes to the model instead of a parser error
_WORD = re.compile(r"(?:^|\s)[a-z]{2,}(?=[\s,.]|$)")


def _reads_like_a_sentence(text: str) -> bool:
    return "?" in text or "？" in text or len(_WORD.findall(text)) >= 2


RUNNABLE = frozenset({"FEAS", "SCREEN", "APPROVE", "STATUS", "CANCEL", "COHORT", "NAV"})
Classifier = Callable[[str, str], ClassifiedIntent]  # (text, language) -> intent


class ProposalError(ValueError):
    pass


@dataclass(frozen=True)
class Proposal:
    line: str
    source: str  # "grammar" (typed exactly, no model) | "model" (classify_intent proposal)
    intent: str
    notes: tuple[str, ...] = field(default_factory=tuple)


def subject_of(line: str) -> Subject:
    try:
        s = parse_subject(line)
    except SubjectError as exc:
        raise ProposalError(str(exc)) from exc
    if s.cmd not in RUNNABLE:
        raise ProposalError(f"{s.cmd} cannot be started from the console")
    return s


def job_create(line: str, requested_by: str, job_id: str, comment: str, inputs: list[Any] | None = None) -> JobCreate:
    """The ``JobCreate`` the mail gateway builds for an e-mail with this subject (``mail_gateway.intake.decide``)."""
    s = subject_of(line)
    options = dict(s.options)
    ruleset: str | None = s.ruleset
    if s.job_id:
        options["target"] = s.job_id
        ruleset = None
    return JobCreate(
        job_id=job_id,
        type=cast(Any, s.cmd),
        ruleset=ruleset,
        options=options,
        comment=comment,
        requested_by=requested_by,
        inputs=inputs or [],
    )


def fill_from_text(intent: ClassifiedIntent, text: str) -> ClassifiedIntent:
    """The study code and look-back the text states plainly, where the model returned none."""
    update: dict[str, Any] = {}
    if intent.study is None:
        codes = {c for c in _STUDY.findall(text) if c not in _NOT_STUDY}
        if len(codes) == 1:
            update["study"] = codes.pop()
    if intent.lookback_months is None and intent.type == "FEAS":
        m = _LOOKBACK.search(text)
        if m:
            n = int(m.group(1)) if m.group(1).isdigit() else _CJK_NUM[m.group(1)]
            months = n if m.group(2) else n * 12
            if 1 <= months <= 120:
                update["lookback_months"] = months
    return intent.model_copy(update=update) if update else intent


def _months(v: str | None) -> str | None:
    if not v:
        return None
    digits = v.lower().removesuffix("m")
    return digits if digits.isdigit() else None


def line_from_intent(intent: ClassifiedIntent) -> Proposal:
    notes: list[str] = []
    if intent.type in ("FEAS", "SCREEN"):
        if not intent.study:
            raise ProposalError("Which study do you mean? Name the study code, for example GZQO.")
        parts = [intent.type, intent.study]
        if intent.type == "FEAS" and intent.lookback_months:
            parts.append(f"lookback={intent.lookback_months}")
        if intent.deadline:
            notes.append(f"deadline {intent.deadline} noted (not a v1 option)")
        return Proposal(" ".join(parts), "model", intent.type, tuple(notes))
    if intent.type == "STATUS":
        raise ProposalError("Status is on the Jobs page; every job shows its state there.")
    if intent.type == "ASK":
        raise ProposalError("Protocol questions are answered by e-mail (ASK); the console starts runs only.")
    raise ProposalError("I could not understand the request. Type an exact line such as 'FEAS GZQO lookback=36'.")


def propose(text: str, language: str, classify: Classifier | None) -> Proposal:
    """An exact line runs without a model; a malformed line gets the parser's message; other text is classified."""
    raw = text.strip()
    if not raw:
        raise ProposalError("Type a request.")
    if len(raw) > 2000:
        raise ProposalError("Requests are limited to 2000 characters.")
    try:
        line = parse_line(raw)
    except GrammarError as exc:
        if classify is None or not _reads_like_a_sentence(raw):
            raise ProposalError(str(exc)) from exc
        line = None
    if line is not None:
        if line.command not in RUNNABLE:
            raise ProposalError(f"{line.command} cannot be started from the console")
        if line.study == "NEW":
            raise ProposalError("Name the study code (for a new protocol use the Protocol page to upload it).")
        if line.grammar == "v1":
            return Proposal(line.text, "grammar", line.command)
        # v4 line for a v1 command (e.g. FEAS GZQO lookback=24m): convert to the v1 subject the orchestrator runs
        parts = [line.command, line.study or ""]
        for k, v in line.params.items():
            if k == "lookback":
                m = _months(v)
                if m:
                    parts.append(f"lookback={m}")
            elif k in ("version", "variant", "dept", "pract", "window", "since", "site"):
                parts.append(f"{k}={v}")
        candidate = " ".join(p for p in parts if p)
        subject_of(candidate)
        return Proposal(candidate, "grammar", line.command)
    if classify is None:
        raise ProposalError("The conversation engine is not available; type an exact line such as 'FEAS GZQO'.")
    try:
        intent = classify(raw, language)
    except Exception as exc:  # the engine is down or answered out of schema: tell the user, never guess
        raise ProposalError(
            "The conversation engine is not available right now; type an exact line such as 'FEAS GZQO'."
        ) from exc
    prop = line_from_intent(fill_from_text(intent, raw))
    subject_of(prop.line)
    return prop


def gateway_classifier(gateway_url: str, model: str | None, data_class: str, today: Callable[[], date]) -> Classifier:
    """``classify_intent`` through tb-gateway with the native engine's prompt and labels."""
    from channels.native.engine import NativeEngine
    from tb_llm import GatewayClient

    # a person is waiting on the page: a slow hosted model answers "not available" instead of a two-minute spinner
    client = GatewayClient(gateway_url, "converse-native", model=model, timeout=45)

    def _unused_frontdoor(_msg: dict[str, Any], _assertion: str, _conv: str) -> dict[str, Any]:
        raise RuntimeError("the console does not call front-door tools")

    engine = NativeEngine(client, _unused_frontdoor, today=today)

    def classify(text: str, language: str) -> ClassifiedIntent:
        return engine.classify(text, (), language, data_class)

    return classify
