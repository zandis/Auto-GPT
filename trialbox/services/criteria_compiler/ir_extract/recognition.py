"""Whether an inclusion's line is positively recognised as a plain statement that the patient has its coded concept
(card 10A-1d, D-1248).

Cards 10A-1 to 10A-1c held an inclusion when its line carried a negation cue, and ran it otherwise. Testers who never
saw the code showed what that costs: a drug stopped, failed, refused or allergic to, a plan or a booking, "candidate
for", another person's condition, remission, a vaccination, a heading, a definition, a symbol, a checkbox ticked
"No": none of them is a negation, and each ran as "the patient has it". A list of cues always lacks the shape nobody
listed, so the owner turned the default round (2026-11-19): **what is not clearly present does not count as met.**

**An inclusion that asks the presence of a concept runs only when every clause of its line is read**, by these rules
(the words are data a clinician can read and extend, ``recognised_assertions.yaml`` next to this module):

* **What governs the concept's name is a closed list.** English: the phrase whose preposition governs the name
  ("diagnosis of", "history of", "treated with"; never "vaccination for", "risk of") and the word right after the
  name. Japanese and Chinese: what follows the name, until a listed frame or a mark closes it, and what owns it
  through の, が, は, 之 or 的.
* **An unlisted word is read only as a content word, where a content word cannot change whether the concept is
  present**: never a closed-class word, never a verb form, never a word of a class that says the concept is not a
  present fact of this patient (doubt, a plan, a risk, another person, an ending, a refusal, an alternative), and a
  bounded number of them. A first version listed every word a line may use; it held 88 of 100 ordinary lines.
* **Some shapes hold whatever their words** (``holds`` in the data file and the checks below): the concept as an arm
  of an alternative, a form's mark, a label and a bare name, a bare measured value, a definition, a name that is
  only part of the coded name, a code that is not the concept's own, an ending.
* Every clause counts: what follows a full stop, "but" or 但 may say the line is not a fact. A clause that names no
  coded concept must be listed words throughout.

Every hold has a reason (:func:`not_recognised`), counted by ``tools.negated_inclusion_score``. The cue rules
(``negation_scope``) stay as a second net: a recognised line that is cued is held.

What this does not do is in D-1248's limits: a value that contradicts the name it stands beside ("Obesity with BMI
below 25") runs, and the places where an unlisted word is read are guarded by lists of classes, not by a proof.
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
from tb_contracts import Atom, BoolExpr
from tb_contracts.criterion_ir import ACTIVE_STATUSES

from criteria_compiler.ir_extract.negation_scope import (
    _mentions,
    _others,
    _patterns,
    _slug_words,
    atoms_of,
    presence_atoms,
    under_or,
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
    joiners: frozenset[str]


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


@lru_cache(maxsize=32)
def _ended(lang: str, domain: str = "condition") -> tuple[tuple[re.Pattern[str], re.Pattern[str] | None], ...]:
    """The words that say the concept ended or lies in the past, each with what makes it not an ending ("ago" after
    a diagnosis date). An entry may name domains it does not apply to: a procedure done "2 years ago" is done."""
    out = []
    for e in (_data().get("ended") or {}).get(lang) or []:
        e = e if isinstance(e, dict) else {"pattern": e}
        if domain in (e.get("not_domains") or []):
            continue
        out.append((re.compile(str(e["pattern"])), re.compile(str(e["unless"])) if e.get("unless") else None))
    return tuple(out)


@lru_cache(maxsize=8)
def _non_fact(lang: str) -> re.Pattern[str] | None:
    p = (_data().get("non_fact") or {}).get(lang)
    return re.compile(str(p)) if p else None


@lru_cache(maxsize=16)
def _hold_names(domain: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Patterns of listed words that together say something else, each with its name (the reason a line is held
    for); an entry may name the domains it applies to."""
    out = []
    for name, h in (_data().get("holds") or {}).items():
        h = h if isinstance(h, dict) else {"pattern": h}
        doms = set(h.get("domains") or ["any"])
        if "any" in doms or domain in doms:
            out.append((str(name), re.compile(str(h["pattern"]).replace("{X}", CONCEPT).replace("{O}", OTHER))))
    return tuple(out)


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
    joiners = frozenset(unicodedata.normalize("NFKC", str(d.get("joiners") or "")))
    return _Vocab({k: tuple(v) for k, v in entries.items()}, pats, marks, joiners)


def _needs_met(lang: str, clause: str) -> frozenset[str]:
    met = set()
    for cls, spec in _classes(lang).items():
        if any(_entry_rx(str(w)).search(clause) for w in spec.get("needs") or []):
            met.add(cls)
    return frozenset(met)


def _words(lang: str, cls: str) -> list[re.Pattern[str]]:
    return [_entry_rx(str(w)) for w in (_classes(lang).get(cls) or {}).get("words") or []]


_INNER = re.compile(r"[0-9A-Za-z\x00\x01぀-ヿ㐀-鿿)\]%]")
# An unlisted word may be read only as what it visibly is: a content word (a noun or an adjective) in a place where a
# content word cannot change whether the concept is present. English: a word of letters that is not a closed-class
# word (an article, a pronoun, an auxiliary, a modal, a conjunction, a preposition: those are read only where
# listed), not shaped like a verb form ("-ed", "-ing": verbs are listed), and not in a class that says the concept is
# not a present fact (``unlisted_never`` in the data file). Japanese and Chinese: a run of kanji or katakana (never
# hiragana, which carries the grammar and is read only where listed) without a character of those classes.
_EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'’]*(?:-[A-Za-z0-9]+)*")
_CJK_RUN = re.compile(r"[㐀-鿿ァ-ヺー々]{1,10}")
_VERB_SHAPED = re.compile(r"(?:ed|ing|n['’]t)$", re.I)
_PLURAL_OR_VERB = re.compile(r"(?<!ou)(?<!s)(?<!u)(?<!i)s$|['’]s?$", re.I)
_HIRAGANA_RUN = re.compile(r"[\u3041-\u3096]+")
_RANGE_ENDS = frozenset(
    [
        "mild",
        "mildly",
        "moderate",
        "moderately",
        "severe",
        "severely",
        "low",
        "medium",
        "high",
        "intermediate",
        "early",
        "late",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "i",
        "ii",
        "iii",
        "iv",
        "v",
    ]
)
_ZH_MODIFIER_END = re.compile(r"(?:性|型|期|度|級|级|類|类|的|之)$")
_CLOSING = frozenset({"frames", "history", "history_after_procedure", "tail"})  # not "seen": "<X>検査" is a test
_BOUNDARY_CJK = frozenset("、。，,;；:（(）) \t\n")
MAX_UNLISTED = {"en": 12, "ja": 8, "zh": 8}
MAX_LINE = 2000  # characters: a longer line is held unread


@lru_cache(maxsize=1)
def _never() -> dict[str, re.Pattern[str]]:
    d = _data().get("unlisted_never") or {}
    en = "|".join(str(x) for x in (d.get("en") or {}).values())
    return {
        "en": re.compile(rf"^(?:{en})$", re.I),
        "ja": re.compile("|".join(str(x) for x in (d.get("ja") or {}).values())),
        "ja_grammar": re.compile(str(d.get("ja_grammar") or "(?!)")),
        "zh": re.compile("|".join(str(x) for x in (d.get("zh") or {}).values())),
    }


@lru_cache(maxsize=1)
def _closed_class() -> frozenset[str]:
    return frozenset(str(w).lower() for w in (_data().get("closed_class") or {}).get("en") or [])


_ALTERNATIVE = re.compile(
    r"\b(?:or|and/or|nor|either)\b(?!\s+(?:more|higher|greater|longer|above|less|lower|fewer|below|older|younger|over|"
    r"under|equal|later|earlier|equivalent\s+dose)\b)|又は|または|もしくは|若しくは|あるいは|或いは|或是|或者|抑或|或|及/或",
    re.I,
)
_SEGMENT_END = re.compile(r"[,，、;；()（）]")
_EN_AFTER_PREP = frozenset(["in", "of", "among", "from", "for", "on", "at", "by", "to", "within", "into"])
_EN_DET = frozenset(["the", "a", "an", "his", "her", "their", "its", "this", "that", "these", "those", "any", "some"])


def _script(ch: str) -> str:
    """The script a character is written in: a word of an unspaced line ends where its script changes."""
    if "\u3041" <= ch <= "\u3096":
        return "hiragana"
    if "\u3400" <= ch <= "\u9fff" or "\u30a1" <= ch <= "\u30fc" or ch == "\u3005":
        return "content"
    return "latin" if ch.isascii() and ch.isalnum() else ""


_LIST_ONLY = re.compile(r"[、,，・/\s\u3400-\u9fff\u30a1-\u30fa\u30fcA-Za-z0-9]{0,30}")


def _in_list_with_name(s: str, a: int, z: int) -> bool:
    """Japanese and Chinese: the alternative at ``s[a:z]`` stands in one list with the concept's name: nothing but
    list marks and names between them ("<X>、高血圧又は喘息"; not "再発又は難治性となった<X>" or
    "…或24小時心電圖記錄之<X>",
    where a verb, の, 之 or 的 makes the alternative part of what describes the name)."""

    def listed(part: str) -> bool:
        part = re.sub("及び|および|並びに|ならびに|かつ", "、", part)
        return _LIST_ONLY.fullmatch(part.replace("之", "\uffff").replace("的", "\uffff")) is not None

    if re.search(r"\x00\s*(?:[(（][^()（）]{0,12}[)）])?\s*$", s[:a]) and s[z:].lstrip().startswith(CONCEPT):
        return False  # both arms are the concept itself ("<X>(MCI)または<X>"): the logic carries them
    left = s.rfind(CONCEPT, max(0, a - 31), a)
    if left >= 0 and listed(s[left + 1 : a]):
        return True
    right = s.find(CONCEPT, z, z + 31)
    return right >= 0 and listed(s[z:right])


def _strict(s: str, lang: str, synonym_at: frozenset[int] = frozenset()) -> list[bool]:
    """Where an unlisted word is never read: what is attached to the concept and governs it, and the arms of an
    alternative.

    * English: the word right after the name, in brackets too ("<diabetes> screening", "<colorectal cancer> (FH)"),
      and after a preposition there the word it takes ("<diabetes> in stepfather"); a word joined to the name by a
      hyphen ("pre-<diabetes>"); the word before a preposition that governs the name ("index case with <X>").
    * Japanese and Chinese: what owns the name through の, が, は, 之 or 的, back to the mark before it ("配偶者の<X>",
      "いとこの<X>", "捐贈者之<X>"). What follows the name is read by :func:`_unread` itself: nothing unlisted until
      a listed frame or a mark closes it ("<X>に対するワクチン接種", "<X>之疫苗接種" never close).
    * Any language: the arms of an alternative ("<X>, hypertension or asthma": the logic would have to carry each
      arm; "stage III or IV" is listed words), and everything before a name that is a synonym, not the coded name
      itself, up
      to the mark before it ("small cell <lung cancer>" may be another kind than the name coded)."""
    n = len(s)
    out = [False] * (n + 1)

    def mark(a: int, z: int) -> None:
        out[max(0, a) : min(n, z)] = [True] * (min(n, z) - max(0, a))

    for alt in _ALTERNATIVE.finditer(s):  # the arms: two words on each side, or six characters in Japanese / Chinese
        if lang == "en":
            left = list(_EN_WORD.finditer(s, max(0, alt.start() - 60), alt.start()))[-2:]
            right = list(_EN_WORD.finditer(s, alt.end(), alt.end() + 60))[:2]
            mark(left[0].start() if left else alt.start(), right[-1].end() if right else alt.end())
        elif _in_list_with_name(s, alt.start(), alt.end()):
            mark(alt.start() - 6, alt.end() + 6)
    for m in re.finditer(CONCEPT, s):
        if m.start() in synonym_at:
            k = m.start()
            while k and s[k - 1] not in ",，、;；:()（）":
                k -= 1
            mark(k, m.start())
        if lang == "en":
            t = re.match(r"[\s\-(]*[A-Za-z][A-Za-z'’\-]*", s[m.end() :])
            if t:
                mark(m.end(), m.end() + t.end())
                word = t.group(0).strip(" -(").lower()
                if word in _EN_AFTER_PREP:
                    t2 = re.match(
                        r"(?:\s+(?:the|a|an|his|her|their|its))?\s+[A-Za-z][A-Za-z'’\-]*", s[m.end() + t.end() :]
                    )
                    if t2:
                        mark(m.end() + t.end(), m.end() + t.end() + t2.end())
            h = re.search(r"[A-Za-z][A-Za-z'’]*-\s*$", s[: m.start()])
            if h:
                mark(h.start(), m.start())
            seg = max(s.rfind(c, 0, m.start()) for c in ",;:()\x00\x01") + 1
            words = list(_EN_WORD.finditer(s, seg, m.start()))
            for k in range(len(words) - 1, max(len(words) - 7, -1), -1):
                if words[k].group(0).lower() in _EN_GOVERNING:
                    if k:
                        mark(words[k - 1].start(), words[k - 1].end())
                    break
        else:
            k = m.start()
            if k and s[k - 1] in "の之的がはも":
                k -= 1
                kind = _script(s[k - 1]) if k else ""
                while k and _script(s[k - 1]) == kind and kind:
                    k -= 1
                    out[k] = True
    return out


def _unlisted_end(s: str, i: int, lang: str, strict: list[bool]) -> int | None:
    """The end of an unlisted word that may be read at ``s[i]``, or None."""
    if strict[i]:
        return None
    if s[i].isascii():
        if i and s[i - 1].isalnum() and s[i - 1].isascii():
            return None  # never from the middle of a word
        m = _EN_TOKEN.match(s, i)
        if m is None or (m.end() < len(s) and s[m.end()].isascii() and s[m.end()].isalnum()):
            return None
        w = m.group(0)
        if re.fullmatch(r"[A-Z]\d{2}", w) and re.match(r"\.\d", s[m.end() :]):
            return None  # shaped like a code ("Z80.0"): a code is read only when it is one of the concept's own
        if len(w) < 2 or w.lower() in _closed_class() or _VERB_SHAPED.search(w) or _never()["en"].match(w):
            return None
        if any(_never()["en"].match(part) for part in re.split(r"[-'’]", w) if part):
            return None
        rest = s[m.end() :].lstrip(" ")
        if rest.startswith(CONCEPT) and _PLURAL_OR_VERB.search(w):
            return None  # right before the name only an adjective is read ("Needs <X>", "Mother's <X>" are not)
        return m.end()
    if lang == "en":
        return None
    if lang == "ja" and (h := _HIRAGANA_RUN.match(s, i)) is not None:
        # Japanese grammar is written in hiragana. A run of it is read unless it holds an ending that denies,
        # doubts, wishes, conditions or allows (ない, ず, たい, らしい, れば, できる …: ``ja_grammar`` in the data
        # file); what is attached to the name is never read this way (the strict stretch after it)
        if i and "\u3041" <= s[i - 1] <= "\u3096":
            return None  # never from the middle of a run
        if any(strict[i : h.end()]) or _never()["ja_grammar"].search(h.group(0)):
            return None
        return -h.end()  # negative: grammar, not counted as an unlisted content word
    m = _CJK_RUN.match(s, i)
    if m is None:
        return None
    end = m.end()
    while end > i and strict[end - 1]:  # never into what is strict
        end -= 1
    return end if end > i else None


def _cjk_piece_ok(s: str, i: int, end: int, lang: str) -> bool:
    """Whether the run of kanji or katakana ``s[i:end]`` may be read as an unlisted content word."""
    piece = s[i:end]
    if _never()["ja"].search(piece) or _never()["zh"].search(piece):
        return False  # both lists, whichever language the line was read as: a line of kanji alone may be either
    if lang == "zh":  # before the name, in its own stretch, only what a 之 / 的 or a listed frame joins to it
        seg_end = next((k for k in range(end, len(s)) if s[k] in _BOUNDARY_CJK), len(s))
        x = s.find(CONCEPT, end, seg_end)
        if x > end and not re.search("[之的]", s[end:x]) and not _zh_governed(s[end:x]):
            return False
    # a run joined to the name is read only when it ends as a modifier does (in Chinese a verb stands before its
    # object as a modifier does; in Japanese 偽痛風 is not 痛風)
    return not (s[end : end + 1] == CONCEPT and not _ZH_MODIFIER_END.search(piece))


@lru_cache(maxsize=1)
def _zh_governors() -> re.Pattern[str]:
    words = sorted((str(w) for w in (_data().get("governors") or {}).get("zh") or []), key=len, reverse=True)
    return re.compile("(?:" + "|".join(re.escape(unicodedata.normalize("NFKC", w)) for w in words) + r")\s*$")


def _zh_governed(between: str) -> bool:
    """Chinese: the name is governed by a listed frame right before it ("診斷為<X>", "接受過<X>")."""
    return _zh_governors().search(between) is not None


def _unread(
    s: str, v: _Vocab, lang: str = "en", unlisted: bool = False, synonym_at: frozenset[int] = frozenset()
) -> str:
    """What is left of ``s`` when it is cut, from its start, into listed words, shapes, marks and mentions (and, with
    ``unlisted``, a bounded number of unlisted content words): empty when all of it is read, else the text from the
    furthest point the cutting reached. A joining mark ("-", "/", ":", "~") counts only between two things it joins
    ("HBsAg: -" and a trailing "-" are not read)."""
    n = len(s)
    big = 10**6
    # cost[k][i]: the fewest unlisted words that read s[:i].
    # k = 0: what was last read is still attached to the concept's name (Japanese and Chinese: nothing unlisted is
    #        read until a listed frame or a mark closes it: "<X>に対するワクチン接種" never closes, "<X>を有する小児"
    #        closes at を有する);
    # k = 2: the last thing read was an unlisted run of kanji or katakana, cut short of its end because a listed
    #        word starts there: only a listed word may follow (two unlisted pieces would read 考慮 as 考 + 慮);
    # k = 1: otherwise.
    cost = [[big] * (n + 1) for _ in range(3)]
    cost[1][0] = 0
    strict = _strict(s, lang, synonym_at) if unlisted else []
    limit = MAX_UNLISTED[lang] if unlisted else 0
    cjk = lang != "en"

    def reach(j: int, c: int, k: int) -> None:
        cost[k][j] = min(cost[k][j], c)

    def listed_at(i: int) -> bool:
        if i >= n:
            return True
        return any(e.rx.match(s, i) for e in v.by_first.get(s[i].lower(), ())) or any(p.match(s, i) for p in v.patterns)

    for i in range(n):
        for k in (0, 1, 2):
            here = cost[k][i]
            if here >= big:
                continue
            c = s[i]
            free = 1 if k == 2 else k
            if c == CONCEPT:
                if k != 2:  # an unlisted piece never runs straight into the name
                    reach(i + 1, here, 0 if cjk else k)
            elif c.isspace() or c in v.marks or c == OTHER:
                reach(i + 1, here, 1 if c in _BOUNDARY_CJK else free)
            elif c in v.joiners and i > 0 and _INNER.match(s[i - 1]):
                rest = s[i + 1 : i + 6]
                if (
                    _INNER.match(rest[:1])
                    or (c in "-\u2013" and re.match(r"\s+(?:to|or|and)\b", rest))
                    or (c == ":" and re.match(r"\s*[0-9A-Za-z\x00\x01\u3040-\u30ff\u3400-\u9fff]", s[i + 1 :]))
                ):
                    reach(i + 1, here, free)
            for p in v.patterns:
                m = p.match(s, i)
                if m and m.end() > i:
                    reach(m.end(), here, free)
            for e in v.by_first.get(c.lower(), ()):
                m = e.rx.match(s, i)
                if m and m.end() > i:
                    if cjk and CONCEPT in m.group(0):  # a listed word that holds the name ("<X>診斷")
                        reach(m.end(), here, 0)
                        continue
                    closes = e.cls in _CLOSING and m.end() - i >= 2
                    reach(m.end(), here, 1 if closes else free)
            if not (unlisted and k == 1 and here < limit):
                continue
            end = _unlisted_end(s, i, lang, strict)
            if end is None:
                continue
            if end < 0 or s[i].isascii():  # hiragana grammar (not counted), or a Latin word
                reach(abs(end), here + (end > 0), 1)
                continue
            if i and _script(s[i - 1]) == "content" and cost[2][i] <= here:
                continue
            for j in range(end, i, -1):  # the whole run, or a piece of it that ends where a listed word starts
                whole = j == end
                if (whole or listed_at(j)) and _cjk_piece_ok(s, i, j, lang):
                    reach(j, here + 1, 1 if whole else 2)
    best = [min(cost[0][i], cost[1][i], cost[2][i]) for i in range(n + 1)]
    if best[n] < big:
        return ""
    far = max(i for i in range(n + 1) if best[i] < big)
    return s[far : far + 24].strip() or s[far:].strip() or "?"


def _made_of_listed_words(s: str, v: _Vocab) -> bool:
    return not _unread(s, v)


_EN_GOVERNING = frozenset(
    [
        "of",
        "for",
        "to",
        "on",
        "against",
        "from",
        "about",
        "regarding",
        "toward",
        "towards",
        "as",
        "at",
        "by",
        "after",
        "before",
        "in",
        "into",
        "over",
        "under",
        "around",
        "among",
        "between",
        "through",
        "during",
        "upon",
        "via",
        "per",
        "than",
        "like",
        "versus",
        "vs",
        "with",
        "without",
        "following",
        "since",
    ]
)
_EN_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-]*")


@lru_cache(maxsize=1)
def _governors() -> tuple[frozenset[str], frozenset[str]]:
    """The listed governing phrases, and those that count only at the start of a clause (written ``^on``)."""
    words = [" ".join(str(w).lower().split()) for w in (_data().get("governors") or {}).get("en") or []]
    return frozenset(w for w in words if not w.startswith("^")), frozenset(w[1:] for w in words if w.startswith("^"))


def _ungoverned(s: str) -> str | None:
    """English: a preposition that governs the concept ("vaccination *for* <X>", "risk *of* <X>") makes the word
    before it what the line is about. The nearest preposition in the few words before the name, with the words
    before it, must end in a listed phrase ("diagnosis of", "history of", "treated with", "patients on"); "with"
    needs none ("women with <X>"). None when every mention is governed by a listed phrase or by nothing."""
    anywhere, at_start = _governors()
    for m in re.finditer(CONCEPT, s):
        before = re.split(r"[,;:()\x00\x01]", s[: m.start()])[-1]
        words = [w.lower() for w in _EN_WORD.findall(before)]
        for k in range(len(words) - 1, max(len(words) - 7, -1), -1):
            if words[k] not in _EN_GOVERNING:
                continue
            if words[k] == "to" and 0 < k < len(words) - 1 and {words[k - 1], words[k + 1]} <= _RANGE_ENDS:
                continue  # "moderate to severe <X>": a range, not what governs
            if words[k] in ("than", "between", "over", "under") and k < len(words) - 1:
                continue  # "more than two <X>": a bound
            if words[k] == "at" and words[k + 1 : k + 2] in (["least"], ["most"]):
                continue  # "moderate to severe <X>", "more than two <X>": a range or a bound, not what governs
            tail = " ".join(words[: k + 1])
            if tail in at_start or any(tail == x or tail.endswith(" " + x) for x in anywhere):
                break
            return "governed:" + " ".join(words[max(0, k - 1) : k + 1])
    return None


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


def _linked(s: str, lang: str, subject: bool) -> bool:
    """Each other named concept in the clause is joined to the mention before it or after it by a link word or a
    list mark between them ("surgery *for* colorectal cancer"; not "metformin allergy"). In a clause that does not
    name this concept, another concept may stand alone (``subject``). Never by an alternative: "or", 又は, 或 make
    the other concept an arm the logic would have to carry as well (it is then this concept's sibling, read as its
    own name), so the clause is held."""
    if OTHER not in s:
        return True
    for p in _words(lang, "alternatives"):
        for m in p.finditer(s):  # an "or" whose nearest mentions are this concept on one side and another on the other
            before = [c for c in s[: m.start()] if c in (CONCEPT, OTHER)][-1:]
            after = [c for c in s[m.end() :] if c in (CONCEPT, OTHER)][:1]
            if {*before, *after} == {CONCEPT, OTHER}:
                return False
    if subject:
        return True
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


# characters written only in Japanese (shinjitai): a line of kanji alone with one of them is Japanese
_JA_MARK = re.compile(r"[転発歴臓剤検経継続薬図様対応実単価気読円売済拠悪覧駆両圧弁鉄栄労帰処拡収歯脳嚢広黒戦]")


def _lang(u: str) -> str:
    """The one vocabulary a line is read with (decided once per line): Japanese when it has kana; for kanji alone,
    Japanese when it has a character written only in Japanese ("転移性乳癌"), else Chinese; English when it has no
    CJK. A Japanese criterion line nearly always has kana; a Chinese one never does."""
    if _KANA.search(u):
        return "ja"
    if not _CJK.search(u):
        return "en"
    return "ja" if _JA_MARK.search(u) else "zh"


def _clause_unread(
    s: str, lang: str, domain: str, history: bool, subject: bool, names: bool, synonym_at: frozenset[int] = frozenset()
) -> str | None:
    """Why the clause ``s`` is not recognised (the reason's class and what was not read), or None when it is.
    ``names``: the clause names this concept or another the logic codes; only such a clause may hold unlisted
    content words (a clause that names nothing must be listed words throughout: "Pending central review.")."""
    v = _vocab(lang, domain, history, _needs_met(lang, s))
    left = _unread(s, v, lang, names, synonym_at)
    if left:
        return "unread:" + left.replace(CONCEPT, "<X>").replace(OTHER, "<O>")
    if lang == "en" and (why := _ungoverned(s)) is not None:
        return why
    return None if _linked(s, lang, subject) else "unlinked_concept"


_ABBR_AFTER = re.compile(r"\s*[（(]\s*([A-Z][A-Za-z0-9\-]{1,9})\s*[）)]")


def _defines(name: str, abbr: str) -> bool:
    """Whether ``abbr`` is an abbreviation of ``name``: its letters and digits in order, the first one first."""
    a, n = re.sub(r"[^a-z0-9]", "", abbr.lower()), name.lower()
    if not a or not n or a[0] != n[0]:
        return False
    k = 0
    for ch in n:
        if k < len(a) and ch == a[k]:
            k += 1
    return k == len(a)


def _code_patterns(codes: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(rf"(?<![A-Za-z0-9.]){re.escape(c.strip())}(?![A-Za-z0-9])", re.I) for c in codes if c.strip()]


_ZERO_WIDTH = re.compile("[\u200b-\u200f\u2060-\u2064\ufeff\u00ad]")
# a measured value written bare: a number and a measurement unit with no bound before or after it ("BMI 22 kg/m2",
# "空腹時血糖値 90 mg/dL"). A plain criterion bounds its measure; a bare value is a record's entry, which may say the
# opposite of the name before it
_BARE_VALUE = re.compile(
    r"(?<![\d.,/])\d+(?:[.,]\d+)?\s*(?:%|kg/m2|mmol/l|mmol/mol|mg/dl|g/dl|g/l|ng/ml|pg/ml|µg/l|μg/l|iu/ml|iu/l|u/l|"
    r"mmhg|ml/min(?:/1\.73\s*m2)?|copies/ml|cells/(?:µl|μl|mm3)|mg/g|g/g|g/日|g/day|µmol/l|μmol/l|meq/l|/µl|/μl|bpm|/min)"
    r"(?![a-z0-9/])",
    re.I,
)
_BARE_TRAILING = re.compile(
    r"\b(?:rate|pressure|count|level|ratio)\s+\d+(?:[.,]\d+)?\s*[.)]?\s*$", re.I
)  # "heart rate 60"
_BOUND_BEFORE = re.compile(
    r"(?:[<>≤≥=~〜\-–]|\b(?:least|than|above|below|over|under|to|and|between|exceeding|exceeds?|of|from|or)|"
    r"至少|超過|超过|低於|低于|高於|高于|大於|大于|小於|小于|至|到|達|达|為|为|介於|介于|から|及|和|或)\s*$",
    re.I,
)
_BOUND_AFTER = re.compile(
    r"^\s*(?:-|–|~|〜|\bto\b|\bor\s+(?:more|greater|higher|above|less|lower|below|over|under)\b|\band\s+(?:above|over|below|"
    r"under)\b|\bpredicted\b|\bof\b|以上|以下|未満|未滿|未满|超|を超|以內|以内|から|至|到|或以上|及以上|(?:或|及)?(?:更高|更低))",
    re.I,
)


def _same_kind_alternative(s_open: str, terms: list[str], lang: str) -> bool:
    """An alternative whose arm is of the concept's own kind: a word of the concept's name stands beside "or" outside
    the name itself ("kidney transplantation, liver transplantation or lung transplantation", 大腸癌、胃癌又は膵癌).
    The arm is another concept the logic does not carry, however its words are listed."""
    if lang == "en":
        heads = {w.lower() for t in terms for w in _EN_WORD.findall(t) if len(w) >= 4}
        for alt in _ALTERNATIVE.finditer(s_open):
            near = _EN_WORD.findall(s_open[max(0, alt.start() - 40) : alt.start()])[-3:]
            near += _EN_WORD.findall(s_open[alt.end() : alt.end() + 40])[:3]
            if any(w.lower() in heads or w.lower().rstrip("s") in heads for w in near):
                return True
        return False
    tails = {unicodedata.normalize("NFKC", t).strip()[-k:] for t in terms for k in (1, 2) if _CJK.search(t[-1:])}
    tails = {x for x in tails if len(x) == 2 or x in "癌炎症病腫瘤術"}
    return any(
        x in s_open[max(0, alt.start() - 8) : alt.start()] + "|" + s_open[alt.end() : alt.end() + 8]
        for alt in _ALTERNATIVE.finditer(s_open)
        for x in tails
    )


# a bracket right after the name that lists its kinds ("認知症(アルツハイマー型、血管性、その他)"): each item ends as a
# kind does (型, 性, 期, 度) or is "other"; the alternatives are then all the concept itself
_KIND = r"(?:[^、,，()（）\s]{1,10}(?:型|性|期|度)|その他|其他|其它)"
_KINDS_AFTER = re.compile(rf"\x00\s*[(（]{_KIND}(?:[、,，]\s*{_KIND})*[)）]")


def _says_never(name: str) -> bool:
    """Whether a name holds a word of a class that is never read unlisted (doubt, a plan, another person, …)."""
    if _never()["ja"].search(name) or _never()["zh"].search(name):
        return True
    return any(_never()["en"].match(w) for w in re.findall(r"[A-Za-z]+", name))


def clear_caches() -> None:
    """Forget what was read from the data file (a test that swaps the file calls this)."""
    for f in (_data, _exceptions, _ended, _non_fact, _hold_names, _vocab, _never, _closed_class, _governors,
              _zh_governors):  # fmt: skip
        f.cache_clear()


def _norm(text: str) -> str:
    """The line as it is read: NFKC (full-width letters, digits and spaces become ASCII), zero-width marks removed."""
    return _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", text))


def _bare_value(s: str) -> bool:
    if _BARE_TRAILING.search(s):
        return True
    for m in _BARE_VALUE.finditer(s):
        if not _BOUND_BEFORE.search(s[max(0, m.start() - 14) : m.start()]) and not _BOUND_AFTER.match(s[m.end() :]):
            return True
    return False


_NAME_TAILS = frozenset(
    [
        "mellitus",
        "disease",
        "diseases",
        "disorder",
        "disorders",
        "syndrome",
        "infection",
        "infections",
        "status",
        "病",
        "症",
        "疾患",
        "感染症",
        "感染",
    ]
)


def _only_a_broader_name(u: str, terms: list[str]) -> bool:
    """The line names the concept only by a name that is the tail of its primary name, with what tells its kind
    dropped from the front ("diabetes" for a concept coded "type 2 diabetes mellitus", 肺癌 for 非小細胞肺癌): the
    line may then be about another kind ("Type 1 diabetes", 小細胞肺癌, "heart failure with preserved ejection
    fraction" for one coded "… with reduced ejection fraction"), which the words alone cannot tell. A name that only
    drops a word that tells nothing ("type 2 diabetes" for "type 2 diabetes mellitus") is the same kind. The primary
    name is the first of ``terms``."""
    if not terms:
        return False
    primary = unicodedata.normalize("NFKC", terms[0]).strip().lower()

    def broader(t: str) -> bool:
        k = unicodedata.normalize("NFKC", t).strip().lower()
        if k == primary or k not in primary:
            return False
        return not (primary.startswith(k) and primary[len(k) :].strip() in _NAME_TAILS)

    return not _mentions(u, _patterns([t for t in terms if not broader(t)]))


def not_recognised(
    text: str,
    terms: Iterable[str],
    other_terms: Iterable[str] = (),
    domain: str = "condition",
    history: bool = True,
    past: bool = False,
    codes: Iterable[str] = (),
    conditional: bool = False,
) -> str | None:
    """Why ``text`` is not read as a plain assertion that the patient has the concept named by ``terms`` (its primary
    name first, then its synonyms and the names of the alternatives the logic itself carries with it): the reason's
    class, or None when the line is recognised. ``other_terms`` are the line's other named concepts; ``history``:
    whether a past occurrence counts (it does not when the criterion's logic asks the concept active only); ``past``:
    whether the logic itself asks a past occurrence (a window that ends before the index day), so that a clause
    saying it ended may run; ``codes``: the codes of the concept's value set, the only codes a line may carry.
    ``conditional``: the logic itself carries a condition on this concept (its atom is one arm of an "or"), so the
    line's "if receiving X" is coded and is read as "with"."""
    terms = list(terms)
    u = _norm(text)
    if len(u) > MAX_LINE:
        return "too_long"  # no plain statement is this long, and the reading's cost grows with the line
    if conditional:
        u = re.sub(r"\bif\b", "with", u, flags=re.I)
    found = _mentions(u, _patterns(terms))
    if not found:
        return "not_named"  # it may be named otherwise
    if any(neg for _, _, neg in found):
        return "negating_prefix"
    if _only_a_broader_name(u, terms):
        return "broader_name"
    # an abbreviation the line defines for the concept ("Type 2 diabetes mellitus (T2DM)") is one of its names
    defined = [m.group(1) for s, e, _ in found if (m := _ABBR_AFTER.match(u, e)) and _defines(u[s:e], m.group(1))]
    found = _mentions(u, _patterns([*terms, *defined]))
    spans = [(s, e) for s, e, _ in found] + [m.span() for p in _code_patterns(codes) for m in p.finditer(u)]
    own = _merge(spans)
    other = [(s, e) for s, e in _merge((s, e) for s, e, _ in _mentions(u, _others(terms, other_terms)))
             if not any(s < e2 and s2 < e for s2, e2 in own)]  # fmt: skip
    lang = _lang(u)
    # where the line names the concept by its coded name itself, an abbreviation it defines, or one of its codes (a
    # mention by another synonym is read more strictly: see _strict)
    primary = [(x, y) for x, y, _ in _mentions(u, _patterns([*terms[:1], *defined]))]
    primary += [m.span() for p in _code_patterns(codes) for m in p.finditer(u)]
    cut_out = _merge(m.span() for p in _exceptions() for m in p.finditer(u) if m.end() > m.start())
    if any(a <= s < z for s, _ in own for a, z in cut_out):
        return "excepted"  # the coded concept is what an exception names ("any immunosuppressant other than X")
    if cut_out:  # each exception and what it names is read as a clause boundary
        u = "".join("\n" if any(a <= i < z for a, z in cut_out) else ch for i, ch in enumerate(u))
    cuts = [0, *[x for m in _CLAUSE_END.finditer(u) for x in (m.start(), m.end())], len(u)]
    holds = _hold_names(domain)
    for a, z in zip(cuts[::2], cuts[1::2], strict=False):
        s = _read_as(u, a, z, own, other)
        if not s.strip(" \t.,;:、，。"):
            continue
        names_it = CONCEPT in s
        # the clause with only this concept masked: another named concept's words are read as written, so naming
        # "remission", "father" or "last infusion" as a concept never hides what it says
        s_open = _read_as(u, a, z, own, [])
        # every clause counts: what follows a full stop, "but" or 但 may say the line is not a fact ("Pending central
        # review.", "Father, aged 52.", "但目前完全緩解")
        ending = [(p, unless) for lng in {lang, "en"} for p, unless in _ended(lng, domain)]
        if not past and any(
            p.search(x) and not (unless is not None and unless.search(x)) for p, unless in ending for x in (s, s_open)
        ):
            return "ended"  # it ended or lies in the past, which an atom with no past window cannot say
        if any((p := _non_fact(lng)) is not None and p.search(s_open) for lng in ("en", "ja", "zh")):
            return "non_fact"  # not a present fact of this patient (another person, remission, a plan, a doubt)
        if any(_says_never(u[x:y]) for x, y in other if a <= x < z):
            return "non_fact"  # another coded concept whose own name is such a word ("chest imaging unremarkable")
        if s.strip(" \t.").endswith(":"):
            return "heading"
        kinds = _KINDS_AFTER.sub(lambda k: CONCEPT + " " * (len(k.group(0)) - 1), s)
        for name, h in holds:  # listed words that together say otherwise
            if name.startswith("alternative") and kinds != s and not h.search(kinds):
                continue  # the alternatives are kinds of the concept itself, listed in a bracket after its name
            for x in (s, s_open):
                m = h.search(x)
                # a definition holds only when it is all the clause says of the concept: "diagnosis of <gout>
                # according to the … <gout> classification criteria" asserts it first
                if m and not (name.startswith(("definition", "criteria_for")) and x[: m.end()].count(CONCEPT) > 1):
                    return "hold:" + name
        if _bare_value(s_open):
            return "hold:bare_value"
        if names_it and _same_kind_alternative(s_open, terms, lang):
            return "hold:alternative_same_kind"
        marks = [i for i, ch in enumerate(s) if ch == CONCEPT]
        inside = [(x, y) for x, y in own if a <= x < z]
        syn = frozenset(
            i for i, (x, y) in zip(marks, inside, strict=False) if not any(x <= p and q <= y for p, q in primary)
        )
        why = _clause_unread(s, lang, domain, history, not names_it, names_it or OTHER in s, syn)
        if why is not None:
            return why
    return None


def recognised(
    text: str,
    terms: Iterable[str],
    other_terms: Iterable[str] = (),
    domain: str = "condition",
    history: bool = True,
    past: bool = False,
    codes: Iterable[str] = (),
) -> bool:
    """Whether ``text`` reads as a plain assertion of the concept (see :func:`not_recognised`)."""
    return not_recognised(text, terms, other_terms, domain, history, past, codes) is None


def _history_counts(atom: Atom) -> bool:
    status = atom.clinical_status or []
    return not (status and set(status) <= set(ACTIVE_STATUSES))


def _asks_the_past(atom: Atom) -> bool:
    """The atom's own logic asks a past occurrence: a window that ends before the index day."""
    w = atom.window
    return w is not None and w.to_days is not None and w.to_days < 0


def _or_siblings(logic: object, atom: Atom) -> list[Atom]:
    """The atoms that are alternatives of ``atom`` in the logic itself: the other arms of each "or" above it."""
    if not isinstance(logic, BoolExpr):
        return []
    for arg in logic.args:
        if arg is atom or atom in atoms_of(arg):
            inner = _or_siblings(arg, atom)
            if logic.op == "or":
                inner += [a for other in logic.args if other is not arg for a in atoms_of(other)]
            return inner
    return []


def presence_not_recognised(
    text: str,
    logic: object,
    terms_for: Callable[[str], list[str]],
    other_terms: Iterable[str] = (),
    codes_for: Callable[[str], list[str]] | None = None,
) -> str | None:
    """Why an inclusion's ``logic`` asks the presence of a concept its ``text`` is not recognised as asserting (card
    10A-1d): the reason's class, or None when every concept it asks the presence of is recognised. Arguments as
    :func:`negation_scope.negated_presence`; ``codes_for(valueset)`` gives the codes of a value set (a code in the
    line is recognised only when it is one of the concept's own). A concept the logic itself joins by "or" to this
    one is read as one of its names: the line's "or" is then carried by the logic.

    Another concept counts as one only when the criterion's own logic codes it: a name the extractor gave but the
    logic does not use (``other_terms``) is read as the words it is, so a line whose second condition the logic
    never checks is held, and naming "spouse" or "remission" as a concept never lets a line run."""
    del other_terms  # kept for the caller's signature; see above
    every = [x for a in atoms_of(logic) for x in (*terms_for(a.valueset or ""), *_slug_words(a.valueset))]
    for atom in presence_atoms(logic):
        siblings = _or_siblings(logic, atom)
        terms = [x for a in (atom, *siblings) for x in (*terms_for(a.valueset or ""), *_slug_words(a.valueset))]
        codes = [c for a in (atom, *siblings) for c in (codes_for(a.valueset or "") if codes_for else [])]
        why = not_recognised(
            text, terms, every, atom.domain, _history_counts(atom), _asks_the_past(atom), codes, under_or(logic, atom)
        )
        if why is not None:
            return why
    return None


def unrecognised_presence(
    text: str,
    logic: object,
    terms_for: Callable[[str], list[str]],
    other_terms: Iterable[str] = (),
    codes_for: Callable[[str], list[str]] | None = None,
) -> bool:
    """Whether :func:`presence_not_recognised` gives a reason."""
    return presence_not_recognised(text, logic, terms_for, other_terms, codes_for) is not None
