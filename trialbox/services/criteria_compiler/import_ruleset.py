"""Install a vendor-approved ruleset from a verified offline update (SPEC §10.1; DECISIONS D-77).

The zip holds one ruleset directory (``<ID>/manifest.yaml``, ``ir/``, ``cql/``, ``sql/``, ``valuesets/``, ``tests/``)
or the same files at the top level. The manifest must be ``status: approved`` with an equivalence result at or above
the site threshold, and list exactly the criteria of its ``ir/`` files; the files are committed to ``main`` of the
ruleset repository, tagged ``<ID>/v<version>`` (an existing tag is never moved) and materialized for the orchestrator.

**One gate** (D-1369, the review of edb77053): :func:`install_outcome` is the one function through which a rule set
from outside this box is written, and it writes nothing new unless (i) the update path verified the bundle's vendor
signature in this run and hands it its evidence for exactly these bytes (:class:`Verified`; on the command line
``--verified``, a root-owned file in the update's root-owned stage), a part also needing the box on at least the
release that compiled it; and (ii) the site accepted this id and version (and hash, when it named one) with its own
routing and scopes (``--site-profile``), which replace the zip's, for a rule-set part (``ORIGIN.json``, checked by
``tb_common.ruleset_part.open_part``) and a plain rule set zip alike. Without evidence the command line checks a zip
(``--check``) and changes no content: a repeat of what the box holds, or the D-640 retag of a shipped example of
exactly the same content (runbook 01's synthetic run). A part older than the box's newest version, or of a version
on the box with other content, is refused. A repeat through the update takes the site's current routing and scopes.

    python -m criteria_compiler.import_ruleset /in/ruleset.zip --by update:2026.10-1 --verified /in/verified.json
    python -m criteria_compiler.import_ruleset ruleset.zip --check
    python -m criteria_compiler.import_ruleset --site-profile GZQO site-GZQO.yaml --version 1.0.1 \\
        [--part-sha256 HASH] --by "<your name>"       # FILE "-": the profile on standard input
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import io
import json
import os
import re
import stat
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml
from pydantic import ValidationError
from tb_common.ruleset import SEEDED_TAG
from tb_common.ruleset_part import (
    BUNDLE_ID,
    RULESET_ID,
    SHA256,
    SITE_SCOPED_MARK,
    VERSION,
    PartRefused,
    criteria_files_match,
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


class NotAccepted(ImportRefused):
    """D-1369: a part this site has not accepted; carries the id, version and the command that accepts it, so the
    command line can print it whole as its last line (the fifth review)."""

    def __init__(self, text: str, rid: str, version: str, command: str) -> None:
        super().__init__(text)
        self.rid, self.version, self.command = rid, version, command


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


#: D-1369 (the review of edb77053, 1-3): the record the update path alone writes, after its verifier checked the
#: bundle's vendor signature in this run (``tools.trialbox.update.ruleset_evidence``)
EVIDENCE_FORMAT = "trialbox-ruleset-evidence/1"
#: the owner an evidence file must have on the command line: the update runs as root and writes it into its root-owned
#: stage; the compiler's service account cannot make a file root's (a test sets its own account)
EVIDENCE_OWNER = 0


@dataclass(frozen=True)
class Verified:
    """D-1369: evidence that a rule set zip arrived inside a bundle whose vendor signature the update path verified in
    this run: the bundle's id and release_seq, the box's installed release_seq before it (the floor a part needs), the
    root-owned stage, and the sha256 of each staged rule-set payload. Only ``tools.trialbox.update.Updater`` builds it
    (in the process, or as the stage's root-owned ``ruleset-evidence.json`` the compiler's container reads)."""

    bundle_id: str
    release_seq: int
    box_release_seq: int | None
    files: tuple[tuple[str, str], ...]
    stage: str

    @classmethod
    def of(cls, data: bytes, name: str, *, bundle_id: str, release_seq: int, box_release_seq: int | None,
           stage: str) -> Verified:  # fmt: skip
        return cls(bundle_id, release_seq, box_release_seq, ((name, hashlib.sha256(data).hexdigest()),), stage)

    def record(self) -> dict[str, Any]:
        return {"format": EVIDENCE_FORMAT, "bundle_id": self.bundle_id, "release_seq": self.release_seq,
                "box_release_seq": self.box_release_seq, "stage": self.stage, "files": dict(self.files)}  # fmt: skip

    @classmethod
    def from_record(cls, rec: Any) -> Verified:
        """The record, held to its strict form; refused otherwise."""
        ok = (
            isinstance(rec, dict)
            and rec.get("format") == EVIDENCE_FORMAT
            and set(rec) == {"format", "bundle_id", "release_seq", "box_release_seq", "stage", "files"}
            and isinstance(rec["bundle_id"], str) and BUNDLE_ID.fullmatch(rec["bundle_id"]) is not None
            and _whole(rec["release_seq"])
            and (rec["box_release_seq"] is None or _whole(rec["box_release_seq"], 0))
            and isinstance(rec["stage"], str)
            and isinstance(rec["files"], dict) and bool(rec["files"])
            and all(isinstance(k, str) and isinstance(v, str) and SHA256.fullmatch(v) for k, v in rec["files"].items())
        )  # fmt: skip
        if not ok:
            raise ImportRefused(_three("evidence_form"))
        return cls(rec["bundle_id"], rec["release_seq"], rec["box_release_seq"], tuple(sorted(rec["files"].items())),
                   rec["stage"])  # fmt: skip


def _whole(v: Any, low: int = 1) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and low <= v < 10**9


#: D-1369 (the review of edb77053): the gate's refusals, in the three languages of the box (the operator's terminal
#: and ``update.rolled_back`` hold one text)
GATE: dict[str, dict[str, str]] = {
    "unverified": {
        "en": "{what} is not from a bundle the update verified in this run (no evidence of a verified vendor "
        "signature): a rule set from outside this box is installed only by tools/apply_update.sh; this command "
        "checks a zip (--check) and writes nothing",
        "ja": "{what} は、この実行で更新処理が検証したバンドルからのものではありません（ベンダー署名を検証した証跡が"
        "ありません）。このボックスの外から来たルールセットは tools/apply_update.sh だけがインストールします。"
        "このコマンドは zip を確認するだけで（--check）、何も書き込みません",
        "zh-TW": "{what} 不是本次執行中更新程序已驗證的更新包內容（沒有廠商簽章已驗證的證據）：來自本機以外的"
        "規則集只由 tools/apply_update.sh 安裝；此指令只檢查 zip（--check），不寫入任何內容",
    },
    "evidence_form": {
        "en": "the evidence of a verified bundle is not of its form; nothing was installed",
        "ja": "検証済みバンドルの証跡が所定の形式ではありません。何もインストールされていません",
        "zh-TW": "已驗證更新包的證據格式不符；未安裝任何內容",
    },
    "evidence_file": {
        "en": "the evidence file {path} was not written by the update (it must be root's and writable by root "
        "alone); nothing was installed",
        "ja": "証跡ファイル {path} は更新処理が書いたものではありません（root が所有し、root だけが書き込める必要が"
        "あります）。何もインストールされていません",
        "zh-TW": "證據檔 {path} 不是更新程序寫入的（必須屬於 root 且只有 root 可寫入）；未安裝任何內容",
    },
    "other_bytes": {
        "en": "{what} is not a zip the update verified in bundle {bundle} (its sha256 {sha} is not one the bundle "
        "staged); nothing was installed",
        "ja": "{what} は、更新処理がバンドル {bundle} で検証した zip ではありません（sha256 {sha} はバンドルが"
        "配置したものではありません）。何もインストールされていません",
        "zh-TW": "{what} 不是更新程序在更新包 {bundle} 中驗證過的 zip（其 sha256 {sha} 不是更新包所放置的）；"
        "未安裝任何內容",
    },
    "release": {
        "en": "{what} was compiled on release_seq {need}; this box runs release_seq {have}: install that release (or a "
        "later one) first; nothing was installed",
        "ja": "{what} は release_seq {need} でコンパイルされました。このボックスは release_seq {have} です。"
        "先にそのリリース（またはそれ以降）をインストールしてください。何もインストールされていません",
        "zh-TW": "{what} 是在 release_seq {need} 編譯的；本機為 release_seq {have}：請先安裝該版本（或更新的版本）；"
        "未安裝任何內容",
    },
    "part": {
        "en": "rule-set part refused: {why}",
        "ja": "ルールセットのパーツを拒否しました（理由は上の英語の行）。何もインストールされていません",
        "zh-TW": "已拒絕規則集部件（原因見上方英文行）；未安裝任何內容",
    },
    "criteria": {
        "en": "{what}: {why}",
        "ja": "{what}：マニフェストに記載された基準が ir/ のファイルと一致しません（記載された除外基準などが評価され"
        "なくなります）。何もインストールされていません",
        "zh-TW": "{what}：清單所列的條件與 ir/ 檔案不一致（所列的排除條件等將不會被評估）；未安裝任何內容",
    },
}


def _three(key: str, **kw: Any) -> str:
    en, ja, zh = (GATE[key][lang].format(**kw) for lang in ("en", "ja", "zh-TW"))
    return f"{en}\n  ja: {ja}\n  zh-TW: {zh}"


def install(
    repo: RulesetRepo,
    data: bytes,
    by: str,
    min_equivalence: float = 98.0,
    pins_problem: PinsCheck | None = None,
    *,
    verified: Verified | None = None,
) -> str:
    """The tag of the installed (or already present) version; :func:`install_outcome` says which."""
    return str(install_outcome(repo, data, by, min_equivalence, pins_problem, verified=verified)["installed"])


def _without_site(raw: bytes | None) -> Any:
    try:
        m = yaml.safe_load(raw.decode("utf-8")) if raw is not None else None
    except (UnicodeDecodeError, yaml.YAMLError):
        return None
    return {k: v for k, v in m.items() if k not in ("routing", "scopes")} if isinstance(m, dict) else m


def _same_content(existing: dict[str, bytes], files: dict[str, bytes]) -> bool:
    """The same rule set: the same files, the manifest the same but for routing and scopes (the site's own replace
    them at install, D-1369)."""
    if existing.keys() != files.keys():
        return False
    if any(existing[p] != files[p] for p in files if p != "manifest.yaml"):
        return False
    return existing.get("manifest.yaml") == files.get("manifest.yaml") or _without_site(
        existing.get("manifest.yaml")
    ) == _without_site(files.get("manifest.yaml"))


def install_outcome(
    repo: RulesetRepo,
    data: bytes,
    by: str,
    min_equivalence: float = 98.0,
    pins_problem: PinsCheck | None = None,
    *,
    verified: Verified | None = None,
    check_only: bool = False,
) -> dict[str, Any]:
    """Install the zip; returns ``installed`` (the tag), ``ruleset``, ``version`` and ``imported``: False when the
    same content was already there and nothing changed (D-1369, the review's N2: a repeat is said as such).

    D-1369 (the review of edb77053, 1-3): **the one gate** through which a rule set from outside this box becomes
    installed. Nothing new is written unless (i) ``verified`` is the update path's evidence for exactly these bytes
    (:class:`Verified`; a part also needs the box on at least the release that compiled it), and (ii) the site
    accepted this id and version (and hash, when it named one) with its own routing and scopes
    (:func:`site_profile`), for a part and for a plain rule set zip alike; the site's routing and scopes replace the
    zip's. Without evidence only what changes no content is done: a repeat of what is already here, or the D-640
    retag of a shipped example of exactly the same content. ``check_only``: every check but (i), nothing written."""
    try:  # D-1369: a part from another box: every member, its record, its hash, no site field, before anything else
        origin = origin_of(data)
        if origin is not None:
            open_part(data)
    except PartRefused as exc:
        raise ImportRefused(_three("part", why=str(exc))) from exc
    rid, files, m = read_zip(data)
    if m.get("status") != "approved":
        raise ImportRefused(f"{rid}: only approved rulesets are installed (status {m.get('status')!r})")
    equivalence = m.get("equivalence")
    eq = equivalence.get("overall_pct") if isinstance(equivalence, dict) else None
    if eq is None or float(eq) < min_equivalence:
        raise ImportRefused(f"{rid}: equivalence {eq} below the compile gate {min_equivalence}%")
    version = str(m.get("version"))
    tag = f"{rid}/v{version}"
    what = f"{rid} v{version}"
    try:  # (the review of edb77053, 4) every listed criterion is there, both forms
        criteria_files_match(files, m)
    except PartRefused as exc:
        raise ImportRefused(_three("criteria", what=what, why=str(exc))) from exc
    out = {"installed": tag, "ruleset": rid, "version": version}
    sha = str(origin["part_sha256"]) if origin is not None else hashlib.sha256(data).hexdigest()
    if f"refs/tags/{tag}".encode() in repo.refs:  # what this box holds already: nothing from outside is written
        if origin is not None:
            if part_sha_on_tag(repo.tag_message(tag)) != origin["part_sha256"]:
                raise ImportRefused(
                    f"{tag} already exists on this box with other content (a part of another hash, a "
                    "local approval or a shipped example): the head box exports a new version or id"
                )
        else:
            existing = {p[len(rid) + 1 :]: b for p, b in repo.files(f"refs/tags/{tag}", f"{rid}/").items()}
            if not _same_content(existing, files):
                raise ImportRefused(f"{tag} already exists with different content; bump the version")
            if SEEDED_TAG in repo.tag_message(tag) and existing == files:
                # D-640: what is there is the example the first start seeded from this box's own image; the
                # operator's install is what the tag records from now on (no content changes)
                if not check_only:
                    repo.retag(tag, f"{tag} (offline update, {by})")
                return {**out, "imported": not check_only}
        if verified is not None and not check_only:
            _refresh_site(repo, rid, version, by)  # (the review of edb77053, 6): the site's current routing
        return {**out, "imported": False}
    if origin is None and (not m.get("routing") or not m.get("scopes")):
        # D-1369 (the third review's S2): a part's manifest without its ORIGIN.json
        raise ImportRefused(
            f"{rid}: a rule set with no routing or no screening scope (a rule-set part without its ORIGIN.json?) is "
            "never installed through an update; nothing was installed"
        )
    newest = max((t.split("/v", 1)[1] for t in repo.tags(f"{rid}/v")), key=_semver, default=None)
    if newest is not None and _semver(version) < _semver(newest):
        raise ImportRefused(f"{tag} is older than the approved {rid} v{newest} on this box: a rule set never goes back")
    if not check_only:
        _gate(verified, data, what, origin)
    m = {**m, **site_profile(repo, rid, version, sha)}
    why = pins_problem(m) if pins_problem is not None else None
    if why:
        raise ImportRefused(f"{tag}: {why}; it would not screen as approved on the head box; nothing was installed")
    if check_only:
        return {**out, "imported": False, "checked": True}
    files = {**files, "manifest.yaml": yaml.safe_dump(m, allow_unicode=True, sort_keys=False).encode("utf-8")}
    note = tag_note(origin, by) if origin is not None else f"{SITE_SCOPED_MARK}; zip sha256 {sha}"
    message = f"{tag} (offline update, {by}); {note}"
    repo.write_dir("main", "main", f"{rid}/", files, f"install {tag} ({by})", author=by.replace(" ", "_"))
    repo.tag(tag, "main", message)
    repo.materialize(rid, "main")
    return {**out, "imported": True}


def _gate(verified: Verified | None, data: bytes, what: str, origin: dict[str, Any] | None) -> None:
    """(i) of :func:`install_outcome`: the update path's evidence for exactly these bytes and, for a part, a box on at
    least the release that compiled it (``compiled_on.release_seq``, 1 or more, :func:`tb_common.ruleset_part
    .check_origin`)."""
    if not isinstance(verified, Verified):
        raise ImportRefused(_three("unverified", what=what))
    sha = hashlib.sha256(data).hexdigest()
    if sha not in dict(verified.files).values():
        raise ImportRefused(_three("other_bytes", what=what, bundle=verified.bundle_id, sha=sha))
    if origin is not None:
        need = (origin.get("compiled_on") or {}).get("release_seq")
        have = verified.box_release_seq
        if not _whole(need) or have is None or have < need:
            raise ImportRefused(_three("release", what=what, need=need, have=have))


def _refresh_site(repo: RulesetRepo, rid: str, version: str, by: str) -> None:
    """A repeat of an installed version (the review of edb77053, 6): when the site set its routing and scopes again
    since (``--site-profile``), main's manifest of that version takes them now, so delivery never goes to superseded
    recipients. Nothing else changes; the approval tag stays."""
    prof = _site_set(repo, rid)
    raw = repo.read("main", f"{rid}/manifest.yaml")
    m = yaml.safe_load(raw.decode("utf-8")) if raw else None
    if prof is None or not isinstance(m, dict) or str(m.get("version")) != version:
        return
    if m.get("routing") == prof["routing"] and m.get("scopes") == prof["scopes"]:
        return
    files = {p[len(rid) + 1 :]: b for p, b in repo.files("main", f"{rid}/").items()}
    files["manifest.yaml"] = yaml.safe_dump({**m, **prof}, allow_unicode=True, sort_keys=False).encode("utf-8")
    repo.write_dir("main", "main", f"{rid}/", files, f"site routing {rid} v{version} ({by})",
                   author=by.replace(" ", "_"))  # fmt: skip
    repo.materialize(rid, "main")


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
#: the largest site profile ``--site-profile`` reads (a file or standard input)
PROFILE_MAX = 64 * 1024
PROFILE_MARK_FORMAT = "trialbox-site-profile/2"
#: the mark's form before a site profile named a version (the first form of PR #1174): it accepts no version
OLD_PROFILE_MARK_FORMAT = "trialbox-site-profile/1"


def accept_command(rid: str, version: str, part_sha256: str | None = None) -> str:
    """The host command that accepts ``version`` of ``rid`` at this site (run in ``deploy/``, the profile file on
    standard input, as the compiler's container holds the repository and does not mount the host's files). ``--by``
    is the name of the person who runs it: inside the container the account is the service's, so the audit records
    that account and the name typed, which the box cannot verify (the fifth review)."""
    sha = f" --part-sha256 {part_sha256}" if part_sha256 else ""
    return (
        f"docker compose exec -T criteria-compiler python -m criteria_compiler.import_ruleset --site-profile {rid} - "
        f'--version {version}{sha} --by "<your name>" < <profile.yaml>'
    )


#: the command line's refusal reaches the operator whole on a container box (the fifth review): the update keeps the
#: first line and the last 600 characters of the import's standard error; one line of at most this many characters
#: holds the command at the end
ACCEPT_LINE_MAX = 399


def refusal_lines(exc: ImportRefused) -> list[str]:
    """What the command line prints to standard error for a refused zip: first a short English sentence (with the id
    and version when it is a part the site has not accepted), then the refusal (en, ja and zh-TW), and, for a part
    not accepted, last one short ASCII line with the exact command that accepts it."""
    if not isinstance(exc, NotAccepted):
        return [f"rule set zip REFUSED: {exc}"]
    head = (
        f"rule set zip REFUSED: the rule-set part {exc.rid} v{exc.version} is not accepted at this site and was not "
        "installed; the command that accepts it follows on the last line"
    )
    last = f"to accept {exc.rid} v{exc.version}, in deploy/ on the box's host: {exc.command}"
    if len(last) <= ACCEPT_LINE_MAX:
        return [head, str(exc), last]
    return [head, str(exc), "the command that accepts it is too long for one line with words: it follows alone",
            exc.command]  # fmt: skip


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


#: D-1369 (the fifth review): ``--site-profile`` (or ``export_part``) without ``--by``; inside the compiler's container
#: the account is the service's, so the name of the person is asked for and recorded as what they typed
NEEDS_BY: dict[str, str] = {
    "en": '{command} needs --by "<your name>": the audit records the account that ran the command and the name '
    "you type, which the box cannot verify; nothing was written",
    "ja": '{command} には --by "<氏名>" が必要です。監査記録には、コマンドを実行したアカウントと入力された氏名が'
    "記録されますが、ボックスはその氏名を確認できません。何も書き込まれていません",
    "zh-TW": '{command} 需要 --by "<您的姓名>"：稽核紀錄會記下執行指令的帳號與您輸入的姓名，'
    "本機無法核實該姓名；未寫入任何內容",
}
#: the most a ``--by`` name may hold (one line, no control character)
BY_MAX = 100
BY_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def by_problem(name: str | None, command: str = "--site-profile") -> str | None:
    """Why ``--by`` is not a name the audit records (None when it is one); ``command`` names what needs it."""
    if name is None or not name.strip():
        return "\n".join(f"{lang}: {text.format(command=command)}" for lang, text in NEEDS_BY.items())
    if len(name) > BY_MAX or BY_CONTROL.search(name):
        return f"--by takes a name of at most {BY_MAX} characters on one line, with no control character"
    return None


def _not_accepted(why: str, rid: str, version: str, sha: str, accepted: str = "") -> NotAccepted:
    cmd = accept_command(rid, version, sha)
    lines = [
        NOT_ACCEPTED[why][lang].format(rid=rid, version=version, sha=sha, accepted=accepted)
        + NOT_ACCEPTED["how"][lang].format(sha=sha, cmd=cmd)
        for lang in ("en", "ja", "zh-TW")
    ]
    return NotAccepted(f"{lines[0]}\n  ja: {lines[1]}\n  zh-TW: {lines[2]}", rid, version, cmd)


def _site_set(repo: RulesetRepo, rid: str) -> dict[str, Any] | None:
    """The routing and scopes ``--site-profile`` wrote for ``rid`` (its mark of the current form matching the profile),
    whatever version it accepts; None when there are none."""
    raw = repo.read("main", f"profiles/{rid}.yaml")
    mark_raw = repo.read("main", PROFILE_MARK.format(rid=rid))
    try:
        mark = json.loads(mark_raw) if mark_raw else {}
    except ValueError:
        return None
    if not (isinstance(mark, dict) and raw is not None and mark.get("ruleset") == rid
            and mark.get("format") == PROFILE_MARK_FORMAT
            and mark.get("sha256") == hashlib.sha256(raw).hexdigest()):  # fmt: skip
        return None
    prof = yaml.safe_load(raw.decode("utf-8")) or {}
    routing, scopes = prof.get("routing"), prof.get("scopes")
    if not (isinstance(routing, dict) and routing.get("list_to") and isinstance(scopes, dict) and scopes.get("screen")):
        return None
    return {"routing": routing, "scopes": scopes}


def site_profile(repo: RulesetRepo, rid: str, version: str, part_sha256: str) -> dict[str, Any]:
    """This box's own ``routing`` and ``scopes`` for ``rid``: ``profiles/<ID>.yaml`` on ``main`` of its repository as
    ``--site-profile`` wrote it (its mark records the profile's sha256; a shipped example profile, or one changed by
    hand since, has none that matches). Refused without them: a rule set that arrived from another box is never
    screened and sent with another site's people or scope (D-1369). The mark names the one version the site accepted
    (and the part's sha256 when the operator gave it): another version or hash is refused, and so is a mark of the
    first form, which named none, or a mark for another id. Each refusal, in en, ja and zh-TW, gives the command that
    accepts the part. The mark is not held against the audit: the compiler's service account, which writes the
    repository, could write one (D-1369, a residual)."""
    raw = repo.read("main", f"profiles/{rid}.yaml")
    mark_raw = repo.read("main", PROFILE_MARK.format(rid=rid))
    try:
        mark = json.loads(mark_raw) if mark_raw else {}
    except ValueError:
        mark = {}
    mark = mark if isinstance(mark, dict) else {}
    # the mark is this id's own (the fifth review): a mark copied from another id's profile does not count
    matches = raw is not None and mark.get("sha256") == hashlib.sha256(raw).hexdigest() and mark.get("ruleset") == rid
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


def put_site_profile(
    repo: RulesetRepo,
    rid: str,
    data: bytes,
    by: str,
    *,
    version: str,
    part_sha256: str | None = None,
    audit: Any,
    by_claimed: str | None = None,
) -> str:
    """``--site-profile``: write this box's own routing and scopes for ``rid`` (``profiles/<ID>.yaml`` on ``main``,
    with its mark), checked against the manifest schema's routing and scopes, before a part of ``rid`` is applied. The
    file holds ``routing`` and ``scopes`` only (any other key is refused). The mark names the one ``version`` of
    ``rid`` the site accepts, and ``part_sha256`` when the operator gives it (from the vendor's release note or the
    export's output): a part of any other version or hash is refused (D-1369, the review's S2). Audited first
    (``approve.site_profile_set``: the account ``by``, the name the operator typed as ``by_claimed`` (a claim the box
    cannot verify), when, the rule set, the version, the part's sha256 when given, the profile's sha256): when the
    audit cannot be written, nothing is. The profile is at most 64 KiB, and no field is unknown at any depth (the
    manifest schema's routing and scopes). Returns the profile's sha256."""
    from tb_contracts import RulesetManifest

    if not RULESET_ID.fullmatch(rid):
        raise ImportRefused(f"{rid!r} is not a rule set id")
    if not VERSION.fullmatch(str(version)):
        raise ImportRefused(f"{version!r} is not a rule set version (three numbers, 1.0.1)")
    if part_sha256 is not None and not SHA256.fullmatch(part_sha256):
        raise ImportRefused("--part-sha256 takes the part's sha256: 64 lowercase hexadecimal characters")
    if len(data) > PROFILE_MAX:
        raise ImportRefused(f"the site profile is larger than {PROFILE_MAX // 1024} KiB: refused")
    try:
        prof = load_yaml(data, "the site profile") or {}
    except PartRefused as exc:
        raise ImportRefused(str(exc)) from exc
    if not isinstance(prof, dict):
        raise ImportRefused("the site profile is not a YAML mapping")
    extra = sorted(str(k) for k in prof if k not in ("routing", "scopes"))
    if extra:
        raise ImportRefused(f"the site profile holds {', '.join(extra[:5])}: it sets routing and scopes only")
    try:  # strict: an unknown field at any depth of routing or scopes is refused (the schema forbids extras)
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
    except ValidationError as exc:  # where and what, never the value typed
        where = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['type']}" for e in exc.errors()[:5])
        raise ImportRefused(
            f"the site profile does not hold the routing and scopes a rule set takes ({where})"
        ) from exc
    body = yaml.safe_dump({"routing": prof.get("routing") or {}, "scopes": prof.get("scopes") or {}},
                          allow_unicode=True, sort_keys=False).encode("utf-8")  # fmt: skip
    sha = hashlib.sha256(body).hexdigest()
    audit.append("approve.site_profile_set", actor=by, ruleset=rid, input_sha=sha,
                 detail={"profile": f"profiles/{rid}.yaml", "version": version,
                         "part_sha256": part_sha256, "by_claimed": by_claimed})  # fmt: skip
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
        help="who runs it (default: offline-update for a zip); required with --site-profile: the name of the person, "
        "recorded as typed (by_claimed) beside the account the command runs as (host:<account>)",
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
    ap.add_argument(
        "--verified",
        metavar="FILE",
        help="D-1369: the update's evidence that the zip arrived in a bundle it verified in this run (written by "
        "tools/apply_update.sh into its root-owned stage); without it a zip from outside is never installed",
    )
    ap.add_argument("--check", action="store_true", help="check the zip as an install would, write nothing")
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
        why = by_problem(args.by)
        if why:  # D-1369 (the fifth review): in the container the account is the service's; the person names themself
            print(f"site profile REFUSED: {why}", file=sys.stderr)
            return 2
        if path == "-":  # the profile on standard input: the compiler's container does not mount the host's files
            data = sys.stdin.buffer.read(PROFILE_MAX + 1)
        else:
            with open(path, "rb") as fh:
                data = fh.read(PROFILE_MAX + 1)
        account = f"host:{_host_user()}"  # the account; the name typed is a claim beside it, never a verified identity
        try:
            sha = put_site_profile(repo, rid, data, account, version=args.version, part_sha256=args.part_sha256,
                                   audit=open_audit(cfg.env.audit_path, cfg.env.tz), by_claimed=args.by)  # fmt: skip
        except ImportRefused as exc:
            print(f"site profile REFUSED: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"site_profile": rid, "version": args.version, "part_sha256": args.part_sha256,
                          "sha256": sha, "by": account, "by_claimed": args.by}))  # fmt: skip
        return 0
    if not args.zip:
        ap.error("a rule set zip, or --site-profile ID FILE")
    gate = float(cfg.settings.thresholds.equivalence_min_pct or 98.0) if cfg.settings.thresholds else 98.0
    with open(args.zip, "rb") as fh:
        data = fh.read()
    try:
        verified = evidence_file(args.verified) if args.verified else None
        res = install_outcome(repo, data, args.by or "offline-update", gate, box_pins_problem, verified=verified,
                              check_only=args.check)  # fmt: skip
    except ImportRefused as exc:  # the fifth review: lines the operator reads whole, in every channel; no traceback
        for line in refusal_lines(exc):
            print(line, file=sys.stderr)
        return 2
    hits = negated_hits(data)
    for h in hits:  # card 10A-1: installed as approved; a person recompiles these lines (the scan lists them again)
        print(f"WARNING {h}: its line may negate what its logic asks the presence of; recompile and approve",
              file=sys.stderr)  # fmt: skip
    if args.check:
        print(json.dumps({"checked": res["installed"], "written": False}))
        return 0
    part = {"rule_set_part": True} if origin_of(data) is not None else {}  # D-1369
    # D-1369 (N2): the update's step reads this line: imported, or already present (a repeat: nothing changed); the
    # last line stays as it was (runbook 01 reads it)
    print(json.dumps({"ruleset": res["ruleset"], "version": res["version"], "imported": res["imported"],
                      "already_present": not res["imported"]}))  # fmt: skip
    print(json.dumps({"installed": res["installed"], **part, **({"negated_inclusions": hits} if hits else {})}))
    return 0


def evidence_file(path: str) -> Verified:
    """The update's evidence as the compiler's container reads it: a regular file owned by :data:`EVIDENCE_OWNER`
    (root: the update writes it into its root-owned stage) that no one else may write, of the strict form. The
    compiler's service account cannot make such a file; root on the host (or anyone who may run containers there)
    can, as it can write the rule-set repository itself (D-1369, the residual)."""
    try:
        st = os.lstat(path)
        with open(path, "rb") as fh:
            raw = fh.read(64 * 1024)
    except OSError as exc:
        raise ImportRefused(_three("evidence_file", path=path)) from exc
    if not stat.S_ISREG(st.st_mode) or st.st_uid != EVIDENCE_OWNER or st.st_mode & 0o022:
        raise ImportRefused(_three("evidence_file", path=path))
    try:
        rec = json.loads(raw)
    except ValueError as exc:
        raise ImportRefused(_three("evidence_form")) from exc
    return Verified.from_record(rec)


def negated_hits(data: bytes) -> list[str]:
    """Card 10A-1: the ids of the zip's inclusions whose line may negate what their logic asks the presence of. The
    install is not refused (the ruleset is the vendor's approved one); the ids are reported for a person to act on."""
    from tb_common.ruleset import Ruleset

    from criteria_compiler.negated_inclusions import ruleset_hits

    _, files, _ = read_zip(data)
    return [h.criterion for h in ruleset_hits(Ruleset.from_files(files))]


if __name__ == "__main__":
    raise SystemExit(main())
