"""Carry a published feed and the site's tagged rule approvals into per-generation SCREEN records."""

from __future__ import annotations

import fcntl
import hashlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from criteria_compiler.repo import RulesetRepo
from lake.flatten import basis_of
from tb_common.authz import norm
from tb_common.flags import Flags
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


def _reviews(
    folder: Path, generation: str, gate: PublishGateRecord, mapping: str, static_inputs: list[dict[str, Any]]
) -> list[RowReview]:
    rows = []
    for path in sorted(folder.glob("*.ndjson")):
        for obj in read_type(folder, path.stem):
            stamps = [
                tag["code"] for tag in (obj.get("meta") or {}).get("tag", []) if tag.get("system") == MAPPING_VERSION
            ]
            # The static site Organization is made by the adapter using the same published mapping.
            stamp = stamps[0] if len(stamps) == 1 else mapping if not stamps and obj in static_inputs else None
            if not stamp or not obj.get("id") or obj.get("resourceType") != path.stem or basis_of(obj) == "proposed":
                raise ScreeningRefused()
            review = obj.get("review_tag", "released")
            if review != "released":
                raise ScreeningRefused()
            rows.append(
                RowReview(
                    source="lake",
                    key=f"{path.stem}/{obj['id']}",
                    generation=generation,
                    owner_rule_stamp=f"{mapping}/{stamp}/{gate.gate_id}",
                    review_tag="released",
                )
            )
    if len({r.key for r in rows}) != len(rows):
        raise ScreeningRefused()
    return rows


def published_inputs(
    cfg: Config,
    report: IngestReport,
    folder: Path,
    gate: PublishGateRecord,
    mapping_sha: str | None,
    static_inputs: list[dict[str, Any]],
    db_url: str | None = None,
) -> None:
    """A new passed night, using only the rules already approved by the site and their default screening use."""
    built = report.lake
    if (
        not report.passed
        or report.held
        or not built
        or not built.generation
        or gate.outcome == "HOLD"
        or gate.blocking_reasons
        or gate.current_after != built.snapshot
        or gate.cycle_id != built.snapshot
    ):
        return
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
    if not mapping_sha:
        # An external bulk feed cannot issue the adapter's own mapping stamps.
        raise ScreeningRefused()
    rows = _reviews(folder, built.generation, gate, mapping_sha, static_inputs)
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
            target = record_path(root, built.generation, study, rule.version)
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
            contact = site.contact
            if not contact:
                continue
            list_to = sorted(set(routing.list_to or []))
            if not list_to and rule.manifest.kind == "cohort":
                list_to = [norm(contact)]
            if not list_to:
                continue
            use = ScreeningUse(
                site=site.id,
                clearance_id=release,
                ruleset=study,
                rule_version=rule.version,
                generation=built.generation,
                list_to=list_to,
                referral_to=routing.referral_to or {},
                aggregate_to=sorted({norm(contact), *(norm(a) for a in routing.aggregate_to or [])}),
                stored_read="off",
                scope=ScreeningScope(
                    practitioners=sc.practitioners or None,
                    departments=[],
                    window_days=sc.appointment_window_days or 180,
                    recent_months=sc.recent_encounter_months or 12,
                ),
            )
            record = ScreeningInputs(
                use=use,
                rows=rows,
                inventory={"lake": [r.key for r in rows], "omop": [], "derived": []},
                accepted_digest=digest,
                trusted_digest=digest,
                holds_released=True,
            )
            body = record.model_dump_json().encode()
            accepted.add(hashlib.sha256(body).hexdigest())
            # Install clearance first. A crash before the atomic record write cannot make it readable.
            _write(path, grant.model_copy(update={"accepted_records": sorted(accepted)}).model_dump_json().encode())
            _write(target, body)
