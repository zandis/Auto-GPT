"""Admission of a generation's pre-merge row inventory and the site's approved screening use.

The owner supplies opaque row keys and stamps. The inventory lists every expected key in each
store, including an explicit empty list for a store with zero rows. Preserve individual row
reviews until admission: merging duplicate keys first could discard the held copy.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from tb_common.db import Database
from tb_common.derived_store import FLAG as DERIVED_FLAG
from tb_common.flags import Flags
from tb_common.generation import Generation
from tb_common.ruleset import Ruleset, load_approved
from tb_common.study_manifest import dumps, load_json

if TYPE_CHECKING:
    from tb_contracts import Settings

RESTORE_FLAG = "screening.after_restore"
RECORD_OPTION = "screening_record_sha"
REFUSAL = "screen.inputs_refused"
ISSUED = "screen.inputs_issued"
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
    # The database this grant was given on (:func:`database_mark`). A replaced database never inherits it.
    database: Text


class PublishedRows(_Record):
    """One passed night's reviewed rows of a generation. Every study's record of that generation is issued from it."""

    site: Text
    clearance_id: Text
    generation: Text
    inventory: dict[Source, list[Text]]
    rows: list[RowReview]
    holds_released: bool


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


def published_path(root: Path, generation: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", generation):
        raise ScreeningRefused()
    return root / "screening-inputs" / generation / "published-rows.json"


def database_mark(url: str | None) -> str:
    """The trial database's own identity: the object id of the table that holds the restore flag's history.

    A restore drops and re-creates that table, so a grant given before it is refused afterwards, even when the
    restore's audited hold was never written. Only a fresh grant after review makes the box list again.
    No ``url``: the trial database the flags read (``TB_DB_URL``)."""
    from tb_common.db import ENV

    url = url or os.environ.get(ENV)
    if not url:
        raise ScreeningRefused()
    with Database.connect(url, "app") as db:
        oid = db.fetchval("SELECT to_regclass(?)::oid::text", (f'"{db.schema}".flag_event',))
        name = db.fetchval("SELECT current_database()")
    if not oid or not name:
        raise ScreeningRefused()
    return f"{name}/{oid}"


def write_durably(path: Path, body: bytes) -> None:
    """Replace ``path`` atomically, synced to disk before the rename."""
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        try:
            tmp.write(body)
            tmp.flush()
            os.fsync(tmp.fileno())
            os.replace(tmp.name, path)
        finally:
            Path(tmp.name).unlink(missing_ok=True)


def _live_grant(root: Path, site: str, flags: Flags, url: str | None) -> RestoreClearance:
    grant = RestoreClearance.model_validate(load_json(clearance_path(root).read_bytes()))
    if (
        grant.site != site
        or grant.clearance_id != release_id(flags)
        or grant.state != "released"
        or grant.database != database_mark(url)
    ):
        raise ScreeningRefused()
    return grant


def screening_uses(settings: Settings, rule: Ruleset, generation: str, release: str) -> list[ScreeningUse]:
    """The study's default screening uses: one per person who may ask for its list, with the manifest's own scope."""
    from tb_common.authz import allowed, known_senders, norm

    sc, routing = rule.manifest.scopes.screen, rule.manifest.routing
    if not sc or not routing or (not sc.practitioners and rule.manifest.kind != "cohort"):
        return []
    uses = []
    for who in sorted(w for w in known_senders(settings) if allowed(settings, "SCREEN", w)):
        list_to = sorted(set(routing.list_to or []))
        if not list_to and rule.manifest.kind == "cohort":
            list_to = [who]
        if list_to:
            uses.append(
                ScreeningUse(
                    site=settings.site.id,
                    clearance_id=release,
                    ruleset=rule.id,
                    rule_version=rule.version,
                    generation=generation,
                    list_to=list_to,
                    referral_to=routing.referral_to or {},
                    aggregate_to=sorted({who, *(norm(a) for a in routing.aggregate_to or [])}),
                    stored_read="off",
                    scope=ScreeningScope(
                        practitioners=sc.practitioners or None,
                        departments=[],
                        window_days=sc.appointment_window_days or 180,
                        recent_months=sc.recent_encounter_months or 12,
                    ),
                )
            )
    return uses


def issue_screening_record(
    settings: Settings,
    *,
    root: Path,
    repo_dir: Path,
    generation: str,
    study: str,
    version: str | None,
    db_url: str | None,
    audit: Any,
    actor: str,
) -> str | None:
    """Gate 4's one writer of a study's SCREEN record: the passed night and a day's approval both call it.

    It issues the record of the approved ``version`` (None: the version in force) for ``generation`` from that
    generation's published rows, under the live grant, and audits the issue. The record is readable only after the
    issue is audited. Returns the record's hash, or None when the study has no default screening use. Every refusal
    is audited and raised: no record is issued from rows that were not published."""
    import fcntl

    from tb_common.ruleset import list_rulesets

    where = {"snapshot": generation, "ruleset": study, "ruleset_version": version, "actor": actor}
    try:
        flags = Flags(url=db_url)
        lock_path = clearance_path(root).with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            grant = _live_grant(root, settings.site.id, flags, db_url)
            gen = Generation.parse(generation)
            if not gen.seq or str(gen) != generation or study not in list_rulesets(repo_dir):
                raise ScreeningRefused()
            # Staleness: only the published rows of this very generation, accepted under this grant.
            raw = published_path(root, generation).read_bytes()
            published = PublishedRows.model_validate(load_json(raw))
            if (
                hashlib.sha256(raw).hexdigest() not in grant.accepted_records
                or published.generation != generation
                or published.site != grant.site
                or published.clearance_id != grant.clearance_id
                or published.holds_released is not True
                or any(r.generation != generation or r.review_tag != "released" for r in published.rows)
            ):
                raise ScreeningRefused()
            rule = load_approved(repo_dir, study, version)
            # Tamper: the materialized copy must be exactly the content of its approval tag.
            from criteria_compiler.repo import RulesetRepo

            prefix = study + "/"
            files = RulesetRepo(repo_dir).files(f"refs/tags/{study}/v{rule.version}", prefix)
            tagged = Ruleset.from_files({p.removeprefix(prefix): b for p, b in files.items()})
            digest = rule_digest(rule)
            if rule.id != study or rule.manifest.status != "approved" or digest != rule_digest(tagged):
                raise ScreeningRefused()
            where["ruleset_version"] = rule.version
            target = record_path(root, generation, study, rule.version)
            if target.exists():
                return None  # issued already; a retry cannot reinstate an individually revoked record
            uses = screening_uses(settings, rule, generation, grant.clearance_id)
            if not uses:
                return None
            record = ScreeningInputs(
                use=uses[0],
                additional_uses=uses[1:],
                rows=published.rows,
                inventory=published.inventory,
                accepted_digest=digest,
                trusted_digest=digest,
                holds_released=True,
            )
            body = record.model_dump_json().encode()
            sha = hashlib.sha256(body).hexdigest()
            # Clearance first, then the audit, then the record: a record on disk always has its audited issue.
            accepted = sorted({*grant.accepted_records, sha})
            cleared = grant.model_copy(update={"accepted_records": accepted})
            write_durably(clearance_path(root), cleared.model_dump_json().encode())
            audit.append(
                ISSUED,
                actor=actor,
                ruleset=study,
                ruleset_version=rule.version,
                input_sha=sha,
                snapshot=generation,
                detail={"rule_sha256": digest, "rows_sha256": hashlib.sha256(raw).hexdigest()},
            )
            write_durably(target, body)
            return sha
    except Exception as exc:
        try:
            audit.append(
                REFUSAL,
                actor=actor,
                ruleset=study,
                ruleset_version=where["ruleset_version"],
                snapshot=generation,
                detail={"reason": REFUSAL, "error": type(exc).__name__, "issue": True},
            )
        finally:
            if isinstance(exc, ScreeningRefused):
                raise
            raise ScreeningRefused() from exc


def admit_screening_inputs() -> tuple[str, str]:
    """Authorize the leased SCREEN job using the site's stores, then return its exact generation and version."""
    from criteria_compiler.terminology import resolver
    from orchestrator import derive
    from orchestrator.core import screening_worker
    from orchestrator.rerun import PinnedLake as ReplayLake
    from orchestrator.scenarios.screen import screening_use
    from orchestrator.scheduler import require_open, screen_lifecycle

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
        if screen_lifecycle(job.ruleset, ctx.orch.db.url) not in (None, "open"):
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
        # After a restore the flag history is a new table: the old grant stays refused whatever the hold did.
        if RestoreClearance.model_validate(load_json(clearance)).database != database_mark(ctx.orch.db.url):
            raise ScreeningRefused()
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
    except Exception as exc:
        _audit_refusal(exc)
        if isinstance(exc, ScreeningRefused):
            raise
        raise ScreeningRefused() from exc


def _audit_refusal(exc: BaseException) -> None:
    """Record the worker's refusal in the audit log. The refusal stands whatever the audit write does."""
    import contextlib

    from orchestrator.core import screening_worker

    with contextlib.suppress(Exception):
        ctx = screening_worker()
        if ctx is not None:
            ctx.orch.audit.append(
                REFUSAL,
                job_id=ctx.job.job_id,
                ruleset=ctx.job.ruleset,
                actor="orchestrator",
                detail={"reason": REFUSAL, "error": type(exc).__name__, "admission": True},
            )
