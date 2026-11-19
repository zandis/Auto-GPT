"""The study manifest in two parts: the protocol part and the site part (10D-2, D-1366; review 14 M14-1).

A study is one folder ``rulesets/<ID>/`` (``tb_common.ruleset``), whose ``manifest.yaml`` mixes what the protocol
fixes with what one hospital sets. This module draws the line, read from the folder as it is today: nothing on disk
changes, and :func:`merge` gives back the same manifest (``Ruleset.load`` and every reader of the manifest are
untouched).

* **The protocol part** (``schemas/study_protocol.schema.json``, :data:`PROTOCOL_FIELDS`): what the coordinating
  centre fixes for every site: the study's identity and versions, the criteria list, the thresholds, the variants, the
  pins (terminology release, prompts, score definitions) and the protocol's files (criteria IR, value sets, CQL and
  ELM, the generated SQL, labels, the synthetic test patients and their expected results). Its canonical serialisation
  (:func:`canonical`) hashes to the **criteria hash** (``criteria_sha256``), the same on every site that adopts it.
* **The site part** (``schemas/study_site.schema.json``, :data:`SITE_FIELDS`): what a hospital sets for itself:
  screening scopes and people, routing, the note-reading models, its approval (status, review, IRB record, the date it
  starts screening), its equivalence run and the code tables its box loaded; and each criterion's review record (who
  approved it at this site, when, with what comment). A criterion's "rejected" stays in the protocol part: dropping a
  criterion is not the site's to do (review 14 section 3.3).

A site edit goes through :func:`site_edit`: a change to a site field is taken; a change to anything in the protocol
part (a threshold, the criteria list, a pin) is refused with a sentence that names it. :func:`differences` says what a
written folder changed in an adopted protocol part. Both return their refusal as sentences, never as a caught error's
text (D-555). The package format (10D-3), its import (10D-4) and the allowed adaptations (10D-5, e.g. a small-cell
floor raised) build on these two parts.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from tb_contracts import RulesetManifest

PROTOCOL_SCHEMA = "tb-study-protocol/1"
SITE_SCHEMA = "tb-study-site/1"
MANIFEST = "manifest.yaml"

#: the manifest fields the coordinating centre fixes for every site (the enum of study_protocol.schema.json)
PROTOCOL_FIELDS: tuple[str, ...] = (
    "id",
    "kind",
    "title",
    "trial_alias",
    "sponsor",
    "version",
    "source_documents",
    "protocol_version",
    "protocol_date",
    "language",
    "index_date_rule",
    "library",
    "criteria",
    "thresholds",
    "variants",
    "twpas",
    "docx_template",
    "cohort",
    "population",
    "nct_id",
    "terminology_release",
    "prompt_pins",
    "derived_pins",
    "source_last_update",
)
#: the manifest fields a site sets for itself (the enum of study_site.schema.json)
SITE_FIELDS: tuple[str, ...] = (
    "status",
    "effective_from",
    "irb_reference",
    "irb_approved_on",
    "scopes",
    "routing",
    "models",
    "review",
    "equivalence",
    "terminology_tables",
    "terminology_refused",
)
#: the files of the folder that are the site's own: its equivalence run on its box (every other file is the protocol's)
SITE_FILES = frozenset({"tests/equivalence.json"})
#: how a refusal names a protocol field (others by their own name)
_WORDS = {
    "thresholds": "the threshold",
    "criteria": "the criteria list",
    "version": "the criteria version",
    "prompt_pins": "the prompt pin",
    "derived_pins": "the score definition pin",
    "terminology_release": "the terminology release",
}
_HINT = "the coordinating centre issues a new protocol version for that"


class SiteEditRefused(ValueError):
    """A site edit that would change the protocol part; its message is the refusal's sentence."""


@dataclass(frozen=True)
class StudyParts:
    """One study folder in its two parts, each the JSON of its schema."""

    protocol: dict[str, Any]
    site: dict[str, Any]

    @property
    def criteria_sha256(self) -> str:
        return str(self.protocol["criteria_sha256"])


# ---------------------------------------------------------------------------------------------- canonical form
def canonical(doc: Mapping[str, Any]) -> bytes:
    """The one serialisation the criteria hash is taken over: JSON, keys sorted, no spaces, UTF-8; never the hash."""
    body = {k: v for k, v in doc.items() if k != "criteria_sha256"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def criteria_sha256(protocol: Mapping[str, Any]) -> str:
    """The criteria hash of a protocol part, computed again from its content."""
    return hashlib.sha256(canonical(protocol)).hexdigest()


def _manifest_json(raw: Mapping[str, Any] | RulesetManifest) -> dict[str, Any]:
    """The manifest as its schema reads it: what the file sets, in JSON form (dates as ISO text), nulls left out."""
    model = raw if isinstance(raw, RulesetManifest) else RulesetManifest.model_validate(dict(raw))
    return model.model_dump(mode="json", exclude_unset=True, exclude_none=True, by_alias=True)


def _check_path(path: str) -> None:
    if path.startswith("/") or ".." in path.split("/") or "\\" in path:
        raise ValueError(f"a study file's path must be relative to its folder: {path!r}")


def _ir_split(data: bytes) -> tuple[bytes, str, dict[str, Any] | None]:
    """A criterion IR file without the site's review record, canonical; its criterion id; that record."""
    doc = json.loads(data)
    review = doc.pop("review", None)
    if isinstance(review, Mapping) and review.get("status") == "rejected":
        doc["review"] = {"status": "rejected"}
    body = json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return body, str(doc.get("id", "")), dict(review) if isinstance(review, Mapping) else None


# ---------------------------------------------------------------------------------------------- split and merge
def split(files: Mapping[str, bytes]) -> StudyParts:
    """The two parts of one study folder, given as ``{relative path: bytes}`` (``Ruleset.from_files``'s form)."""
    if MANIFEST not in files:
        raise FileNotFoundError("a study folder has a manifest.yaml")
    manifest = _manifest_json(yaml.safe_load(files[MANIFEST].decode("utf-8")) or {})
    protocol_files: dict[str, str] = {}
    site_files: dict[str, str] = {}
    reviews: dict[str, Any] = {}
    for path, data in sorted(files.items()):
        _check_path(path)
        if path == MANIFEST:
            continue
        if path in SITE_FILES:
            site_files[path] = hashlib.sha256(data).hexdigest()
            continue
        if path.startswith("ir/") and path.endswith(".json"):
            data, cid, review = _ir_split(data)
            if review is not None:
                reviews[cid] = review
        protocol_files[path] = hashlib.sha256(data).hexdigest()
    protocol: dict[str, Any] = {
        "schema": PROTOCOL_SCHEMA,
        "manifest": {k: manifest[k] for k in PROTOCOL_FIELDS if k in manifest},
        "files": protocol_files,
    }
    protocol["criteria_sha256"] = criteria_sha256(protocol)
    site: dict[str, Any] = {
        "schema": SITE_SCHEMA,
        "criteria_sha256": protocol["criteria_sha256"],
        "manifest": {k: manifest[k] for k in SITE_FIELDS if k in manifest},
    }
    if reviews:
        site["criterion_reviews"] = reviews
    if site_files:
        site["files"] = site_files
    return StudyParts(protocol, site)


def split_dir(directory: Path) -> StudyParts:
    """:func:`split` of a folder on disk, read as ``Ruleset.load`` reads it."""
    files = {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    return split(files)


def protocol_refusal(protocol: Mapping[str, Any]) -> str | None:
    """None when the protocol part's criteria hash is the hash of its content; else the sentence refusing it."""
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        return "this is not a study's protocol part"
    if protocol.get("criteria_sha256") != criteria_sha256(protocol):
        return "the study's protocol part was changed after its criteria hash was taken"
    return None


def merge(protocol: Mapping[str, Any], site: Mapping[str, Any]) -> dict[str, Any]:
    """The manifest of one site: the protocol part's fields and the site part's, in the schema's order. Refused
    (``ValueError``) when the protocol part does not hold its hash or the site part goes with another protocol."""
    why = protocol_refusal(protocol)
    if why:
        raise ValueError(why)
    if site.get("schema") != SITE_SCHEMA or site.get("criteria_sha256") != protocol["criteria_sha256"]:
        raise ValueError("the site part goes with another protocol part (its criteria hash differs)")
    fields = {**protocol["manifest"], **site["manifest"]}
    return {k: fields[k] for k in RulesetManifest.model_fields if k in fields}


# ---------------------------------------------------------------------------------------------- refusals
def _leaves(old: Any, new: Any, path: str) -> list[str]:
    """The dotted paths at which two JSON values differ (lists are compared whole)."""
    if old == new:
        return []
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        out: list[str] = []
        for k in sorted(set(old) | set(new)):
            out += _leaves(old.get(k), new.get(k), f"{path}.{k}")
        return out
    return [path]


def _at(doc: Any, path: str) -> Any:
    for part in path.split(".")[1:]:
        doc = doc.get(part) if isinstance(doc, Mapping) else None
    return doc


def _shown(value: Any) -> str | None:
    if value is None:
        return "nothing"
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 40 and not isinstance(value, (dict, list)) else None


def _protocol_sentence(field_name: str, old: Any, new: Any, chash: str) -> str:
    paths = _leaves(old, new, field_name) or [field_name]
    parts = []
    for path in paths:
        a, b = _shown(_at(old, path)), _shown(_at(new, path))
        change = f" from {a} to {b}" if a is not None and b is not None else ""
        parts.append(f"{path}{change}")
    word = _WORDS.get(field_name, "the protocol field")
    return (
        f"{word} {', '.join(parts)} cannot be changed at a site: it is part of the study's protocol, the same at every "
        f"site that adopted it (criteria hash {chash[:12]}); {_HINT}"
    )


def site_edit(protocol: Mapping[str, Any], site: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any] | str:
    """A site's edit of its study manifest: ``changes`` maps manifest fields to their new value (None removes a site
    field). Returns the new site part, or the sentence refusing the edit: a change to a protocol field (a value equal
    to the protocol's is no change), a field the manifest does not have, or a value the manifest's schema refuses."""
    try:
        current = merge(protocol, site)
    except ValueError as exc:
        return str(exc)
    chash = str(protocol["criteria_sha256"])
    known = set(PROTOCOL_FIELDS) | set(SITE_FIELDS)
    unknown = sorted(k for k in changes if k not in known)
    if unknown:
        return f"{', '.join(unknown)} is not a field of a study manifest"
    refusals = []
    for key in (k for k in PROTOCOL_FIELDS if k in changes):
        old = protocol["manifest"].get(key)
        try:
            new = _manifest_json({**current, key: changes[key]}).get(key)
        except ValidationError:
            new = changes[key]
        if new != old:
            refusals.append(_protocol_sentence(key, old, new, chash))
    if refusals:
        return "; ".join(refusals)
    edited = dict(site["manifest"])
    for key in (k for k in SITE_FIELDS if k in changes):
        if changes[key] is None:
            edited.pop(key, None)
        else:
            edited[key] = changes[key]
    try:
        normal = _manifest_json({**protocol["manifest"], **edited})
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        return f"the site's change to {where} is not a value a study manifest takes: {first.get('msg', '')}"
    return {**site, "manifest": {k: normal[k] for k in SITE_FIELDS if k in normal}}


def apply_site_edit(protocol: Mapping[str, Any], site: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    """:func:`site_edit`, a refusal raised as :class:`SiteEditRefused` with its sentence."""
    got = site_edit(protocol, site, changes)
    if isinstance(got, str):
        raise SiteEditRefused(got)
    return got


def differences(adopted: Mapping[str, Any], written: StudyParts) -> list[str]:
    """What a study folder as written at a site changed in the protocol part it adopted: one sentence per protocol
    field and per file; none when the criteria hashes are equal."""
    if written.criteria_sha256 == adopted.get("criteria_sha256"):
        return []
    chash = str(adopted.get("criteria_sha256", ""))
    old_m, new_m = adopted.get("manifest", {}), written.protocol["manifest"]
    out = [
        _protocol_sentence(k, old_m.get(k), new_m.get(k), chash)
        for k in PROTOCOL_FIELDS
        if old_m.get(k) != new_m.get(k)
    ]
    old_f, new_f = adopted.get("files", {}), written.protocol["files"]
    for path in sorted(set(old_f) | set(new_f)):
        if path not in new_f:
            out.append(f"the protocol's file {path} is missing at this site (criteria hash {chash[:12]})")
        elif path not in old_f:
            out.append(f"the file {path} is not in the study's protocol (criteria hash {chash[:12]}); {_HINT}")
        elif old_f[path] != new_f[path]:
            out.append(
                f"the protocol's file {path} was changed at this site: it is the same at every site that adopted it "
                f"(criteria hash {chash[:12]}); {_HINT}"
            )
    return out or ["the study's protocol part differs from the one adopted"]
