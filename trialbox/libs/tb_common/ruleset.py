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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from tb_contracts import CriterionIR, RulesetManifest

from tb_common.fhir import library_name


class RulesetNotApproved(RuntimeError):
    pass


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


def load_approved(rulesets_dir: Path, ruleset_id: str, version: str | None = None) -> Ruleset:
    """Approved ruleset from the materialized repo copy; refuses drafts and version mismatches (SPEC §5 step 4)."""
    directory = rulesets_dir / ruleset_id
    if not (directory / "manifest.yaml").exists():
        raise RulesetNotApproved(f"ruleset {ruleset_id} has no approved version on this box")
    rs = Ruleset.load(directory)
    if rs.manifest.status != "approved":
        raise RulesetNotApproved(f"ruleset {ruleset_id} is not approved")
    if version and rs.version != version:
        raise RulesetNotApproved(f"ruleset {ruleset_id} approved version is {rs.version}, not {version}")
    tag_ok = (rulesets_dir / ".git").exists() is False or _has_tag(rulesets_dir, f"{ruleset_id}/v{rs.version}")
    if not tag_ok:
        raise RulesetNotApproved(f"ruleset {ruleset_id} v{rs.version} has no approval tag")
    return rs


def _has_tag(repo_dir: Path, tag: str) -> bool:
    from dulwich.repo import Repo

    refs: Any = Repo(str(repo_dir)).refs
    return f"refs/tags/{tag}".encode() in refs


def list_rulesets(rulesets_dir: Path) -> list[str]:
    return sorted(p.parent.name for p in rulesets_dir.glob("*/manifest.yaml"))
