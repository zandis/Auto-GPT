"""A rule set carried in a vendor-signed update bundle, for the dry run only (plan 10 row 10D-28, review 19-9; D-1369).

Until the coordinating centre signs a study package (cards 10D-2 to 10D-4), a screen-only site box gets a rule set
compiled and approved on the head box this way: the head box exports the approved version as a **rule-set part**
(``python -m criteria_compiler.export_part``), the vendor signs it into an update bundle with the vendor key
(``python -m tools.ruleset_bundle`` for a part alone; ``tools/make_bundle.sh --rulesets DIR`` beside a release), and
``tools/apply_update.sh`` installs it on the site box through the import that already installs a bundle's rule sets
(``criteria_compiler.import_ruleset``).

A part is a zip of the ``import_ruleset`` form (one folder ``<ID>/``) with one more member at its root,
``ORIGIN.json``: where it came from and the part's sha256.

* **Criteria and codes only** (:func:`neutral_files`). The protocol's fields of the manifest (the split of D-1366,
  10D-2) and the compiled files travel; every staff or site field is removed before hashing: ``routing`` and
  ``scopes`` (left as empty placeholders the schema requires), the approval record ``review``, ``effective_from``,
  the IRB fields, the site's code tables (``terminology_tables``, ``terminology_refused``), the serving models
  (``models`` keeps ``judge_prompt`` only); ``equivalence`` keeps its numbers (the receiving import's gate reads
  them). Each criterion keeps its review **status** only (who, when and the comment are removed) and loses its
  ``provenance``. ``tests/`` is left out; any other file, or a manifest field nobody placed, refuses the export.
* **The part's hash** (:func:`part_sha256`) covers every carried file (path and bytes) and every field of
  ``ORIGIN.json`` but the hash itself; every field is checked against a strict form (:func:`check_origin`).
* **Not a local approval.** The receiving box takes its own ``routing`` and ``scopes`` for the study from its
  repository's ``profiles/<ID>.yaml`` (the import refuses without them), records the approval tag with
  :data:`ARRIVED_MARK`, and lists it as "arrived in a vendor bundle (interim)".

Standard library and PyYAML only: the vendor's machine and the compiler's image both read it.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

import yaml

from tb_common.zipcap import ZipRefused, check_ruleset_zip

PART_FORMAT = "trialbox-ruleset-part/1"
ORIGIN = "ORIGIN.json"
CARRIED_FILES = ("manifest.yaml", "labels.yaml")
CARRIED_DIRS = ("ir/", "valuesets/", "cql/", "sql/")
LEFT_OUT_DIRS = ("tests/",)
#: written on the approval tag of a rule set a part installed; the console lists such a version as not approved here
ARRIVED_MARK = "arrived in a vendor bundle (interim)"
#: what every installed offline update writes on its tag (D-77): such a version was not approved on this box either
UPDATE_MARK = "(offline update, "

#: D-1366 (10D-2): the protocol part of the manifest, the same at every site
PROTOCOL_FIELDS = ("id", "kind", "title", "trial_alias", "sponsor", "version", "source_documents", "protocol_version",
                   "protocol_date", "language", "index_date_rule", "library", "criteria", "thresholds", "variants",
                   "twpas", "docx_template", "cohort", "population", "nct_id", "terminology_release", "prompt_pins",
                   "derived_pins", "source_last_update")  # fmt: skip
#: D-1366's site part: removed on export (routing and scopes stay as empty placeholders)
SITE_FIELDS = ("effective_from", "irb_reference", "irb_approved_on", "scopes", "routing", "review",
               "terminology_tables", "terminology_refused")  # fmt: skip
EQUIVALENCE_KEPT = ("overall_pct", "sample_size", "per_criterion", "failing")
IR_SITE_KEYS = ("provenance",)

RULESET_ID = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")
VERSION = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
BUNDLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
PROMPT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
ORIGIN_KEYS = {"format", "ruleset", "version", "part_sha256", "files", "left_out", "approval_tag", "compiled_on",
               "pins", "exported_at"}  # fmt: skip


class PartRefused(ValueError):
    pass


def _json(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def _carried_path(path: str) -> bool:
    return path in CARRIED_FILES or path.startswith(CARRIED_DIRS)


def neutral_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """The manifest with the site part removed (D-1366): what a part carries. Refuses a field nobody placed."""
    unplaced = sorted(k for k in manifest if k not in (*PROTOCOL_FIELDS, *SITE_FIELDS, "status", "models",
                                                       "equivalence"))  # fmt: skip
    if unplaced:
        raise PartRefused(f"manifest fields not placed as protocol or site ({', '.join(unplaced)}): not exported")
    out = {k: v for k, v in manifest.items() if k in PROTOCOL_FIELDS or k == "status"}
    out["scopes"], out["routing"] = {}, {}  # required by the schema; the receiving site's own replace them
    models = manifest.get("models") or {}
    if isinstance(models, dict) and models.get("judge_prompt"):
        out["models"] = {"judge_prompt": models["judge_prompt"]}
    eq = manifest.get("equivalence")
    if isinstance(eq, dict):
        out["equivalence"] = {k: eq[k] for k in EQUIVALENCE_KEPT if k in eq}
    return out


def neutral_ir(criterion: dict[str, Any]) -> dict[str, Any]:
    """A criterion with its review status only (no who, when or comment) and no provenance."""
    out = {k: v for k, v in criterion.items() if k not in ("review", *IR_SITE_KEYS)}
    review = criterion.get("review")
    if isinstance(review, dict) and review.get("status"):
        out["review"] = {"status": review["status"]}
    return out


def neutral_files(files: dict[str, bytes]) -> dict[str, bytes]:
    """The files of an approved rule set folder as a part carries them: ``tests/`` left out, any other file refused,
    the manifest and each criterion without their site and staff fields."""
    out: dict[str, bytes] = {}
    for path, data in files.items():
        if path.startswith(LEFT_OUT_DIRS):
            continue
        if not _carried_path(path):
            raise PartRefused(f"{path}: not a file a rule-set part carries (criteria and codes only: "
                              f"{', '.join(CARRIED_FILES + CARRIED_DIRS)})")  # fmt: skip
        if path == "manifest.yaml":
            m = yaml.safe_load(data.decode("utf-8")) or {}
            data = yaml.safe_dump(neutral_manifest(m), allow_unicode=True, sort_keys=False).encode("utf-8")
        elif path.startswith("ir/") and path.endswith(".json"):
            data = _json(neutral_ir(json.loads(data)))
        out[path] = data
    if "manifest.yaml" not in out:
        raise PartRefused("no manifest.yaml")
    return out


def check_neutral(files: dict[str, bytes]) -> None:
    """Refuse a part whose manifest or criteria still hold a site or staff field (a part not made by the export)."""
    m = yaml.safe_load(files["manifest.yaml"].decode("utf-8")) or {}
    if neutral_manifest(m) != m:
        raise PartRefused("its manifest holds site or staff fields (routing, scopes, the approval record, IRB, the "
                          "site's code tables): a part carries criteria and codes only")  # fmt: skip
    for path, data in files.items():
        if path.startswith("ir/") and path.endswith(".json"):
            c = json.loads(data)
            if neutral_ir(c) != c:
                raise PartRefused(f"{path} holds a reviewer's record or provenance: a part carries criteria only")


def part_sha256(files: dict[str, bytes], origin: dict[str, Any]) -> str:
    """sha256 over the sorted lines ``<sha256 of the bytes>  <path>`` of every file, then the line ``origin
    <sha256 of ORIGIN.json without part_sha256, keys sorted>``."""
    lines = "".join(f"{hashlib.sha256(files[p]).hexdigest()}  {p}\n" for p in sorted(files))
    rest = {k: v for k, v in origin.items() if k != "part_sha256"}
    canon = json.dumps(rest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    lines += f"origin {hashlib.sha256(canon).hexdigest()}\n"
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def build_part(ruleset_id: str, files: dict[str, bytes], origin: dict[str, Any]) -> bytes:
    """The part's zip: ``<ID>/<file>`` for each carried file (as :func:`neutral_files` gives them) and
    ``ORIGIN.json`` with :func:`part_sha256` filled in; fixed dates, so the same input gives the same bytes."""
    carried = neutral_files(files)
    origin = {**origin, "files": sorted(carried)}
    origin["part_sha256"] = part_sha256(carried, origin)
    check_origin(origin, ruleset_id, str(origin.get("version")), carried)
    members = {f"{ruleset_id}/{p}": b for p, b in carried.items()}
    members[ORIGIN] = _json(origin)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, members[name])
    return buf.getvalue()


def origin_of(data: bytes) -> dict[str, Any] | None:
    """The part's ``ORIGIN.json``; None for a rule set zip that is no part (a vendor-shipped rule set)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = check_ruleset_zip(z)
            if ORIGIN not in names:
                return None
            raw = z.read(ORIGIN)
    except (ZipRefused, zipfile.BadZipFile) as exc:
        raise PartRefused(f"not a readable rule-set zip: {exc}") from exc
    try:
        origin = json.loads(raw)
    except ValueError as exc:
        raise PartRefused(f"{ORIGIN} is not JSON") from exc
    if not isinstance(origin, dict) or origin.get("format") != PART_FORMAT:
        raise PartRefused(f"{ORIGIN} is not a {PART_FORMAT} record")
    return origin


def _text(v: Any, cap: int) -> bool:
    return isinstance(v, str) and 0 < len(v) <= cap and not CONTROL.search(v)


def _origin_problems(o: dict[str, Any], ruleset_id: str, version: str) -> list[str]:
    bad = [f"unexpected field {k!r}" for k in sorted(set(o) - ORIGIN_KEYS)]
    bad += [f"missing field {k!r}" for k in sorted(ORIGIN_KEYS - set(o) - {"left_out"})]
    if not (isinstance(o.get("ruleset"), str) and RULESET_ID.match(o["ruleset"]) and o["ruleset"] == ruleset_id):
        bad.append(f"ruleset is not {ruleset_id}")
    if not (isinstance(o.get("version"), str) and VERSION.match(o["version"]) and o["version"] == str(version)):
        bad.append(f"version is not {version}")
    if o.get("approval_tag") != f"{ruleset_id}/v{version}":
        bad.append(f"approval_tag is not {ruleset_id}/v{version}")
    if not (isinstance(o.get("part_sha256"), str) and SHA256.match(o["part_sha256"])):
        bad.append("part_sha256 is not 64 lowercase hex digits")
    left = o.get("left_out", [])
    if not (isinstance(left, list) and all(x in LEFT_OUT_DIRS for x in left)):
        bad.append("left_out names something other than tests/")
    on = o.get("compiled_on")
    if not isinstance(on, dict) or not on or set(on) - {"bundle_id", "release_seq", "commit", "release"}:
        bad.append("compiled_on is not {bundle_id, release_seq, commit} or {release}")
    else:
        if on.get("bundle_id") is not None and not (
            isinstance(on["bundle_id"], str) and BUNDLE_ID.match(on["bundle_id"])
        ):
            bad.append("compiled_on.bundle_id is not a bundle id")
        seq = on.get("release_seq")
        if seq is not None and not (isinstance(seq, int) and not isinstance(seq, bool) and 0 <= seq < 10**9):
            bad.append("compiled_on.release_seq is not a whole number")
        if on.get("commit") is not None and not (isinstance(on["commit"], str) and COMMIT.match(on["commit"])):
            bad.append("compiled_on.commit is not a 40-hex commit")
        if "release" in on and not _text(on["release"], 200):
            bad.append("compiled_on.release is not one line of at most 200 characters")
    pins = o.get("pins")
    if not isinstance(pins, dict) or set(pins) - {"judge_prompt", "terminology_release"}:
        bad.append("pins is not {judge_prompt, terminology_release}")
    else:
        if pins.get("judge_prompt") is not None and not (isinstance(pins["judge_prompt"], str) and
                                                          PROMPT.match(pins["judge_prompt"])):  # fmt: skip
            bad.append("pins.judge_prompt is not a prompt name")
        if pins.get("terminology_release") is not None and not _text(pins["terminology_release"], 100):
            bad.append("pins.terminology_release is not one line of at most 100 characters")
    try:
        datetime.fromisoformat(str(o.get("exported_at")))
        if not _text(o.get("exported_at"), 40):
            raise ValueError
    except ValueError:
        bad.append("exported_at is not a date-time")
    return bad


def check_origin(origin: dict[str, Any], ruleset_id: str, version: str, files: dict[str, bytes]) -> None:
    """Refuse a part whose record is not of the strict form, names another rule set or version, whose folder holds a
    file a part does not carry or a file its record does not list, or whose hash is not the one recorded."""
    if not isinstance(origin, dict) or origin.get("format") != PART_FORMAT:
        raise PartRefused(f"{ORIGIN} is not a {PART_FORMAT} record")
    bad = _origin_problems(origin, ruleset_id, version)
    if bad:
        raise PartRefused(f"{ORIGIN} refused: {'; '.join(bad[:5])}")
    extra = sorted(p for p in files if not _carried_path(p))
    if extra:
        raise PartRefused(f"the part holds files a part does not carry: {extra[:5]}")
    if origin.get("files") != sorted(files):
        raise PartRefused(f"{ORIGIN} does not list exactly the files of the part")
    got = part_sha256(files, origin)
    if got != origin["part_sha256"]:
        raise PartRefused(f"{ruleset_id} v{version}: part sha256 {got} is not the {origin['part_sha256']} its "
                          f"{ORIGIN} records; refused")  # fmt: skip


def open_part(data: bytes) -> tuple[str, dict[str, bytes], dict[str, Any], dict[str, Any]]:
    """``(id, files, manifest, origin)`` of a part, checked as the receiving box checks it (the vendor's tool reads it
    before signing): every member inside the folder or ``ORIGIN.json``, the record's form and hash, no site field,
    the rule set approved."""
    origin = origin_of(data)
    if origin is None:
        raise PartRefused(f"no {ORIGIN}: not a rule-set part (python -m criteria_compiler.export_part writes one)")
    rid = origin.get("ruleset")
    if not (isinstance(rid, str) and RULESET_ID.match(rid)):
        raise PartRefused(f"{ORIGIN} names no rule set")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in check_ruleset_zip(z) if not n.endswith("/")]
        stray = [n for n in names if n != ORIGIN and PurePosixPath(n).parts[0] != rid]
        if stray:
            raise PartRefused(f"the part holds members outside its folder {rid}/: {stray[:5]}")
        files = {n[len(rid) + 1 :]: z.read(n) for n in names if n != ORIGIN}
    if "manifest.yaml" not in files:
        raise PartRefused("no manifest.yaml")
    manifest = yaml.safe_load(files["manifest.yaml"].decode("utf-8")) or {}
    if not isinstance(manifest, dict) or manifest.get("id") != rid or manifest.get("status") != "approved":
        raise PartRefused(f"{rid}: the part's manifest is not the approved {rid}")
    check_origin(origin, rid, str(manifest.get("version")), files)
    check_neutral(files)
    return rid, files, manifest, origin


def release_of(origin: dict[str, Any]) -> str:
    """The compiling box's release as one line: ``<bundle id> (release_seq N, commit C)`` (checked fields only)."""
    on = origin.get("compiled_on") or {}
    if on.get("release"):
        return str(on["release"])
    seq = f"release_seq {on.get('release_seq')}" if on.get("release_seq") is not None else ""
    commit = f"commit {str(on['commit'])[:12]}" if on.get("commit") else ""
    extra = ", ".join(x for x in (seq, commit) if x)
    return f"{on.get('bundle_id') or 'unknown'}" + (f" ({extra})" if extra else "")


def tag_note(origin: dict[str, Any], by: str) -> str:
    """What the receiving box adds to the approval tag: the mark, the bundle, the compiling box's release, the hash.
    Only fields :func:`check_origin` accepted, one line."""
    return (f"{ARRIVED_MARK}: {by}; compiled and approved on another box, release {release_of(origin)}, "
            f"its tag {origin['approval_tag']}; part sha256 {origin['part_sha256']}")  # fmt: skip


def arrived(tag_message: str) -> bool:
    """Whether an approval tag records a version that arrived in an update (a part, or any offline update, D-77):
    not approved on this box."""
    return ARRIVED_MARK in tag_message or UPDATE_MARK in tag_message
