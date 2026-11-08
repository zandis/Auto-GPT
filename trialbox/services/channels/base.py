"""Message types of the conversation engine (spec v4 §3.4.1; S1-10; D-121).

``Attachment`` describes a file a person attached; ``ClassifiedIntent`` is the ``classify_intent`` output. The
``Channel`` interface and the email/Teams channel adapters went with the channel relay in D-121: mail commands are the
mail gateway's subject grammar, free text is the console's header command box.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    sha256: str
    size: int
    data: bytes = field(repr=False, default=b"")


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
