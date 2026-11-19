"""The site profile on the box (10B-6, commitment C-6, D-1233; design: docs/data/site-profile.md).

The loader and its checks are :mod:`tb_common.site_profile`; this module is where the adapter meets a profile:

* **Where it is.** ``profile/profile.yaml`` in the site's mapping folder (``deploy/site/mapping/profile/``, mounted
  read-only at ``/etc/trialbox/mapping/profile``, kept by every update like the site mapping, D-367; or a folder of
  ``TB_MAPPING_DIR``). One box is one site: one profile. No folder: the box reads as it did before profiles.
* **Activation, versions and audit.** :func:`activate` compares the profile with the one the box last read
  (``site_profile.json`` in the lake folder, beside ``site_key.json``). A new digest is a new profile: it is recorded
  with who, when, the old and new version and both digests, in the record's history and as one ``site_profile.load``
  event in the hash-chained audit. The same id and version with other content is refused (a steward changes the
  version with the content). Rolling back is loading the earlier folder: it is a change like any other, recorded with
  ``direction: back``.
* **The night.** Every night that reads with a profile writes ``site_profile.json`` beside its snapshot (the profile's
  id, version and digest, and the coverage lines), so "which profile produced this night's read" is one file
  (:func:`night_profile`); the ``ingest.done`` event carries the same stamp and the coverage counts.
* **Coverage lines** (:func:`coverage`): which declared data types arrived and how many rows, which arrived that the
  profile does not declare, how many codes and rows no table could map (by table: counts only), and how many rows
  of each table are still ``verify``. From the night's own files, so any kept night can be asked again.
* **The work list** (:func:`worklist`): the unmapped codes and the ``verify`` rows as CSV for the site's data manager.

    python -m adapter.site_profile check <folder>
    python -m adapter.site_profile load <folder> --lake <lake dir> --by <name> [--audit <dir>]
    python -m adapter.site_profile history --lake <lake dir>
    python -m adapter.site_profile which --lake <lake dir> --snapshot <YYYY-MM-DD>
    python -m adapter.site_profile coverage --night <snapshot folder> [--profile <folder>] [--json]
    python -m adapter.site_profile worklist --night <snapshot folder> --profile <folder> --out <file.csv>
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tb_common.site_profile import MANIFEST, VERIFIED, VERIFY, Profile, ProfileError, load

RECORD = "site_profile.json"  # in the lake folder: the active profile and its history; beside a snapshot: the night's
FOLDER = "profile"  # in the site mapping folder
EVENT = "site_profile.load"
WORKLIST_COLUMNS = ("kind", "table", "code", "rows", "target", "state", "file", "line")
# the night's files the coverage lines read (adapter.pipeline writes them)
COMPLETENESS = "completeness.json"
UNMAPPED_CODES = "unmapped_codes.json"
READER = "reader.json"


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


def activate(
    profile: Profile,
    lake_dir: Path,
    *,
    site_id: str,
    by: str,
    audit_dir: Path | None = None,
    tz: str = "UTC",
    door: str | None = None,
) -> dict[str, Any] | None:
    """Make ``profile`` the box's profile. Returns the change recorded, or None when it is the active one already.

    Refused (:class:`ProfileError`): a profile of another site or another door, or the active profile's id and
    version with other content."""
    if profile.site_id != site_id:
        raise ProfileError(MANIFEST, f"this profile is for site {profile.site_id!r}, not {site_id!r}")
    if door is not None and profile.door != door:
        raise ProfileError(MANIFEST, f"this profile describes a {profile.door} source; the box reads {door}")
    rec = read_record(lake_dir)
    old = rec.get("active") or None
    if old and old.get("digest") == profile.digest:
        return None
    if old and old.get("id") == profile.id and old.get("version") == profile.version:
        raise ProfileError(
            MANIFEST,
            f"version {profile.version} was read before with other content (digest {str(old.get('digest'))[:12]}, "
            f"now {profile.digest[:12]}): give the changed profile a new version",
        )
    at = datetime.now(UTC).isoformat(timespec="seconds")
    direction = "first"
    if old:
        same = old.get("id") == profile.id
        direction = "back" if same and _version(profile.version) < _version(str(old.get("version"))) else "forward"
    entry = {**profile.stamp(), "at": at, "by": by, "direction": direction}
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
    }
    if audit_dir is not None:
        from tb_common.audit_writer import open_audit

        open_audit(audit_dir, tz).append(EVENT, actor=by, output_sha=profile.digest, detail=change)
    rec = {"active": entry, "history": [*rec.get("history", []), entry]}
    lake_dir.mkdir(parents=True, exist_ok=True)
    tmp = lake_dir / (RECORD + ".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(lake_dir / RECORD)
    return {**change, "at": at, "by": by}


def night_profile(night_dir: Path) -> dict[str, Any] | None:
    """The profile a night read with (its id, version, digest), or None for a night read without one."""
    try:
        rec = json.loads((night_dir / RECORD).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    return rec.get("profile") if isinstance(rec, dict) else None


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _unmapped(night_dir: Path) -> dict[str, dict[str, int]]:
    """Code -> rows per table, from the mapping's file (every code) and the SS-MIX2 reader's (its top codes)."""
    out: dict[str, dict[str, int]] = {}
    for table, by_lookup in sorted((_json(night_dir / UNMAPPED_CODES) or {}).items()):
        for _name, codes in sorted(by_lookup.items()):
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


def coverage(profile: Profile, night_dir: Path) -> dict[str, Any]:
    """The coverage lines of one night against ``profile``: counts only, never a patient's value."""
    arrived = _arrived(night_dir, profile.door)
    # SS-MIX2: the storage's canonical tables are not data types; only what the reader names by type is
    if profile.door == "ssmix2":
        read = (_json(night_dir / READER) or {}).get("read") or {}
        typed = {k for k in read if ":" not in k}
        undeclared = sorted(t for t in typed if t not in profile.data_types and arrived.get(t))
    else:
        undeclared = sorted(t for t, n in arrived.items() if n and t not in profile.data_types)
    unmapped = _unmapped(night_dir)
    states = {name: t.states() for name, t in sorted(profile.tables.items())}
    return {
        "profile": profile.stamp(),
        "night_profile": night_profile(night_dir),
        "data_types": [{"type": t, "rows": arrived.get(t, 0)} for t in profile.data_types],
        "not_arrived": [t for t in profile.data_types if not arrived.get(t)],
        "not_declared": [{"type": t, "rows": arrived[t]} for t in undeclared],
        "unmapped": {t: {"codes": len(c), "rows": sum(c.values())} for t, c in sorted(unmapped.items())},
        "tables": {
            name: {"rows": s[VERIFIED] + s[VERIFY], VERIFIED: s[VERIFIED], VERIFY: s[VERIFY]}
            for name, s in states.items()
        },
    }


def summary(cov: dict[str, Any]) -> dict[str, Any]:
    """The few numbers the night's audit event and the data-ops page carry."""
    return {
        **cov["profile"],
        "types_declared": len(cov["data_types"]),
        "types_arrived": sum(1 for d in cov["data_types"] if d["rows"]),
        "not_arrived": cov["not_arrived"],
        "not_declared": [d["type"] for d in cov["not_declared"]],
        "unmapped_codes": sum(u["codes"] for u in cov["unmapped"].values()),
        "unmapped_rows": sum(u["rows"] for u in cov["unmapped"].values()),
        "verify_rows": sum(t[VERIFY] for t in cov["tables"].values()),
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
    return out


def worklist(profile: Profile, night_dir: Path | None) -> list[dict[str, str]]:
    """The data manager's list: every code of the night no table maps (most rows first), then every ``verify`` row
    of the profile's tables. Codes and counts only."""
    out: list[dict[str, str]] = []
    if night_dir is not None:
        for table, codes in _unmapped(night_dir).items():
            for code, n in sorted(codes.items(), key=lambda kv: (-kv[1], kv[0])):
                out.append({"kind": "unmapped", "table": table, "code": code, "rows": str(n), "target": "",
                            "state": "", "file": "", "line": ""})  # fmt: skip
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
    """A cell a spreadsheet will not run as a formula (a code beginning with = + - @ gets a leading quote)."""
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="adapter.site_profile", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate a profile folder")
    c.add_argument("folder", type=Path)
    ld = sub.add_parser("load", help="make a profile the box's (recorded and audited)")
    ld.add_argument("folder", type=Path)
    ld.add_argument("--lake", type=Path, required=True)
    ld.add_argument("--by", required=True, help="who loads it (recorded)")
    ld.add_argument("--site", help="settings.site.id (default: the profile's own)")
    ld.add_argument("--audit", type=Path, help="the audit folder (default: TB_AUDIT_DIR)")
    h = sub.add_parser("history", help="the profiles this box has read, in order")
    h.add_argument("--lake", type=Path, required=True)
    wh = sub.add_parser("which", help="the profile a night was read with")
    wh.add_argument("--lake", type=Path, required=True)
    wh.add_argument("--snapshot", required=True)
    cv = sub.add_parser("coverage", help="a night's coverage lines")
    cv.add_argument("--night", type=Path, required=True, help="the night's snapshot folder (lake/ndjson/<date>)")
    cv.add_argument("--profile", type=Path, help="the profile folder (default: the site's)")
    cv.add_argument("--json", action="store_true")
    wl = sub.add_parser("worklist", help="unmapped codes and verify rows as CSV")
    wl.add_argument("--night", type=Path, help="the night's snapshot folder; without it, the verify rows only")
    wl.add_argument("--profile", type=Path, help="the profile folder (default: the site's)")
    wl.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "check":
            p = load(a.folder)
            print(f"{p.id} {p.version} for site {p.site_id} ({p.country}, {p.door}): digest {p.digest}")
            for name, t in sorted(p.tables.items()):
                s = t.states()
                print(f"  {name}: {len(t.rows)} rows, {s[VERIFIED]} verified, {s[VERIFY]} to verify ({t.file})")
            return 0
        if a.cmd == "load":
            import os

            p = load(a.folder)
            audit = a.audit or (Path(os.environ["TB_AUDIT_DIR"]) if os.environ.get("TB_AUDIT_DIR") else None)
            ch = activate(p, a.lake, site_id=a.site or p.site_id, by=a.by, audit_dir=audit)
            print("already the box's profile" if ch is None else json.dumps(ch, ensure_ascii=False))
            return 0
        if a.cmd == "history":
            for e in read_record(a.lake).get("history", []):
                print(f"{e['at']} {e['by']}: {e['id']} {e['version']} ({e['digest'][:12]}, {e['direction']})")
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
            cov = coverage(p, a.night)
            print(json.dumps(cov, ensure_ascii=False, indent=1) if a.json else "\n".join(lines(cov)))
            return 0
        rows = worklist(p, a.night)
        a.out.write_text(worklist_csv(rows), encoding="utf-8")
        print(f"{len(rows)} rows written to {a.out}")
        return 0
    except ProfileError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
