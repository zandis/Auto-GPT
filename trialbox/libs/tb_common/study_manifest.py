"""The study manifest in two parts: the protocol part and the site part (10D-2, D-1366; review 14 M14-1).

A study is one folder ``rulesets/<ID>/`` (``tb_common.ruleset``), whose ``manifest.yaml`` mixes what the protocol
fixes with what one hospital sets. This module draws the line, read from the folder as it is today: nothing on disk
changes, and :func:`merge` gives back the same manifest (``Ruleset.load`` and every reader of the manifest are
untouched). **Nothing on the live path calls this module yet**: a site can still edit ``manifest.yaml`` by hand and
the box screens on it; wiring the refusal into import, approval and load is 10D-4's.

* **The protocol part** (``schemas/study_protocol.schema.json``, :data:`PROTOCOL_FIELDS` and
  :data:`PROTOCOL_SUBFIELDS`): what the coordinating centre fixes for every site: the study's identity and versions,
  the criteria list, the thresholds, the variants, the pins (terminology release, prompts, score definitions, and the
  judge prompt a manifest from before D-318 names in ``models.judge_prompt``) and the protocol's files
  (:data:`PROTOCOL_FILES`). Its canonical serialisation (:func:`canonical`) hashes to the **criteria hash**
  (``criteria_sha256``), the same on every site that adopts it.
* **The site part** (``schemas/study_site.schema.json``, :data:`SITE_FIELDS`): what a hospital sets for itself:
  screening scopes and people, routing, which model serves (``models`` but its ``judge_prompt``), its approval
  (status, review, IRB record, the date it starts screening), its equivalence run and the code tables its box loaded;
  and each criterion's review record (who approved it at this site, when, with what comment). A criterion's
  "rejected" stays in the protocol part: dropping a criterion is not the site's to do (review 14 section 3.3).

A site edit goes through :func:`site_edit`: a change to a site field is taken; a change to anything in the protocol
part (a threshold, the criteria list, a pin) is refused with a sentence that names it. :func:`differences` says what a
written folder changed in an adopted protocol part. Both return their refusal as sentences, never as a caught error's
text (D-555). The canonical form is written in D-1366 ("The canonical form") so that the package format (10D-3) can
reproduce it byte for byte.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from tb_contracts import RulesetManifest, StudyProtocol, StudySite

PROTOCOL_SCHEMA = "tb-study-protocol/1"
SITE_SCHEMA = "tb-study-site/1"
MANIFEST = "manifest.yaml"

#: the manifest fields the coordinating centre fixes for every site (with PROTOCOL_SUBFIELDS, the enum of
#: study_protocol.schema.json)
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
#: keys of a site field that are the protocol's: ``models.judge_prompt`` is the judge's prompt pin of a manifest
#: without ``prompt_pins`` (``tb_llm.prompt_registry.manifest_pins``); which model serves stays the site's
PROTOCOL_SUBFIELDS: dict[str, tuple[str, ...]] = {"models": ("judge_prompt",)}
#: the files the criteria hash covers, by how each is made canonical: what ``Ruleset.from_files`` reads, the labels,
#: the synthetic test patients and their expected results (and the file ``docx_template`` names, as its bytes).
#: Every other file of the folder is outside the protocol part and outside the hash.
PROTOCOL_FILES = (
    ("ir/", ".json", "ir"),
    ("valuesets/", ".json", "json"),
    ("cql/elm/", ".json", "json"),
    ("cql/elm/", "", "text"),
    ("cql/", ".cql", "text"),
    ("sql/", ".sql", "text"),
    ("labels.yaml", None, "text"),
    ("tests/patients.ndjson", None, "text"),
    ("tests/expected.json", None, "json"),
)
#: the files of the folder that are the site's own: its equivalence run on its box
SITE_FILES = frozenset({"tests/equivalence.json"})
#: how a refusal names a protocol field (others by their own name)
_WORDS = {
    "thresholds": "the threshold",
    "criteria": "the criteria list",
    "version": "the criteria version",
    "prompt_pins": "the prompt pin",
    "models": "the prompt pin",
    "derived_pins": "the score definition pin",
    "terminology_release": "the terminology release",
}
_HINT = "the coordinating centre issues a new protocol version for that"
_MAX_INT = 2**53
_BOM = b"\xef\xbb\xbf"


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
def _number(value: int | float) -> str:
    """A number as RFC 8785 (JCS) writes it, i.e. ECMAScript's Number-to-String: an integer outside ±2**53 refused
    (another reader would not read it back exactly); NaN and infinity refused."""
    if isinstance(value, int):
        if abs(value) > _MAX_INT:
            raise ValueError("a study's protocol holds no integer beyond 2**53")
        return str(value)
    if not math.isfinite(value):
        raise ValueError("a study's protocol holds no NaN or infinity")
    if value == 0:
        return "0"
    mantissa, _, exp = repr(abs(value)).partition("e")  # the shortest digits that read back to the same double
    whole, _, frac = mantissa.partition(".")
    digits = (whole + frac).lstrip("0")
    stripped = digits.rstrip("0")
    k = len(stripped)
    n = k + int(exp or 0) - len(frac) + (len(digits) - k)  # value = 0.<stripped> x 10**n
    if k <= n <= 21:
        out = stripped + "0" * (n - k)
    elif 0 < n <= 21:
        out = f"{stripped[:n]}.{stripped[n:]}"
    elif -6 < n <= 0:
        out = "0." + "0" * -n + stripped
    else:
        e = n - 1
        out = (stripped if k == 1 else f"{stripped[0]}.{stripped[1:]}") + ("e+" if e >= 0 else "e-") + str(abs(e))
    return ("-" if value < 0 else "") + out


def _jcs(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_jcs(v) for v in value) + "]"
    if isinstance(value, Mapping):
        if not all(isinstance(k, str) for k in value):
            raise ValueError("a study's protocol holds only text keys")
        keys = sorted(value, key=lambda k: k.encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(f"{_jcs(k)}:{_jcs(value[k])}" for k in keys) + "}"
    raise ValueError(f"a study's protocol holds no {type(value).__name__}")


def dumps(value: Any) -> bytes:
    """The canonical bytes of a JSON value: RFC 8785 (JCS), UTF-8. No Unicode normalisation: strings, codes and keys
    are written as their exact code points; a lone surrogate is refused."""
    return _jcs(value).encode("utf-8")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"a study's JSON file names the key {k!r} twice")
        out[k] = v
    return out


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"a study's JSON file holds {name}, which JSON does not have")


def load_json(data: bytes) -> Any:
    """A JSON file as the hash reads it: UTF-8 with a leading byte-order mark removed; a key twice, NaN or infinity
    refused."""
    return json.loads(
        data.removeprefix(_BOM).decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_refuse_constant
    )


def canonical(doc: Mapping[str, Any]) -> bytes:
    """The one serialisation the criteria hash is taken over: :func:`dumps` of every key but the hash."""
    return dumps({k: v for k, v in doc.items() if k != "criteria_sha256"})


def criteria_sha256(protocol: Mapping[str, Any]) -> str:
    """The criteria hash of a protocol part, computed again from its content."""
    return hashlib.sha256(canonical(protocol)).hexdigest()


def text(data: bytes) -> bytes:
    """A text file as the hash reads it: its bytes, a leading UTF-8 byte-order mark removed, CR LF and then a lone CR
    written as LF. Nothing else is changed."""
    return data.removeprefix(_BOM).replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _manifest_json(raw: Mapping[str, Any] | RulesetManifest) -> dict[str, Any]:
    """The manifest as its schema reads what the file writes: JSON form (dates as ISO text), nulls left out, no
    default added."""
    model = raw if isinstance(raw, RulesetManifest) else RulesetManifest.model_validate(dict(raw))
    return model.model_dump(mode="json", exclude_unset=True, exclude_none=True, by_alias=True)


def _check_path(path: str) -> None:
    if path.startswith("/") or ".." in path.split("/") or "\\" in path:
        raise ValueError(f"a study file's path must be relative to its folder: {path!r}")


def _kind(path: str, docx: str | None) -> str | None:
    if docx and path == docx:
        return "bytes"
    for prefix, suffix, kind in PROTOCOL_FILES:
        if path == prefix if suffix is None else path.startswith(prefix) and path.endswith(suffix):
            return kind
    return None


def hashed_paths(files: Mapping[str, bytes]) -> set[str]:
    """The paths of a study folder the criteria hash covers (with ``manifest.yaml``, split by field)."""
    docx = (yaml.safe_load(files[MANIFEST].decode("utf-8")) or {}).get("docx_template") if MANIFEST in files else None
    return {p for p in files if p not in SITE_FILES and _kind(p, docx) is not None}


def _ir_split(data: bytes) -> tuple[bytes, str, dict[str, Any] | None]:
    """A criterion IR file as written, without the site's review record (``{"status": "rejected"}`` kept), canonical;
    its criterion id; that record."""
    doc = load_json(data)
    review = doc.pop("review", None)
    if isinstance(review, Mapping) and review.get("status") == "rejected":
        doc["review"] = {"status": "rejected"}
    return dumps(doc), str(doc.get("id", "")), dict(review) if isinstance(review, Mapping) else None


def file_bytes(kind: str, data: bytes) -> bytes:
    """A protocol file's canonical bytes by its kind (:data:`PROTOCOL_FILES`); an IR file through :func:`_ir_split`."""
    if kind == "json":
        return dumps(load_json(data))
    if kind == "text":
        return text(data)
    return data


def _parts_of(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """A manifest's fields as the protocol part's and the site part's."""
    pm = {k: manifest[k] for k in PROTOCOL_FIELDS if k in manifest}
    sm = {k: manifest[k] for k in SITE_FIELDS if k in manifest}
    for field_name, keys in PROTOCOL_SUBFIELDS.items():
        whole = dict(sm.pop(field_name, None) or {})
        mine = {k: whole.pop(k) for k in keys if k in whole}
        if mine:
            pm[field_name] = mine
        if whole:
            sm[field_name] = whole
    return pm, sm


# ---------------------------------------------------------------------------------------------- split and merge
def split(files: Mapping[str, bytes]) -> StudyParts:
    """The two parts of one study folder, given as ``{relative path: bytes}`` (``Ruleset.from_files``'s form)."""
    if MANIFEST not in files:
        raise FileNotFoundError("a study folder has a manifest.yaml")
    manifest = _manifest_json(yaml.safe_load(files[MANIFEST].decode("utf-8")) or {})
    docx = manifest.get("docx_template")
    protocol_files: dict[str, str] = {}
    site_files: dict[str, str] = {}
    reviews: dict[str, Any] = {}
    for path, data in sorted(files.items()):
        _check_path(path)
        if path in SITE_FILES:
            site_files[path] = hashlib.sha256(data).hexdigest()
            continue
        kind = _kind(path, docx)
        if kind is None:
            continue
        if kind == "ir":
            body, cid, review = _ir_split(data)
            if review is not None:
                reviews[cid] = review
        else:
            body = file_bytes(kind, data)
        protocol_files[path] = hashlib.sha256(body).hexdigest()
    pm, sm = _parts_of(manifest)
    protocol: dict[str, Any] = {"schema": PROTOCOL_SCHEMA, "manifest": pm, "files": protocol_files}
    protocol["criteria_sha256"] = criteria_sha256(protocol)
    site: dict[str, Any] = {"schema": SITE_SCHEMA, "criteria_sha256": protocol["criteria_sha256"], "manifest": sm}
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
    """None when the protocol part is one (its schema, only protocol fields) and its criteria hash is the hash of its
    content; else the sentence refusing it."""
    try:
        StudyProtocol.model_validate(protocol)
    except ValidationError:
        return "this is not a study's protocol part"
    for field_name, keys in PROTOCOL_SUBFIELDS.items():
        if set(protocol["manifest"].get(field_name) or {}) - set(keys):
            return f"the study's protocol part carries a site's {field_name} setting"
    try:
        if protocol.get("criteria_sha256") != criteria_sha256(protocol):
            return "the study's protocol part was changed after its criteria hash was taken"
    except ValueError:
        return "this is not a study's protocol part"
    return None


def site_refusal(site: Mapping[str, Any], chash: str) -> str | None:
    """None when the site part is one, holds only site fields and goes with the protocol of ``chash``."""
    try:
        StudySite.model_validate(site)
    except ValidationError:
        return "the site part carries a field that is not the site's, or is not a study's site part"
    for field_name, keys in PROTOCOL_SUBFIELDS.items():
        held = sorted(set(site["manifest"].get(field_name) or {}) & set(keys))
        if held:
            return f"the site part carries {field_name}.{held[0]}, which is the study's protocol"
    if site.get("criteria_sha256") != chash:
        return "the site part goes with another protocol part (its criteria hash differs)"
    return None


def merge(protocol: Mapping[str, Any], site: Mapping[str, Any]) -> dict[str, Any]:
    """The manifest of one site: the protocol part's fields and the site part's, in the schema's order. Refused
    (``ValueError``) when the protocol part does not hold its hash, the site part carries anything of the protocol's,
    or it goes with another protocol."""
    why = protocol_refusal(protocol) or site_refusal(site, str(protocol["criteria_sha256"]))
    if why:
        raise ValueError(why)
    fields = merge_fields(protocol["manifest"], site["manifest"])
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
    shown = json.dumps(value, ensure_ascii=False)
    return shown if len(shown) <= 40 and not isinstance(value, (dict, list)) else None


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


def _same(a: Any, b: Any) -> bool:
    try:
        return dumps(a) == dumps(b)
    except ValueError:
        return bool(a == b)


def site_edit(protocol: Mapping[str, Any], site: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any] | str:
    """A site's edit of its study manifest: ``changes`` maps manifest fields to their whole new value (None removes a
    site field); in ``models`` the protocol's key (``judge_prompt``) stays as the protocol has it when the edit leaves
    it out. Returns the new site part, or the sentence refusing the edit: a change to a protocol field or key (a
    value equal to the protocol's is no change), a field the manifest does not have, or a value the manifest's schema
    refuses."""
    try:
        current = merge(protocol, site)
    except ValueError as exc:
        return str(exc)
    chash = str(protocol["criteria_sha256"])
    unknown = sorted(k for k in changes if k not in set(PROTOCOL_FIELDS) | set(SITE_FIELDS))
    if unknown:
        return f"{', '.join(unknown)} is not a field of a study manifest"
    refusals = []
    for key in (k for k in PROTOCOL_FIELDS if k in changes):
        old = protocol["manifest"].get(key)
        try:
            new = _manifest_json({**current, key: changes[key]}).get(key)
        except ValidationError:
            new = changes[key]
        if not _same(new, old):
            refusals.append(_protocol_sentence(key, old, new, chash))
    edited = dict(site["manifest"])
    for key in (k for k in SITE_FIELDS if k in changes):
        value = changes[key]
        if key in PROTOCOL_SUBFIELDS:
            whole = dict(value or {}) if isinstance(value, Mapping) or value is None else value
            if isinstance(whole, dict):
                # per key: a protocol key the edit leaves out stays as the protocol has it
                old_sub = dict(protocol["manifest"].get(key) or {})
                sent = {k: whole.pop(k) for k in PROTOCOL_SUBFIELDS[key] if k in whole}
                if not _same({**old_sub, **sent}, old_sub):
                    refusals.append(_protocol_sentence(key, old_sub, {**old_sub, **sent}, chash))
                value = whole or None
        if value is None:
            edited.pop(key, None)
        else:
            edited[key] = value
    if refusals:
        return "; ".join(refusals)
    try:
        full = _manifest_json(merge_fields(protocol["manifest"], edited))
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        return f"the site's change to {where} is not a value a study manifest takes: {first.get('msg', '')}"
    pm, sm = _parts_of(full)
    if dumps(pm) != dumps(protocol["manifest"]):
        return _protocol_sentence("models", protocol["manifest"].get("models"), pm.get("models"), chash)
    return {**site, "manifest": sm}


def merge_fields(protocol_manifest: Mapping[str, Any], site_manifest: Mapping[str, Any]) -> dict[str, Any]:
    """The two parts' manifest fields as one manifest (a key of :data:`PROTOCOL_SUBFIELDS` joined), unchecked."""
    fields: dict[str, Any] = {**site_manifest}
    for k, v in protocol_manifest.items():
        fields[k] = {**(fields.get(k) or {}), **v} if k in PROTOCOL_SUBFIELDS else v
    return fields


def apply_site_edit(protocol: Mapping[str, Any], site: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    """:func:`site_edit`, a refusal raised as :class:`SiteEditRefused` with its sentence."""
    got = site_edit(protocol, site, changes)
    if isinstance(got, str):
        raise SiteEditRefused(got)
    return got


def differences(adopted: Mapping[str, Any], written: StudyParts) -> list[str]:
    """What a study folder as written at a site changed in the protocol part it adopted: one sentence per protocol
    field and per file; none when the criteria hashes are equal. An adopted part that does not hold its own hash is
    refused first (its sentence is the one difference)."""
    why = protocol_refusal(adopted)
    if why:
        return [f"the adopted protocol part cannot be trusted: {why}"]
    if written.criteria_sha256 == adopted["criteria_sha256"] and protocol_refusal(written.protocol) is None:
        return []
    chash = str(adopted["criteria_sha256"])
    old_m, new_m = adopted["manifest"], written.protocol["manifest"]
    out = [
        _protocol_sentence(k, old_m.get(k), new_m.get(k), chash)
        for k in (*PROTOCOL_FIELDS, *PROTOCOL_SUBFIELDS)
        if not _same(old_m.get(k), new_m.get(k))
    ]
    old_f, new_f = adopted["files"], written.protocol["files"]
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
