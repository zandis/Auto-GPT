"""Admission of a generation's pre-merge row inventory and the site's approved screening use.

The owner supplies opaque row keys and stamps. The inventory lists every expected key in each
store, including an explicit empty list for a store with zero rows. Preserve individual row
reviews until admission: merging duplicate keys first could discard the held copy.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from tb_common.generation import Generation
from tb_common.ruleset import Ruleset
from tb_common.study_manifest import dumps, load_json

REFUSAL = "screen.inputs_refused"
Source = Literal["lake", "omop", "derived"]
Text = Annotated[str, StringConstraints(pattern=r"\S")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ScreeningRefused(ValueError):
    def __init__(self) -> None:
        super().__init__(REFUSAL)


class _Record(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class RowReview(_Record):
    source: Source
    key: Text
    generation: Text
    owner_rule_stamp: Text
    review_tag: Literal["released", "held", "needs_review"]


class ScreeningScope(_Record):
    # Explicit null means the site's whole-hospital selection. A missing field is invalid.
    practitioners: list[Text] | None
    departments: list[Text]
    window_days: int = Field(gt=0)
    recent_months: int = Field(gt=0)


class ScreeningUse(_Record):
    clearance_id: Text
    site: Text
    generation: Text
    ruleset: Text
    rule_version: Text
    list_to: list[Text] = Field(min_length=1)
    referral_to: dict[Text, Text]
    aggregate_to: list[Text]
    scope: ScreeningScope


class ScreeningInputs(_Record):
    use: ScreeningUse
    inventory: dict[Source, list[Text]]
    rows: list[RowReview]
    holds_released: bool
    trusted_digest: Digest
    accepted_digest: Digest


class RestoreClearance(_Record):
    """Positive site clearance from outside the database, replaced or revoked on restore."""

    site: Text
    clearance_id: Text
    state: Literal["released", "held"]
    accepted_records: list[Digest]


def rule_digest(rule: Ruleset) -> str:
    """Hash the exact loaded content the job uses, including its site settings and decisions."""
    content = {
        "manifest": rule.manifest.model_dump(mode="json", by_alias=True),
        "criteria": [c.model_dump(mode="json", by_alias=True) for c in rule.criteria],
        "valuesets": rule.valuesets,
        "cql": rule.cql,
        "elm": rule.elm,
        "sql": rule.sql,
    }
    return hashlib.sha256(dumps(content)).hexdigest()


def admit_screening_inputs(
    record_bytes: bytes,
    use: ScreeningUse,
    digest: str,
    clearance_bytes: bytes,
    audit: Callable[[str], Mapping[str, object]],
) -> tuple[str, str]:
    """Return the generation and rule version only after all evidence agrees and the audit succeeds."""
    try:
        record = ScreeningInputs.model_validate(load_json(record_bytes))
        clearance = RestoreClearance.model_validate(load_json(clearance_bytes))
        record_digest = hashlib.sha256(record_bytes).hexdigest()
        generation = Generation.parse(use.generation)
        if (
            not generation.seq
            or str(generation) != use.generation
            or record.use != use
            or use.scope.practitioners == []
            or digest != record.trusted_digest
            or digest != record.accepted_digest
            or record.holds_released is not True
            or clearance.state != "released"
            or clearance.site != use.site
            or clearance.clearance_id != use.clearance_id
            or record_digest not in clearance.accepted_records
            or set(record.inventory) != {"lake", "omop", "derived"}
        ):
            raise ScreeningRefused()
        expected = {(source, key) for source, keys in record.inventory.items() for key in keys}
        if len(expected) != sum(map(len, record.inventory.values())):
            raise ScreeningRefused()
        for row in record.rows:
            if row.generation != use.generation or row.review_tag != "released" or not row.owner_rule_stamp.strip():
                raise ScreeningRefused()
            expected.remove((row.source, row.key))  # also refuses extra and duplicate rows
        if expected:
            raise ScreeningRefused()
        if audit(record_digest).get("input_sha") != record_digest:
            raise ScreeningRefused()
    except ScreeningRefused:
        raise
    except Exception as exc:
        raise ScreeningRefused() from exc
    return use.generation, use.rule_version
