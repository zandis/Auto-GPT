"""Teams channel as a **fake transport only** (spec v4 §3.4.1, FR-UX-11; S1-10). No network, no PHI.

Live Teams (Bot Framework, Entra tenant restriction) is MS4. Until then this channel exercises the same relay path
with an in-memory transport:

* inbound activities are dicts shaped like Bot Framework activities; :class:`FakeBotFramework` stands in for JWT
  validation (a set of tokens it accepts) and the tenant check;
* outbound replies go to :attr:`FakeTeamsTransport.sent`; any reply that trips the PHI guard is refused, because
  Teams carries no PHI in this build (FR-UX-11), and approval lines are never accepted (FR-SIG-8).
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from guard.guard import Guard
from tb_common.crypto import sha256_text

from channels.base import Channel, ChannelError, InboundMessage, OutboundMessage


@dataclass
class FakeBotFramework:
    tenant_id: str
    valid_tokens: set[str] = field(default_factory=set)

    def validate(self, activity: Mapping[str, Any]) -> tuple[bool, str]:
        if activity.get("tenantId") != self.tenant_id:
            return False, "tenant mismatch"
        if activity.get("token") not in self.valid_tokens:
            return False, "bot framework token invalid"
        return True, "jwt ok"


@dataclass
class FakeTeamsTransport:
    sent: list[dict[str, Any]] = field(default_factory=list)
    _ids: Any = field(default_factory=lambda: itertools.count(1))

    def post(self, conversation_id: str, reply_to: str | None, text: str) -> str:
        mid = f"teams-out-{next(self._ids)}"
        self.sent.append({"id": mid, "conversation": conversation_id, "replyToId": reply_to, "text": text})
        return mid


class TeamsChannel(Channel):
    name = "teams"
    phi_tolerant = False  # this build: no PHI on Teams (site default may be PHI-tolerant from MS4)
    accepts_approvals = False

    def __init__(
        self,
        transport: FakeTeamsTransport,
        bot: FakeBotFramework,
        *,
        lookup: Callable[[str], str | None],
        guard: Guard | None = None,
    ) -> None:
        self.transport = transport
        self.bot = bot
        self.lookup = lookup  # Entra object id -> directory principal
        self.guard = guard or Guard(None)

    def parse(self, raw: Mapping[str, Any]) -> InboundMessage:
        ok, detail = self.bot.validate(raw)
        sender = str((raw.get("from") or {}).get("aadObjectId") or "")
        principal = self.lookup(sender) if ok and sender else None
        text = str(raw.get("text") or "")
        return InboundMessage(
            channel="teams",
            message_id=str(raw.get("id") or ""),
            sender=sender,
            principal=principal,
            auth_ok=ok,
            auth_detail=detail,
            subject="",
            text=text,
            thread_ref=str(raw.get("conversation", {}).get("id") or "") or None,
            raw_sha256=sha256_text(repr(sorted(raw.items()))),
        )

    def send(self, out: OutboundMessage) -> str:
        if self.guard.tripwire(out.text).hit:
            raise ChannelError("Teams replies carry no PHI (FR-UX-11): reply refused")
        return self.transport.post(out.conv, out.in_reply_to, out.text)
