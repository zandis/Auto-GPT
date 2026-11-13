"""One excerpt builder (T-710, D-479; review 2026-11-12 ``decision.md`` AD-4, root cause R3).

The text a model reads was chosen by each caller: the cascade showed the notes with a lexicon hit (else the notes of
the top five sentences) inside a fixed 2,500 tokens; the v1 path showed the five chunks a retrieval returned and
counted as "left out" only those of the five that did not fit; CASE showed the whole upload with no budget. So the
same note question was answered from different text on each path, and two models agreeing "not met" on five chunks
excluded a patient whose decisive note they never saw (review H4).

:func:`build` is the one place:

* ``window``: **every** note of the patient inside the criterion's window (the caller's query, not a ranking);
* ``evidence``: what the caller's ranking points at, per note: the cascade's lexicon-hit or top sentences, the v1
  retrieval's chunks; empty for CASE. It decides what is read **first** (in the ranking's own order when the caller
  has one), never what counts as read;
* ``budget``: tokens of notes one judge prompt may hold: the models' context (T-603, ``NoteJudge.excerpt_budget``),
  or :data:`DEFAULT_TOKENS` for a client that cannot tell its context (OD-10: no other fixed budget).

It shows whole notes, the evidence notes first and then the rest of the window, newest first, while they fit.
A window note with no text is not shown and counts as left out. An
evidence note longer than half the budget is cut to that half, so one long note never hides the others (D-142,
review A-06): windows of whole sentences around its evidence, each under its heading and the lead-in of its list,
with ``[…]`` wherever sentences were left out and nothing stitched (:func:`clip`; NEW-LLM-1, D-641). Any other note
that does not fit is skipped.

**``left_out`` counts every window note not shown in full**: skipped, or clipped. Both models read the one set, so
with a note left out their agreement on "not met" says nothing about what they did not read: the callers make such
an answer unknown, and flag a "met" (D-276, T-603; the status function sends both to review, D-478). The shown list
is newest first (within a day in the notes' own order), whatever the order the notes were taken in.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from typing import Any

from tb_llm.budget import excerpt_tokens

#: the budget when no client can tell its context: what fits beside the judge prompt and its answer on the smallest
#: registered build (8k, T-603). A known context replaces it; it is the one fixed number of this module (OD-10)
DEFAULT_TOKENS = 2500
#: what an excerpt shows where sentences of its note were left out (NEW-LLM-1, D-641)
GAP = "[…]"
_SENT = re.compile(r"[^。！？!?\n]+[。！？!?]?")


def sentences(text: str) -> list[str]:
    """The sentences of a note (Japanese and Chinese full stops, ``!``, ``?``, line ends), each stripped."""
    return [s.strip() for s in _SENT.findall(text) if s.strip()]


def note_tokens(text: str) -> int:
    """What a note of ``text`` adds to the judge prompt (:func:`tb_llm.budget.excerpt_tokens`): CJK characters about
    one token each, other text about four characters per token, plus its JSON keys and escaping."""
    return excerpt_tokens({"date": "0000-00-00", "note_type": "progress", "text": text})


@dataclass(frozen=True)
class Note:
    """One note of the window: its document id, calendar day, type and text (``sents``: its sentences when the
    caller already split it)."""

    did: str
    day: date | str
    type: str
    text: str
    sents: Sequence[str] | None = None

    @property
    def iso(self) -> str:
        return self.day.isoformat() if isinstance(self.day, date) else str(self.day)[:10]


@dataclass(frozen=True)
class ExcerptSet:
    """What the models are shown, newest first, and what they are not: ``left_out`` window notes (skipped or
    clipped), by document id in ``cut``."""

    shown: list[dict[str, Any]] = field(default_factory=list)
    left_out: int = 0
    cut: list[str] = field(default_factory=list)


# a line that is a heading by its brackets (【既往歴】, [Family history], ■ 家族歴), and a line that ends in a colon: a
# heading written that way (家族歴：) or the lead-in of a list (以下の既往なし：, 病人否認下列病史：, "Denies:")
_HEADING = re.compile(
    r"^(?:【[^】]+】|［[^］]+］|\[[^\]]+\]|〈[^〉]+〉|《[^》]+》|<[^>]+>|[■□◆◇●○▼▽◎＃#]+\s*\S.*)\s*[:：]?$"
)
_LEAD_IN = re.compile(r"[:：]$")


def _outline(sents: Sequence[str], at: int) -> list[int]:
    """What governs sentence ``at``, nearest first: the lines ending in a colon above it, up to and with the nearest
    bracketed heading. A heading ends the scope of every lead-in above it."""
    out: list[int] = []
    for i in range(at - 1, -1, -1):
        if _HEADING.match(sents[i]):
            out.append(i)
            break
        if _LEAD_IN.search(sents[i]):
            out.append(i)
    return out


def clip(note: Note, evidence: Iterable[str], cap: int, tokens: Callable[[str], int] = note_tokens) -> str:
    """At most ``cap`` tokens of a long note, as windows around its evidence (NEW-LLM-1, D-641; review LLM-001).

    Always whole sentences of the note, in the note's order, so a quote the model takes is found in the note.
    Sentences shown next to each other are next to each other in the note: wherever some were left out, at the
    start, between two windows or at the end, the excerpt shows :data:`GAP` on a line of its own. Nothing is
    stitched (before, the evidence sentences and the note's start were joined with nothing between, so a list under
    "family history" or under "denies the following" read as the patient's own history).

    What is shown, in this order while it fits: each evidence sentence; above each, what governs it
    (:func:`_outline`: its heading and the lead-in of its list); the sentences between that and the evidence, from
    the evidence upwards; then each window grows by one sentence down and one up in turn. A direction ends at the
    first sentence that does not fit: nothing is skipped to fit a later, shorter one.

    ``evidence``: sentences of the note, or longer fragments (a retrieved chunk) whose sentences count; with none
    found in the note, the note's start is the window."""
    sents = list(note.sents) if note.sents is not None else sentences(note.text)
    wanted = [frag for frag in evidence if frag]
    overhead = tokens("")  # what an excerpt costs before its text (its JSON keys): once per note, not per sentence
    room = cap - overhead
    # + 1: the line break that joins a line to the next, and the rounding of a sum
    cost = [tokens(x) - overhead + 1 for x in sents]
    gap = tokens(GAP) - overhead + 1
    chosen: set[int] = set()
    used = 0

    def gaps(have: set[int]) -> int:
        order = sorted(have)
        inner = sum(1 for a, b in pairwise(order) if b != a + 1)
        return inner + (order[0] != 0) + (order[-1] != len(sents) - 1)

    def take(i: int) -> bool:
        nonlocal used
        if i in chosen:
            return True
        if used + cost[i] + gap * gaps(chosen | {i}) > room:
            return False
        chosen.add(i)
        used += cost[i]
        return True

    first = [i for i, x in enumerate(sents) if any(x == w or x in w for w in wanted)] or ([0] if sents else [])
    for i in first:
        take(i)
    if not chosen and first and cost[first[0]] <= room:
        return sents[first[0]]  # no room to mark the cut: the first evidence sentence alone
    if not chosen:  # one sentence longer than the cap: the note's start
        out: list[str] = []
        used = 0
        for ch in note.text:
            used += 4 if "　" <= ch <= "鿿" else 1
            if used > max(0, room) * 4:
                break
            out.append(ch)
        return "".join(out)
    centres = [i for i in first if i in chosen]
    tops: dict[int, int] = {}  # per evidence sentence: the top of its window (its heading or lead-in, when shown)
    for i in centres:
        above = _outline(sents, i)
        kept = [a for a in above if take(a)]
        tops[i] = min(kept, default=i)
    for i in centres:  # the lines between what governs the evidence and the evidence, from the evidence upwards
        for k in range(i - 1, tops[i], -1):
            if not take(k):
                break
    up = {i: i - 1 for i in centres}
    down = {i: i + 1 for i in centres}
    open_ = {(i, d) for i in centres for d in ("down", "up")}
    while open_:
        for i in centres:
            for d, cursor, step in (("down", down, 1), ("up", up, -1)):
                if (i, d) not in open_:
                    continue
                k = cursor[i]
                if not 0 <= k < len(sents) or not take(k):
                    open_.discard((i, d))
                else:
                    cursor[i] = k + step
    lines: list[str] = []
    last = -1
    for i in sorted(chosen):
        if i != last + 1:
            lines.append(GAP)
        lines.append(sents[i])
        last = i
    if last != len(sents) - 1:
        lines.append(GAP)
    return "\n".join(lines)


_DIGITS = re.compile(r"(\d+)")


def _order(n: Note) -> tuple[Any, ...]:
    """Newest day first; within a day by the note's id read naturally (``#9`` before ``#10``: the paragraphs of an
    uploaded chart keep their order), then by text, so the order never depends on the order the notes came in."""
    day = n.iso
    natural = tuple((0, int(p)) if p.isdigit() else (1, p) for p in _DIGITS.split(n.did) if p != "")
    return (tuple(-ord(ch) for ch in day), natural, n.text)


def build(
    window: Sequence[Note],
    evidence: Mapping[str, Collection[str]],
    budget: int,
    tokens: Callable[[str], int] = note_tokens,
    ranked: bool = False,
) -> ExcerptSet:
    """The excerpts of one judge prompt and how many window notes they leave out (see the module's text).
    ``ranked``: ``evidence`` is in the order of the caller's ranking (best first), and its notes are read in that
    order; else the evidence notes are read newest first."""
    newest_first = sorted(window, key=_order)
    first = [n for n in newest_first if n.did in evidence]
    if ranked:
        rank = {did: i for i, did in enumerate(evidence)}
        first.sort(key=lambda n: rank[n.did])
    order = first + [n for n in newest_first if n.did not in evidence]
    cap = max(1, budget // 2)
    left = budget
    shown: list[tuple[Note, str]] = []
    cut: list[str] = []
    for n in order:
        if not n.text.strip():
            # a note with no text (a scan, an unreadable note) is in the window and the models did not see it:
            # not shown, and left out (review of T-710: the first version skipped it without counting)
            cut.append(n.did)
            continue
        cost = tokens(n.text)
        if cost <= left:
            shown.append((n, n.text))
            left -= cost
            continue
        cut.append(n.did)  # not shown in full: left out, whatever is shown of it below
        # a cut is worth showing only for an evidence note longer than half the budget, at that half, while half
        # the budget is still free (as the cascade cut before T-710); a shorter note that no longer fits is skipped,
        # never shredded into the last few tokens
        if n.did not in evidence or cost <= cap or cap > left:
            continue
        part = clip(n, evidence[n.did], cap, tokens)
        part_cost = tokens(part)
        if part and part_cost <= left:
            shown.append((n, part))
            left -= part_cost
    shown.sort(key=lambda x: _order(x[0]))
    out = [{"date": n.iso, "note_type": n.type, "text": text, "did": n.did} for n, text in shown]
    return ExcerptSet(out, len(cut), cut)
