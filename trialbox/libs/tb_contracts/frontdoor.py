"""Front-door MCP contracts (spec v4 §9.3, §9.4; S1-09, HER-8 … HER-15).

The front-door server exposes exactly the eight tools of §9.3. This module is the contract for them: the tool table
(name, tier, allowed roles, default rate limit), the input and output model of each tool, the identity-assertion
claims the relay mints (§9.4) and the audit record each call writes before it returns (HER-14).

Rules carried by the models themselves:

* every model forbids extra fields, so a tool cannot grow an undeclared output field (HER-9);
* no output field holds patient-level data, an identifier, a pid, a signing link or the content of a released file
  (HER-9). Counts are control-rounded strings or integers (``"<5"``); free-text fields hold only protocol (D1),
  registry (D0) or orchestrator-rendered text;
* ``tb.submit_request`` parameters reject identifier patterns other than relay tokens such as ``[MRN-1]`` (HER-11).
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tb_contracts.dataclass import ClassLabel, DataClass

SCHEMA_VERSION = "1.0.0"
SERVER_NAME = "trialbox-frontdoor"
AUDIENCE = "frontdoor-mcp"
ASSERTION_MAX_TTL_S = 300  # §9.4: exp is 5 minutes

D0 = ClassLabel(data_class=DataClass.D0)
D1 = ClassLabel(data_class=DataClass.D1)

# A relay token, minted per message by channel-relay (§9.3 "Token resolution"): ``[MRN-1]``, ``[NAME-2]``.
RELAY_TOKEN = re.compile(r"^\[[A-Z][A-Z_]{1,15}-\d{1,4}\]$")
# Identifier shapes refused in submit_request parameters (HER-11). The server also runs the PHI guard; this screen
# keeps the contract self-contained.
_IDENTIFIER_SHAPES = (
    re.compile(r"\d{6,}"),  # MRN-like digit runs, phone numbers, national numbers
    re.compile(r"\b[A-Z][12489]\d{8}\b"),  # Taiwan national ID / ARC
    re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+"),  # e-mail address
    re.compile(r"\b\d{2,4}-\d{3,4}-\d{3,4}\b"),  # phone with separators
)
_PARAM_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_STUDY = re.compile(r"^(?:NEW|[A-Z0-9][A-Z0-9_-]{0,15})$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Tier(StrEnum):
    """Tool tiers of §9.3. T2/T3 tools (patient-level or acting) never exist on the front door (HER-1, HER-9)."""

    T0 = "T0"
    T1 = "T1"


class RequestType(StrEnum):
    """Typed request kinds ``tb.submit_request`` may create (the grammar types of App. D)."""

    FEAS = "FEAS"
    QFILL = "QFILL"
    SCREEN = "SCREEN"
    MATCH = "MATCH"
    ASK = "ASK"
    REPORT = "REPORT"
    CONFIG = "CONFIG"
    ABSTRACT = "ABSTRACT"
    WHATIF = "WHATIF"
    STUDY = "STUDY"
    STATE = "STATE"
    CONFIRM = "CONFIRM"
    REJECT = "REJECT"
    DEFER = "DEFER"
    MONITOR = "MONITOR"
    DIGEST = "DIGEST"


class RequestState(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class ToolSpec(_Model):
    """One row of the §9.3 table."""

    name: str
    tier: Tier
    description: str
    roles: tuple[str, ...]
    delegation: Literal["none", "study", "release"] = "none"
    limit: int
    per: Literal["hour", "day"] = "hour"
    output_class: ClassLabel = D1


# ------------------------------------------------------------------------------------------------ tool table (§9.3)
# Descriptions are declarative (HER-8 lint: no imperative instructions to the model, no URLs, no invisible Unicode).
FRONTDOOR_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="tb.submit_request",
        tier=Tier.T0,
        description=(
            "Creates a typed request in state proposed; nothing runs until the sender confirms it. Types: FEAS (site "
            "feasibility: how many local patients meet a study's criteria over a look-back such as lookback=36m), "
            "SCREEN (candidate list for a study), ASK (protocol question), QFILL, MATCH, REPORT and others. Local "
            "patient counts come only from a confirmed FEAS request."
        ),
        roles=("staff",),
        limit=5,
    ),
    ToolSpec(
        name="tb.status",
        tier=Tier.T1,
        description="Request states, pending gates, due dates and control-rounded pipeline counts.",
        roles=("staff",),
        limit=60,
    ),
    ToolSpec(
        name="tb.ask_protocol",
        tier=Tier.T0,
        description="Protocol answer with section citations, or a not-stated result.",
        roles=("staff",),
        delegation="study",
        limit=30,
    ),
    ToolSpec(
        name="tb.registry_search",
        tier=Tier.T0,
        description="Search of the local public trial registry index (public trial records); it holds no local "
        "patient counts and no site rulesets.",
        roles=("staff",),
        limit=60,
        output_class=D0,
    ),
    ToolSpec(
        name="tb.atlas_describe",
        tier=Tier.T1,
        description="Data coverage, freshness, data-quality scorecard and computability rows, rounded.",
        roles=("steward", "research_office", "admin"),
        limit=30,
    ),
    ToolSpec(
        name="tb.aggregate_query",
        tier=Tier.T1,
        description="Catalogue metrics as a control-rounded table with suppression marks and an accountant entry.",
        roles=("research_office", "pi", "crc"),
        limit=20,
    ),
    ToolSpec(
        name="tb.resend_released_file",
        tier=Tier.T0,
        description="Resends an already released file to the requester's directory address through the outbox.",
        roles=("staff",),
        delegation="release",
        limit=10,
        per="day",
    ),
    ToolSpec(
        name="tb.ops_read",
        tier=Tier.T0,
        description="Operations summaries: health, passes, queues, bench, eval, denials, budgets and changes.",
        roles=("admin",),
        limit=120,
    ),
)
TOOL_NAMES: tuple[str, ...] = tuple(t.name for t in FRONTDOOR_TOOLS)


def tool_spec(name: str) -> ToolSpec:
    for t in FRONTDOOR_TOOLS:
        if t.name == name:
            return t
    raise KeyError(name)


# ------------------------------------------------------------------------------------------------ identity (§9.4)
class IdentityAssertion(_Model):
    """Claims of the relay's ES256 identity assertion. ``msg`` is the message hash; ``conv`` binds the session."""

    sub: str = Field(min_length=1)
    channel: Literal["email", "teams", "line", "admin_tui"]
    conv: str = Field(min_length=1)
    msg: str = Field(min_length=1)
    aud: str
    iat: int
    exp: int


# ------------------------------------------------------------------------------------------------ inputs
def _no_identifier(value: str) -> str:
    if RELAY_TOKEN.match(value):
        return value
    for shape in _IDENTIFIER_SHAPES:
        if shape.search(value):
            raise ValueError("identifier patterns are not accepted; use the relay token (HER-11)")
    return value


class SubmitRequestIn(_Model):
    type: RequestType
    study: str | None = Field(default=None, description="study code or NEW")
    params: dict[str, str | int] = Field(default_factory=dict)
    language: Literal["zh-TW", "en", "ja", "mixed"] = "en"

    @field_validator("study")
    @classmethod
    def _study(cls, v: str | None) -> str | None:
        if v is not None and not _STUDY.match(v):
            raise ValueError("study must be NEW or a study code (1-16 upper-case letters, digits, '-' or '_')")
        return v

    @field_validator("params")
    @classmethod
    def _params(cls, v: dict[str, str | int]) -> dict[str, str | int]:
        if len(v) > 12:
            raise ValueError("at most 12 parameters")
        for k, val in v.items():
            if not _PARAM_KEY.match(k):
                raise ValueError(f"invalid parameter name {k!r}")
            if isinstance(val, str):
                if len(val) > 64:
                    raise ValueError(f"parameter {k} longer than 64 characters")
                _no_identifier(val)
        return v


class StatusIn(_Model):
    ticket_id: str | None = Field(default=None, max_length=40)
    study: str | None = Field(default=None, max_length=16)


class AskProtocolIn(_Model):
    study: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,15}$")
    question: str = Field(min_length=1, max_length=500)


class RegistrySearchIn(_Model):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=20)


class AtlasDescribeIn(_Model):
    domain: str | None = Field(default=None, max_length=40)


class AggregateQueryIn(_Model):
    metric: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    breakdown: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,31}$")
    study: str | None = Field(default=None, pattern=r"^[A-Z0-9][A-Z0-9_-]{0,15}$")


class ResendIn(_Model):
    release_id: str = Field(min_length=1, max_length=64)


OpsPanel = Literal["health", "passes", "queues", "bench", "eval", "denials", "budgets", "changes"]


class OpsReadIn(_Model):
    panel: OpsPanel


# ------------------------------------------------------------------------------------------------ outputs
Count = int | str  # control-rounded: an integer, or a suppression mark such as "<5"


class SubmitRequestOut(_Model):
    ticket_id: str
    state: Literal["proposed"] = "proposed"
    commands: list[str]
    restatement: str
    confirm_instruction: str
    expires_at: datetime


class StatusItem(_Model):
    ticket_id: str
    type: RequestType
    state: RequestState
    study: str | None = None
    next_gate: str | None = None
    due: str | None = None


class StatusOut(_Model):
    items: list[StatusItem]
    counts: dict[str, Count] = Field(default_factory=dict)


class AskProtocolOut(_Model):
    answer: str | None
    citations: list[str]
    not_stated: bool


class RegistryRecord(_Model):
    nct_id: str
    title: str
    status: str
    phases: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)


class RegistrySearchOut(_Model):
    records: list[RegistryRecord]


class AtlasRow(_Model):
    domain: str
    coverage_pct: int | None
    freshness_days: int | None
    dq_status: Literal["green", "amber", "red", "unknown"]
    computable: bool


class AtlasDescribeOut(_Model):
    snapshot: str | None
    rows: list[AtlasRow]


class AggregateRow(_Model):
    key: str
    value: Count
    suppressed: bool


class AggregateQueryOut(_Model):
    metric: str
    breakdown: str | None
    rows: list[AggregateRow]
    data_cut: str
    accountant_entry_id: str


class ResendOut(_Model):
    status: Literal["sent", "refused"]
    reason: str | None = None


class OpsRow(_Model):
    key: str
    value: str


class OpsReadOut(_Model):
    panel: OpsPanel
    rows: list[OpsRow]


TOOL_MODELS: dict[str, tuple[type[_Model], type[_Model]]] = {
    "tb.submit_request": (SubmitRequestIn, SubmitRequestOut),
    "tb.status": (StatusIn, StatusOut),
    "tb.ask_protocol": (AskProtocolIn, AskProtocolOut),
    "tb.registry_search": (RegistrySearchIn, RegistrySearchOut),
    "tb.atlas_describe": (AtlasDescribeIn, AtlasDescribeOut),
    "tb.aggregate_query": (AggregateQueryIn, AggregateQueryOut),
    "tb.resend_released_file": (ResendIn, ResendOut),
    "tb.ops_read": (OpsReadIn, OpsReadOut),
}


class FrontdoorAuditEvent(_Model):
    """HER-14: user, tool, arguments hash, decision, result size (never arguments or results themselves)."""

    user: str
    tool: str
    args_sha256: str
    decision: Literal["intent", "allow", "refuse"]
    reason: str | None = None
    result_size: int = 0
    conv: str | None = None
    channel: str | None = None


__all__ = [
    "ASSERTION_MAX_TTL_S",
    "AUDIENCE",
    "FRONTDOOR_TOOLS",
    "RELAY_TOKEN",
    "SCHEMA_VERSION",
    "SERVER_NAME",
    "TOOL_MODELS",
    "TOOL_NAMES",
    "AggregateQueryIn",
    "AggregateQueryOut",
    "AggregateRow",
    "AskProtocolIn",
    "AskProtocolOut",
    "AtlasDescribeIn",
    "AtlasDescribeOut",
    "AtlasRow",
    "Count",
    "FrontdoorAuditEvent",
    "IdentityAssertion",
    "OpsReadIn",
    "OpsReadOut",
    "OpsRow",
    "RegistryRecord",
    "RegistrySearchIn",
    "RegistrySearchOut",
    "RequestState",
    "RequestType",
    "ResendIn",
    "ResendOut",
    "StatusIn",
    "StatusItem",
    "StatusOut",
    "SubmitRequestIn",
    "SubmitRequestOut",
    "Tier",
    "ToolSpec",
    "tool_spec",
]
