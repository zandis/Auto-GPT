"""The waivers of the supply-chain allow-list and the VEX of a release (card 10G-8, D-1339).

    python -m tools.vex check [--release-date 2026-12-01]     # make lint and CI job `docs` run it without a date
    python -m tools.vex write --release-date 2026-12-01 --out dist/sbom/trialbox-vex.cdx.json [--version 1.0.0]

A waiver is an entry of ``deploy/supply-chain-allowlist.yaml`` that lets a vulnerability gate pass: every entry of
``vulnerabilities`` and of ``os_packages_unreadable`` (tools/supply_chain/allowlist.py). The licence entries and
budgets are no vulnerability waiver and are not read here.

``check`` fails (exit 1) on a waiver with no owner (missing or empty; the owner's form is not ruled on here), no
``date`` (the day the ruling that accepted it was given), no reason, no or a malformed ``review_by``, or a ``date``
after its ``review_by``. Only with ``--release-date`` does it also fail on a ``review_by`` before that date: lint
and CI run it without one, so no calendar day turns every lane red; the review date against today stays with
``make allowlist-check`` (tools/supply_chain/allowlist.py), and ``write`` always applies its release date. It reads
one file and makes no network call. The rest of the entry's rules (reason length, dates at most 180 days ahead,
package, image) stay with ``make allowlist-check``.

``write`` checks first and then writes one CycloneDX 1.6 VEX document for the release (the form of the CycloneDX
SBOMs that Syft writes for every image and for the lock, tools/supply_chain/sbom.py): one ``vulnerabilities`` record
per vulnerability waiver, with the image and package it covers, the owner, the dates and the reason as given. The
status is read from the reason, never guessed: a reason that starts "Not reachable:" is ``not_affected`` with the
justification ``code_not_reachable``; every other waiver is ``exploitable`` (CycloneDX: "may be directly or
indirectly exploitable") with the response ``update``, because the ledger accepts it until a patched upstream image
is pinned and records no analysis that would say more. The document is deterministic: the same allow-list, lock,
version and release date give the same bytes (the timestamp is the release date, the serial number a UUID made from
the content).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from tools.supply_chain.allowlist import image_repository

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "deploy" / "supply-chain-allowlist.yaml"
IMAGES_LOCK = ROOT / "deploy" / "images.lock"
WAIVER_LISTS = ("vulnerabilities", "os_packages_unreadable")
NOT_REACHABLE = "Not reachable:"
LOCK_SUBJECT = "requirements.lock"  # a vulnerability entry with no image covers the Python lock (pip-audit)
SPEC_VERSION = "1.6"
DECISION = "D-1339"


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


def _text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    return value.strip() if isinstance(value, str) else ""


def load(path: Path = ALLOWLIST) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def waivers(data: dict[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
    """(list name, index, entry) of every waiver, in file order; a non-mapping entry is returned as an empty one."""
    out: list[tuple[str, int, dict[str, Any]]] = []
    for name in WAIVER_LISTS:
        rows = data.get(name) or []
        for i, raw in enumerate(rows if isinstance(rows, list) else []):
            out.append((name, i, raw if isinstance(raw, dict) else {}))
    return out


def check(data: dict[str, Any], release_date: dt.date | None) -> list[str]:
    """The problems of the waivers; ``release_date=None`` leaves the review-by rule out (structure only)."""
    errors: list[str] = []
    for name, i, raw in waivers(data):
        label = _text(raw, "id") or _text(raw, "image")
        where = f"{name}[{i}]" + (f" ({label})" if label else "")
        if not _text(raw, "owner"):
            errors.append(f"{where}: no owner; every waiver names who answers for it")
        if not _text(raw, "reason"):
            errors.append(f"{where}: no reason")
        since, until = _date(raw.get("date")), _date(raw.get("review_by"))
        if since is None:
            errors.append(f"{where}: no date (YYYY-MM-DD, the day the waiver was accepted), got {raw.get('date')!r}")
        if until is None:
            errors.append(f"{where}: no review_by (YYYY-MM-DD), got {raw.get('review_by')!r}")
        if since is not None and until is not None and since > until:
            errors.append(f"{where}: date {since} is after its review_by {until}")
        if release_date is not None and until is not None and until < release_date:
            errors.append(
                f"{where}: review_by {until} is before the release date {release_date}; review it or remove it"
            )
    return errors


def _digests(lock: Path) -> dict[str, str]:
    """Image repository -> pinned digest of the third-party images of the lock; empty when it cannot be read."""
    try:
        doc = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = doc.get("third_party") if isinstance(doc, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {
        image_repository(e["image"]): str(e["digest"])
        for e in entries.values()
        if isinstance(e, dict) and isinstance(e.get("image"), str) and e.get("digest")
    }


def _ts(day: dt.date) -> str:
    return f"{day.isoformat()}T00:00:00Z"


def build(data: dict[str, Any], *, version: str, release_date: dt.date, digests: dict[str, str]) -> dict[str, Any]:
    """The CycloneDX VEX document of the waivers (call ``check`` first)."""
    subjects: dict[str, dict[str, Any]] = {}

    def subject(name: str) -> dict[str, Any]:
        if name not in subjects:
            comp: dict[str, Any] = {
                "type": "file" if name == LOCK_SUBJECT else "container",
                "bom-ref": f"subject:{name}",
                "name": name,
            }
            if name in digests:
                comp["version"] = digests[name]
            comp["components"] = {}
            subjects[name] = comp
        return subjects[name]

    vulns: list[dict[str, Any]] = []
    for name, _, raw in waivers(data):
        reason, owner = _text(raw, "reason"), _text(raw, "owner")
        since, until = _date(raw.get("date")), _date(raw.get("review_by"))
        assert since is not None and until is not None  # check() ran
        props = [
            {"name": "trialbox:owner", "value": owner},
            {"name": "trialbox:waiver-date", "value": since.isoformat()},
            {"name": "trialbox:review-by", "value": until.isoformat()},
        ]
        if name == "os_packages_unreadable":
            comp = subject(_text(raw, "image"))
            comp.setdefault("properties", []).append({"name": "trialbox:os-packages-unreadable", "value": reason})
            comp["properties"].extend(props)
            continue
        image = _text(raw, "image") or LOCK_SUBJECT
        package, vid = _text(raw, "package"), _text(raw, "id")
        comp = subject(image)
        pref = f"subject:{image}#{package}"
        comp["components"].setdefault(package, {"type": "library", "bom-ref": pref, "name": package})
        if reason.startswith(NOT_REACHABLE):
            analysis: dict[str, Any] = {"state": "not_affected", "justification": "code_not_reachable"}
        else:
            analysis = {"state": "exploitable", "response": ["update"]}
        analysis.update({"detail": reason, "firstIssued": _ts(since)})
        record: dict[str, Any] = {"bom-ref": f"waiver:{vid}@{image}#{package}", "id": vid}
        if vid == "*":  # D-622: every finding of this package in this image; the ledger names no ids
            record["description"] = f"every finding of {package} in {image} (one package-wide waiver, D-622)"
        record.update({"analysis": analysis, "affects": [{"ref": pref}], "properties": props})
        vulns.append(record)

    components = []
    for name in sorted(subjects):
        comp = subjects[name]
        inner = [comp["components"][k] for k in sorted(comp["components"])]
        if inner:
            comp["components"] = inner
        else:
            del comp["components"]
        components.append(comp)
    vulns.sort(key=lambda v: (v["id"], v["bom-ref"]))
    body: dict[str, Any] = {
        "metadata": {
            "timestamp": _ts(release_date),
            "component": {"type": "application", "bom-ref": "trialbox", "name": "trialbox", "version": version},
            "properties": [
                {"name": "trialbox:source", "value": "deploy/supply-chain-allowlist.yaml"},
                {"name": "trialbox:decision", "value": DECISION},
            ],
        },
        "components": components,
        "vulnerabilities": vulns,
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"urn:trialbox:vex:{version}:{digest}")
    return {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        **body,
    }


def dumps(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _version() -> str:
    from tools.release import version

    return version()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.vex", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="fail on a waiver without an owner, a date or a reason, or past its review_by")
    c.add_argument("--allowlist", type=Path, default=ALLOWLIST)
    c.add_argument(
        "--release-date", type=dt.date.fromisoformat, default=None, help="also fail on a review_by before this date"
    )
    w = sub.add_parser("write", help="write the release's CycloneDX VEX from the waivers")
    w.add_argument("--allowlist", type=Path, default=ALLOWLIST)
    w.add_argument("--images-lock", type=Path, default=IMAGES_LOCK)
    w.add_argument("--release-date", type=dt.date.fromisoformat, required=True)
    w.add_argument("--version", default=None, help="default: [project] version of pyproject.toml")
    w.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        data = load(a.allowlist)
    except (OSError, yaml.YAMLError) as exc:
        print(f"vex: cannot read {a.allowlist}: {exc}", file=sys.stderr)
        return 2
    release_date: dt.date | None = a.release_date
    errors = check(data, release_date)
    for e in errors:
        print(f"vex: {e}", file=sys.stderr)
    n = len(waivers(data))
    if errors:
        on = f" (release date {release_date})" if release_date else ""
        print(f"vex: FAIL, {len(errors)} problems in {n} waivers{on}", file=sys.stderr)
        return 1
    if a.cmd == "check":
        on = f" on or after {release_date}" if release_date else ""
        print(f"vex: {n} waivers, each with an owner, a date, a reason and a review_by{on}")
        return 0
    doc = build(data, version=a.version or _version(), release_date=a.release_date, digests=_digests(a.images_lock))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(dumps(doc), encoding="utf-8")
    print(f"vex: wrote {a.out} ({len(doc['vulnerabilities'])} vulnerability records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
