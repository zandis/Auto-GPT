"""The supply-chain allow-list (D-186): ``deploy/supply-chain-allowlist.yaml``.

A finding is accepted only by a written entry: who may ship with it, why, and until when. Two lists:

    vulnerabilities:
      - id: GHSA-xxxx-xxxx-xxxx          # or CVE-..., PYSEC-...; matches the finding id or any alias
        package: pillow                  # optional: the entry then covers this package only
        reason: Not reachable: ...       # required, a sentence a reviewer can check
        review_by: 2027-01-31            # required ISO date, at most 180 days ahead; after it the gate fails
        owner: security owner            # optional
    licences:
      - package: psycopg
        class: lgpl                      # lgpl, gpl or agpl, as the licence report classes it; a stricter class
                                         # (LGPL -> GPL) is a new finding and fails again
        reason: Used unmodified as an installed package; licence text in the notices
        review_by: 2027-05-01

The checker rejects an entry with no reason, a reason shorter than 20 characters, no or a bad ``review_by``, a
date in the past or more than 180 days ahead, an unknown key, or a duplicate.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = ROOT / "deploy" / "supply-chain-allowlist.yaml"
MIN_REASON = 20
MAX_AHEAD_DAYS = 180

_VULN_KEYS = {"id", "package", "reason", "review_by", "owner"}
_LIC_KEYS = {"package", "class", "reason", "review_by", "owner"}
LICENCE_CLASSES = ("lgpl", "gpl", "agpl")


@dataclass(frozen=True)
class VulnEntry:
    id: str
    package: str | None
    reason: str
    review_by: dt.date


@dataclass(frozen=True)
class LicenceEntry:
    package: str
    cls: str
    reason: str
    review_by: dt.date


@dataclass
class Allowlist:
    vulnerabilities: list[VulnEntry]
    licences: list[LicenceEntry]

    def vuln(self, ids: set[str], package: str) -> VulnEntry | None:
        """The entry accepting a finding known by any of ``ids`` in ``package``, if one does."""
        wanted = {i.upper() for i in ids}
        for e in self.vulnerabilities:
            if e.id.upper() in wanted and (e.package is None or e.package == norm(package)):
                return e
        return None

    def licence(self, package: str, cls: str) -> LicenceEntry | None:
        for e in self.licences:
            if e.package == norm(package) and e.cls == cls:
                return e
        return None


def norm(name: str) -> str:
    """PEP 503 name form, so ``Pillow`` and ``pillow`` match."""
    return name.strip().lower().replace("_", "-").replace(".", "-")


def _date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _common(where: str, raw: dict[str, Any], keys: set[str], today: dt.date | None) -> tuple[list[str], dt.date | None]:
    errors = [f"{where}: unknown key {k!r}" for k in sorted(set(raw) - keys)]
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append(f"{where}: no reason; every entry must say why it is accepted")
    elif len(reason.strip()) < MIN_REASON:
        errors.append(f"{where}: reason {reason.strip()!r} is too short (at least {MIN_REASON} characters)")
    when = _date(raw.get("review_by"))
    if when is None:
        errors.append(f"{where}: review_by must be an ISO date (YYYY-MM-DD), got {raw.get('review_by')!r}")
    elif today is not None:
        if when < today:
            errors.append(f"{where}: review_by {when} has passed; review the entry or remove it")
        elif (when - today).days > MAX_AHEAD_DAYS:
            errors.append(f"{where}: review_by {when} is more than {MAX_AHEAD_DAYS} days ahead")
    return errors, when


def parse(data: Any, *, today: dt.date | None) -> tuple[Allowlist, list[str]]:
    """Validate an allow-list document. ``today=None`` checks structure only (no expiry), for tests of the file."""
    errors: list[str] = []
    out = Allowlist(vulnerabilities=[], licences=[])
    if data is None:
        return out, errors
    if not isinstance(data, dict):
        return out, ["the allow-list must be a mapping with 'vulnerabilities' and 'licences'"]
    errors += [f"unknown top-level key {k!r}" for k in sorted(set(data) - {"vulnerabilities", "licences"})]
    vulns = data.get("vulnerabilities") or []
    lics = data.get("licences") or []
    if not isinstance(vulns, list) or not isinstance(lics, list):
        return out, [*errors, "'vulnerabilities' and 'licences' must be lists"]
    seen: set[tuple[str, str | None]] = set()
    for i, raw in enumerate(vulns):
        if not isinstance(raw, dict):
            errors.append(f"vulnerabilities[{i}]: must be a mapping")
            continue
        vid = raw.get("id")
        has_id = isinstance(vid, str) and bool(vid.strip())
        where = f"vulnerabilities[{i}] ({str(vid).strip()})" if has_id else f"vulnerabilities[{i}]"
        errs, when = _common(where, raw, _VULN_KEYS, today)
        if not has_id:
            errs.append(f"{where}: no id")
        pkg = raw.get("package")
        if pkg is not None and (not isinstance(pkg, str) or not pkg.strip()):
            errs.append(f"{where}: package must be a name")
        if isinstance(vid, str) and has_id:
            key = (vid.strip().upper(), norm(pkg) if isinstance(pkg, str) else None)
            if key in seen:
                errs.append(f"{where}: duplicate entry")
            seen.add(key)
        errors += errs
        if not errs and when is not None and isinstance(vid, str):
            out.vulnerabilities.append(
                VulnEntry(vid.strip(), norm(pkg) if isinstance(pkg, str) else None, str(raw["reason"]).strip(), when)
            )
    seen_l: set[tuple[str, str]] = set()
    for i, raw in enumerate(lics):
        if not isinstance(raw, dict):
            errors.append(f"licences[{i}]: must be a mapping")
            continue
        where = f"licences[{i}] ({raw.get('package')})"
        errs, when = _common(where, raw, _LIC_KEYS, today)
        pkg, lic = raw.get("package"), raw.get("class")
        if not isinstance(pkg, str) or not pkg.strip():
            errs.append(f"{where}: no package")
        if lic not in LICENCE_CLASSES:
            errs.append(f"{where}: class must be one of {', '.join(LICENCE_CLASSES)}, got {lic!r}")
        if isinstance(pkg, str) and isinstance(lic, str):
            key_l = (norm(pkg), lic)
            if key_l in seen_l:
                errs.append(f"{where}: duplicate entry")
            seen_l.add(key_l)
        errors += errs
        if not errs and when is not None and isinstance(pkg, str) and isinstance(lic, str):
            out.licences.append(LicenceEntry(norm(pkg), lic, str(raw["reason"]).strip(), when))
    return out, errors


def load(path: Path = ALLOWLIST, *, today: dt.date | None) -> tuple[Allowlist, list[str]]:
    if not path.is_file():
        return Allowlist([], []), [f"{path} is missing"]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return Allowlist([], []), [f"{path} is not valid YAML: {exc}"]
    return parse(data, today=today)
