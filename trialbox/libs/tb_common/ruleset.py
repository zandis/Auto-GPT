"""Read-only access to compiled rulesets (``rulesets/<ID>/``) for services (orchestrator, compiler).

Layout::

    <ID>/manifest.yaml                ruleset manifest (status draft|approved)
    <ID>/ir/<CRITERION-ID>.json       Criterion IR
    <ID>/valuesets/<VS_NAME>.json     FHIR ValueSets (explicit concepts)
    <ID>/cql/<Library>.cql, cql/TB_Common.cql, cql/elm/<Library>.json
    <ID>/sql/<ID>.sql
    <ID>/tests/{equivalence.json, expected.json, patients.ndjson}
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from tb_contracts import CriterionIR, RulesetManifest

from tb_common.fhir import library_name


class RulesetNotApproved(RuntimeError):
    pass


class RecompileNeeded(RulesetNotApproved):
    """The ruleset was compiled against another terminology release (D-301)."""


@dataclass
class Ruleset:
    manifest: RulesetManifest
    criteria: list[CriterionIR]
    valuesets: dict[str, dict[str, Any]]
    cql: dict[str, str] = field(default_factory=dict)
    elm: dict[str, str] = field(default_factory=dict)
    sql: str = ""
    path: Path | None = None

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def library(self) -> str:
        return self.manifest.library or library_name(self.manifest.id, self.manifest.version)

    @property
    def library_version(self) -> str:
        """Version string inside the CQL text (``<semver>-b<hash>``)."""
        text = self.cql.get(self.library, "")
        for line in text.splitlines():
            if line.startswith("library ") and " version " in line:
                return line.split(" version ", 1)[1].strip().strip("'")
        return self.version

    def ordered(self) -> list[CriterionIR]:
        order = {cid: i for i, cid in enumerate(self.manifest.criteria)}
        return sorted(self.criteria, key=lambda c: (order.get(c.id, 10_000), c.id))

    def active(self) -> list[CriterionIR]:
        """Criteria not rejected by the reviewer, in manifest order."""
        return [c for c in self.ordered() if not (c.review and c.review.status == "rejected")]

    def by_id(self) -> dict[str, CriterionIR]:
        return {c.id: c for c in self.criteria}

    @classmethod
    def from_files(cls, files: dict[str, bytes], path: Path | None = None) -> Ruleset:
        manifest = RulesetManifest.model_validate(yaml.safe_load(files["manifest.yaml"].decode("utf-8")))
        criteria = [
            CriterionIR.model_validate(json.loads(b))
            for p, b in sorted(files.items())
            if p.startswith("ir/") and p.endswith(".json")
        ]
        valuesets = {
            Path(p).stem: json.loads(b)
            for p, b in sorted(files.items())
            if p.startswith("valuesets/") and p.endswith(".json")
        }
        cql = {Path(p).stem: b.decode("utf-8") for p, b in files.items() if p.startswith("cql/") and p.endswith(".cql")}
        elm = {Path(p).stem: b.decode("utf-8") for p, b in files.items() if p.startswith("cql/elm/")}
        sql = next((b.decode("utf-8") for p, b in files.items() if p.startswith("sql/") and p.endswith(".sql")), "")
        return cls(manifest, criteria, valuesets, cql, elm, sql, path)

    @classmethod
    def load(cls, directory: Path) -> Ruleset:
        files = {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        if "manifest.yaml" not in files:
            raise FileNotFoundError(f"no manifest.yaml in {directory}")
        return cls.from_files(files, directory)


def load_approved(
    rulesets_dir: Path,
    ruleset_id: str,
    version: str | None = None,
    terminology: Callable[[RulesetManifest], None] | None = None,
    on: date | None = None,
) -> Ruleset:
    """Approved ruleset from the materialized repo copy; refuses drafts and version mismatches (SPEC §5 step 4).
    ``terminology`` (``criteria_compiler.terminology.resolver.guard()``, D-301) refuses a ruleset compiled against
    another terminology release than the box's until it is recompiled; its refusal is :class:`RulesetNotApproved`.

    ``on`` (the run date, D-364, LIFE-009): the version in force that day. A newer approved version whose
    ``effective_from`` is later is not used; the approved version before it (read from its approval tag) screens
    until then. Without ``on`` the newest approved version is returned, whatever its effective date."""
    directory = rulesets_dir / ruleset_id
    if not (directory / "manifest.yaml").exists():
        raise RulesetNotApproved(f"ruleset {ruleset_id} has no approved version on this box")
    rs = Ruleset.load(directory)
    if rs.manifest.status != "approved":
        raise RulesetNotApproved(f"ruleset {ruleset_id} is not approved")
    if on is not None and not in_force(rs.manifest, on):
        if version and version == rs.version:
            raise RulesetNotApproved(
                f"ruleset {ruleset_id} v{version} takes effect on {rs.manifest.effective_from}, not before"
            )
        rs = _earlier_in_force(rulesets_dir, ruleset_id, rs.version, on)
    if version and rs.version != version:
        raise RulesetNotApproved(f"ruleset {ruleset_id} approved version is {rs.version}, not {version}")
    tag_ok = (rulesets_dir / ".git").exists() is False or _has_tag(rulesets_dir, f"{ruleset_id}/v{rs.version}")
    if not tag_ok:
        raise RulesetNotApproved(f"ruleset {ruleset_id} v{rs.version} has no approval tag")
    if terminology is not None:
        try:
            terminology(rs.manifest)
        except RulesetNotApproved:
            raise
        except RuntimeError as exc:  # TerminologyMismatch: recompile needed (D-301)
            raise RecompileNeeded(str(exc)) from exc
    return rs


def in_force(manifest: RulesetManifest, on: date) -> bool:
    """D-364: an approved version screens from its ``effective_from`` (none = from its approval)."""
    eff = manifest.effective_from
    return eff is None or eff <= on


def _semver(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (-1,)


def _earlier_in_force(rulesets_dir: Path, ruleset_id: str, newest: str, on: date) -> Ruleset:
    """The newest approved version before ``newest`` that is in force ``on``, from its approval tag in the rulesets
    repository (the materialized copy holds only the newest). None found: the study has no version in force yet."""
    from dulwich.object_store import iter_tree_contents
    from dulwich.objects import Commit, Tag
    from dulwich.repo import Repo

    when = f"v{newest} takes effect on a later day"
    if not (rulesets_dir / ".git").exists():
        raise RulesetNotApproved(f"ruleset {ruleset_id} {when} and no earlier version is on this box")
    repo = Repo(str(rulesets_dir))
    refs: Any = repo.refs
    prefix = f"refs/tags/{ruleset_id}/v"
    tags = sorted(
        (k.decode()[len(prefix) :] for k in refs.keys() if k.decode().startswith(prefix)),  # noqa: SIM118
        key=_semver,
        reverse=True,
    )
    for v in tags:
        if _semver(v) >= _semver(newest):
            continue
        obj: Any = repo[refs[f"{prefix}{v}".encode()]]
        while isinstance(obj, Tag):
            obj = repo[obj.object[1]]
        assert isinstance(obj, Commit)
        files: dict[str, bytes] = {}
        for entry in iter_tree_contents(repo.object_store, obj.tree):
            path = entry.path.decode() if entry.path else ""
            if path.startswith(f"{ruleset_id}/") and entry.sha is not None:
                files[path[len(ruleset_id) + 1 :]] = repo[entry.sha].as_raw_string()
        if "manifest.yaml" not in files:
            continue
        rs = Ruleset.from_files(files)
        if rs.manifest.status == "approved" and in_force(rs.manifest, on):
            return rs
    raise RulesetNotApproved(f"ruleset {ruleset_id} {when} and no earlier approved version is in force on {on}")


def approval_state(
    manifest: RulesetManifest,
    *,
    terminology_release: str | None = None,
    prompt_drift: list[dict[str, Any]] | None = None,
    derived_drift: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Whether an approved ruleset still stands as the investigator approved it (D-318, URS-PI-06).

    ``approval_needed`` when a prompt it pins has a newer registered version or its pinned text changed
    (``tb_llm.prompt_registry.pin_drift``), or when the box's terminology release (``terminology_release``, None when
    it cannot be read) is not the one it was compiled against (D-301). A prompt change leaves SCREEN on the pinned
    prompt until the re-approval; a terminology change refuses the run until it is recompiled and re-approved, because
    the box holds only its current release. D-442: ``approval_needed`` too when a score definition it pins
    (``derived_pins``) is computed on this box under another version or text (:func:`tb_common.scores.pin_drift`);
    until the re-approval screening reads those scores as unknown. ``reasons`` lists each cause for the page."""
    if manifest.status != "approved":
        return {"state": "draft", "reasons": []}
    if prompt_drift is None:
        from tb_llm.prompt_registry import pin_drift

        prompt_drift = pin_drift(manifest)
    if derived_drift is None:
        from tb_common.scores import pin_drift as derived_pin_drift

        derived_drift = derived_pin_drift(getattr(manifest, "derived_pins", None))
    reasons: list[dict[str, Any]] = [{"kind": "prompt", **d} for d in prompt_drift]
    reasons += [{"kind": "derived", **d} for d in derived_drift]
    pinned = manifest.terminology_release
    if pinned and terminology_release and pinned != terminology_release:
        reasons.append({"kind": "terminology", "pinned": pinned, "active": terminology_release, "state": "newer"})
    # D-442: approved before score definitions were pinned: a changed definition cannot ask for approval until the
    # next approval writes the pins (never back-filled; the page says so)
    unpinned = not getattr(manifest, "derived_pins", None)
    return {"state": "approval_needed" if reasons else "approved", "reasons": reasons, "derived_unpinned": unpinned}


def _has_tag(repo_dir: Path, tag: str) -> bool:
    from dulwich.repo import Repo

    refs: Any = Repo(str(repo_dir)).refs
    return f"refs/tags/{tag}".encode() in refs


def list_rulesets(rulesets_dir: Path) -> list[str]:
    return sorted(p.parent.name for p in rulesets_dir.glob("*/manifest.yaml"))
