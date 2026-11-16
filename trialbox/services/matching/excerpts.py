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
review A-06): windows of whole sentences around its evidence, each under its heading, with ``[…]`` wherever
sentences were left out and nothing stitched (:func:`clip`; NEW-LLM-1, D-641). Any other note
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
from typing import Any

from tb_common.quotes import CUT
from tb_llm.budget import COPIES, excerpt_tokens

#: the budget when no client can tell its context: what fits beside the judge prompt and its answer on the smallest
#: registered build (8k, T-603). A known context replaces it; it is the one fixed number of this module (OD-10)
DEFAULT_TOKENS = 2500
#: what an excerpt shows where sentences of its note were left out (NEW-LLM-1, D-641)
GAP = CUT
_SENT = re.compile(r"[^。！？!?\n]+[。！？!?]?")


# an English full stop that ends a sentence: ". " (a closing bracket or quote may follow it) before a capital, a digit
# or an opening bracket or quote (A-SENT-EN, D-786)
_EN_STOP = re.compile(r"\.[)\]\"']*\s+(?=[(\[\"'A-Z0-9])")
# short forms a full stop does not end a sentence after; "No." only before a number ("No. 12")
_SHORT = frozenset(
    {"dr", "mr", "mrs", "ms", "prof", "st", "sr", "jr", "vs", "e.g", "i.e", "cf", "approx", "fig", "al", "pt", "hx",
     "dx", "rx", "sx", "tx", "vit", "wd", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov",
     "dec"}
)  # fmt: skip
# a label: words then a colon and white space ("Family history: …", "Denies: …"), never a time ("10:00")
_LABEL = re.compile(r":\s")
_CJK_ANY = re.compile(r"[\u3000-\u30ff\u3400-\u9fff\uff00-\uffef]")


def _english(piece: str) -> list[str]:
    """``piece`` (one line, or the part of it up to a CJK stop) split after each English full stop that ends a
    sentence; never after a short form (Dr., e.g., Pt., Jan.), "No." before a number, a list number ("1."), or an
    initial ("J. Smith"). From the first sentence that carries a label ("Family history: …", "Denies: …") the rest
    of the line stays one unit, so an item is never shown without its label (review of D-786). A piece with
    Japanese or Chinese in it is not split here: it splits as it always did."""
    if _CJK_ANY.search(piece):
        return [piece]
    out, start = [], 0
    for m in _EN_STOP.finditer(piece):
        if _LABEL.search(piece, start, m.start()):
            break  # this sentence carries a label: it and the rest of the line are one unit
        tail = piece[max(start, m.start() - 40) : m.start()]  # a bounded look back: linear in the line's length
        word = tail.rsplit(None, 1)[-1].lstrip("([\"'") if tail.strip() else ""
        nxt = piece[m.end() : m.end() + 1]
        if (
            word.lower() in _SHORT
            or (len(word) == 1 and word.isupper())
            or word.isdigit()
            or (word.lower() == "no" and nxt.isdigit())
        ):
            continue
        out.append(piece[start : m.end()])
        start = m.end()
    out.append(piece[start:])
    return out


def sentences(text: str) -> list[str]:
    """The sentences of a note (Japanese and Chinese full stops, ``!``, ``?``, line ends, and an English full stop
    that ends a sentence), each stripped."""
    return [p.strip() for s in _SENT.findall(text) for p in _english(s) if p.strip()]


def note_tokens(text: str) -> int:
    """What a note of ``text`` adds to the judge prompt (:func:`tb_llm.budget.excerpt_tokens`): CJK characters and
    digits one token each, other text about four characters per token, plus its JSON keys and escaping."""
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
    # copy-forward notes not shown because a newer note of the window has the same text (D-905): not left out
    duplicates: list[str] = field(default_factory=list)


# a line that is a heading by its brackets (【既往歴】, 〔家族歴〕, [Family history]): it must hold a letter, so "[1]",
# "<5>" and the cut mark are none. A line led by a list symbol (■ 家族歴) is a heading only when it stands alone:
# next to another line led the same way it is an item of a list (review of #419: "● 糖尿病" is no heading)
_BRACKETED = re.compile(
    r"^(?:【[^】]+】|〔[^〕]+〕|［[^］]+］|＜[^＞]+＞|〈[^〉]+〉|《[^》]+》|\[[^\]]+\]|<[^>]+>)\s*[:：]?$"
)
_SYMBOL = re.compile(r"^[■□◆◇●○▼▽◎＃#]")
_LETTER = re.compile(r"[^\W\d_]")
_COLON = re.compile(r"[:：]$")


def _is_heading(sents: Sequence[str], i: int) -> bool:
    line = sents[i]
    if line == GAP or not _LETTER.search(line):
        return False
    if _BRACKETED.match(line):
        return True
    if not _SYMBOL.match(line):
        return False
    near = [sents[k] for k in (i - 1, i + 1) if 0 <= k < len(sents)]
    return not any(x[:1] == line[:1] for x in near)


def clip(note: Note, evidence: Iterable[str], cap: int, tokens: Callable[[str], int] = note_tokens) -> str:
    """At most ``cap`` tokens of a long note, as windows around its evidence (NEW-LLM-1, D-641; review LLM-001).

    Always whole sentences of the note, in the note's order, so a quote the model takes is found in the note.
    Sentences shown next to each other are next to each other in the note: wherever some were left out, at the
    start, between two windows or at the end, the excerpt shows :data:`GAP` on a line of its own. Nothing is
    stitched (before, the evidence sentences and the note's start were joined with nothing between, so a list under
    "family history" or under "denies the following" read as the patient's own history).

    What is shown, in this order while it fits: each evidence sentence (one copy of each distinct sentence before any
    second copy, else in the note's order); the line right above each when it ends in a colon (its lead-in);
    above each, the nearest heading
    (:func:`_is_heading`), which may stand across a cut; then each window grows by one sentence up and one down in
    turn, so the lines just above the evidence (the lead-in of its list, a heading written with a colon) are shown
    joined to it or not at all. A direction ends at the first sentence that does not fit: nothing is skipped to
    fit a later, shorter one. A window never ends on a line that ends in a colon or on a heading of other text:
    such a line would read as governing what follows the cut.

    ``evidence``: sentences of the note, or longer fragments (a retrieved chunk) whose sentences count; with none
    found in the note, the note's start is the window."""
    sents = list(note.sents) if note.sents is not None else sentences(note.text)
    wanted = [frag for frag in evidence if frag]
    overhead = tokens("")  # what an excerpt costs before its text (its JSON keys): once per note, not per sentence
    room = cap - overhead
    # + 1: the line break that joins a line to the next, and the rounding of a sum
    cost = [tokens(x) - overhead + 1 for x in sents]
    gap = tokens(GAP) - overhead + 1
    last = len(sents) - 1
    chosen: set[int] = set()
    used = 0
    pieces = 0  # runs of chosen sentences next to each other

    def marks(n_pieces: int, have: set[int], i: int) -> int:
        """Cut marks of ``have`` plus sentence ``i``: between the runs, and at either end the note goes beyond."""
        return (n_pieces - 1) + (0 not in have and i != 0) + (last not in have and i != last)

    def take(i: int) -> bool:
        nonlocal used, pieces
        if i in chosen:
            return True
        after = pieces + 1 - (i - 1 in chosen) - (i + 1 in chosen)
        if used + cost[i] + gap * marks(after, chosen, i) > room:
            return False
        chosen.add(i)
        used += cost[i]
        pieces = after
        return True

    first = [i for i, x in enumerate(sents) if any(x == w or x in w for w in wanted)] or ([0] if sents else [])
    # one copy of every distinct evidence sentence before any second copy (D-645): a line the note repeats (a daily
    # "no change" inside a retrieved chunk makes every copy evidence) else takes, in the note's order, the room of
    # the sentences said once; and a repeated sentence is still shown once (review of D-645)
    nth: dict[int, int] = {}
    copies: dict[str, int] = {}
    for i in first:
        nth[i] = copies[sents[i]] = copies.get(sents[i], -1) + 1
    first.sort(key=lambda i: (nth[i], i))
    for i in first:
        take(i)
    if not chosen:
        bare = next((i for i in first if cost[i] <= room), None)
        if bare is not None:
            return sents[bare]  # no room to mark the cut: the first evidence sentence that fits, alone
        # one sentence longer than the cap: the note's start, as many characters as fit (found by halving: the
        # count of a longer start is never smaller; review of D-645: a walk with character costs of its own)
        lo, hi = 0, len(note.text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if tokens(note.text[:mid]) <= cap:
                lo = mid
            else:
                hi = mid - 1
        return note.text[:lo]
    centres = sorted(i for i in first if i in chosen)
    # the lead-in of the evidence's list ("denies the following:"), the line right above it, before the heading:
    # it says most about the evidence, and with room for one of the two the heading alone, across a cut, read as
    # the list's title (D-645: the denied-list case at a budget of 90). When the lead-in does not fit the heading
    # is still shown: under "family history" it is the context, and bare evidence says no more of a denial than
    # the heading does (second review of D-645). Only the line right above: a colon line further up is not
    # carried across a cut (D-641), so the second and later items of such a list are as before
    for i in centres:
        if i > 0 and _COLON.search(sents[i - 1]):
            take(i - 1)
    heads: set[int] = set()  # the heading each evidence sentence stands under, when it is shown
    for i in centres:
        h = next((k for k in range(i - 1, -1, -1) if _is_heading(sents, k)), None)
        if h is not None and take(h):
            heads.add(h)
    up = {i: i - 1 for i in centres}
    down = {i: i + 1 for i in centres}
    growing = {(i, d) for i in centres for d in ("up", "down")}
    while growing:
        for i in centres:
            for d, cursor, step in (("up", up, -1), ("down", down, 1)):
                if (i, d) not in growing:
                    continue
                k = cursor[i]
                if not 0 <= k <= last or not take(k):
                    growing.discard((i, d))
                else:
                    cursor[i] = k + step
    keep = set(centres) | heads
    for i in sorted(chosen, reverse=True):  # no window ends on a colon line or on a heading of text not shown
        hangs = i != last and i + 1 not in chosen and i not in keep
        if hangs and (_COLON.search(sents[i]) or _is_heading(sents, i)):
            chosen.discard(i)
    lines: list[str] = []
    at = -1
    for i in sorted(chosen):
        if i != at + 1:
            lines.append(GAP)
        lines.append(sents[i])
        at = i
    if at != last:
        lines.append(GAP)
    return "\n".join(lines)


_DIGITS = re.compile(r"(\d+)")


def _order(n: Note) -> tuple[Any, ...]:
    """Newest day first; within a day by the note's id read naturally (``#9`` before ``#10``: the paragraphs of an
    uploaded chart keep their order), then by text, so the order never depends on the order the notes came in."""
    day = n.iso
    natural = tuple((0, int(p)) if p.isdigit() else (1, p) for p in _DIGITS.split(n.did) if p != "")
    return (tuple(-ord(ch) for ch in day), natural, n.text)


def _copies(days: set[str] | None) -> dict[str, Any]:
    """D-941: what a note shown for copies of its text says of them (``tb_llm.budget.COPIES``): the earliest day the
    same text was written and how many other copies there are; nothing for a note with none."""
    if not days:
        return {}
    first, many = COPIES
    return {first: min(days), many: len(days)}


def _copies_cost(days: set[str] | None) -> int:
    """The tokens :func:`_copies` adds to an excerpt (``tb_llm.budget.excerpt_tokens``)."""
    if not days:
        return 0
    base = {"date": "0000-00-00", "note_type": "", "text": ""}
    return excerpt_tokens(base | _copies(days)) - excerpt_tokens(base)


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
    # D-905 (lane G's review): a copied-forward note, the same text as a newer one, is shown once, as the newest copy
    seen: dict[str, Note] = {}
    dups: list[str] = []
    kept: list[Note] = []
    # D-941 (review of D-940): the dates of the copies a shown note stands for. A line in relative time ("last dose
    # given today") read only under the newest copy's date would move an event forward; the models see that the same
    # text was also written on these days
    also: dict[str, set[str]] = {}
    for n in newest_first:
        same = " ".join(n.text.split())
        if same and same in seen:
            dups.append(n.did)
            if n.iso != seen[same].iso:
                also.setdefault(seen[same].did, set()).add(n.iso)
            if n.did in evidence and seen[same].did not in evidence:  # its evidence is the kept copy's too
                evidence = {**evidence, seen[same].did: evidence[n.did]}
            continue
        seen[same] = n
        kept.append(n)
    newest_first = kept
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
        cost = tokens(n.text) + _copies_cost(also.get(n.did))  # D-941: the copies' two values are read too
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
        extra = _copies_cost(also.get(n.did))  # D-941 (review): a clipped note's copies are read too
        part = clip(n, evidence[n.did], max(1, cap - extra), tokens)
        part_cost = tokens(part) + extra
        if part and part_cost <= left:
            shown.append((n, part))
            left -= part_cost
    shown.sort(key=lambda x: _order(x[0]))
    out = [
        {"date": n.iso, "note_type": n.type, "text": text, "did": n.did} | _copies(also.get(n.did)) for n, text in shown
    ]
    return ExcerptSet(out, len(cut), cut, dups)
