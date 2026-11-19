"""Export an approved rule set as a rule-set part for a vendor-signed update bundle (plan 10 row 10D-28; D-1369).

Interim, for the dry run only: the head box that compiled and approved a study hands it to a screen-only site box
through the vendor, until the coordinating centre's study package exists (10D-2 to 10D-4). The part carries criteria
and codes only (``tb_common.ruleset_part``: no ``tests/`` folder, nothing of a patient); it is the version of the
approval tag ``<ID>/v<version>`` of this box's repository, refused when that approval is no approval given here (a
seeded example) or itself arrived in a bundle.

    python -m criteria_compiler.export_part GZQO --out GZQO-1.0.0.part.zip --installed installed.json
    python -m criteria_compiler.export_part GZQO --out GZQO-1.0.0.part.zip --release "2026.11-1 (release_seq 3)"

``--installed``: the box's ``deploy/updates/installed.json`` (bundle id, release_seq, commit), which names the release
that compiled it; ``--release``: the same in words, when the file is not at hand (inside the compiler's container).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from tb_common.ruleset import SEEDED_TAG, load_approved
from tb_common.ruleset_part import ARRIVED_MARK, LEFT_OUT_DIRS, PART_FORMAT, build_part, carried, content_sha256

from criteria_compiler.repo import RulesetRepo


class ExportRefused(ValueError):
    pass


def compiled_on(installed: dict[str, Any] | None = None, release: str | None = None) -> dict[str, Any]:
    """The compiling box's release from its installed record (the release a rule-set-only bundle rode on, D-1369),
    or as words."""
    if installed is not None:
        return {"bundle_id": installed.get("release_bundle_id") or installed.get("bundle_id"),
                "release_seq": installed.get("release_seq"), "commit": installed.get("commit")}  # fmt: skip
    if release and release.strip():
        return {"release": release.strip()[:200]}
    raise ExportRefused("name the release that compiled it: --installed deploy/updates/installed.json or --release")


def export(
    repo: RulesetRepo, ruleset_id: str, on: dict[str, Any], now: datetime | None = None
) -> tuple[bytes, dict[str, Any]]:
    """``(part zip, ORIGIN record)`` of the approved version of ``ruleset_id`` in this box's repository."""
    rs = load_approved(repo.path, ruleset_id)  # a draft, a version with no tag, a seeded one on a site box: refused
    tag = f"{ruleset_id}/v{rs.version}"
    if f"refs/tags/{tag}".encode() not in repo.refs:
        raise ExportRefused(f"{tag}: no approval tag in this box's repository")
    message = repo.tag_message(tag)
    if not message or SEEDED_TAG in message:
        raise ExportRefused(f"{tag}: its approval names nobody at this box (a shipped example); not exported")
    if ARRIVED_MARK in message:
        raise ExportRefused(f"{tag} arrived in a vendor bundle itself; only a box's own approval is carried")
    files = {p[len(ruleset_id) + 1 :]: b for p, b in repo.files(f"refs/tags/{tag}", f"{ruleset_id}/").items()}
    manifest = yaml.safe_load(files.get("manifest.yaml", b"").decode("utf-8")) or {}
    if manifest.get("status") != "approved" or str(manifest.get("version")) != rs.version:
        raise ExportRefused(f"{tag}: the tagged manifest is not the approved v{rs.version}")
    part_files = carried(files)
    origin = {
        "format": PART_FORMAT,
        "ruleset": ruleset_id,
        "version": rs.version,
        "content_sha256": content_sha256(part_files),
        "files": sorted(part_files),
        "left_out": [d for d in LEFT_OUT_DIRS if any(p.startswith(d) for p in files)],
        "approval_tag": tag,
        "compiled_on": on,
        "pins": {"models": manifest.get("models"), "terminology_release": manifest.get("terminology_release")},
        "exported_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
    }
    return build_part(ruleset_id, part_files, origin), origin


def main(argv: list[str] | None = None) -> int:
    from tb_common.config import load

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ruleset")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--installed", type=Path, help="deploy/updates/installed.json of this box")
    ap.add_argument("--release", help="the release that compiled it, in words")
    args = ap.parse_args(argv)
    installed = json.loads(args.installed.read_text(encoding="utf-8")) if args.installed else None
    repo = RulesetRepo(load().env.rulesets_path)
    try:
        data, origin = export(repo, args.ruleset, compiled_on(installed, args.release))
    except (ExportRefused, ValueError, RuntimeError) as exc:
        print(f"export REFUSED: {exc}", file=sys.stderr)
        return 1
    args.out.write_bytes(data)
    print(json.dumps({"part": str(args.out), "ruleset": origin["ruleset"], "version": origin["version"],
                      "content_sha256": origin["content_sha256"]}))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
