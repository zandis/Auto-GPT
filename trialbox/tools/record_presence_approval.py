"""Record a person's approval of one held presence line, exactly as it stands (gate 1).

    python -m tools.record_presence_approval --ruleset-dir DIR --criterion ID --actor "Name" \\
        --approvals FILE --audit-dir DIR [--date YYYY-MM-DD]

The compiler proposes; a person approves each held line once. This writes that approval in the recorded-approval
form (``criteria_compiler.ir_extract.presence_approvals``): the line's protocol, criterion ID, kind, exact text and
its SHA-256, class, coded logic, notes question, flags, and the codes of each coded ValueSet as the ruleset in
``DIR`` holds them, with the person's name and the date. ``admit_presence`` releases the line only while all of
these still match; any change, one character included, holds it again.

The audit event ``compile.presence_approval_recorded`` (actor: the person; with the label) is written first. If it
cannot be written, nothing is recorded. A line with no coded presence logic, an approval already recorded for the
line, or an unreadable approvals file is refused. The messages are in en, zh-TW and ja.

A console screen for this is the next slice of gate 1 (``docs/plan/gates/gate-1.md``).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from criteria_compiler.ir_extract.presence_approvals import (
    PERSON_LABEL,
    SHIPPED_BY,
    SYNTHETIC_LABEL,
    PresenceApprovalsRefused,
    approval_of,
    read_approvals,
    write_approvals,
)
from criteria_compiler.semantics import FILTERED, CompileError, Kind, atoms, kind
from criteria_compiler.terminology.mapper import Concept, MappingResult, ValueSets
from tb_common.audit import AuditLog
from tb_common.ruleset import Ruleset

EVENT = "compile.presence_approval_recorded"
MESSAGES = {
    "recorded": {
        "en": "Approval recorded for {criterion} by {actor}.",
        "zh-TW": "已記錄 {actor} 對 {criterion} 的核准。",
        "ja": "{actor} による {criterion} の承認を記録しました。",
    },
    "not_presence": {
        "en": "{criterion} has no coded presence logic to approve. Nothing was recorded.",
        "zh-TW": "{criterion} 沒有可核准的編碼存在條件，未記錄任何內容。",
        "ja": "{criterion} には承認できるコード化された存在条件がありません。何も記録していません。",
    },
    "already": {
        "en": "An approval for {criterion} is already recorded. Nothing was recorded.",
        "zh-TW": "{criterion} 已有核准紀錄，未記錄任何內容。",
        "ja": "{criterion} の承認は既に記録されています。何も記録していません。",
    },
    "invalid": {
        "en": "The approval could not be recorded (the line, the approvals file or the name is not valid).",
        "zh-TW": "無法記錄核准（條件、核准檔案或姓名無效）。",
        "ja": "承認を記録できませんでした（基準、承認ファイルまたは氏名が不正です）。",
    },
    "audit": {
        "en": "The audit event could not be written. Nothing was recorded.",
        "zh-TW": "無法寫入稽核事件，未記錄任何內容。",
        "ja": "監査イベントを書き込めませんでした。何も記録していません。",
    },
}


def _say(key: str, **values: str) -> str:
    return "\n".join(MESSAGES[key][lang].format(**values) for lang in ("en", "zh-TW", "ja"))


def _mappings(rs: Ruleset, criterion_logic: object) -> dict[str, MappingResult]:
    """The codes of each coded ValueSet as the ruleset holds them: what the person sees and approves."""
    pinned = ValueSets(rs.id, rs.valuesets, None)
    out: dict[str, MappingResult] = {}
    for atom in atoms(criterion_logic):  # type: ignore[arg-type]
        if kind(atom) is Kind.DEMOGRAPHIC:
            continue
        concepts = [Concept(system, code, "") for system, code in sorted(pinned.codes(atom.valueset))]
        families = sorted(pinned.families(atom.valueset))
        out[atom.valueset] = MappingResult(atom.valueset, atom.domain, concepts, "loaded", False, [], families)
    return out


def record(
    ruleset_dir: Path, criterion_id: str, actor: str, approvals_path: Path, audit: AuditLog, on: str
) -> tuple[int, str]:
    """(exit code, message). Writes the audit event first; the approvals file only after it."""
    name = actor.strip()
    if not name or name in {SHIPPED_BY, SYNTHETIC_LABEL, PERSON_LABEL}:
        return 2, _say("invalid")
    try:
        rs = Ruleset.load(ruleset_dir)
        criterion = rs.by_id()[criterion_id]
    except (OSError, KeyError, ValueError):
        return 2, _say("invalid")
    try:
        coded = criterion.class_ in FILTERED and any(kind(a) is Kind.PRESENCE for a in atoms(criterion.logic))
        mappings = _mappings(rs, criterion.logic) if coded else {}
    except (CompileError, KeyError):
        coded = False
    if not coded:
        return 2, _say("not_presence", criterion=criterion_id)
    try:
        approval = approval_of(criterion, mappings, actor=name, recorded_at=on)
        existing = read_approvals(approvals_path) if approvals_path.exists() else ()
    except PresenceApprovalsRefused:
        return 2, _say("invalid")
    if any((a.protocol, a.criterion) == (approval.protocol, approval.criterion) for a in existing):
        return 2, _say("already", criterion=criterion_id)
    try:
        receipt = audit.append(
            EVENT,
            ruleset=approval.protocol,
            actor=name,
            input_sha=approval.text_sha256,
            detail={
                "criterion": approval.criterion,
                "approval_label": approval.label,
                "approval_basis": approval.basis,
                "approvals_file": approvals_path.name,
            },
        )
    except (OSError, RuntimeError, ValueError):
        return 2, _say("audit")
    if not receipt or receipt.get("event") != EVENT:
        return 2, _say("audit")
    partial = approvals_path.with_name(approvals_path.name + ".partial")
    write_approvals(partial, [*existing, approval])
    os.replace(partial, approvals_path)
    return 0, _say("recorded", criterion=criterion_id, actor=name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ruleset-dir", type=Path, required=True)
    parser.add_argument("--criterion", required=True)
    parser.add_argument("--actor", required=True, help="the person's name")
    parser.add_argument("--approvals", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args(argv)
    code, message = record(
        args.ruleset_dir, args.criterion, args.actor, args.approvals, AuditLog(args.audit_dir), args.date
    )
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
