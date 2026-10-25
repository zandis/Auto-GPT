"""The ``Channel`` interface and the message types every channel speaks (spec v4 §3.4.1, §9.2; S1-10).

A channel turns its transport's raw input into an :class:`InboundMessage` (with the sender already authenticated by
the channel's own rule: DMARC for email, Bot Framework JWT for Teams) and delivers an :class:`OutboundMessage` to the
same sender and thread. Channels never parse grammar and never call a model: that is the relay's and the engine's
job. The channel table of §3.4.1 is carried by the class attributes ``phi_tolerant`` and ``accepts_approvals``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChannelName = Literal["email", "teams", "line", "admin_tui"]


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    sha256: str
    size: int
    data: bytes = field(repr=False, default=b"")


@dataclass(frozen=True)
class InboundMessage:
    channel: ChannelName
    message_id: str
    sender: str  # transport address (mail address, Entra object id, LINE user id)
    principal: str | None  # directory principal when the sender is known and authenticated, else None
    auth_ok: bool
    auth_detail: str
    subject: str
    text: str
    thread_ref: str | None  # In-Reply-To / replyToId: the message this one answers
    attachments: tuple[Attachment, ...] = ()
    raw_sha256: str = ""


@dataclass(frozen=True)
class OutboundMessage:
    channel: ChannelName
    to: str  # transport address of the original sender
    subject: str
    text: str
    in_reply_to: str | None
    conv: str


class ChannelError(RuntimeError):
    pass


class Channel(ABC):
    """One transport. Implementations: ``native.email.EmailChannel``, ``native.teams.TeamsChannel`` (fake)."""

    name: ChannelName
    phi_tolerant: bool = True
    accepts_approvals: bool = False

    @abstractmethod
    def parse(self, raw: Any) -> InboundMessage:
        """Authenticate and normalise one raw inbound item. Never raises on an unknown sender: it returns a message
        with ``principal=None`` so the relay can audit and drop it."""

    @abstractmethod
    def send(self, out: OutboundMessage) -> str:
        """Deliver to the same sender and thread; return the transport message id."""


class ClassifiedIntent(BaseModel):
    """Output schema of the ``classify_intent`` role (prompt ``classify_intent@1``): a typed intent, never a line."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["FEAS", "QFILL", "SCREEN", "ASK", "STATUS", "UNKNOWN"]
    study: str | None = Field(default=None, pattern=r"^[A-Z0-9][A-Z0-9_-]{0,15}$")
    scope: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_:,.-]{0,47}$")
    lookback_months: int | None = Field(default=None, ge=1, le=120)
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    question: str | None = Field(default=None, max_length=500)
    language: Literal["zh-TW", "en", "ja", "mixed"] = "en"
