"""Recorded approvals of a held presence line (gate 1): a decision on one exact text, kept as data.

The compiler proposes; a person approves each held line once. That approval is a recorded decision on the exact
text, and :func:`criteria_compiler.ir_extract.postprocess.admit_presence` may release the line only when the
record still matches what the compiler proposes now:

* the protocol, the criterion ID and its kind;
* the text, compared code point by code point. Nothing is normalised: no whitespace folding, no Unicode
  normalisation (an NFC and an NFD spelling of one word are two texts), no case folding, no trimming of a final
  period. ``text_sha256`` is the SHA-256 of the text's UTF-8 bytes and must agree with it;
* the class, the coded logic, the notes question, the compiler's flags, and the codes and code families of every
  coded ValueSet. No approval releases a proposal flagged as negated, invalid, unread or already held. The
  codes of a ValueSet are kept as their count and the SHA-256 of their sorted ``system|code`` lines, one per line.

Any difference holds the line for a person again. A shipped approval (``basis`` ``shipped``) comes with one of the
four synthetic protocols and is labelled as a demonstration, not a clinical sign-off. It applies only to those
four protocols and only on a test box (``TB_ENV`` DEV or TEST); an unset ``TB_ENV`` is PRODUCTION (D-127), where
it is refused. A malformed approvals file refuses with one message key; it never falls back to releasing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from tb_common.crypto import sha256_text
from tb_contracts import Atom, BoolExpr, CriterionIR

from criteria_compiler.semantics import CompileError, Kind, atoms, check_bool, kind
from criteria_compiler.terminology.mapper import MappingResult

FORM = "trialbox.presence-approvals/1"
SYNTHETIC_PROTOCOLS = frozenset({"GZQO", "AD-MAB", "NEUR-COH", "RA-JAK"})
SYNTHETIC_LABEL = "synthetic demonstration approval, not a clinical sign-off"
SHIPPED_BY = "shipped with the synthetic protocol"
PERSON_LABEL = "a person's approval of this exact text"
TEST_ENVIRONMENTS = frozenset({"DEV", "TEST"})
SHIPPED_DIR = Path(__file__).with_name("shipped_approvals")
RELEASED_BY = "recorded_approval"

REFUSED = "compile.presence_approvals_invalid"
REFUSAL_TEXT = {
    "en": "The recorded approvals file is not valid. No line was released from it; fix or remove the file.",
    "zh-TW": "已記錄的核准檔案無效，未依此檔案放行任何條件；請修正或移除該檔案。",
    "ja": "記録済み承認ファイルが不正です。このファイルによる基準の採用は行っていません。修正または削除してください。",
}

_ENTRY_KEYS = frozenset(
    {
        "protocol",
        "criterion",
        "kind",
        "text",
        "text_sha256",
        "criterion_class",
        "logic",
        "note_question",
        "flags",
        "codes",
        "families",
        "label",
        "recorded_by",
        "actor",
        "date",
        "basis",
    }
)
_CODE = re.compile(r"^[^|\s]+\|[^|\s]+$")
# a proposal the compiler flagged like this is never released by an approval, shipped or a person's
_NEVER_APPROVED = re.compile(r"negat|invalid|unread|presence_requires_review")
_LOGIC: TypeAdapter[Atom | BoolExpr] = TypeAdapter(Atom | BoolExpr)


@dataclass(frozen=True)
class Proposal:
    """What the compiler proposes for one line, as an approval is compared with it."""

    ruleset: str
    id: str
    kind: str
    text: str
    class_: str
    logic: Atom | BoolExpr
    note_question: str | None
    flags: Sequence[str] | None


class PresenceApprovalsRefused(Exception):
    """A recorded approvals file that cannot be read exactly. ``key`` names the refusal in en, zh-TW and ja."""

    key = REFUSED

    def __init__(self) -> None:
        super().__init__(f"{REFUSED}: {REFUSAL_TEXT['en']}")


@dataclass(frozen=True)
class RecordedApproval:
    protocol: str
    criterion: str
    kind: str
    text: str
    text_sha256: str
    class_: str
    logic: dict[str, Any]
    note_question: str | None
    flags: tuple[str, ...]
    codes: dict[str, dict[str, Any]]
    families: dict[str, tuple[str, ...]]
    label: str
    recorded_by: str
    actor: str
    date: str
    basis: str

    def record(self) -> dict[str, Any]:
        """The file form of this approval."""
        return {
            "protocol": self.protocol,
            "criterion": self.criterion,
            "kind": self.kind,
            "text": self.text,
            "text_sha256": self.text_sha256,
            "criterion_class": self.class_,
            "logic": self.logic,
            "note_question": self.note_question,
            "flags": list(self.flags),
            "codes": {k: dict(v) for k, v in self.codes.items()},
            "families": {k: list(v) for k, v in self.families.items()},
            "label": self.label,
            "recorded_by": self.recorded_by,
            "actor": self.actor,
            "date": self.date,
            "basis": self.basis,
        }

    def release_note(self) -> str:
        """What travels with a criterion this approval released (its review record, a report, a candidate list)."""
        return (
            f"released_by: {RELEASED_BY}; approval_label: {self.label}; recorded_by: {self.recorded_by}; "
            f"actor: {self.actor}; recorded_at: {self.date}; text_sha256: {self.text_sha256}"
        )


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and _CODE.fullmatch(v) for v in value):
        raise PresenceApprovalsRefused()
    if value != sorted(set(value)):
        raise PresenceApprovalsRefused()
    return tuple(value)


def code_digest(codes: Iterable[str]) -> dict[str, Any]:
    """How an approval pins one ValueSet's codes: their count and the SHA-256 of the sorted lines."""
    lines = sorted(set(codes))
    return {"count": len(lines), "sha256": sha256_text("\n".join(lines))}


def _digest(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"count", "sha256"}
        or not isinstance(value["count"], int)
        or isinstance(value["count"], bool)
        or value["count"] < 1
        or not isinstance(value["sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
    ):
        raise PresenceApprovalsRefused()
    return {"count": value["count"], "sha256": value["sha256"]}


def _entry(raw: Any) -> RecordedApproval:
    if not isinstance(raw, dict) or set(raw) != _ENTRY_KEYS:
        raise PresenceApprovalsRefused()
    for name in (
        "protocol",
        "criterion",
        "kind",
        "text",
        "text_sha256",
        "criterion_class",
        "label",
        "recorded_by",
        "actor",
    ):
        if not isinstance(raw[name], str) or not raw[name].strip():
            raise PresenceApprovalsRefused()
    if raw["note_question"] is not None and not isinstance(raw["note_question"], str):
        raise PresenceApprovalsRefused()
    if sha256_text(raw["text"]) != raw["text_sha256"] or raw["kind"] not in {"inclusion", "exclusion"}:
        raise PresenceApprovalsRefused()
    if raw["criterion_class"] not in {"structured", "mixed"} or raw["basis"] not in {"shipped", "person"}:
        raise PresenceApprovalsRefused()
    if not raw["criterion"].startswith(raw["protocol"] + "-"):
        raise PresenceApprovalsRefused()
    if raw["basis"] == "shipped" and (raw["label"] != SYNTHETIC_LABEL or raw["recorded_by"] != SHIPPED_BY):
        raise PresenceApprovalsRefused()
    if raw["basis"] == "person" and raw["label"] == SYNTHETIC_LABEL:
        raise PresenceApprovalsRefused()
    if not isinstance(raw["date"], str):
        raise PresenceApprovalsRefused()
    try:
        date.fromisoformat(raw["date"])
        logic = _LOGIC.validate_python(raw["logic"])
        check_bool(logic)
    except (CompileError, ValueError):  # pydantic's ValidationError is a ValueError; its text is never used
        raise PresenceApprovalsRefused() from None
    if not isinstance(raw["codes"], dict) or not isinstance(raw["families"], dict):
        raise PresenceApprovalsRefused()
    coded = {a.valueset for a in atoms(logic) if a.domain != "demographic"}
    if not coded or set(raw["codes"]) != coded or not set(raw["families"]) <= coded:
        raise PresenceApprovalsRefused()
    codes = {k: _digest(v) for k, v in sorted(raw["codes"].items())}
    flags = raw["flags"]
    if (
        not isinstance(flags, list)
        or not all(isinstance(f, str) and f for f in flags)
        or flags != sorted(set(flags))
        or any(_NEVER_APPROVED.search(f) for f in flags)
    ):
        raise PresenceApprovalsRefused()
    return RecordedApproval(
        protocol=raw["protocol"],
        criterion=raw["criterion"],
        kind=raw["kind"],
        text=raw["text"],
        text_sha256=raw["text_sha256"],
        class_=raw["criterion_class"],
        logic=_logic_form(logic),
        note_question=raw["note_question"],
        flags=tuple(flags),
        codes=codes,
        families={k: _strings(v) for k, v in sorted(raw["families"].items()) if v},
        label=raw["label"],
        recorded_by=raw["recorded_by"],
        actor=raw["actor"],
        date=raw["date"],
        basis=raw["basis"],
    )


def parse_approvals(raw: Any) -> tuple[RecordedApproval, ...]:
    """Every entry or none: one malformed entry refuses the whole file."""
    if not isinstance(raw, dict) or set(raw) != {"form", "approvals"} or raw["form"] != FORM:
        raise PresenceApprovalsRefused()
    if not isinstance(raw["approvals"], list):
        raise PresenceApprovalsRefused()
    approvals = tuple(_entry(e) for e in raw["approvals"])
    keys = [(a.protocol, a.criterion) for a in approvals]
    if len(set(keys)) != len(keys):
        raise PresenceApprovalsRefused()
    return approvals


def read_approvals(path: Path) -> tuple[RecordedApproval, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # a missing, unreadable or non-JSON file; its error text is never used
        raise PresenceApprovalsRefused() from None
    return parse_approvals(raw)


def write_approvals(path: Path, approvals: Iterable[RecordedApproval]) -> None:
    body = {"form": FORM, "approvals": [a.record() for a in approvals]}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def shipped_approvals(protocol: str, environment: str) -> tuple[RecordedApproval, ...]:
    """The labelled approvals shipped with one of the four synthetic protocols, on a test box only."""
    if protocol not in SYNTHETIC_PROTOCOLS or environment.strip().upper() not in TEST_ENVIRONMENTS:
        return ()
    approvals = read_approvals(SHIPPED_DIR / f"{protocol}.json")
    if any(a.protocol != protocol or a.basis != "shipped" for a in approvals):
        raise PresenceApprovalsRefused()
    return approvals


def _logic_form(logic: Atom | BoolExpr) -> dict[str, Any]:
    return logic.model_dump(mode="json", by_alias=True, exclude_none=True)


def _codes_agree(approval: RecordedApproval, logic: Atom | BoolExpr, mappings: Mapping[str, MappingResult]) -> bool:
    for atom in atoms(logic):
        if kind(atom) is Kind.DEMOGRAPHIC:
            continue
        mapped = mappings.get(atom.valueset)
        if mapped is None or mapped.domain != atom.domain or not mapped.concepts:
            return False
        if code_digest(f"{c.system}|{c.code}" for c in mapped.concepts) != approval.codes.get(atom.valueset):
            return False
        if tuple(sorted({f"{s}|{p}" for s, p in mapped.families})) != approval.families.get(atom.valueset, ()):
            return False
    return True


def approval_for(
    criterion: CriterionIR | Proposal,
    source_text: str,
    mappings: Mapping[str, MappingResult],
    approvals: Sequence[RecordedApproval],
    environment: str,
) -> RecordedApproval | None:
    """The one recorded approval that still matches this proposal exactly, else None."""
    flags = tuple(sorted(set(criterion.flags or [])))
    if any(_NEVER_APPROVED.search(f) for f in flags):
        return None
    test_box = environment.strip().upper() in TEST_ENVIRONMENTS
    for approval in approvals:
        if approval.basis == "shipped" and (not test_box or criterion.ruleset not in SYNTHETIC_PROTOCOLS):
            continue
        if (approval.protocol, approval.criterion, approval.kind) != (criterion.ruleset, criterion.id, criterion.kind):
            continue
        if not (approval.text == source_text == criterion.text) or sha256_text(criterion.text) != approval.text_sha256:
            continue
        if approval.class_ != criterion.class_ or approval.note_question != criterion.note_question:
            continue
        if approval.flags != flags:
            continue
        try:
            same_logic = approval.logic == _logic_form(criterion.logic) and _codes_agree(
                approval, criterion.logic, mappings
            )
        except (CompileError, KeyError, TypeError):
            return None
        if same_logic:
            return approval
    return None


def approval_of(
    criterion: CriterionIR,
    mappings: Mapping[str, MappingResult],
    *,
    actor: str,
    recorded_at: str,
    basis: str = "person",
) -> RecordedApproval:
    """The record of approving this proposal exactly as it stands: its text, logic and mapped codes.

    A person's approval names the person (``actor``). A shipped one is labelled and refused outside a synthetic
    protocol. The record is read back through the file parser, so it cannot hold what a file could not.
    """
    codes: dict[str, dict[str, Any]] = {}
    families: dict[str, list[str]] = {}
    try:
        for atom in atoms(criterion.logic):
            if kind(atom) is Kind.DEMOGRAPHIC:
                continue
            mapped = mappings.get(atom.valueset)
            if mapped is None or mapped.domain != atom.domain or not mapped.concepts:
                raise PresenceApprovalsRefused()
            codes[atom.valueset] = code_digest(f"{c.system}|{c.code}" for c in mapped.concepts)
            if mapped.families:
                families[atom.valueset] = sorted({f"{s}|{p}" for s, p in mapped.families})
    except CompileError:
        raise PresenceApprovalsRefused() from None
    shipped = basis == "shipped"
    return _entry(
        {
            "protocol": criterion.ruleset,
            "criterion": criterion.id,
            "kind": criterion.kind,
            "text": criterion.text,
            "text_sha256": sha256_text(criterion.text),
            "criterion_class": criterion.class_,
            "logic": _logic_form(criterion.logic),
            "note_question": criterion.note_question,
            "flags": sorted(set(criterion.flags or [])),
            "codes": codes,
            "families": families,
            "label": SYNTHETIC_LABEL if shipped else PERSON_LABEL,
            "recorded_by": SHIPPED_BY if shipped else actor,
            "actor": actor,
            "date": recorded_at,
            "basis": basis,
        }
    )


def release_note(criterion: CriterionIR) -> str | None:
    """The release note a criterion carries in its review record, if a recorded approval released it."""
    comment = criterion.review.comment if criterion.review else None
    if comment and comment.startswith(f"released_by: {RELEASED_BY};"):
        return comment.split("\n", 1)[0]
    return None
