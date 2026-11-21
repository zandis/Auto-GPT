"""Carry a published feed and the site's tagged rule approvals into per-generation SCREEN records."""

from __future__ import annotations

import fcntl
import hashlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from criteria_compiler.repo import RulesetRepo
from lake.flatten import BASIS
from tb_common.authz import allowed, known_senders, norm
from tb_common.flags import Flags
from tb_common.generation import Generation
from tb_common.ruleset import Ruleset, RulesetNotApproved, list_rulesets, load_approved
from tb_common.screening_inputs import (
    RESTORE_FLAG,
    RestoreClearance,
    RowReview,
    ScreeningInputs,
    ScreeningRefused,
    ScreeningScope,
    ScreeningUse,
    clearance_path,
    cleared_record,
    lake_resource_key,
    record_path,
    release_id,
    rule_digest,
)
from tb_common.study_manifest import load_json
from tb_contracts import IngestReport
from tb_contracts.landing import PublishGateRecord

from adapter.mapping.engine import MAPPING_VERSION
from adapter.ndjson import read_type

if TYPE_CHECKING:
    from tb_common.config import Config


def _write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        try:
            tmp.write(body)
            tmp.flush()
            os.fsync(tmp.fileno())
            os.replace(tmp.name, path)
        finally:
            Path(tmp.name).unlink(missing_ok=True)


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


def _previous_rows(
    root: Path, base: Path | None, grant: RestoreClearance, study: str, version: str, digest: str
) -> dict[str, str]:
    """Only an individually cleared record of the actual merge base can supply carried row reviews."""
    if base is None:
        raise ScreeningRefused()
    previous = IngestReport.model_validate_json((base / "ingest_report.json").read_bytes())
    built = previous.lake
    if not previous.passed or previous.held or previous.source == "fhir_bulk" or not built or not built.generation:
        raise ScreeningRefused()
    if built.snapshot != base.name:
        raise ScreeningRefused()
    raw = record_path(root, built.generation, study, version).read_bytes()
    record = cleared_record(raw, digest, grant.model_dump_json().encode())
    if (record.use.generation, record.use.ruleset, record.use.rule_version) != (built.generation, study, version):
        raise ScreeningRefused()
    return {row.key: row.owner_rule_stamp for row in record.rows if row.source == "lake"}


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
) -> None:
    """A new passed night, using only the rules already approved by the site and their default screening use."""
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
    repo = RulesetRepo(repo_dir)
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
            events = flags.events(RESTORE_FLAG, limit=2)
            if len(events) != 1 or events[0]["kind"] != "seed":
                raise ScreeningRefused()
            if not path.exists():
                fresh = RestoreClearance(site=site.id, clearance_id=release, state="released", accepted_records=[])
                _write(path, fresh.model_dump_json().encode())
            _write(enrolled, release.encode())
            ticket.unlink()
        grant = RestoreClearance.model_validate(load_json(path.read_bytes()))
        if grant.site != site.id or grant.clearance_id != release or grant.state != "released":
            raise ScreeningRefused()
        accepted = set(grant.accepted_records)
        for study in list_rulesets(repo_dir):
            try:
                rule = load_approved(repo_dir, study)
            except RulesetNotApproved:
                continue
            target = record_path(root, generation, study, rule.version)
            if target.exists():
                continue  # A retry cannot reinstate an individually revoked record.
            prefix = study + "/"
            files = repo.files(f"refs/tags/{study}/v{rule.version}", prefix)
            tagged = Ruleset.from_files({p.removeprefix(prefix): b for p, b in files.items()})
            digest = rule_digest(tagged)
            if digest != rule_digest(rule):
                raise ScreeningRefused()
            sc, routing = rule.manifest.scopes.screen, rule.manifest.routing
            if not sc or not routing or (not sc.practitioners and rule.manifest.kind != "cohort"):
                continue
            senders = sorted(who for who in known_senders(cfg.settings) if allowed(cfg.settings, "SCREEN", who))
            uses = []
            for who in senders:
                list_to = sorted(set(routing.list_to or []))
                if not list_to and rule.manifest.kind == "cohort":
                    list_to = [who]
                if list_to:
                    uses.append(
                        ScreeningUse(
                            site=site.id,
                            clearance_id=release,
                            ruleset=study,
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
            if not uses:
                continue
            prior = _previous_rows(root, base, grant, study, rule.version, digest) if carried else {}
            if not carried.issubset(prior):
                raise ScreeningRefused()
            rows = [
                RowReview(
                    source="lake",
                    key=key,
                    generation=generation,
                    owner_rule_stamp=prior[key] if key in carried else stamp,
                    review_tag="released",
                )
                for key in keys
            ]
            record = ScreeningInputs(
                use=uses[0],
                additional_uses=uses[1:],
                rows=rows,
                inventory={"lake": keys, "omop": [], "derived": []},
                accepted_digest=digest,
                trusted_digest=digest,
                holds_released=True,
            )
            body = record.model_dump_json().encode()
            accepted.add(hashlib.sha256(body).hexdigest())
            # Install clearance first. A crash before the atomic record write cannot make it readable.
            _write(path, grant.model_copy(update={"accepted_records": sorted(accepted)}).model_dump_json().encode())
            _write(target, body)
