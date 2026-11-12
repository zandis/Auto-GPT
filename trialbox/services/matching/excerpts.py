"""One excerpt builder (T-710, D-479; review 2026-11-12 ``decision.md`` AD-4, root cause R3).

The text a model reads was chosen by each caller: the cascade showed the notes with a lexicon hit (else the notes of
the top five sentences) inside a fixed 2,500 tokens; the v1 path showed the five chunks a retrieval returned and
counted as "left out" only those of the five that did not fit; CASE showed the whole upload with no budget. So the
same note question was answered from different text on each path, and two models agreeing "not met" on five chunks
excluded a patient whose decisive note they never saw (review H4).

:func:`build` is the one place:

* ``window``: **every** note of the patient inside the criterion's window (the caller's query, not a ranking);
* ``evidence``: what the caller's ranking points at, per note: the cascade's lexicon-hit or top sentences, the v1
  retrieval's chunks; empty for CASE. It decides what is read **first**, never what counts as read;
* ``budget``: tokens of notes one judge prompt may hold: the models' context (T-603, ``NoteJudge.excerpt_budget``),
  or :data:`DEFAULT_TOKENS` for a client that cannot tell its context (OD-10: no other fixed budget).

It shows whole notes, the evidence notes first and then the rest of the window, newest first, while they fit. A note
that does not fit whole is clipped to whole sentences around its evidence (an evidence note, at most half the
budget, so one long note never hides the others: D-142, review A-06) or skipped.

**``left_out`` counts every window note not shown in full**: skipped, or clipped. Both models read the one set, so
with a note left out their agreement on "not met" says nothing about what they did not read: the callers make such
an answer unknown, and flag a "met" (D-276, T-603; the status function sends both to review, D-478). The shown list
is newest first, whatever the order the notes were taken in.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from tb_llm.budget import excerpt_tokens

#: the budget when no client can tell its context: what fits beside the judge prompt and its answer on the smallest
#: registered build (8k, T-603). A known context replaces it; it is the one fixed number of this module (OD-10)
DEFAULT_TOKENS = 2500
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


def clip(note: Note, evidence: Iterable[str], cap: int, tokens: Callable[[str], int] = note_tokens) -> str:
    """At most ``cap`` tokens of a long note: its evidence sentences first (in note order), then the note's start;
    always whole sentences of the note, so a quote the model takes from it is found in the note. ``evidence``:
    sentences of the note, or longer fragments (a retrieved chunk) whose sentences count."""
    sents = list(note.sents) if note.sents is not None else sentences(note.text)
    wanted = [frag for frag in evidence if frag]
    overhead = tokens("")  # what an excerpt costs before its text (its JSON keys): once per note, not per sentence
    room = cap - overhead
    chosen: list[int] = []
    used = 0
    first = [i for i, s in enumerate(sents) if any(s == w or s in w for w in wanted)]
    for i in first + list(range(len(sents))):
        if i in chosen:
            continue
        cost = tokens(sents[i]) - overhead + 1  # + 1: the line break that joins it, and the rounding of a sum
        if used + cost > room:
            continue
        chosen.append(i)
        used += cost
    if not chosen:  # one sentence longer than the cap: the note's start
        out: list[str] = []
        used = 0
        for ch in note.text:
            used += 4 if "　" <= ch <= "鿿" else 1
            if used > max(0, room) * 4:
                break
            out.append(ch)
        return "".join(out)
    return "\n".join(sents[i] for i in sorted(chosen))


def build(
    window: Sequence[Note],
    evidence: Mapping[str, Collection[str]],
    budget: int,
    tokens: Callable[[str], int] = note_tokens,
) -> ExcerptSet:
    """The excerpts of one judge prompt and how many window notes they leave out (see the module's text)."""
    newest_first = sorted(window, key=lambda n: (n.iso, n.did), reverse=True)
    order = [n for n in newest_first if n.did in evidence] + [n for n in newest_first if n.did not in evidence]
    cap = max(1, budget // 2)
    left = budget
    shown: list[tuple[Note, str]] = []
    cut: list[str] = []
    for n in order:
        cost = tokens(n.text)
        if cost <= left:
            shown.append((n, n.text))
            left -= cost
            continue
        cut.append(n.did)  # not shown in full: left out, whatever is shown of it below
        if n.did not in evidence or left <= 0:
            continue
        part = clip(n, evidence[n.did], min(cap, left), tokens)
        part_cost = tokens(part)
        if part and part_cost <= left:
            shown.append((n, part))
            left -= part_cost
    shown.sort(key=lambda x: (x[0].iso, x[0].did), reverse=True)
    out = [{"date": n.iso, "note_type": n.type, "text": text, "did": n.did} for n, text in shown]
    return ExcerptSet(out, len(cut), cut)
