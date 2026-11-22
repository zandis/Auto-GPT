"""Carry a published feed and the site's tagged rule approvals into per-generation SCREEN records."""

from __future__ import annotations

import fcntl
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lake.flatten import BASIS
from tb_common.flags import Flags
from tb_common.generation import Generation
from tb_common.ruleset import RulesetNotApproved, list_rulesets, load_approved
from tb_common.screening_inputs import (
    RESTORE_FLAG,
    PublishedRows,
    RestoreClearance,
    RowReview,
    ScreeningRefused,
    clearance_path,
    database_mark,
    issue_screening_record,
    lake_resource_key,
    published_path,
    release_id,
    write_durably,
)
from tb_common.study_manifest import load_json
from tb_contracts import IngestReport
from tb_contracts.landing import PublishGateRecord

from adapter.mapping.engine import MAPPING_VERSION
from adapter.ndjson import read_type

if TYPE_CHECKING:
    from tb_common.config import Config


def first_install(secrets: Path) -> None:
    """Only the ceremony that created the site key can enroll the initial database release."""
    with (secrets / "screening-first-install").open("x") as ticket:
        ticket.write("pending\n")


class MappedReviews:
    """Observe every mapped resource before the snapshot merge discards duplicate IDs."""

    def __init__(self, version: str, static: list[dict[str, Any]]) -> None:
        self.version = version
        self.static = static
        self.held = False
        self.issued: set[str] = set()

    def observe(self, obj: dict[str, Any]) -> None:
        tags = (obj.get("meta") or {}).get("tag") or []
        stamps = [tag.get("code") for tag in tags if tag.get("system") == MAPPING_VERSION]
        if (
            not obj.get("id")
            or obj.get("review_tag", "released") != "released"
            or any(tag.get("system") == BASIS and tag.get("code") != "confirmed" for tag in tags)
            or (stamps != [self.version] and not (not stamps and obj in self.static))
        ):
            self.held = True

    def emitted(self, obj: dict[str, Any]) -> None:
        if not self.held:
            self.issued.add(lake_resource_key(obj["resourceType"], obj))


def _previous_rows(root: Path, base: Path | None, grant: RestoreClearance) -> dict[str, str]:
    """Only the cleared published rows of the actual merge base can supply carried row reviews."""
    if base is None:
        raise ScreeningRefused()
    previous = IngestReport.model_validate_json((base / "ingest_report.json").read_bytes())
    built = previous.lake
    if not previous.passed or previous.held or previous.source == "fhir_bulk" or not built or not built.generation:
        raise ScreeningRefused()
    if built.snapshot != base.name:
        raise ScreeningRefused()
    raw = published_path(root, built.generation).read_bytes()
    rows = PublishedRows.model_validate(load_json(raw))
    if (
        hashlib.sha256(raw).hexdigest() not in grant.accepted_records
        or rows.generation != built.generation
        or rows.clearance_id != grant.clearance_id
        or rows.site != grant.site
        or not rows.holds_released
    ):
        raise ScreeningRefused()
    return {row.key: row.owner_rule_stamp for row in rows.rows if row.source == "lake" and row.review_tag == "released"}


def published_inputs(
    cfg: Config,
    report: IngestReport,
    folder: Path,
    gate: PublishGateRecord,
    mapping_sha: str | None,
    mapped: MappedReviews | None,
    base: Path | None,
    promoted_generation: str | None,
    db_url: str | None = None,
    audit: Any = None,
) -> None:
    """A new passed night: publish its reviewed rows, then issue every approved study's record through gate 4."""
    generation = report.lake.generation if report.lake else promoted_generation
    snapshot = report.snapshot.isoformat()
    if (
        not report.passed
        or report.held
        or not generation
        or gate.outcome == "HOLD"
        or gate.blocking_reasons
        or gate.current_after != snapshot
        or gate.cycle_id != snapshot
    ):
        return
    if (report.lake and report.lake.snapshot != snapshot) or Generation.parse(generation).snapshot != snapshot:
        raise ScreeningRefused()
    if promoted_generation and promoted_generation != generation:
        raise ScreeningRefused()
    flags = Flags(url=db_url)
    release = release_id(flags)
    mode = flags.row("derived.stored_read")
    if mode not in ("on", "off"):
        raise ScreeningRefused()
    # The stored-score builder releases its separate batch; it cannot be attested by the adapter.
    if mode == "on":
        return
    root = Path(cfg.env.data_dir)
    repo_dir = cfg.env.rulesets_path
    if not (repo_dir / ".git").is_dir():
        return
    if not mapping_sha or mapped is None or mapped.held:
        # An external bulk feed cannot issue the adapter's own mapping stamps.
        raise ScreeningRefused()
    keys = [
        lake_resource_key(path.stem, row)
        for path in sorted(folder.glob("*.ndjson"))
        for row in read_type(folder, path.stem)
    ]
    carried = set(keys) - mapped.issued
    stamp = f"{mapping_sha}/{mapped.version}/{gate.gate_id}"
    site = cfg.settings.site
    secrets = Path(cfg.env.secrets_dir)
    path = clearance_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    enrolled = path.with_name("enrolled")
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ticket = secrets / "screening-first-install"
        if ticket.is_file() and not enrolled.exists():
            # Enrollment needs a database whose restore flag was only ever seeded, never set.
            events = flags.events(RESTORE_FLAG)
            if len(events) != 1 or events[0]["kind"] != "seed":
                raise ScreeningRefused()
            if not path.exists():
                fresh = RestoreClearance(
                    site=site.id,
                    clearance_id=release,
                    state="released",
                    accepted_records=[],
                    database=database_mark(db_url),
                )
                write_durably(path, fresh.model_dump_json().encode())
            write_durably(enrolled, release.encode())
            ticket.unlink()
        grant = RestoreClearance.model_validate(load_json(path.read_bytes()))
        if (
            grant.site != site.id
            or grant.clearance_id != release
            or grant.state != "released"
            or grant.database != database_mark(db_url)
        ):
            raise ScreeningRefused()
        prior = _previous_rows(root, base, grant) if carried else {}
        if not carried.issubset(prior):
            raise ScreeningRefused()
        target = published_path(root, generation)
        if not target.exists():  # A retry cannot reinstate individually revoked rows.
            published = PublishedRows(
                site=site.id,
                clearance_id=release,
                generation=generation,
                inventory={"lake": keys, "omop": [], "derived": []},
                rows=[
                    RowReview(
                        source="lake",
                        key=key,
                        generation=generation,
                        owner_rule_stamp=prior[key] if key in carried else stamp,
                        review_tag="released",
                    )
                    for key in keys
                ],
                holds_released=True,
            )
            body = published.model_dump_json().encode()
            accepted = sorted({*grant.accepted_records, hashlib.sha256(body).hexdigest()})
            # Clearance first. A crash before the atomic write cannot make the rows readable.
            write_durably(path, grant.model_copy(update={"accepted_records": accepted}).model_dump_json().encode())
            write_durably(target, body)
    # Every approved study's record of this generation, through gate 4's one writer (a day's approval calls it too).
    for study in list_rulesets(repo_dir):
        try:
            load_approved(repo_dir, study)
        except RulesetNotApproved:
            continue
        issue_screening_record(
            cfg.settings,
            root=root,
            repo_dir=repo_dir,
            generation=generation,
            study=study,
            version=None,
            db_url=db_url,
            audit=audit,
            actor="adapter",
        )
