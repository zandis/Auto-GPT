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
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

# a section heading inside a line, after text of its own (glued by the parser). English: the capitalised heading
# ("… Key Inclusion Criteria that must be met"), never "meets all inclusion criteria"; Japanese and Chinese: a heading
# after a space at the end of the line, never "…符合初次申請之納入條件" (an NHI renewal rule's own words)
_HEADING = re.compile(
    r"^(?!\s*(?:Key\s+)?(?:Inclusion|Exclusion)\s+Criteria).*\S\s+(?:Key\s+)?(?:Inclusion|Exclusion)\s+Criteria\b"
    r"|\S\s+(?:主な|主要)?(?:選択基準|除外基準|納入條件|排除條件)\s*[:：]?\s*$"
)
# another study phase, part, period, stage or cohort: an extension, a rollover, a study already completed
_PHASE = re.compile(
    r"\bextension\s+(?:phase|period|study)\b|\bopen[- ]label\s+(?:extension|period|phase)\b"
    r"|\b(?:part|stage|period)\s+(?:[b-e]|[2-5]|ii+)\b(?!\s+of\s+(?!(?:the\s+)?(?:study|trial|protocol)\b))"
    r"|\bphase\s+(?:ii+|[2-4])\s+(?:portion|part)\b|\bcohort\s+(?:[a-e]|[1-9])\b"
    r"|\bcompleted\s+(?:the\s+)?(?:\d+[- ]week\s+)?(?:core\s+study|double[- ]blind|treatment\s+period|parent\s+study"
    r"|(?:period|part|stage)\s+\w+)|\broll(?:ed)?[- ]?over\b|\bparent\s+study\b|\bre-?randomi[sz]"
    r"|継続投与期|延長(?:投与)?期|延伸期|延長試驗",
    re.I,
)
# alternatives inside one line: one of, any of, either … or, いずれか, 任一, 之一
_ANY = re.compile(r"\b(?:one|any)\s+of\b|\beither\b.+\bor\b|いずれか|任一|之一", re.I)
# a lead-in of lines that are all required: it opens no group of alternatives
_ALL = re.compile(r"\ball\b|\bmust\b|\bagree|すべて|全て|全部|所有|均須|皆須|均需", re.I)
_LEAD = re.compile(r"[:：]\s*[.。]?\s*$")
_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")

MESSAGES = {
    "group_heading": "ends with a colon: a heading or the lead-in of a group, not a criterion of its own",
    "group_member": "comes under the lead-in {lead}: it may be one of several alternatives (any of), not required on "
    "its own",
    "alternatives_in_line": "holds alternatives inside one line (one of, any of, either … or): compiled as one "
    "criterion they may all be required",
    "heading_in_line": "holds a section heading inside its text: two lines may have been glued together",
    "other_phase": "names another study phase, part, period or cohort (an extension, a rollover, a study already "
    "completed)",
    "second_section": "comes from a second {kind} section ({title}): another study phase or population",
}
# what the reviewer is asked, by the first flag found in this order
QUESTIONS = (
    ("group_heading", "This line is a heading or the lead-in of a group, not a criterion: reject it, or rewrite it "
     "with the lines under it as one criterion."),
    ("heading_in_line", "This line holds a section heading: correct or split it."),
    ("other_phase", "This line belongs to another study phase, part or cohort: reject it for this screening, or "
     "confirm it applies."),
    ("second_section", "This line comes from a second section (another phase or population): reject it for this "
     "screening, or confirm it applies."),
    ("alternatives_in_line", "This line holds alternatives: rewrite it so that one of them is enough, or confirm."),
    ("group_member", "This line may be one of several alternatives: rewrite the group as one criterion, or confirm it "
     "is required on its own."),
)  # fmt: skip


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


def _opens_group(text: str) -> bool:
    """A lead-in opens a group of perhaps-alternative lines unless its own last words say its lines are all required
    ("… must be met by all participants:", "… must agree to the following:"). Only the last words count: the parser
    glues a heading to the end of the line before it ("… corroborated by an informant Mild Alzheimer's disease
    dementia:"), and the earlier words are that line's own."""
    if _ANY.search(text):
        return True
    body = _LEAD.sub("", text).strip()
    tail = body[-12:] if _CJK.search(body[-12:]) else " ".join(body.split()[-6:])
    return not _ALL.search(tail)


def check(lines: Sequence[dict[str, Any]], doc_kind: str = "trial") -> Report:
    """What in ``lines`` (``text``, ``kind``, ``source_ref`` as ``"<section title> #<n>"``) is structure rather
    than one required criterion. ``doc_kind`` ``cohort``: an alliance cohort document's two inclusion sections are
    its population and its counted characteristics (D-71), not two phases.

    The parser keys a line's section by its text, so a text found twice carries the later section for both: such a
    line's section is not used (neither as a second section nor to decide which came first)."""
    rep = Report()
    seen = Counter(str(ln.get("text") or "").strip() for ln in lines)
    # NEW-LIFE-2: the parser gave each line its lead-in and its own section (positional): a group is exactly the
    # lines that name its lead-in, and a repeated text keeps its own section
    given = any("parent" in ln for ln in lines)
    lead: int | None = None
    lead_at = ("", "")
    first_section: dict[str, str] = {}
    for i, ln in enumerate(lines):
        text, kind = str(ln.get("text") or "").strip(), str(ln.get("kind") or "")
        raw = _section(str(ln.get("source_ref") or ""))
        section = raw if (given or seen[text] == 1) else ""
        if (kind, raw) != lead_at:
            lead = None  # a group ends with its section
        found: list[tuple[str, str]] = []
        if section and doc_kind != "cohort":
            first = first_section.setdefault(kind, section)
            if section != first:
                found.append(("second_section", MESSAGES["second_section"].format(kind=kind, title=section)))
                warning = f"two {kind} sections ({first}; {section}): another study phase or population?"
                if warning not in rep.warnings:
                    rep.warnings.append(warning)
        if _LEAD.search(text):
            found.append(("group_heading", MESSAGES["group_heading"]))
            lead, lead_at = (i if _opens_group(text) else None), (kind, raw)
        elif given:
            p = ln.get("parent")
            if isinstance(p, int) and 0 <= p < len(lines) and _opens_group(str(lines[p].get("text") or "")):
                found.append(("group_member", MESSAGES["group_member"].format(lead=f"line {p + 1}")))
        elif lead is not None:
            found.append(("group_member", MESSAGES["group_member"].format(lead=f"line {lead + 1}")))
        if _ANY.search(text):
            found.append(("alternatives_in_line", MESSAGES["alternatives_in_line"]))
        if _HEADING.search(text):
            found.append(("heading_in_line", MESSAGES["heading_in_line"]))
        if _PHASE.search(text) or (section and _PHASE.search(section)):
            found.append(("other_phase", MESSAGES["other_phase"]))
        rep.findings += [Finding(i, flag, msg) for flag, msg in found]
    if any(f.flag in ("group_member", "alternatives_in_line") for f in rep.findings):
        rep.warnings.append(
            "some lines may be alternatives (any of), not each required: each is sent to a person; write a group of "
            "alternatives as one line"
        )
    return rep


def send_to_a_person(criteria: list[Any], rep: Report, keep: Collection[int] = ()) -> tuple[list[Any], list[str]]:
    """``criteria`` (one per line, in the lines' order) with each line :func:`check` found made class ``human``
    (flags ``needs_review``, ``structure`` and what was found; the question says what to do), and one warning per
    such criterion. ``keep``: lines of criteria reused from the approved version, whose reviewer already decided."""
    found = rep.by_index()
    out: list[Any] = []
    warnings: list[str] = []
    for i, c in enumerate(criteria):
        fs = found.get(i)
        if not fs or i in keep:
            out.append(c)
            continue
        names = {f.flag for f in fs}
        flags = sorted(set(c.flags or []) | {"needs_review", "structure"} | names)
        ask = next(q for flag, q in QUESTIONS if flag in names)
        question = f"{ask} ({c.text})"
        out.append(c.model_copy(update={"class_": "human", "human_question": question, "flags": flags}))
        warnings.append(f"{c.id}: " + "; ".join(f.message for f in fs) + "; moved to human review")
    return out, warnings
