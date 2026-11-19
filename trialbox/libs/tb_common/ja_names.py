"""Card 10C-1b: Japanese person names from a morphological analyser, an optional recogniser of the privacy guard.

The guard's rules (``tb_common.phi_guard``, card 10C-1) find a Japanese name by a label, an honorific, a title or a
listed surname. A name with none of these beside it (見本太郎は本日来院, 68歳男性 ミホン タロウ) needs a dictionary
that knows names: a morphological analyser tags each word, and its lexicon marks surnames (姓), given names (名) and
other person names (人名).

**Off and absent by default.** Nothing in the product imports this module, and importing it imports no analyser:
the package (SudachiPy with a SudachiDict, or a MeCab binding with a dictionary) is loaded only by
:func:`analyser`, called by a person or a test. The analyser is not in the lock files or the images: adding it is
the owner's decision (decision D-1235, ``docs/research/2026-11-19-japanese-name-analyser.md``). :func:`enable`
registers :func:`name_spans` in ``phi_guard.NAME_RECOGNISERS``; with that list empty every output is master's.

**The combination rule** (:func:`name_spans`): the analyser proposes, the guard decides.

1. *Propose.* A run of words the analyser tags as a person name (姓, 名, or 人名 一般), joined across one space or a
   middle dot; then one more word on either side when it reads as the other half of the name (a kanji word of one
   to four characters, or a katakana word of two to eight, that is a noun and not a protected word): the surname
   before a given name (見本 before 太郎), the given name after a surname.
2. *Not a lone surname.* A run that is a single surname, or one character, is dropped: 松本, 長崎, 岡山 are places as
   often as people, and a listed surname before a staff word or an honorific is the rules' job already.
3. *Not inside a medical or place term.* A span directly followed by a word of a disease, a sign, a procedure, a
   scale, an institution or a place (病, 症候群, 炎, 型, 分類, 手術, 反射, 徴候, 母斑, 病院, 医院, 内科, 市 ...) is an
   eponym or a place (橋本病, 高安動脈炎, パーキンソン病, 杉野医院), never masked. So is a span that the analyser
   itself joined into a longer common noun (川崎病 as one word).
4. *The guard's own protections.* A span whose text is a word the rules already say is no name: a relative, a role,
   a description of the patient (``phi_guard._JA_RELATIVES``, ``phi_guard._JA_NOT_A_NAME_VALUE``'s words), a word
   of the ``-like`` list before 様 (``phi_guard._JA_LIKE``).

Text is read a line at a time (a line of more than 2,000 characters in pieces at punctuation), so the analyser's
input limit is never reached and time stays linear in the note.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from tb_common import phi_guard

#: the analysers this module can load, by the name :func:`analyser` takes
CHOICES = ("sudachi-small", "sudachi-core", "sudachi-full", "mecab-unidic-lite", "mecab-ipadic", "janome")


@dataclass(frozen=True)
class Token:
    surface: str
    start: int
    end: int
    pos: tuple[str, ...]  # the first four part-of-speech fields

    @property
    def name(self) -> str:
        """``sei`` (surname), ``mei`` (given name), ``person`` (other person name) or ``""``."""
        if len(self.pos) >= 3 and self.pos[0] == "名詞" and self.pos[1] == "固有名詞" and self.pos[2] == "人名":
            tail = self.pos[3] if len(self.pos) > 3 else ""
            return {"姓": "sei", "名": "mei"}.get(tail, "person")
        return ""

    @property
    def noun(self) -> bool:
        return bool(self.pos) and self.pos[0] == "名詞" and (len(self.pos) < 2 or self.pos[1] not in ("数", "数詞"))


class Analyser(Protocol):
    label: str

    def tokens(self, text: str) -> list[Token]: ...


def _offsets(text: str, surfaces: list[tuple[str, tuple[str, ...]]]) -> list[Token]:
    """Tokens with their places in ``text``, for an analyser that gives the surfaces only (MeCab drops spaces)."""
    out, i = [], 0
    for surface, pos in surfaces:
        j = text.find(surface, i)
        if j < 0:  # an analyser that changed the surface (it should not): skip it, never shift the rest
            continue
        out.append(Token(surface, j, j + len(surface), pos))
        i = j + len(surface)
    return out


class _Sudachi:
    def __init__(self, dict_type: str) -> None:
        from sudachipy import Dictionary, SplitMode  # type: ignore[import-not-found,unused-ignore]  # optional, not in the lock

        self.label = f"sudachi-{dict_type}"
        self._tok = Dictionary(dict=dict_type).tokenizer(mode=SplitMode.C)

    def tokens(self, text: str) -> list[Token]:
        return [
            Token(m.surface(), m.begin(), m.end(), tuple(m.part_of_speech()[:4]))
            for m in self._tok.tokenize(text)
            if not m.surface().isspace()
        ]


class _Mecab:
    def __init__(self, dictionary: str) -> None:
        import fugashi  # type: ignore[import-not-found,unused-ignore]  # optional, not in the lock

        self.label = f"mecab-{dictionary}"
        if dictionary == "unidic-lite":
            import unidic_lite  # type: ignore[import-not-found,unused-ignore]  # optional, not in the lock

            self._tagger: Any = fugashi.Tagger(f"-d {unidic_lite.DICDIR}")
            self._unidic = True
        else:
            import ipadic  # type: ignore[import-not-found,unused-ignore]  # optional, not in the lock

            self._tagger = fugashi.GenericTagger(ipadic.MECAB_ARGS)
            self._unidic = False

    def tokens(self, text: str) -> list[Token]:
        words = []
        for w in self._tagger(text):
            f = w.feature
            pos = (f.pos1, f.pos2, f.pos3, f.pos4) if self._unidic else tuple(f[:4])
            words.append((w.surface, tuple(p for p in pos if p and p != "*")))
        return _offsets(text, words)


class _Janome:
    def __init__(self) -> None:
        from janome.tokenizer import Tokenizer  # type: ignore[import-not-found,unused-ignore]  # optional, not in the lock

        self.label = "janome"
        self._tok = Tokenizer()

    def tokens(self, text: str) -> list[Token]:
        words = [
            (t.surface, tuple(p for p in t.part_of_speech.split(",")[:4] if p != "*"))
            for t in self._tok.tokenize(text)
            if not t.surface.isspace()
        ]
        return _offsets(text, words)


def analyser(choice: str = "sudachi-core") -> Analyser:
    """Load an analyser (ImportError when its package is not installed: nothing here installs one)."""
    if choice.startswith("sudachi-"):
        return _Sudachi(choice.removeprefix("sudachi-"))
    if choice.startswith("mecab-"):
        return _Mecab(choice.removeprefix("mecab-"))
    if choice == "janome":
        return _Janome()
    raise ValueError(f"unknown analyser {choice!r}; one of {CHOICES}")


# ------------------------------------------------------------------------------------------------ the rule
_KANJI = phi_guard._JA_KANJI
_KANJI_WORD = re.compile(f"[{_KANJI}]{{1,4}}")
_KATA_WORD = re.compile("[ァ-ヺー]{2,8}|[ｦ-ﾟ]{2,8}")
_GAP = re.compile("[ 　]{1,2}|[・･]")
#: a text the analyser reads: it holds kana or 歳 (the Japanese form; Chinese writes 歲 or 岁)
_JAPANESE = re.compile("[ぁ-ゖァ-ヺｦ-ﾝ]|歳")
# step 3: a word of a disease, a sign, a procedure, a scale, an institution or a place; what follows an eponym
_TERM = (
    r"(?:病|症候群|症|炎|型|分類|法|式|手術|術|反射|徴候|母斑|白斑|結節|細胞|試験|療法|リンパ腫|腫|ジストロフィー"
    r"|反応|カテーテル|スコア|スケール|心電図|病院|医院|歯科|内科|外科|科|クリニック|診療所|大学|市|区|町|村|県|駅"
    r"|製薬|錠|散|液|菌|毒素|ウイルス|抗体|線|管|室|棟|会|社|地方|地区|転移|調律|様[のなに])"
)
# after the name: a term directly, after one space (松本 歯科), or after the rest of a compound (ギラン・バレー症候群)
_TERM_AFTER = re.compile(rf"(?:[ 　]?|[・･][ァ-ヺー]{{1,12}}){_TERM}")
_TERM_WORD = re.compile(rf"{_TERM}|.*[病症炎癌痛熱感腫]$")
# a kanji word that can be a given name after a surname: the guard's own class (never 錦, 製薬, 市, 科 ...)
_GIVEN = re.compile(f"{phi_guard._JA_GIVEN_KANJI}{{1,3}}")
# step 4: the words the guard's rules already say are no name
_NOT_A_NAME = re.compile(
    rf"(?:{phi_guard._JA_RELATIVES}|{phi_guard._JA_LIKE}"
    r"|患者|本人|家族|男性|女性|男児|女児|小児|成人|新生児|乳児|幼児|妊婦|高齢|主治医|担当医|研修医|当直医|執刀医"
    r"|麻酔科医|医師|看護師|看護師長|師長|薬剤師|技師|院長|部長|課長|医長|教授|先生|管理栄養士|理学療法士"
    r"|ケアマネジャー|ソーシャルワーカー|キーパーソン|同室|紹介元|救急隊|担当|方針|本日|昨日|明日|昨夜|今朝|明朝)"
)
_NOT_A_NAME_VALUE = re.compile(phi_guard._JA_NOT_A_NAME_VALUE)  # a look ahead: no match where a protected word starts
_AFTER_DR = re.compile(r"\bDr\.?[ 　]{0,2}$")  # the guard reads no Japanese name after Dr. (Dr. 指示, Dr. コール)
_LINE_MAX = 2000
_SPLIT_AT = re.compile(r"[。、，,；;\n]")


def _kata(s: str) -> bool:
    return _KATA_WORD.fullmatch(s) is not None


def _name_like(tok: Token) -> bool:
    """A word that can be the other half of a name: a noun of 1-4 kanji or 2-8 katakana, never a protected word or
    a word of a term."""
    s = tok.surface
    return (
        tok.noun
        and (_KANJI_WORD.fullmatch(s) is not None or _kata(s))
        and _NOT_A_NAME.fullmatch(s) is None
        and _TERM_WORD.fullmatch(s) is None
    )


def _gap(text: str, a: Token, b: Token) -> str | None:
    """What stands between ``a`` and ``b``: "" (nothing), the gap (one space, two at most, or a middle dot) or None."""
    gap = text[a.end : b.start]
    return gap if gap == "" or _GAP.fullmatch(gap) is not None else None


def _given_after(sei: Token, nxt: Token, gap: str | None) -> bool:
    """``nxt`` can be the given name after the surname ``sei`` (directly, or after one space or a dot): katakana, or
    kanji of the guard's given-name class (佐藤錦 is a cherry, 山田錦 a rice)."""
    if gap is None:
        return False
    if _kata(nxt.surface):
        return True
    return _GIVEN.fullmatch(nxt.surface) is not None and _TERM_WORD.fullmatch(nxt.surface) is None


def _given_ok(tok: Token) -> bool:
    """A given name in kanji is of the guard's given-name class (錦, 市, 科 ... are no given name)."""
    return tok.name != "mei" or _kata(tok.surface) or _GIVEN.fullmatch(tok.surface) is not None


def _alone_ok(tok: Token) -> bool:
    """A name word standing alone is taken only when it is kanji, two characters or more, and a given name or a
    whole name (太郎 on a line of its own, 山田太郎 as one word of the full dictionary), ending in a character of the
    guard's given-name class; never a surname alone (松本, 長崎 are places too) or a katakana word alone (ミヤ, コール,
    パーキンソン)."""
    s = tok.surface
    return (
        tok.name in ("mei", "person")
        and len(s) >= 2
        and _KANJI_WORD.fullmatch(s) is not None
        and re.fullmatch(phi_guard._JA_GIVEN_KANJI, s[-1]) is not None
    )


def _proposals(text: str, toks: list[Token]) -> Iterator[tuple[int, int, list[Token], int]]:
    """Steps 1 and 2: runs of name words, a neighbouring half of the name added; a name word alone only as
    :func:`_alone_ok` says, and never a name of one character. Yields the span, its words and the end of the tagged
    run (before a given name added after it)."""
    toks = [t if _given_ok(t) else Token(t.surface, t.start, t.end, ()) for t in toks]
    i, n = 0, len(toks)
    while i < n:
        if not toks[i].name:
            i += 1
            continue
        j = i
        while j + 1 < n and toks[j + 1].name and (g := _gap(text, toks[j], toks[j + 1])) is not None:
            if toks[j].name == "sei" and not _given_after(toks[j], toks[j + 1], g):
                break  # 佐藤 錦, 山田錦: a surname and a word that is no given name
            j += 1
        lo, hi = i, j
        first, last = toks[i], toks[j]
        if (
            first.name in ("mei", "person")
            and i > 0
            and _name_like(toks[i - 1])
            and _gap(text, toks[i - 1], first) is not None
        ):
            lo = i - 1  # the surname before a given name (見本太郎, ミホン タロウ)
        if (
            last.name == "sei"
            and j + 1 < n
            and _name_like(toks[j + 1])
            and _given_after(last, toks[j + 1], _gap(text, last, toks[j + 1]))
        ):
            hi = j + 1  # the given name after a surname
        words = toks[lo : hi + 1]
        if (len(words) > 1 or _alone_ok(words[0])) and words[-1].end - words[0].start >= 2:
            yield words[0].start, words[-1].end, words, toks[j].end
        i = j + 1


def _protected(text: str, start: int, end: int, words: list[Token], run_end: int) -> bool:
    """Steps 3 and 4: an eponym, a place or an institution; a word the guard says is no name; after Dr."""
    if _TERM_AFTER.match(text, end) or _TERM_AFTER.match(text, run_end):
        return True
    if any(_NOT_A_NAME.fullmatch(w.surface) for w in words):
        return True
    if _NOT_A_NAME.fullmatch(text[start:end]) or _NOT_A_NAME_VALUE.match(text, start) is None:
        return True
    return _AFTER_DR.search(text, 0, start) is not None


def _pieces(text: str) -> Iterator[tuple[int, str]]:
    """The text a line at a time, a long line in pieces of at most :data:`_LINE_MAX` characters cut at punctuation."""
    pos = 0
    for line in text.split("\n"):
        start = 0
        while len(line) - start > _LINE_MAX:
            cut = max((m.end() for m in _SPLIT_AT.finditer(line, start, start + _LINE_MAX)), default=start + _LINE_MAX)
            yield pos + start, line[start:cut]
            start = cut
        yield pos + start, line[start:]
        pos += len(line) + 1


def name_spans(text: str, an: Analyser, *, protect: bool = True) -> list[tuple[int, int]]:
    """``(start, end)`` of every person name the rule takes from the analyser's tags. A text with no kana and no 歳
    is not Japanese and is not read. ``protect=False``: every word the analyser tags as a person name, with no rule
    (what the analyser alone would mask, to show what the rule does)."""
    if not protect:
        return [
            (o + t.start, o + t.end) for o, piece in _pieces(text) if piece.strip() for t in an.tokens(piece) if t.name
        ]
    if _JAPANESE.search(text) is None:
        return []
    out: list[tuple[int, int]] = []
    for offset, piece in _pieces(text):
        if not piece.strip():
            continue
        for s, e, words, run_end in _proposals(piece, an.tokens(piece)):
            if protect and _protected(piece, s, e, words, run_end):
                continue
            out.append((offset + s, offset + e))
    return out


_ENABLED: dict[str, Callable[[str], list[tuple[int, int]]]] = {}


def enable(an: Analyser) -> None:
    """Add the analyser's names to the guard (``phi_guard.NAME_RECOGNISERS``). For a person or a test: the product
    never calls it until the owner has approved the dependency."""
    disable()
    recognise = lambda text: name_spans(text, an)  # noqa: E731
    _ENABLED["fn"] = recognise
    phi_guard.NAME_RECOGNISERS.append(recognise)


def disable() -> None:
    fn = _ENABLED.pop("fn", None)
    if fn is not None and fn in phi_guard.NAME_RECOGNISERS:
        phi_guard.NAME_RECOGNISERS.remove(fn)
