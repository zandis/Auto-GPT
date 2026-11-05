"""The Hermes engine as seen from channel-relay (spec v4 §9.2; S1-11, HER-6, HER-18).

The relay hands the tokenised message to Hermes through ``tb_relay_adapter`` (the ``tb_relay`` platform plugin of
the pinned release) over mTLS, and Hermes answers the same way:

1. :meth:`HermesEngine.converse` opens a turn for the conversation in :class:`HermesReplies`, then
   :class:`MtlsHermesTransport` posts the relay envelope (conversation, message hash, channel, the relay-minted
   identity assertion, tokenised text) to the adapter's listener (``https://hermes:8444/inject``, client certificate
   ``channel-relay``). The adapter re-checks it and feeds Hermes a ``MessageEvent``.
2. Hermes' replies come back to channel-relay's ``/hermes/reply`` (client certificate ``hermes``): each message the
   agent sends is collected, and the adapter's ``on_processing_complete`` ends the turn.
3. The last message of a successful turn is the reply; the relay audits the turn and sends it (FR-CONV-16). A turn
   that fails, times out or says nothing is a fixed message plus the grammar lines, never Hermes' error text. When
   the turn created a proposal, the orchestrator's restatement and exact line are appended unless the reply already
   quotes the line, so the sender can always confirm what will run.

Whether the turn produced a proposal is read from the orchestrator's request store (the front door wrote it), not
from Hermes' text. Hermes may only run on a release pinned by tag, commit SHA and image digest, mirrored internally
outside DEV/TEST (``integrations/hermes/lock.py``); without a transport or with pin problems :attr:`available` is
``False`` and the relay falls back to native (OPS-02).
"""

from __future__ import annotations

import base64
import json
import re
import ssl
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from channels.grammar import HELP_LINES
from channels.native.engine import EngineTurn, EngineUnavailable
from integrations.hermes.lock import HermesLock, pin_problems

ADAPTER_MISSING = "Hermes relay-adapter connection not configured"
TURN_TIMEOUT_S = 180.0
FAILED_TEXT = "The assistant could not complete this request. You can type one of these lines instead:"
OpenProposals = Callable[[str, str], list[str]]  # (conv, sender) -> open proposal ticket ids
ProposalText = Callable[[str], str | None]  # ticket id -> the orchestrator-rendered proposal block
_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def proposal_block(p: Any) -> str | None:
    """Restatement, exact grammar line(s) and confirm instruction of a stored proposal (FR-CONV-2), or ``None``."""
    if p is None:
        return None
    return "\n".join([p.restatement, *p.commands, p.confirm_instruction])


def clean_reply(text: str) -> str:
    """Hermes' reply as mail text: literal JSON escapes some models emit (``\\u2019``) become the characters."""

    def char(m: re.Match[str]) -> str:
        cp = int(m.group(1), 16)
        return m.group(0) if 0xD800 <= cp <= 0xDFFF else chr(cp)  # a lone surrogate cannot be mailed

    return _ESCAPE.sub(char, text).replace("\\n", "\n").strip()


def with_proposal(reply: str, block: str | None) -> str:
    """The reply always carries the exact line to confirm, whatever the model wrote (stress test #26): the block is
    appended unless every one of its command lines already appears in the reply."""
    if not block:
        return reply
    commands = [ln for ln in block.splitlines()[1:-1] if ln.strip()]
    if commands and all(c in reply for c in commands):
        return reply
    return f"{reply}\n\n{block}" if reply else block


class HermesTransport(Protocol):
    def inject(self, envelope: Mapping[str, Any]) -> None: ...


@dataclass
class _Turn:
    done: threading.Event = field(default_factory=threading.Event)
    texts: list[str] = field(default_factory=list)
    outcome: str | None = None


class HermesReplies:
    """Replies posted by ``tb_relay_adapter`` (``/hermes/reply``), grouped into the open turn of each conversation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: dict[str, _Turn] = {}

    def open(self, conv: str) -> _Turn:
        with self._lock:
            turn = _Turn()
            self._turns[conv] = turn
            return turn

    def close(self, conv: str, turn: _Turn) -> None:
        with self._lock:
            if self._turns.get(conv) is turn:
                del self._turns[conv]

    def deliver(self, conv: str, text: str) -> bool:
        """One message from Hermes. ``False`` when no turn is open for the conversation (the caller audits it)."""
        with self._lock:
            turn = self._turns.get(conv)
            if turn is None or turn.done.is_set():
                return False
            turn.texts.append(text)
            return True

    def complete(self, conv: str, outcome: str) -> bool:
        with self._lock:
            turn = self._turns.get(conv)
            if turn is None:
                return False
            turn.outcome = outcome
            turn.done.set()
            return True


def assertion_claims(assertion: str) -> dict[str, Any]:
    """The claims of a relay-minted assertion, unverified (the relay just signed it; the front door verifies)."""
    try:
        part = assertion.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError) as e:
        raise EngineUnavailable("assertion does not decode") from e
    return claims if isinstance(claims, dict) else {}


class MtlsHermesTransport:
    """POST the envelope to ``tb_relay_adapter``'s listener with the relay's client certificate."""

    def __init__(self, url: str, context: ssl.SSLContext, timeout_s: float = 10.0) -> None:
        if not url.startswith("https://"):
            raise ValueError("the Hermes adapter URL must be https (mTLS)")
        self.url = url
        self.context = context
        self.timeout_s = timeout_s

    def inject(self, envelope: Mapping[str, Any]) -> None:
        body = json.dumps(dict(envelope), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310 (https checked in __init__)
            self.url, data=body, headers={"content-type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s, context=self.context) as resp:  # noqa: S310
                status = resp.status
        except urllib.error.HTTPError as e:
            raise EngineUnavailable(f"Hermes adapter refused the envelope (HTTP {e.code})") from e
        except OSError as e:
            raise EngineUnavailable(f"Hermes adapter unreachable ({type(e).__name__})") from e
        if status != 202:
            raise EngineUnavailable(f"Hermes adapter answered HTTP {status}")


class HermesEngine:
    name = "hermes"
    actor_type = "hermes"
    client_id = "hermes"

    def __init__(
        self,
        lock_path: Path,
        environment: str = "DEV",
        *,
        transport: HermesTransport | None = None,
        replies: HermesReplies | None = None,
        open_proposals: OpenProposals | None = None,
        proposal_text: ProposalText | None = None,
        turn_timeout_s: float = TURN_TIMEOUT_S,
    ) -> None:
        self.problems = pin_problems(HermesLock.load(lock_path), environment=environment)
        self.transport = transport
        self.replies = replies
        self.open_proposals = open_proposals
        self.proposal_text = proposal_text
        self.turn_timeout_s = turn_timeout_s
        self.available = not self.problems and transport is not None and replies is not None

    def converse(
        self, *, text: str, attachments: tuple[Any, ...], conv: str, assertion: str, data_class: str
    ) -> EngineTurn:
        if not self.available or self.transport is None or self.replies is None:
            reason = "; ".join(self.problems) or ADAPTER_MISSING
            raise EngineUnavailable(f"Hermes unavailable: {reason}")
        claims = assertion_claims(assertion)
        sender, channel = str(claims.get("sub") or ""), str(claims.get("channel") or "")
        before = set(self.open_proposals(conv, sender)) if self.open_proposals else set()
        envelope = {
            "origin": "channel-relay",
            "conv": conv,
            "msg_sha256": str(claims.get("msg") or ""),
            "channel": channel,
            "assertion": assertion,
            "text": text,  # tokenised; attachments never reach Hermes (text only, ADVISORIES: Pillow)
        }
        turn = self.replies.open(conv)
        try:
            self.transport.inject(envelope)
            finished = turn.done.wait(self.turn_timeout_s)
        finally:
            self.replies.close(conv, turn)
        texts = [t for t in turn.texts if t.strip()]
        if not finished or turn.outcome != "success" or not texts:
            reason = "hermes_timeout" if not finished else f"hermes_{turn.outcome or 'silent'}"
            return EngineTurn("\n".join([FAILED_TEXT, *HELP_LINES]), refused=reason)
        new = [t for t in (self.open_proposals(conv, sender) if self.open_proposals else []) if t not in before]
        ticket = new[-1] if new else None
        reply = clean_reply(texts[-1])
        if ticket and self.proposal_text is not None:
            reply = with_proposal(reply, self.proposal_text(ticket))
        return EngineTurn(reply, ticket_id=ticket, tool="tb.submit_request" if ticket else None, proposal=bool(ticket))
