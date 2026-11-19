"""Export an approved rule set as a rule-set part for a vendor-signed update bundle (plan 10 row 10D-28; D-1369).

Interim, for the dry run only: the head box that compiled and approved a study hands it to a screen-only site box
through the vendor, until the coordinating centre's study package exists (10D-2 to 10D-4). The part carries criteria
and codes only (``tb_common.ruleset_part.neutral_files``: the protocol's manifest fields and compiled files; no
routing, scope, approver, reviewer, IRB record or site code table; no ``tests/`` folder; nothing of a patient). It is
the version of the approval tag ``<ID>/v<version>`` of this box's repository, refused when that approval was not given
on this box (a seeded example, or a version that arrived in any update). The export is audited on this box before the
part is written (``approve.part_exported``: who, when, the rule set and version, the part's hash; in the approval
family the criteria compiler writes, D-1369). The part holds no time: the same version exported again from the same
release is the same part, byte for byte.

    python -m criteria_compiler.export_part GZQO --out GZQO-1.0.0.part.zip --installed installed.json [--by NAME]
    python -m criteria_compiler.export_part GZQO --out GZQO-1.0.0.part.zip --release "2026.11-1 (release_seq 3)"

``--installed``: the box's ``deploy/updates/installed.json`` (bundle id, release_seq, commit), which names the release
that compiled it; ``--release``: the bundle id (and ``(release_seq N)``), when the file is not at hand (inside the
compiler's container); nothing else is taken, so no free words travel.
``--by``: who runs it (default: the user the command runs as).
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from tb_common.ruleset import SEEDED_TAG, load_approved
from tb_common.ruleset_part import (
    LEFT_OUT_DIRS,
    PART_FORMAT,
    PartRefused,
    arrived,
    build_part,
    origin_of,
)

from criteria_compiler.repo import RulesetRepo

#: ``--release``: a bundle id, optionally `` (release_seq N)``
RELEASE = re.compile(r"^(?P<bundle>[A-Za-z0-9][A-Za-z0-9._-]{0,99})(?: \(release_seq (?P<seq>\d{1,9})\))?$")


class ExportRefused(ValueError):
    pass


def compiled_on(installed: dict[str, Any] | None = None, release: str | None = None) -> dict[str, Any]:
    """The compiling box's release from its installed record (the release a rule-set-only bundle rode on, D-1369),
    or as its bundle id (and release_seq): no free words."""
    if installed is not None:
        on = {"bundle_id": installed.get("release_bundle_id") or installed.get("bundle_id"),
              "release_seq": installed.get("release_seq"), "commit": installed.get("commit")}  # fmt: skip
        return {k: v for k, v in on.items() if v is not None}
    if release and release.strip():
        m = RELEASE.match(" ".join(release.split()))
        if not m:
            raise ExportRefused("--release takes a bundle id, optionally followed by (release_seq N), nothing else")
        return {"bundle_id": m["bundle"], **({"release_seq": int(m["seq"])} if m["seq"] else {})}
    raise ExportRefused("name the release that compiled it: --installed deploy/updates/installed.json or --release")


def export(
    repo: RulesetRepo, ruleset_id: str, on: dict[str, Any], *, audit: Any = None, by: str = ""
) -> tuple[bytes, dict[str, Any]]:
    """``(part zip, ORIGIN record)`` of the approved version of ``ruleset_id`` in this box's repository; with
    ``audit``, the event ``approve.part_exported`` (who, the rule set and version, the part's hash, the file count;
    its time is the export's), written before the part is returned: a failed write exports nothing."""
    rs = load_approved(repo.path, ruleset_id)  # a draft, a version with no tag, a seeded one on a site box: refused
    tag = f"{ruleset_id}/v{rs.version}"
    if f"refs/tags/{tag}".encode() not in repo.refs:
        raise ExportRefused(f"{tag}: no approval tag in this box's repository")
    message = repo.tag_message(tag)
    if not message or SEEDED_TAG in message:
        raise ExportRefused(f"{tag}: its approval names nobody at this box (a shipped example); not exported")
    if arrived(message):
        raise ExportRefused(f"{tag} arrived in an update (approved elsewhere); only a box's own approval is carried")
    files = {p[len(ruleset_id) + 1 :]: b for p, b in repo.files(f"refs/tags/{tag}", f"{ruleset_id}/").items()}
    manifest = yaml.safe_load(files.get("manifest.yaml", b"").decode("utf-8")) or {}
    if manifest.get("status") != "approved" or str(manifest.get("version")) != rs.version:
        raise ExportRefused(f"{tag}: the tagged manifest is not the approved v{rs.version}")
    models = manifest.get("models") or {}
    origin: dict[str, Any] = {
        "format": PART_FORMAT,
        "ruleset": ruleset_id,
        "version": rs.version,
        "left_out": [d for d in LEFT_OUT_DIRS if any(p.startswith(d) for p in files)],
        "approval_tag": tag,
        "compiled_on": on,
        "pins": {
            "judge_prompt": models.get("judge_prompt"),
            "terminology_release": manifest.get("terminology_release"),
        },
    }
    try:
        data = build_part(ruleset_id, files, origin)
    except PartRefused as exc:
        raise ExportRefused(f"{tag}: {exc}") from exc
    origin = origin_of(data) or origin
    if audit is not None:
        audit.append("approve.part_exported", actor=by or "export_part", ruleset=ruleset_id,
                     ruleset_version=rs.version, output_sha=origin["part_sha256"],
                     detail={"files": len(origin["files"]), "left_out": origin["left_out"],
                             "compiled_on": origin["compiled_on"]})  # fmt: skip
    return data, origin


def main(argv: list[str] | None = None) -> int:
    from tb_common.audit_writer import open_audit
    from tb_common.config import load

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ruleset")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--installed", type=Path, help="deploy/updates/installed.json of this box")
    ap.add_argument("--release", help="the release that compiled it, in words")
    ap.add_argument("--by", help="who runs the export (default: the user the command runs as)")
    args = ap.parse_args(argv)
    installed = json.loads(args.installed.read_text(encoding="utf-8")) if args.installed else None
    cfg = load()
    repo = RulesetRepo(cfg.env.rulesets_path)
    try:
        by = args.by or f"host:{getpass.getuser()}"
    except Exception:  # no user name in the container: the event still says it was a host command
        by = "host command"
    try:
        data, origin = export(repo, args.ruleset, compiled_on(installed, args.release),
                              audit=open_audit(cfg.env.audit_path, cfg.env.tz), by=by)  # fmt: skip
    except (ExportRefused, ValueError, RuntimeError) as exc:
        print(f"export REFUSED: {exc}", file=sys.stderr)
        return 1
    args.out.write_bytes(data)
    print(json.dumps({"part": str(args.out), "ruleset": origin["ruleset"], "version": origin["version"],
                      "part_sha256": origin["part_sha256"]}))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
