"""The Japanese release note and the change-impact sheet every release bundle carries (10K-7, D-1363; review 18 SO-7).

    python -m tools.release_note check [--source docs/releases/next-release.ja.yaml]
    python -m tools.release_note build --id 2026.12-1 --release-seq 7 --out-dir DIR [--source FILE]

The vendor writes one source file per release, ``docs/releases/next-release.ja.yaml`` (the release's "Unreleased",
as ``CHANGELOG.md`` has one): a Japanese title and summary, each change class of ``docs/validation/change-control.md``
§2 (CC1 to CC6) stated changed or not with what changed in Japanese, and the impact on the site (minutes the box is
down, a database migration or not, rulesets to approve again or not, what hospital IT does). ``tools/make_bundle.sh``
runs ``build``: a source that does not read, or that leaves a class unstated, stops the bundle before an image is
exported. ``build`` writes two payloads of kind ``other``:

* ``RELEASE-NOTE.ja.md``: the note in Japanese (title, summary, the change-class table, the impact, IT's actions);
* ``CHANGE-IMPACT.json``: the same facts as data (``trialbox-change-impact/1``): every class with ``changed``, the
  bundle id and ``release_seq``, the minutes down, migration, re-approval, the actions.

Both are files of the signed manifest (their sha256 is in it), so nobody changes them on the stick unseen. On the
box, :func:`read_from_bundle` reads them back from a bundle the verifier accepted (sizes capped, each sha256 compared
with the manifest again): ``tools/verify_update.py`` reports them (a bundle without them is a warning, not a refusal:
D-1363) and the operations runner shows them on the console's update page. Standard library only, except ``build``
and ``check``, which read the YAML source with PyYAML (the vendor's machine).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "releases" / "next-release.ja.yaml"
SOURCE_FORMAT = "trialbox-release-note/1"
IMPACT_FORMAT = "trialbox-change-impact/1"
NOTE = "RELEASE-NOTE.ja.md"
IMPACT = "CHANGE-IMPACT.json"
MAX_BYTES = 256 * 1024  # a note and a sheet are a few kilobytes
#: the change classes of docs/validation/change-control.md §2 (D-344), in their order, with their Japanese names
CLASSES: dict[str, str] = {
    "CC1": "モデルに影響する変更",
    "CC2": "データ経路の変更",
    "CC3": "外部接続の変更",
    "CC4": "画面と文言の変更",
    "CC5": "セキュリティ修正",
    "CC6": "施設の設定",
}
_JA = re.compile(r"[぀-ヿ㐀-鿿]")


class NoteError(ValueError):
    pass


def _ja(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip()) and bool(_JA.search(v))


def source_problems(src: Any) -> list[str]:
    """What keeps a release-note source from making a bundle: each problem as one line."""
    if not isinstance(src, Mapping):
        return ["the source is not a mapping"]
    out = []
    if src.get("format") != SOURCE_FORMAT:
        out.append(f"format is {src.get('format')!r}, not {SOURCE_FORMAT!r}")
    for k in ("title_ja", "summary_ja"):
        if not _ja(src.get(k)):
            out.append(f"{k}: Japanese text is required")
    changes = src.get("changes")
    if not isinstance(changes, Mapping):
        out.append("changes: one entry per change class CC1 to CC6 is required")
        changes = {}
    for cc in CLASSES:
        c = changes.get(cc)
        if not isinstance(c, Mapping) or not isinstance(c.get("changed"), bool):
            out.append(f"changes.{cc}: say changed: true or changed: false")
        elif c["changed"] and not _ja(c.get("what_ja")):
            out.append(f"changes.{cc}: changed, so what_ja (what changed, in Japanese) is required")
    out += [f"changes.{k}: not a change class (CC1 to CC6)" for k in changes if k not in CLASSES]
    imp = src.get("impact")
    if not isinstance(imp, Mapping):
        return [*out, "impact: the minutes down, migration, re-approval and IT's actions are required"]
    mins = imp.get("downtime_minutes")
    if not isinstance(mins, int) or isinstance(mins, bool) or mins < 0:
        out.append("impact.downtime_minutes: a whole number of minutes, 0 or more")
    for k in ("database_migration", "ruleset_reapproval"):
        if not isinstance(imp.get(k), bool):
            out.append(f"impact.{k}: true or false")
    acts = imp.get("site_actions_ja")
    if not isinstance(acts, list) or not all(_ja(a) for a in acts):
        out.append("impact.site_actions_ja: a list of what hospital IT does, in Japanese (an empty list is allowed)")
    return out


def impact_sheet(src: Mapping[str, Any], bundle_id: str, release_seq: int) -> dict[str, Any]:
    imp = src["impact"]
    return {
        "format": IMPACT_FORMAT,
        "bundle_id": bundle_id,
        "release_seq": release_seq,
        "title_ja": src["title_ja"].strip(),
        "classes": [
            {
                "class": cc,
                "name_ja": name,
                "changed": bool(src["changes"][cc]["changed"]),
                "what_ja": str(src["changes"][cc].get("what_ja") or "").strip(),
            }
            for cc, name in CLASSES.items()
        ],
        "downtime_minutes": int(imp["downtime_minutes"]),
        "database_migration": bool(imp["database_migration"]),
        "ruleset_reapproval": bool(imp["ruleset_reapproval"]),
        "backup_first": True,  # every update backs up first (D-126); said here so the sheet stands alone
        "site_actions_ja": [str(a).strip() for a in imp.get("site_actions_ja") or []],
    }


def sheet_problems(sheet: Any) -> list[str]:
    """A change-impact sheet read from a bundle: every class listed, once, in order, each changed or not."""
    if not isinstance(sheet, Mapping) or sheet.get("format") != IMPACT_FORMAT:
        return [f"{IMPACT} is not a {IMPACT_FORMAT} sheet"]
    rows = sheet.get("classes")
    if not isinstance(rows, list) or [r.get("class") if isinstance(r, Mapping) else None for r in rows] != list(
        CLASSES
    ):
        return [f"{IMPACT} does not list the change classes CC1 to CC6"]
    if not all(isinstance(r.get("changed"), bool) for r in rows):
        return [f"{IMPACT}: a change class is neither changed nor unchanged"]
    return []


def render_note(sheet: Mapping[str, Any], summary_ja: str) -> str:
    yes = {True: "あり", False: "なし"}
    lines = [
        f"# {sheet['title_ja']}",
        "",
        f"リリース {sheet['bundle_id']}（release_seq {sheet['release_seq']}）",
        "",
        summary_ja.strip(),
        "",
        "## 変更区分",
        "",
        "| 区分 | 名称 | 変更 | 内容 |",
        "| --- | --- | --- | --- |",
    ]
    for r in sheet["classes"]:
        lines.append(f"| {r['class']} | {r['name_ja']} | {yes[r['changed']]} | {r['what_ja'] or '–'} |")
    lines += [
        "",
        "## 施設への影響",
        "",
        f"- 停止時間の目安: 約 {sheet['downtime_minutes']} 分（その間は誰も作業できません）",
        f"- データベースの移行: {yes[sheet['database_migration']]}",
        f"- 選択・除外基準の再承認: {'必要' if sheet['ruleset_reapproval'] else '不要'}",
        "- 適用の前に自動でバックアップを取り、確認に失敗した場合は自動で元のリリースに戻ります。",
        "",
        "## 病院IT担当の作業",
        "",
    ]
    lines += [f"- {a}" for a in sheet["site_actions_ja"]] or ["- なし"]
    return "\n".join(lines) + "\n"


def load_source(path: Path) -> Any:
    import yaml

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise NoteError(f"{path}: {exc}") from exc


def build(source: Path, bundle_id: str, release_seq: int, out_dir: Path) -> tuple[Path, Path]:
    """The two payloads in ``out_dir``; :class:`NoteError` with every problem when the source does not make them."""
    src = load_source(source)
    problems = source_problems(src)
    if problems:
        raise NoteError(f"{source}: " + "; ".join(problems))
    sheet = impact_sheet(src, bundle_id, release_seq)
    out_dir.mkdir(parents=True, exist_ok=True)
    note, imp = out_dir / NOTE, out_dir / IMPACT
    note.write_text(render_note(sheet, src["summary_ja"]), encoding="utf-8")
    imp.write_text(json.dumps(sheet, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return note, imp


def read_from_bundle(bundle: Path) -> dict[str, Any]:
    """The note and the sheet of a bundle the verifier has accepted, each read only when its size and sha256 are the
    manifest's: ``{"bundle_id", "release_seq", "note_ja", "impact", "warnings"}``. A missing or unreadable file is
    None with a warning; nothing here raises on the bundle's content."""
    out: dict[str, Any] = {"bundle_id": None, "release_seq": None, "note_ja": None, "impact": None, "warnings": []}
    try:
        with tarfile.open(bundle, "r:") as tf:
            mem = tf.getmember("manifest.json")
            f = tf.extractfile(mem) if mem.isfile() and mem.size <= 4 << 20 else None
            manifest = json.loads(f.read()) if f is not None else {}
            if not isinstance(manifest, dict):
                manifest = {}
            out["bundle_id"], out["release_seq"] = manifest.get("bundle_id"), manifest.get("release_seq")
            listed = {e.get("path"): e for e in manifest.get("files") or [] if isinstance(e, dict)}
            for name, key in ((NOTE, "note_ja"), (IMPACT, "impact")):
                entry = listed.get(name)
                if entry is None or entry.get("kind") != "other":
                    out["warnings"].append(f"no {name} in this bundle")
                    continue
                try:
                    m = tf.getmember(f"files/{name}")
                except KeyError:
                    out["warnings"].append(f"{name} is listed but not in the bundle")
                    continue
                fh = tf.extractfile(m) if m.isfile() and m.size <= MAX_BYTES else None
                body = fh.read(MAX_BYTES + 1) if fh is not None else b""
                if (
                    fh is None
                    or len(body) != entry.get("size")
                    or hashlib.sha256(body).hexdigest() != entry.get("sha256")
                ):
                    out["warnings"].append(f"{name} does not match the manifest (or is too large); not shown")
                    continue
                try:
                    text = body.decode("utf-8")
                    out[key] = text if key == "note_ja" else json.loads(text)
                except ValueError:
                    out["warnings"].append(f"{name} is not readable UTF-8 text or JSON")
    except (OSError, KeyError, ValueError, tarfile.TarError) as exc:
        out["warnings"].append(f"the bundle could not be read: {type(exc).__name__}")
    if out["impact"] is not None and (bad := sheet_problems(out["impact"])):
        out["warnings"] += bad
        out["impact"] = None
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ck = sub.add_parser("check", help="the source makes a note and a sheet (exit 1 with each problem)")
    ck.add_argument("--source", type=Path, default=SOURCE)
    b = sub.add_parser("build", help="RELEASE-NOTE.ja.md and CHANGE-IMPACT.json into --out-dir")
    b.add_argument("--source", type=Path, default=SOURCE)
    b.add_argument("--id", required=True)
    b.add_argument("--release-seq", type=int, required=True)
    b.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "check":
            problems = source_problems(load_source(a.source))
            for p in problems:
                print(f"release note: {a.source}: {p}", file=sys.stderr)
            if not problems:
                print(f"release note: {a.source} states every change class")
            return 1 if problems else 0
        note, imp = build(a.source, a.id, a.release_seq, a.out_dir)
    except NoteError as exc:
        print(f"release note: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {note.name} and {imp.name} for {a.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
