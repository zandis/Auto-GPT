"""Install a vendor-approved ruleset from a verified offline update (SPEC §10.1; DECISIONS D-77).

The zip holds one ruleset directory (``<ID>/manifest.yaml``, ``ir/``, ``cql/``, ``sql/``, ``valuesets/``, ``tests/``)
or the same files at the top level. The manifest must be ``status: approved`` with an equivalence result at or above
the site threshold; the files are committed to ``main`` of the ruleset repository, tagged ``<ID>/v<version>`` (an
existing tag is never moved) and materialized for the orchestrator.

A rule-set part (``ORIGIN.json`` at the zip's root: a rule set compiled and approved on another box, carried in a
vendor-signed bundle for the dry run, D-1369) is checked first (``tb_common.ruleset_part.check_origin``: its files and
their content sha256); its tag records that it arrived in a vendor bundle, from which release, with which hash.

    python -m criteria_compiler.import_ruleset ruleset.zip --by update:2026.10-1
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import PurePosixPath
from typing import Any

import yaml
from tb_common.ruleset import SEEDED_TAG
from tb_common.ruleset_part import PartRefused, check_origin, origin_of, tag_note
from tb_common.zipcap import ZipRefused, check_ruleset_zip

from criteria_compiler.repo import RulesetRepo


class ImportRefused(ValueError):
    pass


def read_zip(data: bytes) -> tuple[str, dict[str, bytes], dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        try:  # 10G-6, D-1102: members, sizes, ratio and names from the central directory, before any read
            names = [n for n in check_ruleset_zip(z) if not n.endswith("/")]
        except ZipRefused as exc:
            raise ImportRefused(str(exc)) from exc
        manifests = [n for n in names if PurePosixPath(n).name == "manifest.yaml" and len(PurePosixPath(n).parts) <= 2]
        if len(manifests) != 1:
            raise ImportRefused("the zip must hold exactly one ruleset manifest.yaml")
        prefix = str(PurePosixPath(manifests[0]).parent)
        prefix = "" if prefix == "." else prefix + "/"
        files = {n[len(prefix) :]: z.read(n) for n in names if n.startswith(prefix)}
    manifest = yaml.safe_load(files["manifest.yaml"].decode("utf-8")) or {}
    rid = str(manifest.get("id") or "")
    if not rid or (prefix and prefix.rstrip("/") != rid):
        raise ImportRefused("manifest id does not match the ruleset directory")
    return rid, files, manifest


def install(repo: RulesetRepo, data: bytes, by: str, min_equivalence: float = 98.0) -> str:
    rid, files, m = read_zip(data)
    if m.get("status") != "approved":
        raise ImportRefused(f"{rid}: only approved rulesets are installed (status {m.get('status')!r})")
    equivalence = m.get("equivalence")
    eq = equivalence.get("overall_pct") if isinstance(equivalence, dict) else None
    if eq is None or float(eq) < min_equivalence:
        raise ImportRefused(f"{rid}: equivalence {eq} below the compile gate {min_equivalence}%")
    try:  # D-1369: a part from another box: its record and hash before anything is written
        origin = origin_of(data)
        if origin is not None:
            check_origin(origin, rid, str(m.get("version")), files)
    except PartRefused as exc:
        raise ImportRefused(f"{rid}: {exc}") from exc
    tag = f"{rid}/v{m.get('version')}"
    message = f"{tag} (offline update, {by})" + (f"; {tag_note(origin, by)}" if origin is not None else "")
    if f"refs/tags/{tag}".encode() in repo.refs:
        existing = {p[len(rid) + 1 :]: b for p, b in repo.files(f"refs/tags/{tag}", f"{rid}/").items()}
        if existing == files:
            # same content already installed. D-640: when what is there is the example the first start seeded, the
            # operator's install is what the tag records from now on (a site box refuses a seeded approval)
            if SEEDED_TAG in repo.tag_message(tag):
                repo.retag(tag, message)
            return tag
        raise ImportRefused(f"{tag} already exists with different content; bump the version")
    repo.write_dir("main", "main", f"{rid}/", files, f"install {tag} ({by})", author=by.replace(" ", "_"))
    repo.tag(tag, "main", message)
    repo.materialize(rid, "main")
    return tag


def main(argv: list[str] | None = None) -> int:
    from tb_common.config import load

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip")
    ap.add_argument("--by", default="offline-update")
    args = ap.parse_args(argv)
    cfg = load()
    repo = RulesetRepo(cfg.env.rulesets_path)
    gate = float(cfg.settings.thresholds.equivalence_min_pct or 98.0) if cfg.settings.thresholds else 98.0
    with open(args.zip, "rb") as fh:
        data = fh.read()
    tag = install(repo, data, args.by, gate)
    hits = negated_hits(data)
    for h in hits:  # card 10A-1: installed as approved; a person recompiles these lines (the scan lists them again)
        print(f"WARNING {h}: its line may negate what its logic asks the presence of; recompile and approve",
              file=sys.stderr)  # fmt: skip
    arrived = {"arrived_in_vendor_bundle": True} if origin_of(data) is not None else {}  # D-1369
    print(json.dumps({"installed": tag, **arrived, **({"negated_inclusions": hits} if hits else {})}))
    return 0


def negated_hits(data: bytes) -> list[str]:
    """Card 10A-1: the ids of the zip's inclusions whose line may negate what their logic asks the presence of. The
    install is not refused (the ruleset is the vendor's approved one); the ids are reported for a person to act on."""
    from tb_common.ruleset import Ruleset

    from criteria_compiler.negated_inclusions import ruleset_hits

    _, files, _ = read_zip(data)
    return [h.criterion for h in ruleset_hits(Ruleset.from_files(files))]


if __name__ == "__main__":
    raise SystemExit(main())
