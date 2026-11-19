"""A rule set carried in a vendor-signed update bundle, for the dry run only (plan 10 row 10D-28, review 19-9; D-1369).

Until the coordinating centre signs a study package (cards 10D-2 to 10D-4), a screen-only site box gets a rule set
compiled and approved on the head box this way: the head box exports the approved version as a **rule-set part**
(``python -m criteria_compiler.export_part``), the vendor signs it into an update bundle with the vendor key
(``python -m tools.ruleset_bundle`` for a part alone; ``tools/make_bundle.sh --rulesets DIR`` beside a release), and
``tools/apply_update.sh`` installs it on the site box through the import that already installs a bundle's rule sets
(``criteria_compiler.import_ruleset``).

A part is a zip of the ``import_ruleset`` form (one folder ``<ID>/``) with one more member at its root,
``ORIGIN.json``: where it came from (the compiling box's release, its approval tag) and the sha256 of its content.

* **Criteria and codes only.** The folder carries ``manifest.yaml``, ``labels.yaml``, ``ir/``, ``valuesets/``,
  ``cql/`` and ``sql/``; ``tests/`` is left out (a box's compile writes its equivalence report there, one row per
  disagreeing case; the shipped examples hold synthetic patients there), and any other file refuses the export.
* **The content hash** (:func:`content_sha256`) is computed over every carried file, path and bytes; the receiving
  box computes it again and refuses the part when it differs, on top of the bundle's own per-payload sha256.
* **Not a local approval.** The receiving box records the part's approval tag with :data:`ARRIVED_MARK`, the bundle,
  the compiling box's release and the hash; the console lists it as "arrived in a vendor bundle (interim)".

Standard library and PyYAML only: the vendor's machine and the compiler's image both read it.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
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


class PartRefused(ValueError):
    pass


def content_sha256(files: dict[str, bytes]) -> str:
    """sha256 over the sorted lines ``<sha256 of the bytes>  <path>`` of every file (the ``sha256sum`` form)."""
    lines = "".join(f"{hashlib.sha256(files[p]).hexdigest()}  {p}\n" for p in sorted(files))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def carried(files: dict[str, bytes]) -> dict[str, bytes]:
    """The files of an approved rule set folder that a part carries; ``tests/`` is left out, anything else refused."""
    out: dict[str, bytes] = {}
    for path, data in files.items():
        if path in CARRIED_FILES or path.startswith(CARRIED_DIRS):
            out[path] = data
        elif not path.startswith(LEFT_OUT_DIRS):
            raise PartRefused(f"{path}: not a file a rule-set part carries (criteria and codes only: "
                              f"{', '.join(CARRIED_FILES + CARRIED_DIRS)})")  # fmt: skip
    if "manifest.yaml" not in out:
        raise PartRefused("no manifest.yaml")
    return out


def build_part(ruleset_id: str, files: dict[str, bytes], origin: dict[str, Any]) -> bytes:
    """The part's zip: ``<ID>/<file>`` for each carried file and ``ORIGIN.json``, with fixed dates (the same files
    give the same bytes)."""
    members = {f"{ruleset_id}/{p}": b for p, b in carried(files).items()}
    members[ORIGIN] = (json.dumps(origin, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
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


def check_origin(origin: dict[str, Any], ruleset_id: str, version: str, files: dict[str, bytes]) -> None:
    """Refuse a part whose record names another rule set or version, whose folder holds a file a part does not
    carry, or whose content hash is not the one recorded."""
    if origin.get("ruleset") != ruleset_id or str(origin.get("version")) != str(version):
        raise PartRefused(f"{ORIGIN} names {origin.get('ruleset')} v{origin.get('version')}, "
                          f"the part holds {ruleset_id} v{version}")  # fmt: skip
    extra = sorted(p for p in files if not (p in CARRIED_FILES or p.startswith(CARRIED_DIRS)))
    if extra:
        raise PartRefused(f"the part holds files a part does not carry: {extra[:5]}")
    got = content_sha256(files)
    if got != origin.get("content_sha256"):
        raise PartRefused(f"{ruleset_id} v{version}: content sha256 {got} is not the {origin.get('content_sha256')} "
                          f"its {ORIGIN} records; refused")  # fmt: skip


def open_part(data: bytes) -> tuple[str, dict[str, bytes], dict[str, Any], dict[str, Any]]:
    """``(id, files, manifest, origin)`` of a part, checked as the receiving box checks it (the vendor's tool reads it
    before signing). Refuses a zip that is no part or whose rule set is not approved."""
    origin = origin_of(data)
    if origin is None:
        raise PartRefused(f"no {ORIGIN}: not a rule-set part (python -m criteria_compiler.export_part writes one)")
    rid = str(origin.get("ruleset") or "")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in check_ruleset_zip(z) if not n.endswith("/")]
        stray = [n for n in names if n != ORIGIN and PurePosixPath(n).parts[0] != rid]
        if not rid or stray:
            raise PartRefused(f"the part holds members outside its folder {rid!r}: {stray[:5]}")
        files = {n[len(rid) + 1 :]: z.read(n) for n in names if n != ORIGIN}
    if "manifest.yaml" not in files:
        raise PartRefused("no manifest.yaml")
    manifest = yaml.safe_load(files["manifest.yaml"].decode("utf-8")) or {}
    if manifest.get("id") != rid or manifest.get("status") != "approved":
        raise PartRefused(f"{rid}: the part's manifest is not the approved {rid} (id {manifest.get('id')!r}, "
                          f"status {manifest.get('status')!r})")  # fmt: skip
    check_origin(origin, rid, str(manifest.get("version")), files)
    return rid, files, manifest, origin


def release_of(origin: dict[str, Any]) -> str:
    """The compiling box's release as one line: ``<bundle id> (release_seq N, commit C)``."""
    on = origin.get("compiled_on") or {}
    if not isinstance(on, dict):
        return "unknown"
    if on.get("release"):
        return str(on["release"])[:200]
    seq = f"release_seq {on.get('release_seq')}" if on.get("release_seq") is not None else ""
    commit = f"commit {str(on['commit'])[:12]}" if on.get("commit") else ""
    extra = ", ".join(x for x in (seq, commit) if x)
    return f"{on.get('bundle_id') or 'unknown'}" + (f" ({extra})" if extra else "")


def tag_note(origin: dict[str, Any], by: str) -> str:
    """What the receiving box adds to the approval tag: the mark, the bundle, the compiling box's release, the hash."""
    return (f"{ARRIVED_MARK}: {by}; compiled and approved on another box, release {release_of(origin)}, "
            f"its tag {origin.get('approval_tag')}; content sha256 {origin.get('content_sha256')}")  # fmt: skip
