"""Whether an inclusion's line is positively recognised as a plain assertion of its coded concept (card 10A-1d).

Cards 10A-1 to 10A-1c held an inclusion when its line carried a negation cue, and ran it otherwise. Two testers who
never saw the code showed what that costs: a drug stopped, failed, refused or allergic to, a plan or a booking,
"candidate for", another person's condition, remission, a vaccination, a heading, a definition, an instruction, a
symbol, a checkbox ticked "No", "pre-diabetes" with diabetes coded: none of them is a negation, and each ran as "the
patient has it". A list of cues always lacks the shape nobody listed, so the default turns round (D-1248):

**An inclusion that asks the presence of a concept runs only when every clause of its line that names the concept is
made of nothing but that concept's name (or a listed synonym) and words recognised as part of a plain assertion.**
What is recognised is data a clinician can read and extend, ``recognised_assertions.yaml`` next to this module: per
language (English, Japanese, Chinese), assertion frames ("diagnosis of", "patients with", と診断された, 確診為) and
qualifier classes of the concept itself (stage, grade, severity, type, laterality, site, a measure or a threshold, a
date or a duration, the confirming method), plus numbers, codes and marks. Any other word in the concept's clause
means hold: an unknown word is a reason to hold, never a reason to run. The cue rules (``negation_scope``) stay as a
second net: a recognised line that is cued is held.

A clause ends at ";", a sentence's end, "but", "however", が、, 但 and the like; a comma does not end one. Another
concept the extractor named may share the clause when a link word joins it ("surgery *for* colorectal cancer"). A
clause that names no concept but points back at one ("Diagnosis pending confirmation") must be recognised as well. A
clause that ends in a colon is a heading. A concept name with a negating prefix ("non-diabetic") is never recognised.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from tb_contracts import Atom
from tb_contracts.criterion_ir import ACTIVE_STATUSES

from criteria_compiler.ir_extract.negation_scope import (
    _mentions,
    _others,
    _patterns,
    _slug_words,
    atoms_of,
    presence_atoms,
)

DATA = Path(__file__).with_name("recognised_assertions.yaml")
CONCEPT, OTHER = "\x00", "\x01"  # what a mention of this concept, or of another named one, is read as

_CLAUSE_END = re.compile(
    r";|\.(?=\s|$)|\n|\b(?:but|however|whereas|although|though)\b|[。；]|が、|但是|但し|但|然而|ただし|不過|不过", re.I
)
_KANA = re.compile(r"[぀-ヿ]")
_CJK = re.compile(r"[぀-ヿ㐀-鿿]")
_LATIN_EDGE = re.compile(r"[a-z0-9]", re.I)


@dataclass(frozen=True)
class _Entry:
    rx: re.Pattern[str]
    cls: str


@dataclass(frozen=True)
class _Vocab:
    by_first: dict[str, tuple[_Entry, ...]]
    patterns: tuple[re.Pattern[str], ...]
    marks: frozenset[str]


def _entry_rx(word: str) -> re.Pattern[str]:
    """A listed word as a pattern: Latin words whole, a space or hyphen between them matching any run of both;
    ``{X}`` and ``{O}`` stand for a mention of this concept and of another named one."""
    w = unicodedata.normalize("NFKC", word).strip().replace("{X}", CONCEPT).replace("{O}", OTHER)
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", w) if p]
    body = r"[\s\-]*".join(parts) if CONCEPT in w or OTHER in w else r"[\s\-]+".join(parts)
    head = r"(?<![a-z])" if _LATIN_EDGE.match(w[0]) else ""  # a unit may follow a number ("1000mg")
    tail = r"(?![a-z])" if _LATIN_EDGE.match(w[-1]) else ""
    return re.compile(head + body + tail, re.I)


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    return data


@lru_cache(maxsize=1)
def _exceptions() -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(str(p)) for p in (_data().get("exceptions") or {}).values())


@lru_cache(maxsize=8)
def _ended(lang: str) -> re.Pattern[str] | None:
    p = (_data().get("ended") or {}).get(lang)
    return re.compile(str(p)) if p else None


@lru_cache(maxsize=1)
def _holds() -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(str(p).replace("{X}", CONCEPT)) for p in (_data().get("holds") or {}).values())


def _classes(lang: str) -> dict[str, dict[str, Any]]:
    d = _data()
    out = {f"common.{k}": v for k, v in (d.get("common") or {}).items()}
    out.update({k: v for k, v in (d["languages"].get(lang) or {}).items()})
    return out


@lru_cache(maxsize=256)
def _vocab(lang: str, domain: str, history: bool, needs_met: frozenset[str]) -> _Vocab:
    """The words a clause in ``lang`` may be made of, for a concept of ``domain``."""
    d = _data()
    entries: dict[str, list[_Entry]] = {}
    for cls, spec in _classes(lang).items():
        if cls == "anaphora" or (cls.startswith("history") and not history):
            continue
        doms = set(spec.get("domains") or ["any"])
        if "any" not in doms and domain not in doms:
            continue
        if spec.get("needs") and cls not in needs_met:
            continue
        for w in spec.get("words") or []:
            if not isinstance(w, str):  # YAML reads a bare on / no / yes as a boolean: quote it in the file
                raise ValueError(f"{DATA.name}: {lang}.{cls} lists {w!r}, not a word")
            w = unicodedata.normalize("NFKC", w).strip()
            if w:
                first = w.replace("{X}", CONCEPT).replace("{O}", OTHER)[0].lower()
                entries.setdefault(first, []).append(_Entry(_entry_rx(w), cls))
    pats = tuple(re.compile(p, re.I) for p in (d.get("patterns") or {}).values())
    marks = frozenset(unicodedata.normalize("NFKC", str(d.get("marks") or "")) + ".")
    return _Vocab({k: tuple(v) for k, v in entries.items()}, pats, marks)


def _needs_met(lang: str, clause: str) -> frozenset[str]:
    met = set()
    for cls, spec in _classes(lang).items():
        if any(_entry_rx(str(w)).search(clause) for w in spec.get("needs") or []):
            met.add(cls)
    return frozenset(met)


def _words(lang: str, cls: str) -> list[re.Pattern[str]]:
    return [_entry_rx(str(w)) for w in (_classes(lang).get(cls) or {}).get("words") or []]


def _made_of_listed_words(s: str, v: _Vocab) -> bool:
    """Whether ``s`` can be cut, from start to end, into listed words, numbers, codes, marks and mentions."""
    n = len(s)
    ok = [False] * (n + 1)
    ok[0] = True
    for i in range(n):
        if not ok[i]:
            continue
        c = s[i]
        if c.isspace() or c in v.marks or c in (CONCEPT, OTHER):
            ok[i + 1] = True
        for p in v.patterns:
            m = p.match(s, i)
            if m and m.end() > i:
                ok[m.end()] = True
        for e in v.by_first.get(c.lower(), ()):
            m = e.rx.match(s, i)
            if m and m.end() > i:
                ok[m.end()] = True
    return ok[n]


def _merge(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if out and s < out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _read_as(u: str, a: int, z: int, own: list[tuple[int, int]], other: list[tuple[int, int]]) -> str:
    """The clause ``u[a:z]`` with each mention of this concept, and of another named one, as one character."""
    marks = sorted([(s, e, CONCEPT) for s, e in own if a <= s < z] + [(s, e, OTHER) for s, e in other if a <= s < z])
    out, i = [], a
    for s, e, ch in marks:
        if s < i:
            continue
        out += [u[i:s], ch]
        i = min(e, z)
    out.append(u[i:z])
    return "".join(out)


def _positional(lang: str) -> list[re.Pattern[str]]:
    return [_entry_rx(str(w)) for spec in _classes(lang).values() for w in spec.get("words") or []
            if "{O}" in str(w)]  # fmt: skip


def _linked(s: str, lang: str) -> bool:
    """Each other named concept in the clause is joined to the mention before it or after it by a link word or a
    list mark between them ("surgery *for* colorectal cancer"; not "metformin allergy")."""
    links = _words(lang, "links")
    marks = (",", "、", "，", "/", "・")
    covered = {i for p in _positional(lang) for m in p.finditer(s) for i in range(m.start(), m.end())}
    for k, ch in enumerate(s):
        if ch != OTHER or k in covered:
            continue
        sides = re.split(f"[{CONCEPT}{OTHER}]", s[:k])[-1], re.split(f"[{CONCEPT}{OTHER}]", s[k + 1 :])[0]
        if not any(any(m in side for m in marks) or any(p.search(side) for p in links) for side in sides):
            return False
    return True


def _langs(u: str) -> tuple[str, ...]:
    """The vocabularies a line is read with: Japanese when it has kana, English when it has no CJK at all, and both
    Japanese and Chinese for a line of kanji alone ("転移性乳癌")."""
    return ("ja",) if _KANA.search(u) else ("ja", "zh") if _CJK.search(u) else ("en",)


def _clause_recognised(s: str, lang: str, domain: str, history: bool) -> bool:
    v = _vocab(lang, domain, history, _needs_met(lang, s))
    return _made_of_listed_words(s, v) and _linked(s, lang)


def recognised(
    text: str,
    terms: Iterable[str],
    other_terms: Iterable[str] = (),
    domain: str = "condition",
    history: bool = True,
    past: bool = False,
) -> bool:
    """Whether ``text`` reads as a plain assertion that the patient has the concept named by ``terms`` (its name and
    synonyms). ``other_terms`` are the line's other named concepts; ``history``: whether a past occurrence counts (it
    does not when the criterion's logic asks the concept active only); ``past``: whether the logic itself asks a past
    occurrence (a window that ends before the index day), so that a clause saying it ended may run."""
    terms = list(terms)
    u = unicodedata.normalize("NFKC", text)
    found = _mentions(u, _patterns(terms))
    if not found or any(neg for _, _, neg in found):
        return False  # never named (it may be named otherwise), or named with a negating prefix
    own = _merge((s, e) for s, e, _ in found)
    other = [(s, e) for s, e in _merge((s, e) for s, e, _ in _mentions(u, _others(terms, other_terms)))
             if not any(s < e2 and s2 < e for s2, e2 in own)]  # fmt: skip
    langs = _langs(u)
    cut_out = _merge(m.span() for p in _exceptions() for m in p.finditer(u) if m.end() > m.start())
    if any(a <= s < z for s, _ in own for a, z in cut_out):
        return False  # the coded concept is what an exception names ("any immunosuppressant other than prednisolone")
    if cut_out:  # each exception and what it names is read as a clause boundary
        u = "".join("\n" if any(a <= i < z for a, z in cut_out) else ch for i, ch in enumerate(u))
    cuts = [0, *[x for m in _CLAUSE_END.finditer(u) for x in (m.start(), m.end())], len(u)]
    anaphora = [p for lang in langs for p in _words(lang, "anaphora")]
    for a, z in zip(cuts[::2], cuts[1::2], strict=False):
        names_it = any(a <= s < z for s, _ in own)
        names_other = any(a <= s < z for s, _ in other)
        clause = u[a:z]
        if (
            not past
            and (names_it or not names_other)
            and any((p := _ended(lang)) is not None and p.search(clause) for lang in {*langs, "en"})
        ):
            return False  # it ended or lies in the past, which an atom with no past window cannot say
        if not names_it:
            points_back = not names_other and any(p.search(clause) for p in anaphora)
            if not points_back:
                continue
        s = _read_as(u, a, z, own, other)
        if s.strip(" \t.").endswith(":") or any(h.search(s) for h in _holds()):
            return False  # a heading ("Diabetes:"), or listed words that together say otherwise
        if not any(_clause_recognised(s, lang, domain, history) for lang in langs):
            return False
    return True


def _history_counts(atom: Atom) -> bool:
    status = atom.clinical_status or []
    return not (status and set(status) <= set(ACTIVE_STATUSES))


def _asks_the_past(atom: Atom) -> bool:
    """The atom's own logic asks a past occurrence: a window that ends before the index day."""
    w = atom.window
    return w is not None and w.to_days is not None and w.to_days < 0


def unrecognised_presence(
    text: str, logic: object, terms_for: Callable[[str], list[str]], other_terms: Iterable[str] = ()
) -> bool:
    """Whether an inclusion's ``logic`` asks the presence of a concept its ``text`` is not recognised as asserting
    (card 10A-1d). Arguments as :func:`negation_scope.negated_presence`."""
    every = [x for a in atoms_of(logic) for x in (*terms_for(a.valueset or ""), *_slug_words(a.valueset))]
    every += list(other_terms)
    for atom in presence_atoms(logic):
        terms = [*terms_for(atom.valueset or ""), *_slug_words(atom.valueset)]
        if not recognised(text, terms, every, atom.domain, _history_counts(atom), _asks_the_past(atom)):
            return True
    return False
