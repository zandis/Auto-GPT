"""Recall ledger and certificate contracts (spec v4 §6.7, §10.14 SAFE; sprint task S1-12).

* :class:`RecallCell` — the ledger key: (canonical criterion hash, stratum), pooled across studies and months.
* :class:`RecallObservation` — one adjudicated audit draw of a cell (pseudonymous pid hash, so D3).
* :class:`RecallCertificate` — the study certificate for one run (aggregates only, so D1). It carries per-cell
  anytime bounds at the pre-registered α_c, per-stratum sums, and **both** labelled known-positive lines.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tb_contracts.dataclass import DataClass


class Stratum(StrEnum):
    """The stage that excluded the patient–criterion pair (§10.14 strata)."""

    S1_AFFIRMATIVE = "S1-affirmative"
    S2_ABSENCE_INDEX = "S2-absence(index)"
    S2_ZERO_HIT_NOTE = "S2-zero_hit(note)"
    S2B_BELOW = "S2b-below"
    S3_NOT_MET = "S3-not_met"


class KnownPositiveLineKind(StrEnum):
    HISTORICAL_ENROLLEES = "historical_enrollees"
    BLINDED_CHART_REVIEW = "blinded_chart_review"


LINE_LABELS: dict[KnownPositiveLineKind, str] = {
    KnownPositiveLineKind.HISTORICAL_ENROLLEES: "historical enrollees; biased: found by the previous process",
    KnownPositiveLineKind.BLINDED_CHART_REVIEW: "blinded chart review; unbiased population; r = {r}",
}

#: line B is quoted only from this many blinded positives on (§10.14 quoting rule)
LINE_B_MIN_R = 30


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecallCell(_Model):
    canonical_hash: str = Field(min_length=1, description="hash of the canonical criterion (criterion library)")
    stratum: Stratum
    series: int = Field(default=1, ge=1, description="a G5 change or re-promotion starts a new series (SAFE-8)")
    criterion_type: str | None = None
    data_class: DataClass = DataClass.D1

    @property
    def key(self) -> str:
        return f"{self.canonical_hash}|{self.stratum.value}|{self.series}"


class RecallObservation(_Model):
    """One audit draw. ``y`` is what enters the sequence; with uniform weighting (the only one implemented, §6.7)
    it equals ``label``."""

    canonical_hash: str = Field(min_length=1)
    stratum: Stratum
    series: int = Field(default=1, ge=1)
    draw_id: str = Field(min_length=1, description="unique per cell series; makes appends idempotent")
    pid_hash: str = Field(min_length=1)
    study_id: str
    run_id: str
    draw_prob: float = Field(gt=0.0, le=1.0)
    weight: float = Field(gt=0.0)
    label: Literal[0, 1] = Field(description="1 = wrongly excluded (in fact a candidate)")
    route: Literal["s4", "human_blinded", "both"]
    observed_at: datetime
    weighting: Literal["uniform"] = "uniform"
    data_class: DataClass = DataClass.D3

    @property
    def y(self) -> float:
        return float(self.label)

    @field_validator("observed_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("observed_at must carry an offset")
        return v


class CsStateRef(_Model):
    ref: str
    sha: str
    n: int = Field(ge=0)


class CellBound(_Model):
    canonical_hash: str
    stage: Stratum
    series: int
    excluded: int = Field(ge=0)
    alpha_c: float = Field(gt=0.0, lt=1.0)
    ledger_sampled: int = Field(ge=0)
    found: int = Field(ge=0)
    upper_cs: float = Field(ge=0.0, le=1.0)
    upper_cp_single_look: float = Field(ge=0.0, le=1.0, description="for information only; valid for one look")
    weighting: Literal["uniform"] = "uniform"
    cs_state: CsStateRef
    observation_seq_sha: str
    looks: int = Field(ge=0)
    first_look: str | None = None


class StratumBound(_Model):
    stage: Stratum
    excluded: int = Field(ge=0)
    ledger_sampled: int = Field(ge=0)
    found: int = Field(ge=0)
    missed_point: float = Field(ge=0.0)
    missed_upper: float = Field(ge=0.0)
    per_1000_excluded_upper: float = Field(ge=0.0)


class KnownPositiveLine(_Model):
    line: KnownPositiveLineKind
    biased: bool
    label: str
    population: str
    r: int = Field(ge=0)
    missed: int = Field(ge=0)
    recall_lower: float = Field(ge=0.0, le=1.0)
    method: str
    recall_lower_single_look_info: float | None = None

    @model_validator(mode="after")
    def _consistent(self) -> KnownPositiveLine:
        if self.biased != (self.line is KnownPositiveLineKind.HISTORICAL_ENROLLEES):
            raise ValueError("line H is biased and line B is not (§10.14)")
        if self.missed > self.r:
            raise ValueError("missed cannot exceed r")
        return self


class RecallCertificate(_Model):
    schema_version: Literal["3.0.0"] = "3.0.0"
    rc_id: str
    study_id: str
    run_id: str
    ruleset: str
    period: str
    alpha: float = Field(gt=0.0, lt=1.0)
    k_cells: int = Field(ge=1)
    series: int = Field(ge=1)
    registered_at: str
    method: str
    cells: list[CellBound]
    strata: list[StratumBound]
    missed_point: float = Field(ge=0.0)
    missed_upper: float = Field(ge=0.0)
    per_1000_excluded_upper: float = Field(ge=0.0)
    known_positive: tuple[KnownPositiveLine, KnownPositiveLine]
    quoted_line: KnownPositiveLineKind
    demotions: list[str] = Field(default_factory=list, description="demotions in force (SAFE-15)")
    statement: dict[str, str]
    seed: int | None = None
    lineage_id: str | None = None
    data_class: DataClass = DataClass.D1

    @model_validator(mode="after")
    def _two_lines(self) -> RecallCertificate:
        kinds = [kp.line for kp in self.known_positive]
        if kinds != [KnownPositiveLineKind.HISTORICAL_ENROLLEES, KnownPositiveLineKind.BLINDED_CHART_REVIEW]:
            raise ValueError("a certificate carries line H then line B (§10.14)")
        if self.data_class is not DataClass.D1:
            raise ValueError("a recall certificate is an aggregate D1 object")
        alpha_sum = sum(c.alpha_c for c in self.cells)
        if self.cells and alpha_sum > self.alpha * (1 + 1e-9):
            raise ValueError("pre-registered α_c must not sum above α")
        return self


__all__ = [
    "LINE_B_MIN_R",
    "LINE_LABELS",
    "CellBound",
    "CsStateRef",
    "KnownPositiveLine",
    "KnownPositiveLineKind",
    "RecallCell",
    "RecallCertificate",
    "RecallObservation",
    "Stratum",
    "StratumBound",
]
