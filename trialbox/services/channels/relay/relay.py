"""channel-relay (spec v4 §3.4.1 intake order, §9.2 message path; S1-10, FR-CONV-1, FR-CONV-6, FR-CONV-14, FR-CONV-16).

For every inbound message, on every channel, in this order:
1. **authenticate** (the channel's rule) and map to a directory principal; unknown or unauthenticated senders get no
   reply, only an audit event (FR-CONV-14);
2. **strip** quoted history, signatures and invisible Unicode;
3. **grammar**: the subject, then the first body line, through :func:`channels.grammar.parse_line`. A line that parses
   runs deterministically through :class:`Intake` and never reaches a model; a malformed line gets the error and the
   accepted lines; approval lines are accepted from email only;
4. **tokenise** identifiers in PHI-tolerant channels (``[MRN-1]`` …; the map stays with the relay and the front-door
   server, HER-12); a no-PHI channel drops a message with a guard hit and answers with a pointer;
5. **converse**: the remaining free text goes to the configured engine (``channels.engine``) with an identity
   assertion minted for this message; if the Hermes engine is unavailable the relay falls back to native and audits
   it. Proposals live in the orchestrator's request store, so the switch loses no request (FR-CONV-6);
6. every turn is audited (actor type, on behalf of, channel, request and proposal id) **before** the reply is sent.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from frontdoor_mcp.identity import AssertionSigner
from frontdoor_mcp.requests import ConfirmRefused, RequestStore
from frontdoor_mcp.tokens import RelayTokenMap
from guard.guard import Guard
from tb_common.crypto import sha256_text
from tb_common.policy.classes import Environment

from channels.base import Channel, ChannelError, InboundMessage, OutboundMessage
from channels.config import ChannelsConfig
from channels.grammar import HELP_LINES, GrammarError, Line, parse_line
from channels.native.engine import EngineTurn, EngineUnavailable

_QUOTE_START = re.compile(
    r"^(?:On .+ wrote:|.+ 於 .+ 寫道：|寄件者[:：]|差出人[:：]|From:\s|-----Original Message-----|_{10,})", re.M
)
_TOKEN_KIND = {"MRN": "MRN", "NAME": "NAME", "EMAIL": "EMAIL", "PHONE": "PHONE"}
POINTER = {
    "approval": "Approvals are accepted by email only (reply to the gate e-mail).",
    "no_phi": "This channel carries no patient information. Please use e-mail for this request.",
}


class Engine(Protocol):
    name: str
    actor_type: str
    client_id: str

    def converse(
        self, *, text: str, attachments: tuple[Any, ...], conv: str, assertion: str, data_class: str
    ) -> EngineTurn: ...


class JobSink(Protocol):
    """The orchestrator's workflow start for a deterministic line (typed by the person or confirmed with OK)."""

    def start(self, line: Line, *, sender: str, ticket_id: str | None, refs: Mapping[str, str]) -> str: ...


class AuditSink(Protocol):
    def append(self, event: str, **fields: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RelayResult:
    action: str  # dropped | line | confirmed | proposal | answer | grammar_error | pointer
    conv: str | None = None
    reply_id: str | None = None
    ticket_id: str | None = None
    job_id: str | None = None
    engine: str | None = None
    reason: str | None = None


def strip(text: str) -> str:
    """Quoted history, ``>`` blocks, signatures (``-- ``) and invisible/format Unicode out (§3.4.1 step 2)."""
    m = _QUOTE_START.search(text)
    if m:
        text = text[: m.start()]
    lines = []
    for line in text.splitlines():
        if line.startswith(">"):
            continue
        if line.rstrip() == "--":
            break
        lines.append(line)
    clean = "\n".join(lines).strip()
    return "".join(c for c in clean if unicodedata.category(c) != "Cf")


class Intake:
    """Deterministic intake: ``OK`` confirms the open proposal; a typed line starts its workflow (no model)."""

    def __init__(self, requests: RequestStore, jobs: JobSink) -> None:
        self.requests = requests
        self.jobs = jobs

    def run(self, line: Line, *, sender: str, conv: str) -> RelayResult:
        if line.command == "OK":
            try:
                p = self.requests.confirm(conv=conv, sender=sender)
            except ConfirmRefused as e:
                return RelayResult("grammar_error", conv=conv, reason=e.reason)
            # the orchestrator-rendered line is parsed again here; engine output is never executed (FR-CONV-2)
            parsed = parse_line(p.commands[0])
            assert parsed is not None
            job = self.jobs.start(parsed, sender=sender, ticket_id=p.ticket_id, refs=self.requests.refs(p.ticket_id))
            self.requests.attach_job(p.ticket_id, job)
            return RelayResult("confirmed", conv=conv, ticket_id=p.ticket_id, job_id=job)
        if line.command == "HELP":
            return RelayResult("line", conv=conv)
        job = self.jobs.start(line, sender=sender, ticket_id=None, refs={})
        return RelayResult("line", conv=conv, job_id=job)


class ChannelRelay:
    def __init__(
        self,
        *,
        config: ChannelsConfig,
        channels: Mapping[str, Channel],
        engines: Mapping[str, Engine],
        intake: Intake,
        signer: AssertionSigner,
        tokens: RelayTokenMap,
        audit: AuditSink,
        guard: Guard | None = None,
        environment: Environment = Environment.TEST,
        on_quarantine: Callable[[InboundMessage], None] | None = None,
    ) -> None:
        self.config = config
        self.channels = dict(channels)
        self.engines = dict(engines)
        self.intake = intake
        self.signer = signer
        self.tokens = tokens
        self.audit = audit
        self.guard = guard or Guard(None)
        self.environment = environment
        self.on_quarantine = on_quarantine
        self.threads: dict[str, str] = {}  # message id (inbound or our reply) -> conversation id

    # ------------------------------------------------------------------------------------------------ helpers
    def conversation_class(self, channel: Channel) -> str:
        """FR-CONV-8: D3 for tokenised text from a PHI-tolerant channel, D1 otherwise. DEV and TEST hold D0 and
        synthetic data only (§17.8), so conversation text there is D0."""
        if self.environment in (Environment.DEV, Environment.TEST):
            return "D0"
        return "D3" if channel.phi_tolerant else "D1"

    def _conv(self, m: InboundMessage) -> str:
        if m.thread_ref and m.thread_ref in self.threads:
            return self.threads[m.thread_ref]
        if m.channel == "teams" and m.thread_ref:
            return f"teams:{m.thread_ref}"
        return "conv-" + sha256_text(m.message_id or m.raw_sha256).removeprefix("sha256:")[:16]

    def _tokenise(self, text: str, m: InboundMessage, principal: str, conv: str) -> str:
        spans = self.guard.detect(text)
        if not spans:
            return text
        out: list[str] = []
        pos = 0
        for f in spans:
            out.append(text[pos : f.start])
            kind = _TOKEN_KIND.get(f.kind, "ID")
            out.append(
                self.tokens.mint(msg=m.raw_sha256, sender=principal, conv=conv, kind=kind, value=text[f.start : f.end])
            )
            pos = f.end
        out.append(text[pos:])
        return "".join(out)

    def _engine(self) -> tuple[Engine, str | None]:
        wanted = self.config.engine
        eng = self.engines.get(wanted)
        if eng is not None and getattr(eng, "available", True):
            return eng, None
        return self.engines[self.config.fallback], f"{wanted} unavailable; fell back to {self.config.fallback}"

    def _reply(
        self,
        channel: Channel,
        m: InboundMessage,
        conv: str,
        text: str,
        *,
        actor_type: str,
        action: str,
        ticket: str | None = None,
        job: str | None = None,
        engine: str | None = None,
        reason: str | None = None,
    ) -> RelayResult:
        # FR-CONV-16: the turn is in the ledger before the reply leaves
        self.audit.append(
            "channel.turn",
            actor=m.principal or "?",
            detail={
                "actor_type": actor_type,
                "on_behalf_of": m.principal,
                "channel": m.channel,
                "conv": conv,
                "request_id": job,
                "proposal_id": ticket,
                "engine": engine,
                "action": action,
                "reason": reason,
                "msg_sha256": m.raw_sha256,
            },
        )
        subject = m.subject if m.subject.lower().startswith("re:") or not m.subject else f"Re: {m.subject}"
        try:
            rid = channel.send(OutboundMessage(m.channel, m.sender, subject or "TrialBox", text, m.message_id, conv))
        except ChannelError as e:
            self.audit.append("channel.reply.refuse", actor=m.principal or "?", detail={"conv": conv, "reason": str(e)})
            return RelayResult("pointer", conv=conv, reason="outbound_refused", ticket_id=ticket, job_id=job)
        self.threads[rid] = conv
        return RelayResult(action, conv=conv, reply_id=rid, ticket_id=ticket, job_id=job, engine=engine, reason=reason)

    # ------------------------------------------------------------------------------------------------ the path
    def receive(self, channel_name: str, raw: Any) -> RelayResult:
        channel = self.channels[channel_name]
        m = channel.parse(raw)
        if m.principal is None:
            # FR-CONV-14: unknown or unauthenticated senders never reach the engine and get no reply
            self.audit.append(
                "channel.inbound.refuse",
                actor="?",
                detail={"channel": m.channel, "auth": m.auth_detail, "msg_sha256": m.raw_sha256},
            )
            if self.on_quarantine is not None:
                self.on_quarantine(m)
            return RelayResult("dropped", reason="sender_not_authenticated")
        conv = self._conv(m)
        self.threads[m.message_id] = conv
        body = strip(m.text)
        candidates = [m.subject, next((ln for ln in body.splitlines() if ln.strip()), "")]
        for cand in candidates:
            try:
                line = parse_line(cand)
            except GrammarError as e:
                return self._reply(
                    channel,
                    m,
                    conv,
                    "\n".join([str(e), *HELP_LINES]),
                    actor_type="user",
                    action="grammar_error",
                    reason="grammar",
                )
            if line is None:
                continue
            if line.approval and not channel.accepts_approvals:
                return self._reply(
                    channel,
                    m,
                    conv,
                    POINTER["approval"],
                    actor_type="user",
                    action="pointer",
                    reason="approval_off_email",
                )
            res = self.intake.run(line, sender=m.principal, conv=conv)
            if res.action == "grammar_error":
                return self._reply(
                    channel,
                    m,
                    conv,
                    f"OK not applied: {res.reason}",
                    actor_type="user",
                    action="grammar_error",
                    reason=res.reason,
                )
            text = "\n".join(HELP_LINES) if line.command == "HELP" else f"{line.text}: started ({res.job_id})"
            return self._reply(
                channel, m, conv, text, actor_type="user", action=res.action, ticket=res.ticket_id, job=res.job_id
            )
        free = body if not m.subject or m.subject.lower().startswith("re:") else f"{m.subject}\n{body}".strip()
        if not channel.phi_tolerant and self.guard.tripwire(free).hit:
            return self._reply(
                channel,
                m,
                conv,
                POINTER["no_phi"],
                actor_type="agent",
                action="pointer",
                reason="phi_on_no_phi_channel",
            )
        tokenised = self._tokenise(free, m, m.principal, conv)
        engine, fallback = self._engine()
        if fallback:
            self.audit.append("channels.engine.fallback", actor="relay", detail={"conv": conv, "detail": fallback})
        assertion = self.signer.mint(sub=m.principal, channel=m.channel, conv=conv, msg=m.raw_sha256)
        try:
            turn = engine.converse(
                text=tokenised,
                attachments=m.attachments,
                conv=conv,
                assertion=assertion,
                data_class=self.conversation_class(channel),
            )
        except EngineUnavailable as e:
            turn = EngineTurn(str(e), refused="engine_unavailable")
        return self._reply(
            channel,
            m,
            conv,
            turn.text,
            actor_type=engine.actor_type,
            action="proposal" if turn.proposal else "answer",
            ticket=turn.ticket_id,
            engine=engine.name,
            reason=turn.refused,
        )
