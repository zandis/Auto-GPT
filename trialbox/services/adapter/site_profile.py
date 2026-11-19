"""The site profile on the box (10B-6, commitment C-6, D-1233; design: docs/data/15-the-site-profile.md).

The loader and its checks are :mod:`tb_common.site_profile`; this module is where the adapter meets a profile:

* **Where it is.** ``profile/profile.yaml`` in the site's mapping folder (``deploy/site/mapping/profile/``, mounted
  read-only at ``/etc/trialbox/mapping/profile``, kept by every update like the site mapping, D-367; or a folder of
  ``TB_MAPPING_DIR``). One box is one site: one profile. No folder: the box reads as it did before profiles.
* **Checked against the box** (:func:`check_mapping`, :func:`check_settings`): a table a mapping reads has the
  mapping's look-up key and every column of the mapping's own look-up, and no other column; the profile's country
  is the one the settings give and its standard versions agree with ``settings.profiles``.
* **Activation, versions and audit.** :func:`activate` compares the profile with what the box read before
  (``site_profile.json`` in the lake folder, beside ``site_key.json``, and the rows' states beside it). A new digest
  is recorded with who, when, the old and new version, both digests and every row whose state changed, in the
  record's history and as one ``terminology.site_profile_load`` event in the hash-chained audit (the adapter's own
  audit family); without an audit destination nothing is activated. An id and version read before with other content
  is refused (the steward changes the version with the content). Rolling back is loading the earlier folder,
  recorded with ``direction: back``. The country layer above the profile (``tb_common.country_layer``, C-7, D-1250)
  ships with the release: a load's record entry (not the audit event, which is as before) names the layer's country,
  version and digest read at that load. Reloading the same profile writes nothing, whatever the layer's version now.
* **The night.** Every night that reads with a profile writes ``site_profile.json`` beside its snapshot (the
  profile's id, version and digest, and the coverage lines); the ``ingest.done`` event carries the same stamp and the
  counts. A fact whose standard code comes from a ``verify`` row carries D-135's basis tag ``verify``
  (:func:`verify_rules`): it stays coded and is listed in the lake's ``site_fact``.
* **Coverage lines** (:func:`coverage`): which declared data types arrived and how many rows, which this version does
  not read, which arrived undeclared, how many codes and rows no table could map (by table: counts only), how many
  rows of each table are still ``verify`` and how many facts rest on them. From the night's own files.
* **The work list** (:func:`worklist`): the unmapped codes, the ``verify`` rows and (with the site set-up store) every
  code that store maps otherwise, as CSV for the site's data manager.

    python -m adapter.site_profile check <folder> [--mapping <mapping.yaml>]
    python -m adapter.site_profile load <folder> --lake <lake dir> --by <name> [--audit <dir>] [--mapping <file>]
    python -m adapter.site_profile history --lake <lake dir>
    python -m adapter.site_profile which --lake <lake dir> --snapshot <YYYY-MM-DD>
    python -m adapter.site_profile coverage --night <snapshot folder> [--profile <folder>] [--json]
    python -m adapter.site_profile worklist --night <snapshot folder> [--profile <folder>] [--setup-db <url>] --out f
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tb_common import country_layer
from tb_common.site_profile import MANIFEST, VERIFIED, VERIFY, Profile, ProfileError, content_sha, load

RECORD = "site_profile.json"  # in the lake folder: the active profile and its history; beside a snapshot: the night's
STATES = "site_profile.states.json"  # in the lake folder: every row's state as last activated
KEPT = "site_profile"  # in the lake folder: each version a person loaded, as loaded (<digest>.json)
REMOVED = "terminology.site_profile_removed"
NOT_LOADED = "terminology.site_profile_not_loaded"
FOLDER = "profile"  # in the site mapping folder
EVENT = "terminology.site_profile_load"  # the adapter's audit family (tb_common.audit_writer.ROLE_EVENTS)
MAX_CHANGES_IN_EVENT = 2000  # rows whose state changed named in one audit event; the count is always complete
WORKLIST_COLUMNS = ("kind", "table", "code", "rows", "target", "state", "file", "line")
# the night's files the coverage lines read (adapter.pipeline writes them)
COMPLETENESS = "completeness.json"
UNMAPPED_CODES = "unmapped_codes.json"
READER = "reader.json"
#: the SS-MIX2 data types the reader reads (its README: ADT-00/12/22/52, PPR-01, OMP-01/02/11/12, OML-11 and the
#: extended storage's documents); a declared type outside these and the mapping's tables is not read by this version
SSMIX2_READS = frozenset({"ADT-00", "ADT-12", "ADT-22", "ADT-52", "PPR-01", "OMP-01", "OMP-02", "OMP-11", "OMP-12",
                          "OML-11", "document"})  # fmt: skip
#: the SS-MIX2 reader's tables: the canonical table, the column of the site's code, the column of the standard code
SSMIX2_COLUMNS = {"ssmix2.diagnosis": ("diagnosis", "byomei_code", "icd10"),
                  "ssmix2.drug": ("medication", "nhi_drug_code", "atc")}  # fmt: skip
#: columns a table a mapping reads may have besides the mapping's own look-up columns and its state
LOOKUP_OPTIONAL = frozenset({"plausible_low", "plausible_high", "source_unit"})


def find(extra: Iterable[Path] = ()) -> Path | None:
    """The site's profile folder: ``profile/`` of the first site mapping folder that has a ``profile.yaml``."""
    from adapter.mapping.site import site_dirs

    for d in site_dirs(extra):
        try:
            if (d / FOLDER / MANIFEST).is_file():
                return d / FOLDER
        except OSError:  # an unreadable or absent mount
            continue
    return None


# ------------------------------------------------------------------------------------ checks against the box
def check_mapping(profile: Profile, mapping: Any) -> None:
    """Refuse a table a mapping reads (``mapping.<look-up>``) that the mapping would read otherwise than its own:
    the look-up must be declared, the table keyed by the look-up's key, and hold every column of the mapping's own
    look-up file (the columns its elements and builders read) and no column besides those, the optional ones
    (:data:`LOOKUP_OPTIONAL`) and its state. ``mapping`` is an :class:`adapter.mapping.engine.Mapping` loaded without
    the profile."""
    for t in profile.tables.values():
        for use in t.used_by:
            if not use.startswith("mapping."):
                continue
            name = use.split(".", 1)[1]
            lk = mapping.lookups.get(name)
            if lk is None:
                raise ProfileError(t.file, f"{use}: the mapping {mapping.name} has no look-up {name!r}")
            if t.key != lk.key:
                raise ProfileError(t.file, f"{use}: the mapping looks {name} up by {lk.key!r}, not {t.key!r}")
            have = set(t.columns)
            missing = [c for c in lk.columns if c not in have and c != "verified"]
            if missing:
                raise ProfileError(f"{t.file}:1", f"{use}: no column {missing[0]!r} (the mapping reads it)")
            allowed = set(lk.columns) | LOOKUP_OPTIONAL | {t.state_column}
            extra = sorted(c for c in have if c not in allowed)
            if extra:
                raise ProfileError(f"{t.file}:1", f"{use}: column {extra[0]!r} is not one the mapping reads")


def check_settings(profile: Profile, *, country: str | None, standards: Mapping[str, str] | None = None) -> None:
    """Refuse a profile whose country is not the one the box's settings give (``tb_common.derived.country_of``: JP or
    TW; None checks nothing), or whose standard versions disagree with ``settings.profiles`` on a name both state."""
    if country and profile.country.upper() != country.upper():
        raise ProfileError(MANIFEST, f"country {profile.country} is not the site's ({country.lower()}, from settings)")
    for k, v in (standards or {}).items():
        if v and k in profile.standards and profile.standards[k] != str(v):
            raise ProfileError(MANIFEST, f"standards.{k} {profile.standards[k]} is not settings.profiles.{k} ({v})")


def verify_rules(profile: Profile) -> dict[str, list[Any]]:
    """The SS-MIX2 rows whose standard code comes from a ``verify`` row, per canonical table (the rules the mapper
    tags with, :class:`adapter.mapping.engine.VerifyRule`): the reader's code column holds the row's code, exactly as
    the reader looks it up, and the row's standard code is the one that row gives. The reader is not asked where it
    took the code from, so a message that carried the same code itself is counted too (an over-count; the follow-up
    after #1095 has the reader say). A mapping's look-up needs no rule: the mapper asks the row the look-up matched
    (:func:`lookup_files`)."""
    from adapter.mapping.engine import VerifyRule

    out: dict[str, list[Any]] = {}
    for t in profile.tables.values():
        codes = {r.code: r.target for r in t.rows.values() if r.state == VERIFY}
        for use in t.used_by:
            if codes and use in SSMIX2_COLUMNS:
                table, col, target = SSMIX2_COLUMNS[use]
                out.setdefault(table, []).append(VerifyRule(table, col, codes, target))
    return out


def write_tables(profile: Profile, folder: Path) -> dict[str, Path]:
    """Each table of the profile as loaded (every cell trimmed) in ``folder``, by ``used_by``: what the night reads,
    never the raw file."""
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for name, t in sorted(profile.tables.items()):
        path = folder / f"{name}.csv"
        path.write_text(t.csv_text(), encoding="utf-8")
        for use in t.used_by:
            out[use] = path
    return out


def mark_unverified(profile: Profile, mapping: Any) -> None:
    """Tell each of the mapping's look-ups that a profile table fills which of its keys are still to verify."""
    for t in profile.tables.values():
        verify = frozenset(r.code for r in t.rows.values() if r.state == VERIFY)
        for use in t.used_by:
            if use.startswith("mapping.") and use.split(".", 1)[1] in mapping.lookups:
                mapping.lookups[use.split(".", 1)[1]].unverified = verify


# ------------------------------------------------------------------------------------- versions and audit
def _version(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def read_record(lake_dir: Path) -> dict[str, Any]:
    try:
        rec = json.loads((lake_dir / RECORD).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"active": None, "history": []}
    if not isinstance(rec, dict) or "history" not in rec:
        raise ProfileError(str(lake_dir / RECORD), "not a site profile record")
    return rec


def _states(profile: Profile) -> dict[str, dict[str, str]]:
    return {n: {c: r.state for c, r in sorted(t.rows.items())} for n, t in sorted(profile.tables.items())}


def _state_changes(before: dict[str, dict[str, str]], now: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for table in sorted(set(before) | set(now)):
        a, b = before.get(table, {}), now.get(table, {})
        for code in sorted(set(a) | set(b)):
            if a.get(code) != b.get(code):
                out.append({"table": table, "code": code, "from": a.get(code), "to": b.get(code)})
    return out


def _write(path: Path, data: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def activate(
    profile: Profile,
    lake_dir: Path,
    *,
    site_id: str,
    by: str,
    audit_dir: Path | None,
    tz: str = "UTC",
    door: str | None = None,
) -> dict[str, Any] | None:
    """Make ``profile`` the box's profile. Returns the change recorded, or None when it is the active one already.

    Refused (:class:`ProfileError`): no audit destination; a profile of another site or another door; an id and
    version the box read before with other content (the whole history is asked, not only the active profile)."""
    if audit_dir is None:
        raise ProfileError(MANIFEST, "a profile is made the box's only with its audit: no audit folder was given")
    if profile.site_id != site_id:
        raise ProfileError(MANIFEST, f"this profile is for site {profile.site_id!r}, not {site_id!r}")
    if door is not None and profile.door != door:
        raise ProfileError(MANIFEST, f"this profile describes a {profile.door} source; the box reads {door}")
    rec = read_record(lake_dir)
    old = rec.get("active") or None
    if old and old.get("digest") == profile.digest:
        return None
    # the country layer above the profile (C-7, D-1250) ships with the release: the load's record entry names the one
    # read at this load (never the audit event, which stays as before); no layer, or a broken one: nothing new
    layer = country_layer.stamp(profile.country)
    for h in rec.get("history", []):
        if h.get("id") == profile.id and h.get("version") == profile.version and h.get("digest") != profile.digest:
            raise ProfileError(
                MANIFEST,
                f"version {profile.version} was read on {h.get('at')} with other content (digest "
                f"{str(h.get('digest'))[:12]}, now {profile.digest[:12]}): give the changed profile a new version",
            )
    at = datetime.now(UTC).isoformat(timespec="seconds")
    direction = "first"
    if old:
        same = old.get("id") == profile.id
        direction = "back" if same and _version(profile.version) < _version(str(old.get("version"))) else "forward"
    try:
        before = json.loads((lake_dir / STATES).read_text(encoding="utf-8"))
    except FileNotFoundError:
        before = {}
    now = _states(profile)
    changes = _state_changes(before, now)
    change = {
        "profile": profile.id,
        "site": site_id,
        "old_version": old.get("version") if old else None,
        "new_version": profile.version,
        "old_digest": old.get("digest") if old else None,
        "new_digest": profile.digest,
        "old_profile": old.get("id") if old else None,
        "direction": direction,
        "synthetic": profile.synthetic,
        "rows_changed": len(changes),  # rows added, removed or whose state changed, each by `by` at `at`
        "row_changes": changes[:MAX_CHANGES_IN_EVENT],
    }
    copy = profile.to_json()
    copy["copy_sha"] = change["copy_sha"] = content_sha(copy)  # the kept copy, as every night will ask it again
    from tb_common.audit_writer import open_audit

    open_audit(audit_dir, tz).append(EVENT, actor=by, output_sha=profile.digest, detail=change)
    entry = {**profile.stamp(), "at": at, "by": by, "direction": direction, "rows_changed": len(changes),
             "copy_sha": change["copy_sha"], **({"layer": layer} if layer else {})}  # fmt: skip
    lake_dir.mkdir(parents=True, exist_ok=True)
    (lake_dir / KEPT).mkdir(exist_ok=True)
    _write(lake_dir / KEPT / f"{profile.digest}.json", copy)  # what the night reads: this version only
    _write(lake_dir / STATES, now)
    _write(lake_dir / RECORD, {"active": entry, "history": [*rec.get("history", []), entry]})
    return {**change, "at": at, "by": by}


def night_profile(night_dir: Path) -> dict[str, Any] | None:
    """The profile a night read with (its id, version, digest), or None for a night read without one."""
    try:
        rec = json.loads((night_dir / RECORD).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    return rec.get("profile") if isinstance(rec, dict) else None


COPY_REFUSED = "terminology.site_profile_copy_refused"


def kept(lake_dir: Path, digest: str, copy_sha: str | None = None) -> Profile:
    """The version a person loaded (:func:`activate`), as it was loaded and checked: its content is hashed again and
    must be what was recorded and audited at the load, and every row is checked again; else :class:`ProfileError`."""
    path = lake_dir / KEPT / f"{digest}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProfileError(str(path), "the loaded version is not kept here: load the profile again") from None
    except (ValueError, UnicodeDecodeError):
        raise ProfileError(
            str(path), "the kept copy of the loaded version is not readable: load the profile again"
        ) from None
    sha = content_sha(doc) if isinstance(doc, dict) else ""
    if (
        not isinstance(doc, dict)
        or doc.get("digest") != digest
        or sha != doc.get("copy_sha")
        or (copy_sha is not None and sha != copy_sha)
    ):
        raise ProfileError(str(path), "the kept copy changed since it was loaded (it is not what the audit recorded): "
                                      "load the profile again")  # fmt: skip
    return Profile.from_json(doc, lake_dir / KEPT)


def deactivate(lake_dir: Path, *, by: str, audit_dir: Path | None, tz: str = "UTC", why: str) -> dict[str, Any]:
    """The box reads without a profile from now on: recorded and audited (``terminology.site_profile_removed``)."""
    if audit_dir is None:
        raise ProfileError(MANIFEST, "a profile is taken off the box only with its audit: no audit folder was given")
    rec = read_record(lake_dir)
    old = rec.get("active") or {}
    at = datetime.now(UTC).isoformat(timespec="seconds")
    detail = {"profile": old.get("id"), "old_version": old.get("version"), "old_digest": old.get("digest"),
              "why": why}  # fmt: skip
    from tb_common.audit_writer import open_audit

    open_audit(audit_dir, tz).append(REMOVED, actor=by, detail=detail)
    entry = {"id": None, "site_id": old.get("site_id"), "version": None, "digest": None, "at": at, "by": by,
             "direction": "removed", "rows_changed": 0}  # fmt: skip
    _write(lake_dir / RECORD, {"active": None, "history": [*rec.get("history", []), entry]})
    (lake_dir / STATES).unlink(missing_ok=True)
    return {**detail, "at": at, "by": by}


def for_night(
    folder: Path | None, lake_dir: Path, *, site_id: str, audit_dir: Path | None, tz: str = "UTC"
) -> tuple[Profile | None, dict[str, Any]]:
    """The profile a night reads with, and what the night says of it. The night applies only the version a person
    loaded (``load --by``): a folder whose content is not that version is not applied (the loaded version is read, a
    problem is said and audited once per content); a folder nobody loaded is not applied either; a folder taken away
    takes the profile off the box (audited) and the night reads without one."""
    rec = read_record(lake_dir)
    active = rec.get("active") or None
    note: dict[str, Any] = {}
    if folder is None:
        if active:
            deactivate(lake_dir, by="adapter", audit_dir=audit_dir, tz=tz, why="the profile folder is gone")
            note["removed"] = {"id": active.get("id"), "version": active.get("version")}
        return None, note
    try:
        on_disk: Profile | str = load(folder)
    except ProfileError as exc:
        on_disk = str(exc)
    disk_digest = on_disk.digest if isinstance(on_disk, Profile) else None
    if not active:
        raise ProfileError(str(folder / MANIFEST), "a profile folder is on the box and no person has loaded it: load "
                           "it (python -m adapter.site_profile load --by <name>) or take it away; the night stops "
                           "rather than read without it")  # fmt: skip
    loaded = _kept_or_refuse(lake_dir, active, audit_dir, tz)
    if disk_digest == active.get("digest"):
        return loaded, note
    pending = disk_digest or "unreadable"
    note["pending"] = {"digest": pending[:12], "why": on_disk if isinstance(on_disk, str) else "not loaded by a person"}
    if rec.get("pending_said") != pending and audit_dir is not None:
        from tb_common.audit_writer import open_audit

        detail = {"pending_digest": disk_digest, "loaded_digest": active.get("digest") if active else None,
                  "why": note["pending"]["why"]}  # fmt: skip
        open_audit(audit_dir, tz).append(NOT_LOADED, actor="adapter", detail=detail)
        _write(lake_dir / RECORD, {**rec, "pending_said": pending})
    return loaded, note


def _kept_or_refuse(lake_dir: Path, active: dict[str, Any], audit_dir: Path | None, tz: str) -> Profile:
    """The loaded version, or the night stops: a kept copy that is not what was loaded is audited and refused."""
    try:
        return kept(lake_dir, str(active["digest"]), active.get("copy_sha"))
    except ProfileError as exc:
        if audit_dir is not None:
            from tb_common.audit_writer import open_audit

            open_audit(audit_dir, tz).append(COPY_REFUSED, actor="adapter", detail={
                "profile": active.get("id"), "version": active.get("version"), "why": exc.why})  # fmt: skip
        raise


# ----------------------------------------------------------------------------------- coverage and work list
def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


#: the names of the night's counter (``unmapped_codes.json``) that are a unit the look-up's row does not give
#: (``adapter.pipeline._UNIT_NOT_READ``): the value was not read, never converted (R-31, D-590)
UNIT_NAMES = ("unit_mismatch", "no_unit_implausible")


def _units(night_dir: Path) -> dict[str, dict[str, int]]:
    """Code -> rows per table whose unit is not the one the table's row gives."""
    out: dict[str, dict[str, int]] = {}
    for table, by_name in sorted((_json(night_dir / UNMAPPED_CODES) or {}).items()):
        for name, codes in sorted(by_name.items()):
            if name in UNIT_NAMES:
                for code, n in codes.items():
                    out.setdefault(table, {})
                    out[table][code] = out[table].get(code, 0) + int(n)
    return out


def _unmapped(night_dir: Path) -> dict[str, dict[str, int]]:
    """Code -> rows per table, from the mapping's file (every code) and the SS-MIX2 reader's (its top codes)."""
    out: dict[str, dict[str, int]] = {}
    for table, by_lookup in sorted((_json(night_dir / UNMAPPED_CODES) or {}).items()):
        for _name, codes in sorted((k, v) for k, v in by_lookup.items() if k not in UNIT_NAMES):
            for code, n in codes.items():
                out.setdefault(table, {})
                out[table][code] = out[table].get(code, 0) + int(n)
    for table, items in sorted(((_json(night_dir / READER) or {}).get("unmapped") or {}).items()):
        for it in items:
            out.setdefault(table, {})
            out[table][str(it["code"])] = out[table].get(str(it["code"]), 0) + int(it["count"])
    return out


def _arrived(night_dir: Path, door: str) -> dict[str, int]:
    """Rows per data type the night read: the SS-MIX2 reader's types (and the extended storage's tables), or the
    source tables of a csv or SQL door."""
    done = (_json(night_dir / COMPLETENESS) or {}).get("tables") or {}
    tables = {t: int(v.get("rows") or 0) for t, v in done.items()}
    if door != "ssmix2":
        return tables
    read = (_json(night_dir / READER) or {}).get("read") or {}
    out = {k: int(n) for k, n in read.items() if ":" not in k}
    return {**{t: n for t, n in tables.items() if t not in out}, **out}


def readable(profile: Profile, mapping_tables: Iterable[str]) -> frozenset[str]:
    """The data types this version reads at the profile's door: the mapping's tables, and the SS-MIX2 types."""
    return frozenset(mapping_tables) | (SSMIX2_READS if profile.door == "ssmix2" else frozenset())


def coverage(
    profile: Profile,
    night_dir: Path,
    *,
    reads: Iterable[str] | None = None,
    from_verify: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """The coverage lines of one night against ``profile``: counts only, never a patient's value. ``reads``: the
    data types this version reads (:func:`readable`); a declared type outside them is "not read by this version",
    not "none arrived". ``from_verify``: facts per table that rest on a ``verify`` row (the night's mapper); asked
    again of a kept night, the night's own record gives them."""
    arrived = _arrived(night_dir, profile.door)
    said = _json(night_dir / RECORD) or {}
    if from_verify is None:
        from_verify = ((said.get("coverage") or {}).get("facts_from_verify")) or {}
    reads = frozenset(reads) if reads is not None else None
    # SS-MIX2: the storage's canonical tables are not data types; only what the reader names by type is
    if profile.door == "ssmix2":
        read = (_json(night_dir / READER) or {}).get("read") or {}
        typed = {k for k in read if ":" not in k}
        undeclared = sorted(t for t in typed if t not in profile.data_types and arrived.get(t))
    else:
        undeclared = sorted(t for t, n in arrived.items() if n and t not in profile.data_types)
    not_read = [t for t in profile.data_types if reads is not None and t not in reads and not arrived.get(t)]
    unmapped = _unmapped(night_dir)
    states = {name: t.states() for name, t in sorted(profile.tables.items())}
    return {
        "profile": profile.stamp(),
        "night_profile": night_profile(night_dir),
        "data_types": [{"type": t, "rows": arrived.get(t, 0)} for t in profile.data_types],
        "not_read": not_read,
        "not_arrived": [t for t in profile.data_types if not arrived.get(t) and t not in not_read],
        "not_declared": [{"type": t, "rows": arrived[t]} for t in undeclared],
        "unmapped": {t: {"codes": len(c), "rows": sum(c.values())} for t, c in sorted(unmapped.items())},
        "tables": {
            name: {"rows": s[VERIFIED] + s[VERIFY], VERIFIED: s[VERIFIED], VERIFY: s[VERIFY]}
            for name, s in states.items()
        },
        "facts_from_verify": {t: int(n) for t, n in sorted(from_verify.items()) if n},
        "units_not_read": {t: {"codes": len(c), "rows": sum(c.values())} for t, c in sorted(_units(night_dir).items())},
    }


def summary(cov: dict[str, Any]) -> dict[str, Any]:
    """The few numbers the night's audit event and the data-ops page carry."""
    return {
        **cov["profile"],
        "types_declared": len(cov["data_types"]),
        "types_arrived": sum(1 for d in cov["data_types"] if d["rows"]),
        "not_arrived": cov["not_arrived"],
        "not_read": cov.get("not_read", []),
        "not_declared": [d["type"] for d in cov["not_declared"]],
        "unmapped_codes": sum(u["codes"] for u in cov["unmapped"].values()),
        "unmapped_rows": sum(u["rows"] for u in cov["unmapped"].values()),
        "verify_rows": sum(t[VERIFY] for t in cov["tables"].values()),
        "facts_from_verify": sum(cov.get("facts_from_verify", {}).values()),
        "units_not_read_rows": sum(u["rows"] for u in cov.get("units_not_read", {}).values()),
    }


def lines(cov: dict[str, Any]) -> list[str]:
    """The coverage lines as text, for the command line and the night's log."""
    p = cov["profile"]
    out = [f"site profile {p['id']} {p['version']} (digest {p['digest'][:12]}) for site {p['site_id']}"]
    night = cov.get("night_profile")
    if night is None:
        out.append("this night was read without a site profile")
    elif night.get("digest") != p["digest"]:
        said = f"{night.get('id')} {night.get('version')} ({str(night.get('digest'))[:12]})"
        out.append(f"this night was read with {said}, not this profile")
    arrived = sum(1 for d in cov["data_types"] if d["rows"])
    out.append(f"data types: {arrived} of {len(cov['data_types'])} declared arrived")
    out += [f"  {d['type']}: {d['rows']} rows" for d in cov["data_types"]]
    if cov.get("not_read"):
        out.append(f"declared, not read by this version: {', '.join(cov['not_read'])}")
    if cov["not_arrived"]:
        out.append(f"declared, none arrived: {', '.join(cov['not_arrived'])}")
    if cov["not_declared"]:
        out.append("arrived, not declared: " + ", ".join(f"{d['type']} ({d['rows']})" for d in cov["not_declared"]))
    if cov["unmapped"]:
        out.append("codes no table maps (by table):")
        out += [f"  {t}: {u['codes']} codes, {u['rows']} rows" for t, u in cov["unmapped"].items()]
    else:
        out.append("codes no table maps: none")
    out.append("table rows still to verify:")
    out += [f"  {n}: {t[VERIFY]} of {t['rows']}" for n, t in cov["tables"].items()]
    for t, u in (cov.get("units_not_read") or {}).items():
        out.append(f"problem: {t}: {u['rows']} results of {u['codes']} codes in a unit their row does not give "
                   "(kept without a value, never converted)")  # fmt: skip
    facts = cov.get("facts_from_verify") or {}
    out.append("facts resting on a row still to verify: " + (", ".join(f"{t} {n}" for t, n in facts.items()) or "none"))
    return out


# --------------------------------------------------------------- the site set-up store (D-135) and the profile
def store_wins(profile: Profile, confirmed: Mapping[tuple[str, str, str], Mapping[str, str]]) -> dict[str, str]:
    """The lab code -> LOINC the site uses when both homes map a code: the site set-up store's confirmed map (a named
    person's recorded act, D-135) wins over the profile's lab table (coordinator's ruling on #1128). ``confirmed`` is
    ``sitesetup.store.SetupStore.mapping``. Not yet applied at night: the adapter does not read that store."""
    out = {code: r.target for t in profile.tables.values() if "mapping.lab" in t.used_by for code, r in t.rows.items()}
    for (domain, system, code), m in confirmed.items():
        if domain == "observation" and system.rsplit(":", 1)[-1] in ("lab-code",) and m.get("code"):
            out[code] = str(m["code"])
    return out


def disagreements(
    profile: Profile, confirmed: Mapping[tuple[str, str, str], Mapping[str, str]]
) -> list[dict[str, str]]:
    """Every lab code both homes map, to different standard codes: the work list's ``disagree`` rows."""
    table = next((t for t in profile.tables.values() if "mapping.lab" in t.used_by), None)
    if table is None:
        return []
    out = []
    for (domain, system, code), m in sorted(confirmed.items()):
        row = table.rows.get(code)
        lab = domain == "observation" and system.rsplit(":", 1)[-1] == "lab-code"
        if lab and row is not None and m.get("code") and row.target != m["code"]:
            out.append({"kind": "disagree", "table": table.name, "code": code, "rows": "",
                        "target": f"profile {row.target}; site set-up {m['code']} (wins)", "state": row.state,
                        "file": table.file, "line": str(row.line)})  # fmt: skip
    return out


def worklist(
    profile: Profile,
    night_dir: Path | None,
    confirmed: Mapping[tuple[str, str, str], Mapping[str, str]] | None = None,
) -> list[dict[str, str]]:
    """The data manager's list: every code of the night no table maps (most rows first), every lab code the site
    set-up store maps otherwise than the profile, then every ``verify`` row. Codes and counts only."""
    out: list[dict[str, str]] = []
    if night_dir is not None:
        for table, codes in _unmapped(night_dir).items():
            for code, n in sorted(codes.items(), key=lambda kv: (-kv[1], kv[0])):
                out.append({"kind": "unmapped", "table": table, "code": code, "rows": str(n), "target": "",
                            "state": "", "file": "", "line": ""})  # fmt: skip
        for table, codes in _units(night_dir).items():
            for code, n in sorted(codes.items(), key=lambda kv: (-kv[1], kv[0])):
                out.append({"kind": "unit", "table": table, "code": code, "rows": str(n), "target": "",
                            "state": "", "file": "", "line": ""})  # fmt: skip
    out += disagreements(profile, confirmed or {})
    for t, r in profile.verify_rows():
        out.append({"kind": "verify", "table": t.name, "code": r.code, "rows": "", "target": r.target,
                    "state": r.state, "file": t.file, "line": str(r.line)})  # fmt: skip
    return out


def worklist_csv(rows: Sequence[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=WORKLIST_COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: _cell(r.get(k, "")) for k in WORKLIST_COLUMNS})
    return buf.getvalue()


def _cell(v: str) -> str:
    """A cell a spreadsheet will not run as a formula: a value starting with = + - @, a tab or a carriage return
    gets a leading quote."""
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


# ---------------------------------------------------------------------------------------------- the command
def _settings() -> Any:
    """The box's settings (``tb_common.config``): the site id, its zone and locale, ``settings.profiles``."""
    from tb_common.config import get_config

    return get_config()


def _check_with_settings(p: Profile, cfg: Any) -> None:
    from tb_common.derived import country_of

    profiles = cfg.settings.profiles.model_dump() if cfg.settings.profiles is not None else {}
    check_settings(p, country=country_of(cfg.env.tz, cfg.settings.site.locale), standards=profiles)


def _mapping(path: Path | None) -> Any:
    from adapter.mapping.engine import Mapping as MappingFile

    return MappingFile.load(path) if path is not None else None


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="adapter.site_profile", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate a profile folder")
    c.add_argument("folder", type=Path)
    c.add_argument("--mapping", type=Path, help="the site mapping its mapping.<look-up> tables are held to")
    ld = sub.add_parser("load", help="make a profile the box's (recorded and audited)")
    ld.add_argument("folder", type=Path)
    ld.add_argument("--lake", type=Path, required=True)
    ld.add_argument("--by", required=True, help="who loads it (recorded)")
    ld.add_argument("--audit", type=Path, help="the audit folder (default: TB_AUDIT_DIR)")
    ld.add_argument("--mapping", type=Path, help="the site mapping (needed when a table is a mapping's look-up)")
    ul = sub.add_parser("unload", help="take the profile off the box (recorded and audited)")
    ul.add_argument("--lake", type=Path, required=True)
    ul.add_argument("--by", required=True, help="who takes it off (recorded)")
    ul.add_argument("--audit", type=Path, help="the audit folder (default: TB_AUDIT_DIR)")
    h = sub.add_parser("history", help="the profiles this box has read, in order")
    h.add_argument("--lake", type=Path, required=True)
    wh = sub.add_parser("which", help="the profile a night was read with")
    wh.add_argument("--lake", type=Path, required=True)
    wh.add_argument("--snapshot", required=True)
    cv = sub.add_parser("coverage", help="a night's coverage lines")
    cv.add_argument("--night", type=Path, required=True, help="the night's snapshot folder (lake/ndjson/<date>)")
    cv.add_argument("--profile", type=Path, help="the profile folder (default: the site's)")
    cv.add_argument("--mapping", type=Path, help="the site mapping (names the tables this version reads)")
    cv.add_argument("--json", action="store_true")
    wl = sub.add_parser("worklist", help="unmapped codes, disagreements and verify rows as CSV")
    wl.add_argument("--night", type=Path, help="the night's snapshot folder; without it, no unmapped codes")
    wl.add_argument("--profile", type=Path, help="the profile folder (default: the site's)")
    wl.add_argument("--setup-db", help="the trial database URL: compare with the site set-up store's maps (D-135)")
    wl.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "check":
            p = load(a.folder)
            needs = any(u.startswith("mapping.") for t in p.tables.values() for u in t.used_by)
            if needs and a.mapping is None:
                print("refused: a table is a mapping's look-up: give --mapping <the site mapping>", file=sys.stderr)
                return 2
            if a.mapping is not None:
                check_mapping(p, _mapping(a.mapping))
            print(f"{p.id} {p.version} for site {p.site_id} ({p.country}, {p.door}): digest {p.digest}")
            for name, t in sorted(p.tables.items()):
                s = t.states()
                print(f"  {name}: {len(t.rows)} rows, {s[VERIFIED]} verified, {s[VERIFY]} to verify ({t.file})")
            return 0
        if a.cmd == "load":
            p = load(a.folder)
            if any(u.startswith("mapping.") for t in p.tables.values() for u in t.used_by):
                if a.mapping is None:
                    print("refused: a table is a mapping's look-up: give --mapping <the site mapping>", file=sys.stderr)
                    return 2
                check_mapping(p, _mapping(a.mapping))
            cfg = _settings()
            _check_with_settings(p, cfg)
            audit = a.audit or (Path(os.environ["TB_AUDIT_DIR"]) if os.environ.get("TB_AUDIT_DIR") else None)
            ch = activate(p, a.lake, site_id=cfg.settings.site.id, by=a.by, audit_dir=audit, tz=cfg.env.tz or "UTC")
            print("already the box's profile" if ch is None else json.dumps(ch, ensure_ascii=False))
            return 0
        if a.cmd == "unload":
            audit = a.audit or (Path(os.environ["TB_AUDIT_DIR"]) if os.environ.get("TB_AUDIT_DIR") else None)
            cfg = _settings()
            print(json.dumps(deactivate(a.lake, by=a.by, audit_dir=audit, tz=cfg.env.tz or "UTC", why="unload")))
            return 0
        if a.cmd == "history":
            for e in read_record(a.lake).get("history", []):
                said = f"{e['id']} {e['version']} ({e['digest'][:12]}" if e.get("digest") else "(no profile"
                print(f"{e['at']} {e['by']}: {said}, {e['direction']})")
            return 0
        if a.cmd == "which":
            stamp = night_profile(a.lake / "ndjson" / a.snapshot)
            print(json.dumps(stamp) if stamp else "read without a site profile")
            return 0
        folder = a.profile or find()
        if folder is None:
            print("no site profile: give --profile or put one in the site mapping folder's profile/", file=sys.stderr)
            return 2
        p = load(folder)
        if a.cmd == "coverage":
            m = _mapping(a.mapping)
            cov = coverage(p, a.night, reads=readable(p, m.tables) if m is not None else None)
            print(json.dumps(cov, ensure_ascii=False, indent=1) if a.json else "\n".join(lines(cov)))
            return 0
        confirmed: dict[tuple[str, str, str], dict[str, str]] = {}
        if a.setup_db:
            from sitesetup.store import SetupStore

            st = SetupStore(a.setup_db)
            try:
                confirmed = st.mapping("main")
            finally:
                st.close()
        rows = worklist(p, a.night, confirmed)
        a.out.write_text(worklist_csv(rows), encoding="utf-8")
        print(f"{len(rows)} rows written to {a.out}")
        return 0
    except ProfileError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
