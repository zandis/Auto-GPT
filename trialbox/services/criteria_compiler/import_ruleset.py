"""Install a vendor-approved ruleset from a verified offline update (SPEC §10.1; DECISIONS D-77).

The zip holds one ruleset directory (``<ID>/manifest.yaml``, ``ir/``, ``cql/``, ``sql/``, ``valuesets/``, ``tests/``)
or the same files at the top level. The manifest must be ``status: approved`` with an equivalence result at or above
the site threshold; the files are committed to ``main`` of the ruleset repository, tagged ``<ID>/v<version>`` (an
existing tag is never moved) and materialized for the orchestrator.

A rule-set part (``ORIGIN.json`` at the zip's root: a rule set compiled and approved on another box, carried in a
vendor-signed bundle for the dry run, D-1369) is checked first (``tb_common.ruleset_part.open_part``: every member,
the record's form, the part's sha256, no site or staff field); it is refused when older than the box's newest approved
version of the id, or when its version is on the box with other content; it takes this box's own routing and scopes
(``profiles/<ID>.yaml`` as ``--site-profile`` wrote it, audited as ``approve.site_profile_set``; a profile shipped as
an example or edited by hand since does not count) and is refused without them. The profile names the one version of
the id the site accepts (and, when the operator gave it, the part's sha256): any other version, or another hash, is
refused with the command that accepts it, so every version that screens here had one act by a person at the site.
Its tag records that it arrived in a vendor bundle, from which release, with which hash. A zip whose ``ORIGIN.json``
is not at its root, or a rule set
with no routing or no scope (the form a part's manifest has), is refused: a part never installs without its record.

    python -m criteria_compiler.import_ruleset ruleset.zip --by update:2026.10-1
    python -m criteria_compiler.import_ruleset --site-profile GZQO site-GZQO.yaml --version 1.0.1 \\
        [--part-sha256 HASH] [--by operator]          # FILE "-": the profile on standard input
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import io
import json
import sys
import zipfile
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

import yaml
from tb_common.ruleset import SEEDED_TAG
from tb_common.ruleset_part import (
    RULESET_ID,
    SHA256,
    VERSION,
    PartRefused,
    load_yaml,
    open_part,
    origin_of,
    part_sha_on_tag,
    tag_note,
)
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
    try:  # bounded: a manifest nested too deep is refused, never a RecursionError
        manifest = load_yaml(files["manifest.yaml"], "manifest.yaml") or {}
    except PartRefused as exc:
        raise ImportRefused(str(exc)) from exc
    if not isinstance(manifest, dict):
        raise ImportRefused("manifest.yaml is not a mapping")
    rid = str(manifest.get("id") or "")
    if not rid or (prefix and prefix.rstrip("/") != rid):
        raise ImportRefused("manifest id does not match the ruleset directory")
    return rid, files, manifest


def install(
    repo: RulesetRepo, data: bytes, by: str, min_equivalence: float = 98.0, pins_problem: PinsCheck | None = None
) -> str:
    """The tag of the installed (or already present) version; :func:`install_outcome` says which."""
    return str(install_outcome(repo, data, by, min_equivalence, pins_problem)["installed"])


def install_outcome(
    repo: RulesetRepo, data: bytes, by: str, min_equivalence: float = 98.0, pins_problem: PinsCheck | None = None
) -> dict[str, Any]:
    """Install the zip; returns ``installed`` (the tag), ``ruleset``, ``version`` and ``imported``: False when the
    same content was already there and nothing changed (D-1369, the review's N2: a repeat is said as such)."""
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
    out = {"installed": tag, "ruleset": rid, "version": str(m.get("version"))}
    if origin is not None:
        return {**out, "imported": _install_part(repo, rid, files, m, origin, by, pins_problem)}
    if not m.get("routing") or not m.get("scopes"):
        # D-1369 (the third review's S2): a part's manifest without its ORIGIN.json; no rule set the vendor ships
        # has no routing or scope, and none is screened without them
        raise ImportRefused(
            f"{rid}: a rule set with no routing or no screening scope (a rule-set part without its ORIGIN.json?) is "
            "never installed through an update; nothing was installed"
        )
    message = f"{tag} (offline update, {by})"
    if f"refs/tags/{tag}".encode() in repo.refs:
        existing = {p[len(rid) + 1 :]: b for p, b in repo.files(f"refs/tags/{tag}", f"{rid}/").items()}
        if existing == files:
            # same content already installed. D-640: when what is there is the example the first start seeded, the
            # operator's install is what the tag records from now on (a site box refuses a seeded approval)
            if SEEDED_TAG in repo.tag_message(tag):
                repo.retag(tag, message)
                return {**out, "imported": True}
            return {**out, "imported": False}
        raise ImportRefused(f"{tag} already exists with different content; bump the version")
    repo.write_dir("main", "main", f"{rid}/", files, f"install {tag} ({by})", author=by.replace(" ", "_"))
    repo.tag(tag, "main", message)
    repo.materialize(rid, "main")
    return {**out, "imported": True}


#: D-1369: what a part's pins need of this box; returns the sentence of a mismatch, or None
PinsCheck = Callable[[dict[str, Any]], str | None]


def box_pins_problem(manifest: dict[str, Any]) -> str | None:
    """D-1369 (the second review): the part's pins against this box, before it is installed. The terminology release
    it was compiled against must be the one this box resolves through (else the run is refused anyway, and a
    screen-only box cannot recompile, D-301); every prompt it pins must stand in this box's registry unchanged
    (``tb_llm.prompt_registry.pin_drift``, D-318)."""
    from tb_contracts import RulesetManifest
    from tb_llm.prompt_registry import pin_drift

    pinned = manifest.get("terminology_release")
    if pinned:
        from criteria_compiler.terminology import resolver

        have = resolver.current_release()
        if have != pinned:
            return f"it was compiled against terminology release {pinned}; this box resolves through {have}"
    drift = pin_drift(RulesetManifest.model_validate(manifest))
    if drift:
        named = ", ".join(f"{d.get('pinned')} {d.get('state')}" for d in drift[:3])
        return f"its prompt pins do not stand on this box ({named})"
    return None


def _semver(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (-1,)


#: written beside ``profiles/<ID>.yaml`` by ``--site-profile`` alone: the sha256 of the profile it wrote, and the one
#: version of the id (and, when given, the part's sha256) the site accepted with it
PROFILE_MARK = "profiles/{rid}.site-set.json"
PROFILE_MARK_FORMAT = "trialbox-site-profile/2"
#: the mark's form before a site profile named a version (the first form of PR #1174): it accepts no version
OLD_PROFILE_MARK_FORMAT = "trialbox-site-profile/1"


def accept_command(rid: str, version: str, part_sha256: str | None = None) -> str:
    """The host command that accepts ``version`` of ``rid`` at this site (run in ``deploy/``, the profile file on
    standard input, as the compiler's container holds the repository and does not mount the host's files)."""
    sha = f" --part-sha256 {part_sha256}" if part_sha256 else ""
    return (
        f"docker compose exec -T criteria-compiler python -m criteria_compiler.import_ruleset --site-profile {rid} - "
        f"--version {version}{sha} < <profile.yaml>"
    )


#: D-1369 (the review's S2): why a part is not installed for want of the site's act, in the three languages of the
#: box; the import's refusal carries all three (the operator's terminal and ``update.rolled_back`` hold one text)
NOT_ACCEPTED: dict[str, dict[str, str]] = {
    "none": {
        "en": "this box has no routing (list_to) and screening scope of its own for {rid} (an example profile shipped "
        "with the box does not count), so it accepts no version of {rid}",
        "ja": "このボックスには {rid} の自施設の送付先（list_to）とスクリーニング対象範囲がありません（ボックスに同梱の"
        "例のプロファイルは数えません）。{rid} のどの版も受け入れていません",
        "zh-TW": "本機沒有 {rid} 的本院寄送對象（list_to）與篩選範圍（隨機附帶的範例設定不算），"
        "因此不接受 {rid} 的任何版本",
    },
    "old": {
        "en": "the site profile for {rid} was written before a site profile named the version it accepts, so it "
        "accepts no version of {rid}",
        "ja": "{rid} の施設プロファイルは、受け入れる版を記録する前の形式で書かれたため、"
        "{rid} のどの版も受け入れていません",
        "zh-TW": "{rid} 的本院設定是在記錄所接受版本之前的格式寫入的，因此不接受 {rid} 的任何版本",
    },
    "version": {
        "en": "{rid} v{version} is not the version this site accepted (its site profile accepts v{accepted})",
        "ja": "{rid} v{version} は、この施設が受け入れた版ではありません"
        "（施設プロファイルが受け入れる版：v{accepted}）",
        "zh-TW": "{rid} v{version} 不是本院接受的版本（本院設定接受的版本：v{accepted}）",
    },
    "hash": {
        "en": "{rid} v{version} has part sha256 {sha}, not the one this site accepted ({accepted})",
        "ja": "{rid} v{version} のパーツ sha256 は {sha} で、この施設が受け入れたもの（{accepted}）ではありません",
        "zh-TW": "{rid} v{version} 的部件 sha256 為 {sha}，不是本院接受的（{accepted}）",
    },
    "how": {
        "en": "; nothing was installed. To accept it, compare the part's sha256 {sha} with the vendor's release note, "
        "then on the box's host, in deploy/: {cmd}; then apply the bundle again",
        "ja": "。何もインストールされていません。受け入れるには、パーツの sha256 {sha} を"
        "ベンダーのリリースノートと照合し、ボックスのホストの deploy/ で {cmd} を実行してから、"
        "バンドルをもう一度適用してください",
        "zh-TW": "；未安裝任何內容。若要接受，請先將部件 sha256 {sha} 與廠商的版本說明核對，"
        "再於本機主機的 deploy/ 執行 {cmd}，然後重新套用更新包",
    },
}


def _not_accepted(why: str, rid: str, version: str, sha: str, accepted: str = "") -> ImportRefused:
    cmd = accept_command(rid, version, sha)
    lines = [
        NOT_ACCEPTED[why][lang].format(rid=rid, version=version, sha=sha, accepted=accepted)
        + NOT_ACCEPTED["how"][lang].format(sha=sha, cmd=cmd)
        for lang in ("en", "ja", "zh-TW")
    ]
    return ImportRefused(f"{lines[0]}\n  ja: {lines[1]}\n  zh-TW: {lines[2]}")


def site_profile(repo: RulesetRepo, rid: str, version: str, part_sha256: str) -> dict[str, Any]:
    """This box's own ``routing`` and ``scopes`` for ``rid``: ``profiles/<ID>.yaml`` on ``main`` of its repository as
    ``--site-profile`` wrote it (its mark records the profile's sha256; a shipped example profile, or one changed by
    hand since, has none that matches). Refused without them: a rule set that arrived from another box is never
    screened and sent with another site's people or scope (D-1369). The mark names the one version the site accepted
    (and the part's sha256 when the operator gave it): another version or hash is refused, and so is a mark of the
    first form, which named none. Each refusal, in en, ja and zh-TW, gives the command that accepts the part."""
    raw = repo.read("main", f"profiles/{rid}.yaml")
    mark_raw = repo.read("main", PROFILE_MARK.format(rid=rid))
    try:
        mark = json.loads(mark_raw) if mark_raw else {}
    except ValueError:
        mark = {}
    mark = mark if isinstance(mark, dict) else {}
    matches = raw is not None and mark.get("sha256") == hashlib.sha256(raw).hexdigest()
    set_here = matches and mark.get("format") == PROFILE_MARK_FORMAT
    prof = (yaml.safe_load(raw.decode("utf-8")) if raw and set_here else None) or {}
    routing, scopes = prof.get("routing"), prof.get("scopes")
    if matches and mark.get("format") == OLD_PROFILE_MARK_FORMAT:
        raise _not_accepted("old", rid, version, part_sha256)
    if not (isinstance(routing, dict) and routing.get("list_to") and isinstance(scopes, dict) and scopes.get("screen")):
        raise _not_accepted("none", rid, version, part_sha256)
    if mark.get("version") != version:
        raise _not_accepted("version", rid, version, part_sha256, str(mark.get("version")))
    if mark.get("part_sha256") and mark.get("part_sha256") != part_sha256:
        raise _not_accepted("hash", rid, version, part_sha256, str(mark.get("part_sha256")))
    return {"routing": routing, "scopes": scopes}


def _install_part(
    repo: RulesetRepo,
    rid: str,
    files: dict[str, bytes],
    m: dict[str, Any],
    origin: dict[str, Any],
    by: str,
    pins_problem: PinsCheck | None = None,
) -> bool:
    """D-1369: a rule-set part. Never older than the box's newest approved version of the id; the same version again
    is a no-op only when it is the same part (its hash on the tag); installed only when the site accepted this version
    (and hash, when it named one), with the site's own routing and scope. True when installed, False on a repeat."""
    version = str(m.get("version"))
    tag = f"{rid}/v{version}"
    newest = max((t.split("/v", 1)[1] for t in repo.tags(f"{rid}/v")), key=_semver, default=None)
    if newest is not None and _semver(version) < _semver(newest):
        raise ImportRefused(f"{tag} is older than the approved {rid} v{newest} on this box: a part never goes back")
    if f"refs/tags/{tag}".encode() in repo.refs:
        if part_sha_on_tag(repo.tag_message(tag)) == origin["part_sha256"]:
            return False  # the same part again: nothing to do
        raise ImportRefused(
            f"{tag} already exists on this box with other content (a part of another hash, a "
            "local approval or a shipped example): the head box exports a new version or id"
        )
    m = {**m, **site_profile(repo, rid, version, str(origin["part_sha256"]))}
    why = pins_problem(m) if pins_problem is not None else None
    if why:
        raise ImportRefused(f"{tag}: {why}; it would not screen as approved on the head box; nothing was installed")
    files = {**files, "manifest.yaml": yaml.safe_dump(m, allow_unicode=True, sort_keys=False).encode("utf-8")}
    message = f"{tag} (offline update, {by}); {tag_note(origin, by)}"
    repo.write_dir("main", "main", f"{rid}/", files, f"install {tag} ({by})", author=by.replace(" ", "_"))
    repo.tag(tag, "main", message)
    repo.materialize(rid, "main")
    return True


def put_site_profile(
    repo: RulesetRepo,
    rid: str,
    data: bytes,
    by: str,
    *,
    version: str,
    part_sha256: str | None = None,
    audit: Any,
) -> str:
    """``--site-profile``: write this box's own routing and scopes for ``rid`` (``profiles/<ID>.yaml`` on ``main``,
    with its mark), checked against the manifest schema's routing and scopes, before a part of ``rid`` is applied. The
    file holds ``routing`` and ``scopes`` only (any other key is refused). The mark names the one ``version`` of
    ``rid`` the site accepts, and ``part_sha256`` when the operator gives it (from the vendor's release note or the
    export's output): a part of any other version or hash is refused (D-1369, the review's S2). Audited first
    (``approve.site_profile_set``: who, when, the rule set, the version, the part's sha256 when given, the profile's
    sha256): when the audit cannot be written, nothing is. Returns the profile's sha256."""
    from tb_contracts import RulesetManifest

    if not RULESET_ID.match(rid):
        raise ImportRefused(f"{rid!r} is not a rule set id")
    if not VERSION.match(str(version)):
        raise ImportRefused(f"{version!r} is not a rule set version (three numbers, 1.0.1)")
    if part_sha256 is not None and not SHA256.match(part_sha256):
        raise ImportRefused("--part-sha256 takes the part's sha256: 64 lowercase hexadecimal characters")
    try:
        prof = load_yaml(data, "the site profile") or {}
    except PartRefused as exc:
        raise ImportRefused(str(exc)) from exc
    if not isinstance(prof, dict):
        raise ImportRefused("the site profile is not a YAML mapping")
    extra = sorted(str(k) for k in prof if k not in ("routing", "scopes"))
    if extra:
        raise ImportRefused(f"the site profile holds {', '.join(extra[:5])}: it sets routing and scopes only")
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
    body = yaml.safe_dump({"routing": prof.get("routing") or {}, "scopes": prof.get("scopes") or {}},
                          allow_unicode=True, sort_keys=False).encode("utf-8")  # fmt: skip
    sha = hashlib.sha256(body).hexdigest()
    audit.append("approve.site_profile_set", actor=by, ruleset=rid, input_sha=sha,
                 detail={"profile": f"profiles/{rid}.yaml", "version": version,
                         "part_sha256": part_sha256})  # fmt: skip
    current = {p[len("profiles/") :]: b for p, b in repo.files("main", "profiles/").items()}
    current[f"{rid}.yaml"] = body
    mark = {"format": PROFILE_MARK_FORMAT, "ruleset": rid, "sha256": sha, "version": version,
            "part_sha256": part_sha256}  # fmt: skip
    current[PROFILE_MARK.format(rid=rid)[len("profiles/") :]] = (json.dumps(mark, sort_keys=True) + "\n").encode()
    repo.write_dir("main", "main", "profiles/", current, f"site profile {rid} v{version} ({by})",
                   author=by.replace(" ", "_"))  # fmt: skip
    return sha


def _host_user() -> str:
    """The user the command runs as; ``unknown`` when there is no user variable and no passwd entry (getpass raises)."""
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    from tb_common.config import load

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip", nargs="?")
    ap.add_argument(
        "--by",
        help="who runs it (default: offline-update for a zip; for --site-profile the user the "
        "command runs as, host:<user>)",
    )
    ap.add_argument(
        "--site-profile",
        nargs=2,
        metavar=("ID", "FILE"),
        help="D-1369: write this box's own routing and scopes for a rule set that arrives as a part, and accept one "
        "version of it (FILE - reads standard input)",
    )
    ap.add_argument("--version", help="with --site-profile (required): the one version of the rule set it accepts")
    ap.add_argument(
        "--part-sha256",
        help="with --site-profile: the part's sha256 (the vendor's release note, the export's output); only that "
        "part of the version is accepted",
    )
    args = ap.parse_args(argv)
    if args.site_profile and not args.version:
        ap.error("--site-profile needs --version: the version of the rule set this site accepts")
    if (args.version or args.part_sha256) and not args.site_profile:
        ap.error("--version and --part-sha256 go with --site-profile")
    cfg = load()
    repo = RulesetRepo(cfg.env.rulesets_path)
    if args.site_profile:
        from tb_common.audit_writer import open_audit

        rid, path = args.site_profile
        if path == "-":  # the profile on standard input: the compiler's container does not mount the host's files
            data = sys.stdin.buffer.read()
        else:
            with open(path, "rb") as fh:
                data = fh.read()
        by = args.by or f"host:{_host_user()}"  # a person, as export_part names one (the re-check of #1174)
        try:
            sha = put_site_profile(repo, rid, data, by, version=args.version, part_sha256=args.part_sha256,
                                   audit=open_audit(cfg.env.audit_path, cfg.env.tz))  # fmt: skip
        except ImportRefused as exc:
            print(f"site profile REFUSED: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"site_profile": rid, "version": args.version, "part_sha256": args.part_sha256,
                          "sha256": sha}))  # fmt: skip
        return 0
    if not args.zip:
        ap.error("a rule set zip, or --site-profile ID FILE")
    gate = float(cfg.settings.thresholds.equivalence_min_pct or 98.0) if cfg.settings.thresholds else 98.0
    with open(args.zip, "rb") as fh:
        data = fh.read()
    res = install_outcome(repo, data, args.by or "offline-update", gate, box_pins_problem)
    hits = negated_hits(data)
    for h in hits:  # card 10A-1: installed as approved; a person recompiles these lines (the scan lists them again)
        print(f"WARNING {h}: its line may negate what its logic asks the presence of; recompile and approve",
              file=sys.stderr)  # fmt: skip
    part = {"rule_set_part": True} if origin_of(data) is not None else {}  # D-1369
    # D-1369 (N2): the update's step reads this line: imported, or already present (a repeat: nothing changed)
    print(json.dumps({**res, "already_present": not res["imported"], **part,
                      **({"negated_inclusions": hits} if hits else {})}))  # fmt: skip
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
