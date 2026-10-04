"""Install a vendor-approved ruleset from a verified offline update (SPEC §10.1; DECISIONS D-77).

The zip holds one ruleset directory (``<ID>/manifest.yaml``, ``ir/``, ``cql/``, ``sql/``, ``valuesets/``, ``tests/``)
or the same files at the top level. The manifest must be ``status: approved`` with an equivalence result at or above
the site threshold; the files are committed to ``main`` of the ruleset repository, tagged ``<ID>/v<version>`` (an
existing tag is never moved) and materialized for the orchestrator.

    python -m criteria_compiler.import_ruleset ruleset.zip --by update:2026.10-1
"""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import PurePosixPath
from typing import Any

import yaml

from criteria_compiler.repo import RulesetRepo


class ImportRefused(ValueError):
    pass


def read_zip(data: bytes) -> tuple[str, dict[str, bytes], dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        for n in names:
            p = PurePosixPath(n)
            if p.is_absolute() or ".." in p.parts:
                raise ImportRefused(f"unsafe path {n!r}")
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
    tag = f"{rid}/v{m.get('version')}"
    if f"refs/tags/{tag}".encode() in repo.refs:
        existing = {p[len(rid) + 1 :]: b for p, b in repo.files(f"refs/tags/{tag}", f"{rid}/").items()}
        if existing == files:
            return tag  # same content already installed
        raise ImportRefused(f"{tag} already exists with different content; bump the version")
    repo.write_dir("main", "main", f"{rid}/", files, f"install {tag} ({by})", author=by.replace(" ", "_"))
    repo.tag(tag, "main", f"{tag} (offline update, {by})")
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
        tag = install(repo, fh.read(), args.by, gate)
    print(json.dumps({"installed": tag}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
