"""Data model of the filter-first cascade (spec v4 §4.5, CAS-1 … CAS-20; §6.9 run manifest ``cascade`` block).

Everything here is patient level and therefore D3 (§7.1): the per-patient traces, the per-pair outcomes and the
review queue. Aggregates derived from them are D3 until the privacy accountant lowers them (§7.8,
:func:`tb_common.policy.classes.lower`).

Status vocabulary, from the eligibility perspective (v1 D-25): ``pass`` = the criterion does not stand in the way;
``fail`` = it excludes; ``unknown`` = undecided (``unknown_kind`` says whether data are missing, ``data_gap``, or the
judgement abstained, disagreed or did not verify, ``uncertain``; CAS-17); ``pending_human`` = a ``human`` criterion
waiting for S5.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

Status = Literal["pass", "fail", "unknown", "pending_human"]
UnknownKind = Literal["data_gap", "uncertain"]
Stage = Literal["S0", "S1", "S2", "S2b", "S3", "S4", "S5"]
Tier = Literal["strong", "potential:data_gap", "potential:uncertain", "watchlist", "excluded", "out_of_scope"]
Semantics = Literal["v1", "affirmative"]

STAGES: tuple[Stage, ...] = ("S0", "S1", "S2", "S2b", "S3", "S4", "S5")
TIERS: tuple[Tier, ...] = ("strong", "potential:data_gap", "potential:uncertain", "watchlist", "excluded")
#: recall-ledger stratum per excluding stage (§10.14 table; values of ``tb_contracts.recall.Stratum``)
STRATUM_S1 = "S1-affirmative"
STRATUM_INDEX = "S2-absence(index)"
STRATUM_ZERO_HIT = "S2-zero_hit(note)"
STRATUM_S2B = "S2b-below"
STRATUM_S3 = "S3-not_met"


@dataclass
class Outcome:
    """One patient–criterion pair after the stage that decided it."""

    criterion_id: str
    status: Status
    stage: Stage
    hard: bool = False  # a fail that may exclude (CAS-7: verified, assertion-agreeing, not abstained)
    unknown_kind: UnknownKind | None = None
    stratum: str | None = None  # recall stratum when the pair excluded the patient
    evidence: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    rescue: dict[str, Any] | None = None  # CAS-18: rescuing stage and sentence hash


@dataclass
class PatientTrace:
    pid: str
    index_date: date
    department: str | None = None
    in_scope: bool = True
    scope_reason: str = ""
    contact_ok: bool = True
    outcomes: dict[str, Outcome] = field(default_factory=dict)
    exit_stage: Stage | None = None  # stage at which the patient left the cascade (excluded)
    exit_criterion: str | None = None
    unprocessed: bool = False  # budget ran out before S3 finished (CAS-4, SAFE-13: never an exclusion)
    sampled: bool = True  # CAS-8: in a feasibility run S3/S4 see only a stratified sample
    sample_stratum: str = ""  # CAS-8 stratum: S2/S2b outcome signature × department
    tier: Tier = "out_of_scope"
    review: dict[str, Any] | None = None  # S5 decision

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["index_date"] = self.index_date.isoformat()
        return d


@dataclass
class StageLog:
    """CAS-1: patients and patient–criterion pairs entering and leaving one stage, with the class label of the stage
    output and the hash of the IR the stage evaluated."""

    stage: Stage
    patients_in: int
    patients_out: int
    pairs_in: int
    pairs_out: int
    data_class: str
    ir_hash: str
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def excluded(self) -> int:
        return self.patients_in - self.patients_out


@dataclass
class ReviewItem:
    """One S5 queue item: a candidate for the PI decision sheet (D3)."""

    pid: str
    tier: Tier
    pending_human: list[str]
    uncertain: list[str]
    data_gap: list[str]
    department: str | None = None


@dataclass
class CascadeMetrics:
    """CAS-7 manifest metrics."""

    n_scope: int = 0
    n_after: dict[str, int] = field(default_factory=dict)
    note_criteria: int = 0
    pairs_s2_hit: int = 0
    pairs_s2_zero_hit: int = 0
    pairs_s2_no_notes: int = 0
    pairs_s2b_above: int = 0
    pairs_s2b_below: int = 0
    pairs_judged: dict[str, int] = field(default_factory=lambda: {"S3": 0, "S4": 0})
    tokens_in: int = 0
    tokens_out: int = 0
    cache_hits: int = 0
    llm_share: float = 0.0
    unprocessed: int = 0
    rescued: int = 0
    s2b_embed_batches: int = 0
    sampled_patients: int = 0
    gateway_refusals: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "STAGES",
    "STRATUM_INDEX",
    "STRATUM_S1",
    "STRATUM_S2B",
    "STRATUM_S3",
    "STRATUM_ZERO_HIT",
    "TIERS",
    "CascadeMetrics",
    "Outcome",
    "PatientTrace",
    "ReviewItem",
    "Semantics",
    "Stage",
    "StageLog",
    "Status",
    "Tier",
    "UnknownKind",
]
