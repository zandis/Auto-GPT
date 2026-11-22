"""Admission of a generation's pre-merge row inventory and the site's approved screening use.

The owner supplies opaque row keys and stamps. The inventory lists every expected key in each
store, including an explicit empty list for a store with zero rows. Preserve individual row
reviews until admission: merging duplicate keys first could discard the held copy.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from tb_common.db import Database
from tb_common.derived_store import FLAG as DERIVED_FLAG
from tb_common.flags import Flags
from tb_common.generation import Generation
from tb_common.ruleset import Ruleset, load_approved
from tb_common.study_manifest import dumps, load_json

RESTORE_FLAG = "screening.after_restore"
RECORD_OPTION = "screening_record_sha"
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
    stored_read: Literal["on", "off"]


class ScreeningInputs(_Record):
    use: ScreeningUse
    additional_uses: list[ScreeningUse] = Field(default_factory=list)
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


def cleared_record(
    record_bytes: bytes,
    digest: str,
    clearance_bytes: bytes,
    use: ScreeningUse | None = None,
) -> ScreeningInputs:
    """Match each reviewed row and the complete use to the separately cleared bytes."""
    try:
        record = ScreeningInputs.model_validate(load_json(record_bytes))
        clearance = RestoreClearance.model_validate(load_json(clearance_bytes))
        record_digest = hashlib.sha256(record_bytes).hexdigest()
        use = use or record.use
        generation = Generation.parse(use.generation)
        if (
            not generation.seq
            or str(generation) != use.generation
            or (record.use != use and use not in record.additional_uses)
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

    except ScreeningRefused:
        raise
    except Exception as exc:
        raise ScreeningRefused() from exc
    return record


def lake_resource_key(kind: str, row: dict[str, Any]) -> str:
    """Bind a review to the complete resource consumed by the builder, including its row identity."""
    content = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return f"{kind}/{row['id']}#{hashlib.sha256(content.encode()).hexdigest()}"


def inventory_hash(keys: Iterable[str]) -> str:
    """Length-prefixed keys in source order, including every copy before a patient merge."""
    digest = hashlib.sha256(b"screening-inventory-v2\0")
    for key in keys:
        encoded = key.encode()
        digest.update(len(encoded).to_bytes(8))
        digest.update(encoded)
    return digest.hexdigest()


def release_id(flags: Flags) -> str:
    events = flags.events(RESTORE_FLAG, limit=1)
    if flags.row(RESTORE_FLAG) != "released" or not events or events[0]["new_value"] != "released":
        raise ScreeningRefused()
    return f"{events[0]['id']}:{events[0]['at']}"


def clearance_path(root: Path) -> Path:
    """Live site authorization, outside both stores replaced by the shipped restore."""
    return root / "screening-inputs" / "screening-clearance.json"


def record_path(root: Path, generation: str, study: str, version: str) -> Path:
    if any(not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", part) for part in (generation, study, version)):
        raise ScreeningRefused()
    return root / "screening-inputs" / generation / study / f"{version}.json"


def admit_screening_inputs() -> tuple[str, str]:
    """Authorize the leased SCREEN job using the site's stores, then return its exact generation and version."""
    from criteria_compiler.terminology import resolver
    from orchestrator import derive
    from orchestrator.core import screening_worker
    from orchestrator.rerun import PinnedLake as ReplayLake
    from orchestrator.scenarios.screen import screening_use
    from orchestrator.scheduler import require_open

    try:
        ctx = screening_worker()
        if ctx is None:
            raise ScreeningRefused()
        job = ctx.job
        if job.type != "SCREEN" or not job.ruleset or ctx.orch.db.get(job.job_id) != job:
            raise ScreeningRefused()
        options = job.options or {}
        lake = ctx.orch.services.lake
        replay = isinstance(lake, ReplayLake)
        if job.snapshot_date is None and (replay or job.ruleset_version or options.get(RECORD_OPTION)):
            raise ScreeningRefused()
        if job.snapshot_date is not None and (not job.ruleset_version or not options.get(RECORD_OPTION)):
            raise ScreeningRefused()
        if isinstance(lake, ReplayLake):
            lake = lake.lake
        resolve = getattr(lake, "generation", None)
        if resolve is None:
            raise ScreeningRefused()
        # Reattach only an existing record whose hash uniquely matches the restored date alias.
        # Resumes still read their saved generation, even when a newer build now serves the date.
        observed = resolve(job.snapshot_date.isoformat() if job.snapshot_date else None, recover=True)
        generation = options.get("lake_generation") if job.snapshot_date is not None else observed
        if not isinstance(generation, str):
            raise ScreeningRefused()
        gen = Generation.parse(generation)
        if (
            not gen.seq
            or str(gen) != generation
            or (job.snapshot_date and gen.snapshot != job.snapshot_date.isoformat())
        ):
            raise ScreeningRefused()
        require_open(job.ruleset, site_url=ctx.orch.db.url)
        # A missing row has the product's default lifecycle. A missing table has lost its history.
        with Database.connect(ctx.orch.db.url, "site") as db:
            state = db.fetchval(
                "SELECT state FROM study_state WHERE ruleset = ? ORDER BY at DESC, id DESC LIMIT 1",
                (job.ruleset.upper(),),
            )
            if state not in (None, "open"):
                raise ScreeningRefused()
        ctx.decision.bind_screen_register(ctx.orch.db.url)
        flags = Flags(url=ctx.orch.db.url)
        mode = flags.row(DERIVED_FLAG)
        if mode not in ("on", "off"):
            raise ScreeningRefused()
        rule = load_approved(
            ctx.rulesets_dir,
            job.ruleset.upper(),
            job.ruleset_version or options.get("version"),
            terminology=resolver.guard(),
            on=ctx.today(),
        )
        if rule.id != job.ruleset.upper() or rule.manifest.status != "approved":
            raise ScreeningRefused()
        use = screening_use(ctx, rule, generation, release_id(flags), "on" if mode == "on" else "off")
        digest = rule_digest(rule)
        path = record_path(Path(ctx.cfg.env.data_dir), use.generation, use.ruleset, use.rule_version)
        raw = path.read_bytes()
        clearance = clearance_path(Path(ctx.cfg.env.data_dir)).read_bytes()
        record = cleared_record(raw, digest, clearance, use)
        record_sha = hashlib.sha256(raw).hexdigest()
        previous = (job.options or {}).get(RECORD_OPTION)
        if job.snapshot_date is not None and previous != record_sha:
            raise ScreeningRefused()
        # This is metadata in the immutable generation itself, read before any patient query is permitted.
        (meta,) = ctx.orch.services.lake.query(
            "SELECT lake_inventory, omop_inventory FROM lake_meta", snapshot=use.generation
        ).to_pylist()
        if meta["lake_inventory"] != inventory_hash(record.inventory["lake"]) or meta[
            "omop_inventory"
        ] != inventory_hash(record.inventory["omop"]):
            raise ScreeningRefused()
        derived_keys = derive.bind_screen_reader(ctx, use.generation, mode)
        if sorted(record.inventory["derived"]) != derived_keys:
            raise ScreeningRefused()
        receipt = ctx.orch.audit.append(
            "screen.inputs_admitted",
            job_id=job.job_id,
            ruleset=rule.id,
            ruleset_version=rule.version,
            input_sha=record_sha,
            snapshot=use.generation,
            detail={"rule_sha256": digest, "stored_read": mode},
        )
        if receipt.get("input_sha") != record_sha or not (
            receipt.get("hash") or (receipt.get("journal") or {}).get("seq")
        ):
            raise ScreeningRefused()
        ctx.screen_admission = (rule, use, record_sha)
        return use.generation, use.rule_version
    except ScreeningRefused:
        raise
    except Exception as exc:
        raise ScreeningRefused() from exc
