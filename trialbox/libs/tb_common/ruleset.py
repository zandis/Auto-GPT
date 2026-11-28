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
import logging
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from tb_contracts import CriterionIR, RulesetManifest
from tb_contracts.atomicity import check_criterion
from tb_contracts.criterion_ir import upgrade_v1

from tb_common.config import environment_name
from tb_common.fhir import library_name

# D-469: the rulesets that ship with the product. The checkout's (image's) folder is the seed and nothing the product
# runs ever writes to it; the working copy is ``Env.rulesets_path`` (under ``TB_DATA_DIR``).
SEED_RULESETS = Path(__file__).resolve().parents[2] / "rulesets"

# NEW-LIFE-1 (D-640; review LIFE-001): the shipped rulesets are synthetic examples, approved by nobody at a site. Only
# a box that says it is one of these gets them; every other name (VALIDATION, PRODUCTION, unset, a name nobody knows)
# is a site box, where a study is approved by the site or not at all
EXAMPLE_ENVS = ("DEV", "TEST")
#: what the compiler's first start wrote on the tag of each ruleset it seeded (``RulesetRepo._tag_seeded``)
SEEDED_TAG = "(vendor-shipped, approved)"


def examples_allowed(env: Mapping[str, str] | None = None) -> bool:
    """Whether this box may hold and run the shipped example rulesets (``TB_ENV`` DEV or TEST; D-640)."""
    return environment_name(os.environ if env is None else env) in EXAMPLE_ENVS


log = logging.getLogger(__name__)


class RulesetNotApproved(RuntimeError):
    pass


class RecompileNeeded(RulesetNotApproved):
    """The ruleset was compiled against another terminology release (D-301)."""


class RulesetReadIncomplete(Exception):
    """INT-R3A: what was read of a ruleset's working copy is not the whole version its approval tag holds (a read
    that met an approval swapping the folder, or a file changed, cut, removed or added on disk). Never a partial
    ruleset, and not :class:`RulesetNotApproved`: a caller must not read it as "no approved version"."""


#: INT-R3A: reads of a working copy before :class:`RulesetReadIncomplete`; an approval's swap is one rename, so a
#: read that met one is whole when read again
READ_TRIES = 5


@dataclass
class Ruleset:
    manifest: RulesetManifest
    criteria: list[CriterionIR]
    valuesets: dict[str, dict[str, Any]]
    cql: dict[str, str] = field(default_factory=dict)
    elm: dict[str, str] = field(default_factory=dict)
    sql: str = ""
    path: Path | None = None
    # the atomicity lint at load (tb_contracts.atomicity): "<criterion>.<atom>" -> reasons; reported, never refused
    lint: dict[str, list[str]] = field(default_factory=dict)

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
        lint = {f"{c.id}.{a}": r for c in criteria for a, r in check_criterion(upgrade_v1(c)).items()}
        if lint:
            log.info("ruleset %s: %d atoms fail the atomicity lint: %s", manifest.id, len(lint), sorted(lint))
        return cls(manifest, criteria, valuesets, cql, elm, sql, path, lint)

    @classmethod
    def load(cls, directory: Path) -> Ruleset:
        files = _read_dir(directory)
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
    rs = Ruleset.from_files(_read_whole(rulesets_dir, ruleset_id), directory)
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
    if not examples_allowed() and seeded_approval(rulesets_dir, ruleset_id, rs.version):
        raise RulesetNotApproved(
            f"ruleset {ruleset_id} v{rs.version} is not approved at this site: its approval names nobody here "
            "(a shipped example, or a folder with no approval tag; D-640)"
        )
    if terminology is not None:
        try:
            terminology(rs.manifest)
        except RulesetNotApproved:
            raise
        except RuntimeError as exc:  # TerminologyMismatch: recompile needed (D-301)
            raise RecompileNeeded(str(exc)) from exc
    return rs


def _read_dir(directory: Path) -> dict[str, bytes]:
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


def _read_whole(rulesets_dir: Path, ruleset_id: str) -> dict[str, bytes]:
    """INT-R3A: the files of ``ruleset_id``'s working copy, checked against the git hashes of its approval tag's
    tree (the version its manifest names): read again while they differ, then :class:`RulesetReadIncomplete`.
    Unchecked where there is nothing to hold them against: a copy with no repository (``seed_working_copy``; a site
    box refuses it, D-640), a version with no tag or a manifest that does not parse (both refused after this), and a
    tag that points at nothing (a site box refuses it in ``seeded_approval``; a DEV or TEST box runs it, as before)."""
    why = ""
    for _ in range(READ_TRIES):
        try:
            files = _read_dir(rulesets_dir / ruleset_id)
        except (FileNotFoundError, NotADirectoryError) as exc:  # a file listed, then gone in a swap
            why = type(exc).__name__
            continue
        why = _differs_from_tag(rulesets_dir, ruleset_id, files)
        if not why:
            return files
    raise RulesetReadIncomplete(f"ruleset {ruleset_id}: {why} (after {READ_TRIES} reads)")


def _differs_from_tag(rulesets_dir: Path, ruleset_id: str, files: dict[str, bytes]) -> str:
    """Why ``files`` are not the tree of ``ruleset_id``'s approval tag, or "" when they are (or cannot be held)."""
    if "manifest.yaml" not in files:
        return "no manifest.yaml"
    if not (rulesets_dir / ".git").exists():
        return ""
    try:
        version = (yaml.safe_load(files["manifest.yaml"].decode("utf-8")) or {}).get("version")
    except (yaml.YAMLError, UnicodeDecodeError, AttributeError):
        return ""
    from dulwich.object_store import iter_tree_contents, tree_lookup_path
    from dulwich.objects import Blob, Commit, Tag
    from dulwich.repo import Repo

    repo = Repo(str(rulesets_dir))
    refs: Any = repo.refs
    tag = f"refs/tags/{ruleset_id}/v{version}".encode()
    if tag not in refs:
        return ""
    try:
        obj: Any = repo[refs[tag]]
        while isinstance(obj, Tag):
            obj = repo[obj.object[1]]
    except KeyError:  # a tag that points at nothing: not held here, as before (seeded_approval reads it on a site box)
        return ""
    if not isinstance(obj, Commit):
        return ""
    try:
        _, tree = tree_lookup_path(repo.__getitem__, obj.tree, ruleset_id.encode())
    except KeyError:
        return f"its approval tag v{version} holds no {ruleset_id}/"
    want = {e.path.decode(): e.sha for e in iter_tree_contents(repo.object_store, tree) if e.path and e.sha}
    got = {p: Blob.from_string(b).id for p, b in files.items()}
    if got == want:
        return ""
    bad = sorted(p for p in set(want) | set(got) if want.get(p) != got.get(p))
    return f"{len(bad)} file(s) differ from its approval tag v{version}"


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


def seeded_approval(rulesets_dir: Path, ruleset_id: str, version: str) -> bool:
    """Whether the approval of ``ruleset_id`` v``version`` in this working copy names nobody who gave it at this
    site (D-640): what seeding the shipped examples left on a box started before NEW-LIFE-1.

    An approval is an annotated tag of the compiler's repository that says who: the site's approval writes
    "approved by <who>", an installed update "(offline update, <by>)" (D-77). The tag the first start wrote on a
    seeded example (:data:`SEEDED_TAG`) names nobody, and neither does a bare tag. Without a repository (the copy
    ``seed_working_copy`` made) there is no tag at all: nothing in such a folder is approved, whatever its
    manifests say (a box seeded by an earlier release holds manifests that differ from today's image)."""
    if not (rulesets_dir / ".git").exists():
        return True
    from dulwich.objects import Tag
    from dulwich.repo import Repo

    repo = Repo(str(rulesets_dir))
    refs: Any = repo.refs
    tag = f"refs/tags/{ruleset_id}/v{version}".encode()
    if tag not in refs:
        return True
    obj: Any = repo[refs[tag]]
    return not isinstance(obj, Tag) or SEEDED_TAG in obj.message.decode("utf-8", "replace")


def approved_here(rulesets_dir: Path, ruleset_id: str) -> bool:
    """Whether ``ruleset_id`` has an approved version this box may run (:func:`load_approved` without a run date or
    a terminology check): what a timer asks before it starts a job for it. A ruleset that cannot be read (a broken
    manifest, a tag that points at nothing) is one the timer does not start; the timer goes on to the next."""
    try:
        load_approved(rulesets_dir, ruleset_id)
    except RulesetNotApproved:
        return False
    except Exception as exc:  # the scheduler's loop must outlive one unreadable ruleset
        log.warning("ruleset %s cannot be read, no job is started for it: %s", ruleset_id, type(exc).__name__)
        return False
    return True


def list_rulesets(rulesets_dir: Path) -> list[str]:
    # INT-R3A (INTR3A-04): never a dot-name, a copy being built or swapped out (``.<ruleset>.tmp``)
    return sorted(p.parent.name for p in rulesets_dir.glob("*/manifest.yaml") if not p.parent.name.startswith("."))


def seed_working_copy(dest: Path, seed: Path = SEED_RULESETS) -> bool:
    """Give a service that only reads rulesets a first copy of the shipped ones when its folder holds none (a new
    box, a development run). Never touches a folder that already holds a ruleset (a box that compiled its own keeps
    them), never writes ``seed``, and does nothing when ``dest`` cannot be written (a read-only mount: the criteria
    compiler seeds that folder). True when it copied.

    D-640 (NEW-LIFE-1): only a DEV or TEST box is seeded. The shipped rulesets carry an approval nobody at a site
    gave; a VALIDATION or PRODUCTION box starts with no study and gets its first one by the site's own approval."""
    if not examples_allowed():
        return False
    if dest.resolve() == seed.resolve() or list_rulesets(dest) or not seed.is_dir():
        return False
    try:
        shutil.copytree(seed, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".*", "*.tmp", "__pycache__"))
    except OSError:
        return False
    return True
