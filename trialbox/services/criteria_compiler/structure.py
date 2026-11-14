"""A protocol's structure in the lines the compiler is given (NEW-LIFE-2, compiler half; deep review 2026-11-12,
LIFE-002).

The parser hands the compiler one flat list per section, and the compiler made one ANDed criterion of each line. A
real protocol is not flat: a heading or a group's lead-in ends with a colon and the lines under it may be
alternatives ("MCI due to AD: …" or "Mild AD dementia: …"); a heading can be glued to the end of a line; an
extension phase or a later part has criteria of its own ("completed the Core Study"); and a second inclusion section
is another phase or population. Made into required criteria, an alternative excludes every patient of the other
group, silently. Until the IR can say "any of" (step 2), :func:`check` finds these lines and the compiler sends each
to a person with a warning that says why (``Compiler.compile``). A plain list is left alone.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

# a section heading inside a line, after some text of its own (glued by the parser)
_HEADING = re.compile(
    r"\S.*?\b(?:key\s+)?(?:inclusion|exclusion)\s+criteria\b|\S.*?(?:選択基準|除外基準|納入條件|排除條件)", re.I
)
# a line naming another study phase: an extension, a later part, a core or double-blind study already completed
_PHASE = re.compile(
    r"\bextension\s+(?:phase|period|study)\b|\bopen[- ]label\s+(?:extension|period|phase)\b|\bpart\s+[b-e]\b"
    r"|\bcompleted\s+(?:the\s+)?(?:core\s+study|double[- ]blind|week\s+\d+)|継続投与期|延長(?:投与)?期|延伸期|延長期",
    re.I,
)
_LEAD = re.compile(r"[:：]\s*$")

MESSAGES = {
    "group_heading": "ends with a colon: a heading or the lead-in of a group, not a criterion of its own",
    "group_member": "comes under the lead-in {lead}: it may be one of several alternatives (any of), not required on "
    "its own",
    "heading_in_line": "holds a section heading inside its text: two lines may have been glued together",
    "other_phase": "names another study phase (an extension, a later part, or a study already completed)",
    "second_section": "comes from a second {kind} section ({title}): another study phase or population",
}


@dataclass(frozen=True)
class Finding:
    """Line ``index`` of the compiler's lines, what was found (``flag``, a key of :data:`MESSAGES`) and why."""

    index: int
    flag: str
    message: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # about the protocol as a whole

    def by_index(self) -> dict[int, list[Finding]]:
        out: dict[int, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.index, []).append(f)
        return out


def _section(ref: str) -> str:
    return ref.rsplit(" #", 1)[0] if " #" in ref else ref


def check(lines: Sequence[dict[str, Any]]) -> Report:
    """What in ``lines`` (``text``, ``kind``, ``source_ref`` as ``"<section title> #<n>"``) is structure rather
    than one required criterion."""
    rep = Report()
    lead: int | None = None
    kind_of_lead = section_of_lead = ""
    first_section: dict[str, str] = {}
    for i, ln in enumerate(lines):
        text, kind = str(ln.get("text") or "").strip(), str(ln.get("kind") or "")
        section = _section(str(ln.get("source_ref") or ""))
        if kind != kind_of_lead or section != section_of_lead:
            lead = None  # a group ends with its section
        if section:
            first = first_section.setdefault(kind, section)
            if section != first:
                rep.findings.append(
                    Finding(i, "second_section", MESSAGES["second_section"].format(kind=kind, title=section))
                )
                warning = f"two {kind} sections ({first}; {section}): another study phase or population?"
                if warning not in rep.warnings:
                    rep.warnings.append(warning)
        if _LEAD.search(text):
            rep.findings.append(Finding(i, "group_heading", MESSAGES["group_heading"]))
            lead, kind_of_lead, section_of_lead = i, kind, section
        elif lead is not None:
            rep.findings.append(Finding(i, "group_member", MESSAGES["group_member"].format(lead=f"line {lead + 1}")))
        if _HEADING.search(text):
            rep.findings.append(Finding(i, "heading_in_line", MESSAGES["heading_in_line"]))
        if _PHASE.search(text):
            rep.findings.append(Finding(i, "other_phase", MESSAGES["other_phase"]))
    if any(f.flag == "group_member" for f in rep.findings):
        rep.warnings.append(
            "lines under a lead-in ending with a colon may be alternatives (any of), not each required: each is sent "
            "to a person; write a group of alternatives as one line"
        )
    return rep


def send_to_a_person(criteria: list[Any], rep: Report) -> tuple[list[Any], list[str]]:
    """``criteria`` (one per line, in the lines' order) with each line :func:`check` found made class ``human``
    (flags ``needs_review``, ``structure`` and what was found), and one warning per such criterion."""
    found = rep.by_index()
    out: list[Any] = []
    warnings: list[str] = []
    for i, c in enumerate(criteria):
        fs = found.get(i)
        if not fs or (c.review and c.review.status == "rejected"):
            out.append(c)
            continue
        flags = sorted(set(c.flags or []) | {"needs_review", "structure"} | {f.flag for f in fs})
        question = c.human_question or f"Confirm with the patient/clinician: {c.text}"
        out.append(c.model_copy(update={"class_": "human", "human_question": question, "flags": flags}))
        warnings.append(f"{c.id}: " + "; ".join(f.message for f in fs) + "; moved to human review")
    return out, warnings
