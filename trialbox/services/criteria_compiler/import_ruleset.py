"""Install a vendor-approved ruleset from a verified offline update (SPEC §10.1; DECISIONS D-77).

The zip holds one ruleset directory (``<ID>/manifest.yaml``, ``ir/``, ``cql/``, ``sql/``, ``valuesets/``, ``tests/``)
or the same files at the top level. The manifest must be ``status: approved`` with an equivalence result at or above
the site threshold; the files are committed to ``main`` of the ruleset repository, tagged ``<ID>/v<version>`` (an
existing tag is never moved) and materialized for the orchestrator.

A rule-set part (``ORIGIN.json`` at the zip's root: a rule set compiled and approved on another box, carried in a
vendor-signed bundle for the dry run, D-1369) is checked first (``tb_common.ruleset_part.open_part``: every member,
the record's form, the part's sha256, no site or staff field); it is refused when older than the box's newest approved
version of the id, or when its version is on the box with other content; it takes this box's own routing and scopes
(``profiles/<ID>.yaml``, written with ``--site-profile``) and is refused without them; its tag records that it
arrived in a vendor bundle, from which release, with which hash.

    python -m criteria_compiler.import_ruleset ruleset.zip --by update:2026.10-1
    python -m criteria_compiler.import_ruleset --site-profile GZQO site-GZQO.yaml --by operator
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
from tb_common.ruleset_part import RULESET_ID, PartRefused, open_part, origin_of, tag_note
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
    try:  # D-1369: a part from another box: every member, its record, its hash, no site field, before anything else
        origin = origin_of(data)
        if origin is not None:
            open_part(data)
    except PartRefused as exc:
        raise ImportRefused(f"rule-set part refused: {exc}") from exc
    rid, files, m = read_zip(data)
    if m.get("status") != "approved":
        raise ImportRefused(f"{rid}: only approved rulesets are installed (status {m.get('status')!r})")
    equivalence = m.get("equivalence")
    eq = equivalence.get("overall_pct") if isinstance(equivalence, dict) else None
    if eq is None or float(eq) < min_equivalence:
        raise ImportRefused(f"{rid}: equivalence {eq} below the compile gate {min_equivalence}%")
    tag = f"{rid}/v{m.get('version')}"
    if origin is not None:
        return _install_part(repo, rid, files, m, origin, by)
    message = f"{tag} (offline update, {by})"
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


def _semver(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (-1,)


def site_profile(repo: RulesetRepo, rid: str) -> dict[str, Any]:
    """This box's own ``routing`` and ``scopes`` for ``rid``: ``profiles/<ID>.yaml`` on ``main`` of its repository,
    the site profile its own compile reads (``Compiler._profile``). Refused when either is missing: a rule set that
    arrived from another box is never screened and sent with another site's people or scope (D-1369)."""
    raw = repo.read("main", f"profiles/{rid}.yaml")
    prof = (yaml.safe_load(raw.decode("utf-8")) if raw else None) or {}
    routing, scopes = prof.get("routing"), prof.get("scopes")
    if not (isinstance(routing, dict) and routing.get("list_to") and isinstance(scopes, dict) and scopes.get("screen")):
        raise ImportRefused(
            f"{rid}: this box has no routing (list_to) and screening scope of its own for {rid}: write them with "
            f"python -m criteria_compiler.import_ruleset --site-profile {rid} FILE, then apply the bundle again; "
            "nothing was installed"
        )
    return {"routing": routing, "scopes": scopes}


def _install_part(
    repo: RulesetRepo, rid: str, files: dict[str, bytes], m: dict[str, Any], origin: dict[str, Any], by: str
) -> str:
    """D-1369: a rule-set part. Never older than the box's newest approved version of the id; the same version again
    is a no-op only when it is the same part (its hash on the tag); the site's own routing and scope go in."""
    version = str(m.get("version"))
    tag = f"{rid}/v{version}"
    newest = max((t.split("/v", 1)[1] for t in repo.tags(f"{rid}/v")), key=_semver, default=None)
    if newest is not None and _semver(version) < _semver(newest):
        raise ImportRefused(f"{tag} is older than the approved {rid} v{newest} on this box: a part never goes back")
    if f"refs/tags/{tag}".encode() in repo.refs:
        if f"part sha256 {origin['part_sha256']}" in repo.tag_message(tag):
            return tag  # the same part again: nothing to do
        raise ImportRefused(
            f"{tag} already exists on this box with other content (a part of another hash, a "
            "local approval or a shipped example): the head box exports a new version or id"
        )
    m = {**m, **site_profile(repo, rid)}
    files = {**files, "manifest.yaml": yaml.safe_dump(m, allow_unicode=True, sort_keys=False).encode("utf-8")}
    message = f"{tag} (offline update, {by}); {tag_note(origin, by)}"
    repo.write_dir("main", "main", f"{rid}/", files, f"install {tag} ({by})", author=by.replace(" ", "_"))
    repo.tag(tag, "main", message)
    repo.materialize(rid, "main")
    return tag


def put_site_profile(repo: RulesetRepo, rid: str, data: bytes, by: str) -> None:
    """``--site-profile``: write this box's own routing and scopes for ``rid`` (``profiles/<ID>.yaml`` on ``main``),
    checked against the manifest schema's routing and scopes, before a part of ``rid`` is applied."""
    from tb_contracts import RulesetManifest

    if not RULESET_ID.match(rid):
        raise ImportRefused(f"{rid!r} is not a rule set id")
    prof = yaml.safe_load(data.decode("utf-8")) or {}
    if not isinstance(prof, dict):
        raise ImportRefused("the site profile is not a YAML mapping")
    RulesetManifest.model_validate(
        {
            "id": rid,
            "kind": "trial",
            "title": rid,
            "version": "0.0.0",
            "index_date_rule": "run_date",
            "criteria": [],
            "thresholds": {},
            "scopes": prof.get("scopes") or {},
            "routing": prof.get("routing") or {},
        }
    )
    current = {p[len("profiles/") :]: b for p, b in repo.files("main", "profiles/").items()}
    current[f"{rid}.yaml"] = data
    repo.write_dir("main", "main", "profiles/", current, f"site profile {rid} ({by})", author=by.replace(" ", "_"))


def main(argv: list[str] | None = None) -> int:
    from tb_common.config import load

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip", nargs="?")
    ap.add_argument("--by", default="offline-update")
    ap.add_argument(
        "--site-profile",
        nargs=2,
        metavar=("ID", "FILE"),
        help="D-1369: write this box's own routing and scopes for a rule set that arrives as a part",
    )
    args = ap.parse_args(argv)
    cfg = load()
    repo = RulesetRepo(cfg.env.rulesets_path)
    if args.site_profile:
        rid, path = args.site_profile
        with open(path, "rb") as fh:
            put_site_profile(repo, rid, fh.read(), args.by)
        from tb_common.audit_writer import open_audit

        open_audit(cfg.env.audit_path, cfg.env.tz).append("ruleset.site_profile_set", actor=args.by, ruleset=rid)
        print(json.dumps({"site_profile": rid}))
        return 0
    if not args.zip:
        ap.error("a rule set zip, or --site-profile ID FILE")
    gate = float(cfg.settings.thresholds.equivalence_min_pct or 98.0) if cfg.settings.thresholds else 98.0
    with open(args.zip, "rb") as fh:
        data = fh.read()
    tag = install(repo, data, args.by, gate)
    hits = negated_hits(data)
    for h in hits:  # card 10A-1: installed as approved; a person recompiles these lines (the scan lists them again)
        print(f"WARNING {h}: its line may negate what its logic asks the presence of; recompile and approve",
              file=sys.stderr)  # fmt: skip
    part = {"rule_set_part": True} if origin_of(data) is not None else {}  # D-1369
    print(json.dumps({"installed": tag, **part, **({"negated_inclusions": hits} if hits else {})}))
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
