"""Card 10C-1b: Japanese person names from a morphological analyser, an optional recogniser of the privacy guard.

The guard's rules (``tb_common.phi_guard``, card 10C-1) find a Japanese name by a label, an honorific, a title or a
listed surname. A name with none of these beside it (見本太郎は本日来院, 68歳男性 ミホン タロウ) needs a dictionary
that knows names: a morphological analyser tags each word, and its lexicon marks surnames (姓), given names (名) and
other person names (人名).

**On by default, loaded lazily.** SudachiPy 0.7.0 with SudachiDict-small 20261015 is a runtime dependency (the
owner's yes, decision D-1235, ``docs/research/2026-11-19-japanese-name-analyser.md``): ``phi_guard.japanese_names``,
registered in ``phi_guard.NAME_RECOGNISERS``, imports this module and loads the analyser on the first Japanese text
(``phi_guard.japanese_text``: kana, 歳 or a kanji only Japanese writes at any site; any Han text when the site declares
Japanese notes, or declares nothing and the text holds no character only Chinese writes), one tokenizer per thread.
Importing this module imports no analyser: a package is loaded only by :func:`analyser`. The other analysers
(SudachiDict-core and -full, MeCab, Janome) are not in the lock; the harness (``tools/ja_name_eval.py``) measures them
where they are installed by hand. :func:`enable` puts another analyser in the guard's place for a test; :func:`disable`
puts the default back.

**The combination rule** (:func:`name_spans`): the analyser proposes, the guard decides.

1. *Propose.* A run of words the analyser tags as a person name (姓, 名, or 人名 一般), joined across one space, and
   across a middle dot by this module (the analyser returns ・ as a word of its own: グエン・ヴァン・アン, a katakana
   word joining a katakana name); a hiragana surname by its reading (さいとう: サイトウ is tagged 姓); then one more
   word on either side when it reads as the other half of the name: the surname before a given name (見本 before
   太郎), the given name after a surname (a kanji word of the guard's given-name class that is no common noun, a
   katakana word, a hiragana word after a space: 中川 ひかり; never the start of a title: 井上看護師).
2. *Not a lone surname.* A run that is a single surname, or one character, is dropped (松本, 長崎, 岡山 are places as
   often as people), unless an age or a sex follows it (浅野 52歳); a katakana person name alone is taken from four
   characters (ブラウン), never an eponym (パーキンソン); a hiragana name word alone from three (まなみ).
3. *Not inside a medical or place term.* A span directly followed by a word of a disease, a sign, a procedure, a
   scale, an institution or a place (病, 症候群, 炎, 型, 分類, 手術, 反射, 徴候, 母斑, 病院, 医院, 内科, 市 ...) is an
   eponym or a place (橋本病, 高安動脈炎, パーキンソン病, 杉野医院, ボルマン3型, 母 福田 心療内科), never masked.
4. *The guard's own protections.* A span whose text is a word the rules already say is no name: a relative, a role,
   a description of the patient (``phi_guard._JA_RELATIVES``, ``phi_guard._JA_NOT_A_NAME_VALUE``'s words), a word
   of the ``-like`` list before 様 (``phi_guard._JA_LIKE``).
5. *By position, not by list.* The word directly before a title or an honorific (先生, 医師, 看護師, 様, さん, 氏, 殿,
   君, ちゃん, Dr, Ns: 原先生, 宮崎医師, 太郎君, はなちゃん, Kimura先生, 中山Drへ, 野村 Dr., 百目鬼 透 氏), the word
   after a title or a role (Dr. 木村, Dr.Kimura, 担当PT：浅野, 主治医 は 坂本 です, 看護師　野口　より) or a name label
   (患者：, 氏名, 旧姓, キーパーソン, a relative's word: 旧姓 渡邊, 患者：＊＊太郎), the words before an age or a sex
   (スギノ ナオト 52歳) and the two words after one (68歳男性 ツツミ ケンタ) are a name when the analyser calls them a
   name or a proper noun, or no common noun; never a role, a family word, a common noun (校長先生, 主治医の判断), a
   prefix or a suffix after a label (患者：要介護, 担当者：未定), a word that runs on into a compound (長女 山田錦の酒),
   a nationality (韓国籍 42歳) or a word in a name's place that is none (担当医：当番医, 主治医：交代予定). The titles,
   the roles and those words are data: ``ja_name_cues.json`` beside this module.
6. *Latin letters* (:func:`romaji_spans`): two Hepburn words, one a surname by its reading, written as a name is
   (Taro Yamada, YAMADA Taro, hanako sato, full-width letters too); a Latin word in romaji before or after a title,
   after a label; a romaji name after its kanji form (石井 Ishii 様).
7. *Brackets*: a form or a reading in brackets after a name, and the given name after it (さいとう(斉藤)　まなみ); a
   name and its reading before an honorific (須藤（すどう）さん, すどう（須藤）さん). The brackets are masked with it.

``phi_guard`` keeps a name whole (四月一日 君子: a rule that starts inside a run of kanji takes the run), masks a name
masked once at its other bare occurrences in the same note (河野さんへ。河野は不在。; never inside a longer word or
before a term: 河野病院), and drops a span in a name's place that is no name (主治医：交代予定). The guard's redaction
may take the honorific with the name (鈴木一郎先生 -> [NAME]); the masker keeps it (○○○○先生).

**Limits** (``eval/phi_synth/ja_name_classes.json`` ``limit``): a kanji surname alone with no title, label, age or
sex beside it (浅野: a place as often); a hiragana surname the analyser does not know by its reading (すどう); a
romaji surname alone (Kimura); a romaji name of two words where neither is a listed surname, in a text that is not
Japanese; initials (Y.T.); a name inside a clinic's name; rare surnames the dictionary does not hold (四十物, 勅使河原,
小鳥遊) unless a cue stands beside them.

Text is read a line at a time (a line of more than 2,000 characters in pieces at punctuation), so the analyser's
input limit is never reached and time stays linear in the note; a piece read once is not read again (a bounded cache
of 1,024 pieces).
"""

from __future__ import annotations

import bisect
import csv
import itertools
import json
import re
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path
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


# Each thread owns its tokenizer, but opening the same read-only dictionary for every
# simultaneous model call can exhaust the gateway's admission deadline.
_DICTIONARY_LOCK = threading.Lock()


@cache
def _dictionary(dict_type: str) -> Any:
    from sudachipy import Dictionary  # type: ignore[import-untyped,unused-ignore]

    return Dictionary(dict=dict_type)


class _Sudachi:
    def __init__(self, dict_type: str) -> None:
        from sudachipy import SplitMode  # type: ignore[import-untyped,unused-ignore]  # no stubs (D-1235)

        self.label = f"sudachi-{dict_type}"
        with _DICTIONARY_LOCK:
            self._tok = _dictionary(dict_type).tokenizer(mode=SplitMode.C)

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
_HIRA_WORD = re.compile("[ぁ-ゖー]{2,8}")
_DOT = frozenset("・･")
#: a text the analyser reads: it holds kana or 歳 (the Japanese form; Chinese writes 歲 or 岁)
_JAPANESE = re.compile("[ぁ-ゖァ-ヺｦ-ﾝ]|歳")
# step 3: a word of a disease, a sign, a procedure, a scale, an institution or a place; what follows an eponym
#: the cue words (titles, roles, words in a name's place that are none): data, not code (third round, D-1235)
CUES_FILE = Path(__file__).with_name("ja_name_cues.json")
CUES: dict[str, Any] = json.loads(CUES_FILE.read_text(encoding="utf-8"))


def _alt(words: list[str]) -> str:
    """The words as one alternation, the longest first; a word of Latin letters stands alone (Dr, never Drug)."""
    out = []
    for w in sorted(words, key=len, reverse=True):
        e = re.escape(w)
        if re.match("[A-Za-z]", w):  # Dr stands alone; Dr. may touch the name (Dr.Kimura)
            e = rf"(?<![A-Za-z]){e}" + ("" if w.endswith(".") else "(?![A-Za-z])")
        out.append(e)
    return "|".join(out)


_TERM = rf"(?:{'|'.join(re.escape(w) for w in sorted(CUES['terms_after_name'], key=len, reverse=True))}|様[のなに])"
# after the name: a term directly, after one space (松本 歯科), or after the rest of a compound (ギラン・バレー症候群)
_TERM_AFTER = re.compile(
    rf"(?:[ 　]?[0-9０-９IVⅠ-Ⅻ]{{0,3}}|[・･][ァ-ヺー]{{1,12}}){_TERM}"
    rf"|[ 　][{phi_guard._JA_KANJI}]{{1,4}}(?:科|院|医院|病院|クリニック)"
)
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


def _hira(s: str) -> bool:
    return _HIRA_WORD.fullmatch(s) is not None


def _common(tok: Token) -> bool:
    """The analyser calls the word a common noun (普通名詞): 胃散, 看護, 君子; never a name of its own."""
    return len(tok.pos) >= 2 and tok.pos[0] == "名詞" and tok.pos[1] == "普通名詞"


def _proper(tok: Token) -> bool:
    """A proper noun (a person, a place, an organisation) or a prefix (原 before 先生 is tagged one)."""
    return bool(tok.name) or (len(tok.pos) >= 2 and tok.pos[1] == "固有名詞") or tok.pos[:1] == ("接頭辞",)


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


def _given_after(sei: Token, nxt: Token, gap: str | None, text: str = "") -> bool:
    """``nxt`` can be the given name after the surname ``sei`` (directly, or after one space or a dot): katakana; a
    hiragana word after a space (中川 ひかり; never directly: 中川から); or kanji of the guard's given-name class that
    the analyser does not call a common noun (佐藤錦 is a cherry, 山田錦 a rice, 太田胃散 a medicine). Never the start
    of a title (井上看護師: 看護 is no given name)."""
    if gap is None or _TITLE.match(text, nxt.start):
        return False
    if _kata(nxt.surface):
        return True
    if _hira(nxt.surface):
        return gap != "" and (nxt.name == "mei" or nxt.noun)
    return (
        _GIVEN.fullmatch(nxt.surface) is not None
        and _TERM_WORD.fullmatch(nxt.surface) is None
        and (nxt.name in ("mei", "person") or not _common(nxt))
    )


def _given_ok(tok: Token) -> bool:
    """A given name in kanji is of the guard's given-name class (錦, 市, 科 ... are no given name)."""
    return tok.name != "mei" or _kata(tok.surface) or _hira(tok.surface) or _GIVEN.fullmatch(tok.surface) is not None


def _alone_ok(tok: Token) -> bool:
    """A name word standing alone is taken only when it is kanji, two characters or more, and a given name or a
    whole name (太郎 on a line of its own, 山田太郎 as one word of the full dictionary), ending in a character of the
    guard's given-name class; never a surname alone (松本, 長崎 are places too) or a katakana word alone (ミヤ, コール,
    パーキンソン); a hiragana name word of three characters or more."""
    s = tok.surface
    if tok.name and re.search("[（(]", s) and re.search(f"[{_KANJI}]", s):
        return True  # 工藤（くどう）: a name and its reading, one word of the analyser
    if _hira(s):  # まなみ, さいとう: a hiragana name word of three characters or more (はな, ゆき are words too)
        return bool(tok.name) and len(s) >= 3
    return (
        tok.name in ("mei", "person")
        and len(s) >= 2
        and _KANJI_WORD.fullmatch(s) is not None
        and re.fullmatch(phi_guard._JA_GIVEN_KANJI, s[-1]) is not None
    )


# a surname alone is a person when an age or a sex follows it (浅野 52歳, 野村 男性): a place has neither
_AGE_OR_SEX_AFTER = re.compile(phi_guard._JA_AGE_OR_SEX)
# eponyms the analyser tags as person names, never masked alone (パーキンソン, クローン)
_EPONYM = re.compile(
    r"(?:パーキンソン|アルツハイマー|クローン|ベーチェット|バセドウ|バセドー|ギラン|バレー|ホジキン|ハンチントン|レイノー"
    r"|シェーグレン|クッシング|アジソン|ウィルソン|ウイルソン|ダウン|ターナー|マルファン|メニエール|ネフローゼ|ワレンベルグ"
    r"|ブローカ|ウェルニッケ|コルサコフ|ホルネル|ホーナー|バビンスキー|ラセーグ|マックバーニー|マーフィー|ブルンベルグ"
    r"|ヘルニア|ガイドライン|フォンタン|ファロー|カポジ|ベル|ミュンヒハウゼン|ヒルシュスプルング|ペルテス|オスグッド)"
)


def _lone_ok(text: str, tok: Token) -> bool:
    """A name word alone the position vouches for: a kanji surname before an age or a sex (浅野 52歳); a katakana
    person name of four characters or more that is no eponym (ブラウン; never パーキンソン, コール, ミヤ)."""
    if tok.name == "sei" and _KANJI_WORD.fullmatch(tok.surface) and len(tok.surface) >= 2:
        return _AGE_OR_SEX_AFTER.match(text, tok.end) is not None
    return tok.name == "person" and _kata(tok.surface) and len(tok.surface) >= 4 and not _EPONYM.fullmatch(tok.surface)


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
        while j + 1 < n and (g := _gap(text, toks[j], toks[j + 1])) is not None:
            nxt = toks[j + 1]
            dotted = g in _DOT and _kata(toks[j].surface) and _kata(nxt.surface) and nxt.noun
            if not nxt.name and not dotted:
                break  # a katakana word joins a katakana name across a middle dot (グエン・ヴァン・アン)
            if toks[j].name == "sei" and not dotted and not _given_after(toks[j], nxt, g, text):
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
            and (_name_like(toks[j + 1]) or _hira(toks[j + 1].surface))
            and _given_after(last, toks[j + 1], _gap(text, last, toks[j + 1]), text)
        ):
            hi = j + 1  # the given name after a surname
        words = toks[lo : hi + 1]
        head = words[0]
        if (
            head.name == "sei"
            and len(head.surface) == 1
            and lo > 0
            and _gap(text, toks[lo - 1], head) == ""
            and _common(toks[lo - 1])
            and _KANJI_WORD.fullmatch(toks[lo - 1].surface) is not None
        ):
            i = j + 1
            continue  # 呼吸音清: a one-kanji surname glued to a common noun is the end of that word, not a name
        alone = len(words) == 1 and (_alone_ok(words[0]) or _lone_ok(text, words[0]))
        if (len(words) > 1 or alone) and words[-1].end - words[0].start >= 2:
            yield words[0].start, words[-1].end, words, toks[j].end
        i = j + 1


_AGE_THRESHOLD = re.compile(r"年[滿满満][ 　]*\d{1,3}[ 　]*[歲岁歳]")


def _protected(text: str, start: int, end: int, words: list[Token], run_end: int) -> bool:
    """Steps 3 and 4: an eponym, a place or an institution; a word the guard says is no name; after Dr."""
    # In a mixed-language chart Sudachi reads 滿 as a given name, including in a Chinese age threshold.
    if end - start == 2 and _AGE_THRESHOLD.match(text, start):
        return True
    whole = (
        len(words) >= 2
        and words[0].name == "sei"
        and words[-1].name == "mei"
        and all(_KANJI_WORD.fullmatch(w.surface) for w in words)
    )
    if not whole and (_TERM_AFTER.match(text, end) or _TERM_AFTER.match(text, run_end)):
        return True  # 橋本病, ホーン・ヤール分度; a surname with its given name is a person (佐藤翔太検査結果)
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


# ------------------------------------------------------------------------------------------------ by position
# a title or an honorific after a name (the guard's own honorifics, with their ends, and the staff words)
_LATIN_CUES = frozenset(w for k in ("titles_before_name", "titles_after_name") for w in CUES[k] if w[:1].isascii())
_ROLE_WORDS = frozenset(CUES["titles_before_name"] + CUES["titles_after_name"])
_NOT_A_NAME_WORDS = frozenset(CUES["not_a_name_value"])
_NOT_A_NAME_ENDING = tuple(CUES["not_a_name_ending"])
_PREFIX_BEFORE_TITLE = frozenset(CUES["prefixes_before_title"])  # 老先生, 故先生: a prefix, never a name
# a title or an honorific after a name: the guard's own honorifics, with their ends, and the cue words
_TITLE = re.compile(rf"(?:{phi_guard._JA_HON}|{_alt(CUES['titles_after_name'])})")
# a title before a name (Dr. 木村, 担当OT：宮田, 主治医 は 岡田, 看護師　野口　より)
_CUE_BEFORE = re.compile(
    rf"(?:{_alt(CUES['titles_before_name'])})[ 　]*(?:[:：]|(?:{_alt(CUES['between_title_and_name'])}))?[ 　]*"
)
_KANA_HON = frozenset(("さん", "さま", "くん", "ちゃん", "様", "君", "殿", "氏"))
_GIVEN_HON = frozenset(("くん", "ちゃん", "君"))  # after a given name alone: 太郎君, はなちゃん
# a label before a name: the guard's name labels, the staff and referral words, a maiden name, a relative's word;
# then の, a colon or a space
_LABEL = re.compile(
    r"(?:患者氏名|患者名|患者|氏名|名前|担当医|主治医|紹介元|紹介医|キーパーソン|ｷｰﾊﾟｰｿﾝ|旧姓|記載者|同席者"
    rf"|{phi_guard._JA_RELATIVES})(?:の|[ 　]*[:：][ 　]*|[ 　]{{1,2}})"
)
_PLACEHOLDER = re.compile(r"[＊*○●×✕〇]{1,8}")  # a part of the name already masked (患者：＊＊太郎)
_LATIN = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ][A-Za-z'Ａ-Ｚａ-ｚ]{1,19}")
_KANJI_RUN = re.compile(f"[{_KANJI}]{{1,4}}")
# a word before an honorific that is no name: the guard's lists, and the words of a family or a baby
_HON_NOT_A_NAME = re.compile(
    r"(?:赤|坊|爺|婆|伯父|伯母|叔父|叔母|お?嬢|奥|旦那|彼|彼女|皆|みな|みんな|おじい|おばあ|おじ|おば|おにい|おねえ|おかあ"
    r"|おとう|かあ|とう|にい|ねえ|じい|ばあ|あか|ぼっ|お子|お客|お医者|お兄|お姉|お母|お父|お爺|お婆|看護|師)"
)


class _Words(list[Token]):
    """The analyser's words of a piece, found by where they start and end (a long line stays linear)."""

    def __init__(self, toks: list[Token]) -> None:
        super().__init__(toks)
        self.starts = [t.start for t in toks]
        self.by_start = {t.start: t for t in toks}
        self.by_end = {t.end: t for t in toks}


def _starts_word(toks: list[Token], pos: int) -> bool:
    return pos in toks.by_start if isinstance(toks, _Words) else any(t.start == pos for t in toks)


def _words_in(toks: list[Token], start: int, end: int) -> list[Token]:
    if isinstance(toks, _Words):
        i = bisect.bisect_left(toks.starts, start)
        out = []
        while i < len(toks) and toks[i].end <= end:
            out.append(toks[i])
            i += 1
        return out
    return [t for t in toks if t.start >= start and t.end <= end]


def _not_common(toks: list[Token], start: int, end: int) -> bool:
    """The text ``start:end`` is not one or more common nouns of the analyser: a name, a place, a prefix, a word it
    does not know as one piece (百目鬼 reads as 百 目 鬼)."""
    words = _words_in(toks, start, end)
    if not words or words[0].start != start or words[-1].end != end:
        return False  # the run cuts an analyser word: no word of its own
    if len(words) > 1 and not any(w.name for w in words):
        return not all(_common(w) for w in words)
    return any(_proper(w) for w in words) or not all(_common(w) or w.pos[:1] == ("接尾辞",) for w in words)


def _protected_word(word: str) -> bool:
    return (
        word in _NOT_A_NAME_WORDS
        or word in _ROLE_WORDS
        or _NOT_A_NAME.fullmatch(word) is not None
        or _HON_NOT_A_NAME.fullmatch(word) is not None
        or _TERM_WORD.fullmatch(word) is not None
        or word.isdigit()
    )


_ROLE_NO_BEFORE = re.compile(rf"(?:{_alt(CUES['titles_before_name'])})の$")
_LIKE_BEFORE = re.compile(rf"(?:{phi_guard._JA_LIKE})$")
_LATIN_BEFORE = re.compile(r"(?<![A-Za-z'])[A-Za-z][A-Za-z']{1,19}$")
_KANJI_BEFORE = re.compile(f"(?<![{_KANJI}])[{_KANJI}]{{1,4}}$")
_SURNAME_BEFORE = re.compile(f"(?<![{_KANJI}])([{_KANJI}]{{1,4}})[ 　]$")
_HON_KANJI_OK = re.compile(phi_guard._JA_NOT_A_NAME_KANJI)
_L = "A-Za-zＡ-Ｚａ-ｚĀĪŪĒŌāīūēō"
_LATIN_VALUE = re.compile(rf"[{_L}][{_L}']{{1,19}}(?![{_L}'])")
_NEXT_LATIN = re.compile(rf"[ 　]{{1,2}}({_LATIN_VALUE.pattern})")
# These are the English clinical terms already curated for Japanese notes on the box.
with (CUES_FILE.parent / "refdata_src" / "ja_clinical_synonyms.csv").open(encoding="utf-8", newline="") as _terms:
    _CLINICAL_LATIN = {r["canonical"] for r in csv.DictReader(_terms) if r["canonical_lang"] == "en"}
_NON_NAME_LATIN = re.compile(_alt(sorted(_CLINICAL_LATIN | {w for w in _NOT_A_NAME_WORDS if w.isascii()})), re.I)


_REPEAT_PIECE = re.compile(rf"[{_KANJI}]{{2,6}}|[ァ-ヺー]{{3,12}}|[{_L}]{{2,16}}")


def repeat_spans(text: str, names: list[str]) -> list[tuple[int, int]]:
    """The other bare occurrences, in the same note, of a name masked once (河野さんへ。河野は不在。): each word of
    two kanji or more, three katakana or more, or a romaji word, of every name; where it stands as a word of its own
    (no kanji, katakana or letter runs on into it) and not before a term (河野病院 is an institution). Never a word the
    guard says is no name."""
    words = {
        w.group(0)
        for n in set(names)
        for w in _REPEAT_PIECE.finditer(n)
        if not _protected_word(w.group(0)) and not protected_prefix(w.group(0))
    }
    if not words:
        return []
    if any(not (_KANJI_WORD.match(w) or _kata(w)) for w in words):
        # This fold maps one character to one: the original offsets still apply.
        words = {w.translate(_FOLD_LATIN) for w in words}
        text = text.translate(_FOLD_LATIN)
    alts = []
    for w in sorted(words, key=len, reverse=True):
        cls = f"[{_KANJI}]" if _KANJI_WORD.match(w) else "[ァ-ヺー]" if _kata(w) else f"[{_L}]"
        alts.append(rf"(?<!{cls}){re.escape(w)}(?!{cls})")
    return [(m.start(), m.end()) for m in re.finditer("|".join(alts), text) if not _TERM_AFTER.match(text, m.end())]


def not_a_name(span: str) -> bool:
    """A span in a name's place that is none: a word of ``not_a_name_value`` (当直医, 未定, 同上), alone or with a
    word or two of kanji after it (交代予定, 不在中)."""
    value = span.strip()
    return value in _ROLE_WORDS or _NOT_A_NAME_SPAN.fullmatch(value) is not None


_NOT_A_NAME_SPAN = re.compile(
    rf"(?:{_alt(sorted(_NOT_A_NAME_WORDS))})|(?:{_alt([w for w in _NOT_A_NAME_WORDS if len(w) >= 2])})[{_KANJI}]{{1,3}}"
)


def protected_prefix(word: str) -> bool:
    """A kanji word before a name that is no part of it (長女, 主治医, 本日, 患者): ``phi_guard`` keeps a name whole
    (四月一日 君子) but never takes these."""
    return _protected_word(word) or any(_protected_word(word[i:]) for i in range(1, len(word)))


def _before_title(text: str, toks: list[Token]) -> Iterator[tuple[int, int]]:
    """A name directly before a title or an honorific (原先生, 宮崎医師, 坂本さん, 太郎君, はなちゃん, Kimura先生), the
    position deciding, not a list: a kanji run of one to four (and a surname before it after one space), a hiragana
    or katakana name word, a word of Latin letters. Never a role, a relative or a family word (校長先生, 看護師さん,
    お母さん, 赤ちゃん), never a common noun except before 君, くん, ちゃん (太郎君), never inside a word."""
    for m in _TITLE.finditer(text):
        title, p = m.group(0), m.start()
        if p == 0 or not (_starts_word(toks, p) or title in _LATIN_CUES):
            continue
        q = p
        while q > 0 and p - q < 2 and text[q - 1] in " 　":
            q -= 1  # 百目鬼 透 氏, 野村 Dr., Matsuda さん
        if title == "様" and _LIKE_BEFORE.search(text, max(0, q - 12), q):
            continue  # 水様, 感冒様
        br = _BRACKET_BEFORE.search(text, max(0, q - 16), q) if text[q - 1 : q] in ("）", ")") else None
        if br is not None:  # 工藤（くどう）様: the name before its reading in brackets, both masked
            found = _name_before(text, toks, br.start(), title)
            if found is not None:
                yield found[0], q
                continue
            inside = _words_in(toks, br.start() + 1, br.end() - 1)
            kana = _KANA_BEFORE.search(text, max(0, br.start() - 8), br.start())
            if kana is not None and inside and any(w.name for w in inside):
                yield kana.start(), q  # すだ（須田）様: the reading before the name in brackets
                continue
        found = _name_before(text, toks, q, title)
        if found is not None:
            yield found


def _name_before(text: str, toks: list[Token], q: int, title: str) -> tuple[int, int] | None:
    last = text[q - 1 : q]
    lat = _LATIN_BEFORE.search(text, max(0, q - 21), q) if last.isascii() and last.isalpha() else None
    if lat is not None and (title in ("先生", "医師", "さん", "様", "氏", "看護師") or title in _LATIN_CUES):
        if title in _LATIN_CUES and _kana(lat.group(0)) is None:
            return None  # a Latin word before Dr or Ns is a name only in romaji (Nakamura Ns.; never ECG ST)
        s0 = lat.start()
        sur = _SURNAME_BEFORE.search(text, max(0, s0 - 5), s0)
        if sur is not None and not _protected_word(sur.group(1)):
            s0 = sur.start(1)  # 石井 Ishii 様: the name in kanji and in romaji
        return s0, q  # Kimura先生
    if last in _PREFIX_BEFORE_TITLE:
        return None  # 一位老先生, 故先生: the word before the title is a prefix of it
    run = _KANJI_BEFORE.search(text, max(0, q - 4), q) if _KANJI_WORD.match(last) else None
    if run is not None:
        s0 = run.start()
        word = run.group(0)
        if _protected_word(word) or _HON_KANJI_OK.match(text, s0) is None:
            return None
        after_role = title in ("先生", "医師") and _ROLE_NO_BEFORE.search(text, max(0, s0 - 8), s0) is not None
        if not (_not_common(toks, s0, q) or (title in _GIVEN_HON and _starts_word(toks, s0)) or after_role):
            return None  # 前医の平野先生: after a role and の, a name even when 平野 reads as "plain"
        inner = _words_in(toks, s0, q)
        for a, b in itertools.pairwise(inner):
            if a.name == "sei" and not _given_after(a, b, _gap(text, a, b), text):
                return None  # 佐藤錦医師: a cherry, not a name
        sur = _SURNAME_BEFORE.search(text, max(0, s0 - 5), s0)
        if sur is not None and not _protected_word(sur.group(1)):
            s0 = sur.start(1)  # 南 一平先生, 百目鬼 透先生: the surname before the given name
        return s0, q
    w = toks.by_end.get(q) if isinstance(toks, _Words) else next((t for t in toks if t.end == q), None)
    if w is None:
        return None
    if w.name and re.search("[（(]", w.surface):
        return w.start, q  # 工藤（くどう）様: the analyser reads the name and its reading as one word
    if not (_kata(w.surface) or _hira(w.surface)):
        return None
    if _kata(w.surface) and w.name == "person" and title != "様" and _HON_NOT_A_NAME.match(w.surface) is None:
        return w.start, q  # パーキンソンさん: an eponym's word is a person before さん (様 after it means "-like")
    if _protected_word(w.surface) or _HON_NOT_A_NAME.match(w.surface):
        return None
    if _hira(w.surface) and (w.name or (title in _GIVEN_HON and w.noun)) and title in _KANA_HON:
        return w.start, q  # はなちゃん, まなみさん
    if (
        _kata(w.surface)
        and (_proper(w) or not _common(w))
        and (title in ("先生", "医師", "看護師", "氏") or title in _LATIN_CUES)
    ):
        return w.start, q  # the guard's rules take a katakana name before さん and 様 already
    return None


def _after_label(text: str, toks: list[Token]) -> Iterator[tuple[int, int]]:
    """A name after a label (患者：, 氏名, 主治医, 紹介元, 旧姓, キーパーソン, a relative's word with の, a colon or a
    space), a part already masked skipped (患者：＊＊太郎): a word the analyser tags as a name or a proper noun, a
    kanji run of one to four or a katakana word that is not a common noun, a hiragana name word, words of Latin
    letters; then a given name after it. Never a word the guard says is no name (患者：独歩, 患者 意識清明), a common
    noun (主治医の判断), or a word before a term (紹介元：杉野医院)."""
    for m in _LABEL.finditer(text):
        v = m.end()
        ph = _PLACEHOLDER.match(text, v)
        if ph is not None:
            v = ph.end()
        if v >= len(text) or _NOT_A_NAME_VALUE.match(text, v) is None:
            continue
        lat = _LATIN_VALUE.match(text, v)
        if lat is not None:
            word = lat.group()
            if not word[0].isupper() or word in _ROLE_WORDS or _NON_NAME_LATIN.match(text, v):
                continue
            first = toks.by_start.get(v) if isinstance(toks, _Words) else next((t for t in toks if t.start == v), None)
            # Labels also introduce foreign names that have no Japanese reading.
            # An all-capitals value needs independent name evidence (clinical abbreviations).
            if not word.isupper() or _cued_romaji(word) or (first and first.name):
                latin_end = lat.end()
                following = _NEXT_LATIN.match(text, latin_end)
                if (
                    following
                    and following[1][0].isupper()
                    and following[1] not in _ROLE_WORDS
                    and not _NON_NAME_LATIN.match(text, following.start(1))
                ):
                    latin_end = following.end()
                yield v, latin_end
            continue
        first = toks.by_start.get(v) if isinstance(toks, _Words) else next((t for t in toks if t.start == v), None)
        if first is None:
            continue
        end = _value_end(text, toks, first)
        if end is None or _TERM_AFTER.match(text, end):
            continue
        yield v, end


def has_name_cue(text: str) -> bool:
    return bool(_CUE_BEFORE.search(text) or _LABEL.search(text) or _TITLE.search(text))


def latin_cues(text: str) -> list[tuple[int, int]]:
    """Latin titles need no dictionary. Apply the same positional rules as a Japanese line."""
    if not any(cue in text for cue in _LATIN_CUES):
        return []
    return [*_after_cue(text, []), *_before_title(text, [])]


def _after_cue(text: str, toks: list[Token]) -> Iterator[tuple[int, int]]:
    """A name after a title or a role (Dr. 木村, Dr.Kimura, Ns.田村より, 担当OT：宮田, 主治医 は 岡田 です, 看護師　野口
    より), the words from ``ja_name_cues.json``: a word of Latin letters in romaji, or a word as after a label. Never a
    word in a name's place that is none (Dr. 指示, Dr.コール, 担当医：当番医, Ns.より報告)."""
    for m in _CUE_BEFORE.finditer(text):
        v = m.end()
        if v >= len(text) or _NOT_A_NAME_VALUE.match(text, v) is None:
            continue
        lat = _LATIN_VALUE.match(text, v)
        if lat is not None:
            if _cued_romaji(lat.group()) and not _NON_NAME_LATIN.match(text, v):
                yield v, lat.end()
            continue
        first = toks.by_start.get(v) if isinstance(toks, _Words) else next((t for t in toks if t.start == v), None)
        if first is None or first.surface in _NOT_A_NAME_WORDS:
            continue
        end = _value_end(text, toks, first)
        if end is None or _TERM_AFTER.match(text, end) or text[v:end] in _NOT_A_NAME_WORDS:
            continue
        yield v, end


def _cued_romaji(word: str) -> bool:
    return word[0].isupper() and word not in _LATIN_CUES and word.lower() not in _ENGLISH and _kana(word) is not None


_AFTER_AGE_SEX = re.compile(
    rf"[0-9０-９]{{1,3}}[ 　]?(?:歳|才)(?:代)?[ 　]?(?:男性|女性|男児|女児|男|女)?[ 　、,，]{{1,2}}"
    rf"(?P<v>[ァ-ヺー]{{2,8}}[ 　][ァ-ヺー]{{2,8}}|[ｦ-ﾟ]{{2,8}}[ 　][ｦ-ﾟ]{{2,8}}|[{_KANJI}]{{1,4}}[ 　][{_KANJI}]{{1,4}})"
    rf"(?![ァ-ヺーｦ-ﾟ{_KANJI}])"
)
_KANA_BEFORE = re.compile("(?<![ぁ-ゖァ-ヺー])(?:[ぁ-ゖー]{2,8}|[ァ-ヺー]{2,8})$")
_BRACKET_BEFORE = re.compile(rf"[（(][ぁ-ゖァ-ヺーｦ-ﾟ{_KANJI}・ 　]{{1,12}}[）)]$")
_BRACKET_AFTER = re.compile(rf"[ 　]?[（(](?P<in>[ぁ-ゖァ-ヺーｦ-ﾟ{_KANJI}A-Za-z・ 　]{{1,12}})[）)]")


def _after_age_sex(text: str, toks: list[Token]) -> Iterator[tuple[int, int]]:
    """A name of two words after an age and a sex (68歳男性 ツツミ ケンタ, 70歳 女性 見本 花子): katakana, half-width
    katakana or kanji, when not both words are common nouns (70歳女性 アムロジピン ロキソニン stays)."""
    for m in _AFTER_AGE_SEX.finditer(text):
        s0, e0 = m.span("v")
        parts = re.split("[ 　]", m.group("v"))
        if any(_protected_word(p) for p in parts):
            continue
        words = _words_in(toks, s0, e0)
        if words and not all(_common(w) for w in words):
            yield s0, e0


def _with_brackets(text: str, toks: list[Token], s: int, e: int) -> int:
    """A name's end, taking a form or a reading in brackets after it and a given name after that
    (さいとう(斉藤)　まなみ, 須藤（すどう）); never a bracket that holds a role, a relative or a sex
    (山田（主治医）)."""
    m = _BRACKET_AFTER.match(text, e)
    if m is None or _protected_word(m.group("in").strip()) or protected_prefix(m.group("in").strip()):
        return e
    e = m.end()
    gap = _SPACES.match(text, e)
    if gap is None:
        return e
    by_start = toks.by_start if isinstance(toks, _Words) else {t.start: t for t in toks}
    nxt = by_start.get(gap.end())
    given = nxt is not None and (
        nxt.name in ("mei", "person") or (_hira(nxt.surface) and nxt.noun) or _kata(nxt.surface)
    )
    return nxt.end if nxt is not None and given and not _protected_word(nxt.surface) else e


_SPACES = re.compile("[ 　]{1,2}")


def _value_end(text: str, toks: list[Token], first: Token) -> int | None:
    """Where the name after a label ends, or None: the first word is a name (tagged, proper, or a kanji or katakana
    word that is no common noun; never a prefix: 患者：要介護, 父の高血圧) and, with a given name after it, ends where
    a word ends; a word that runs on into more kanji or katakana is part of a compound (長女 山田錦の酒)."""
    s = first.surface
    if _protected_word(s) or (_hira(s) and not first.name) or first.pos[:1] in (("接頭辞",), ("接尾辞",)):
        return None  # 患者：要介護 (a prefix), 担当者：未定 (者 ends the word 担当者)
    named = first.name or (len(first.pos) >= 2 and first.pos[1] == "固有名詞")
    if not (named or ((_KANJI_WORD.fullmatch(s) or _kata(s)) and not _common(first))):
        return None
    end = first.end
    by_start = toks.by_start if isinstance(toks, _Words) else {t.start: t for t in toks}
    nxt = by_start.get(end) or (by_start.get(end + 1) if text[end : end + 1] in (" ", "　") else None)
    if nxt is not None and not _protected_word(nxt.surface):
        g = _gap(text, first, nxt)
        if first.name == "sei" and _given_after(first, nxt, g, text):
            return nxt.end  # the given name after a surname
        if first.name != "sei" and (nxt.name or (_kata(nxt.surface) and _kata(s))) and g is not None:
            return nxt.end
    if end < len(text) and re.match(f"[{_KANJI}ァ-ヺー]", text[end]):
        return None  # the word runs on: a compound, not a name
    return end


_BEFORE_AGE = re.compile(
    rf"(?:^|(?<=[\s、。，,：:；;（(「『【\[/・]))"
    rf"(?P<v>(?:[{_KANJI}]{{1,6}}|[ァ-ヺー]{{2,8}})(?:[ 　](?:[{_KANJI}]{{1,4}}|[ァ-ヺー]{{2,8}}))?)"
    rf"(?={phi_guard._JA_AGE_OR_SEX})"
)


def _nationality(words: list[Token]) -> bool:
    """A nationality or a home (韓国籍, 中国出身, ベトナム人), never a name: the last word is an ending of the cue
    list after a place."""
    last = words[-1].surface
    if len(words) < 2 or not last.endswith(_NOT_A_NAME_ENDING):
        return False
    return last != "人" or (len(words[-2].pos) > 2 and words[-2].pos[2] == "地名")


def _before_age(text: str, toks: list[Token]) -> Iterator[tuple[int, int]]:
    """A name before an age or a sex (スギノ ナオト 52歳, 試 一太 72歳 男性, 渡邊架空子 80歳): a word or two of
    kanji or katakana, starting a line or after punctuation, with a name or a proper noun in it, or no common noun of
    the analyser's. Never a word the guard says is no name (患者 68歳, 長女 40歳), a term (糖尿病 52歳) or common
    nouns (胃癌術後 72歳, カロナール ロキソニン 3歳児)."""
    for m in _BEFORE_AGE.finditer(text):
        s0, e0 = m.span("v")
        parts = re.split("[ 　]", m.group("v"))
        if any(protected_prefix(p) or _protected_word(p) for p in parts):
            continue
        words = _words_in(toks, s0, e0)
        if not words or words[0].start != s0 or words[-1].end != e0:
            continue  # the run cuts an analyser word
        if _nationality(words):
            continue  # 韓国籍 42歳, 中国出身
        if any(w.name or _proper(w) for w in words) or not any(_common(w) for w in words):
            yield s0, e0


# ------------------------------------------------------------------------------------------------ Latin letters
_ROMAJI_SYLLABLE = re.compile(
    r"(?:[kgsztdnhbpmr]y[aueo]|sh[aiueo]|ch[aiueo]|ts[u]|j[aiueo]|f[aiueo]|[kgsztdnhbpmrwy]?[aiueo]h?"
    r"|(?:kk|ss|tt|pp|tch|cch)(?=[aiueoy])|n(?![aiueoy])|n'|ou|uu|oo)",
)
_ROMAJI_WORD = re.compile(rf"(?:{_ROMAJI_SYLLABLE.pattern})+")
_KANA_OF = {
    **dict(zip("aiueo", "アイウエオ", strict=True)),
    **{c + v: k for c, row in {
        "k": "カキクケコ", "g": "ガギグゲゴ", "s": "サシスセソ", "z": "ザジズゼゾ", "t": "タチツテト",
        "d": "ダヂヅデド", "n": "ナニヌネノ", "h": "ハヒフヘホ", "b": "バビブベボ", "p": "パピプペポ",
        "m": "マミムメモ", "r": "ラリルレロ",
    }.items() for v, k in zip("aiueo", row, strict=True)},
    "ya": "ヤ", "yu": "ユ", "yo": "ヨ", "wa": "ワ", "wo": "ヲ", "shi": "シ", "chi": "チ", "tsu": "ツ", "fu": "フ",
    "ji": "ジ", "ja": "ジャ", "ju": "ジュ", "jo": "ジョ", "sha": "シャ", "shu": "シュ", "sho": "ショ", "cha": "チャ",
    "chu": "チュ", "cho": "チョ", "n": "ン", "n'": "ン",
}  # fmt: skip
_ENGLISH_WORDS = (
    "a an and are as at be by do done go he home if in into is it me more name no none note on one or so some same "
    "sure take time to tone up we were made make came come gone mine nine fine line side bone dose nose rose tube "
    "tune cure pure sore core here hare rate date gate late kite site note mode code"
)
_ENGLISH = frozenset(_ENGLISH_WORDS.split())


def _kana(word: str) -> str | None:
    """The katakana of a word in Hepburn romaji (Yamada -> ヤマダ, Saito -> サイト), or None when it is none."""
    w = word.lower().translate(_FOLD_LATIN)
    if _ROMAJI_WORD.fullmatch(w) is None:
        return None
    out, i = [], 0
    while i < len(w):
        if i + 1 < len(w) and w[i] == w[i + 1] and w[i] not in "aiueon":
            out.append("ッ")
            i += 1
            continue
        if w[i] == "h" and i > 0 and w[i - 1] in "aiueo" and (i + 1 == len(w) or w[i + 1] not in "aiueoy"):
            i += 1  # Ohno, Ohta: a long vowel
            continue
        for size in (3, 2, 1):
            piece = w[i : i + size]
            if piece in _KANA_OF and not (piece == "n" and i + 1 < len(w) and w[i + 1] in "aiueoy"):
                out.append(_KANA_OF[piece])
                i += size
                break
            if size == 3 and w[i : i + 2] in ("ky", "gy", "ny", "hy", "by", "py", "my", "ry") and i + 2 < len(w):
                base = _KANA_OF.get(w[i] + "i")
                small = {"a": "ャ", "u": "ュ", "o": "ョ"}.get(w[i + 2])
                if base and small:
                    out.append(base + small)
                    i += 3
                    break
        else:
            return None
    return "".join(out)


_FOLD_LATIN = str.maketrans(
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚāīūēōĀĪŪĒŌ",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzaiueoAIUEO",
)


def _fold_long(kana: str) -> str:
    """Long vowels written or not (Sato, Satou, Satoh are サトウ; Ota, Oota are オオタ): compared without them."""
    return re.sub("(?<=[オコソトノホモヨロゴゾドボポョ])[ウオ]|(?<=[ウクスツヌフムユルグズブプュ])ウ", "", kana)


_LISTED_FOLDED = frozenset(_fold_long(k) for k in phi_guard.JP_SURNAMES_KANA)


def _surname_reading(kana: str, an: Analyser | None) -> bool:
    """A surname by its reading: one of the guard's listed surnames, or (with the analyser) a word it tags 姓."""
    if _fold_long(kana) in _LISTED_FOLDED:
        return True
    if an is None or len(kana) < 2:
        return False
    return _reading_is_sei(an, kana)


_SEI_CACHE: dict[tuple[int, str], bool] = {}
_SEI_CACHE_MAX = 4096


def _reading_is_sei(an: Analyser, kana: str) -> bool:
    key = (id(an), kana)
    if key not in _SEI_CACHE:
        if len(_SEI_CACHE) >= _SEI_CACHE_MAX:
            _SEI_CACHE.clear()  # bounded: a note of many words never grows it without end
        words = an.tokens(kana)
        _SEI_CACHE[key] = len(words) == 1 and words[0].name == "sei"
    return _SEI_CACHE[key]


_LINE_BREAK = r"[ \t　]*\r?\n[ \t　]*"
_LATIN_PAIR = re.compile(
    rf"(?<![{_L}'])(?=([{_L}]{{2,12}})(?:[ \t　]{{1,2}}|{_LINE_BREAK})([{_L}]{{2,12}})(?![{_L}']))"
)


def _case_ok(a: str, b: str) -> bool:
    """A name's two words are written alike or as a name is (Taro Yamada, YAMADA Taro, hanako sato), never as a
    sentence (Taking ono)."""

    def shape(w: str) -> str:
        return "U" if w.isupper() else "T" if w[0].isupper() and w[1:].islower() else "L" if w.islower() else "?"

    return (shape(a), shape(b)) in {("T", "T"), ("U", "U"), ("L", "L"), ("U", "T"), ("T", "U")}


def romaji_spans(text: str, an: Analyser | None = None) -> list[tuple[int, int]]:
    """Two words of Latin letters that read as a Japanese name: both are Hepburn romaji, one is a surname by its
    reading (the guard's listed surnames; with the analyser, any word it tags 姓), written as a name is (Taro Yamada,
    YAMADA Taro, hanako sato, ＹＡＭＡＤＡ　Ｔａｒｏ), a common English word needs name case and a separate surname."""
    out = []
    for m in _LATIN_PAIR.finditer(text):
        a, b = m.group(1), m.group(2)
        fa, fb = a.translate(_FOLD_LATIN), b.translate(_FOLD_LATIN)
        if not _case_ok(fa, fb) or a in _LATIN_CUES or b in _LATIN_CUES:
            continue
        ka, kb = _kana(fa), _kana(fb)
        if ka is None or kb is None:
            continue
        # Common English words in running text are weak evidence. In name case a
        # separate, confirmed surname supplies the evidence (Go Sato).
        english_a, english_b = fa.lower() in _ENGLISH, fb.lower() in _ENGLISH
        if (english_a or english_b) and not (fa[0].isupper() and fb[0].isupper()):
            continue
        if (not english_a and _surname_reading(ka, an)) or (not english_b and _surname_reading(kb, an)):
            out.append((m.start(1), m.end(2)))
    return out


# ------------------------------------------------------------------------------------------------ the whole rule
def _retag(toks: list[Token], an: Analyser) -> list[Token]:
    """A hiragana noun of three characters or more that the analyser does not tag, read as a surname when its
    katakana form is one (さいとう: サイトウ is tagged 姓)."""
    out = []
    for t in toks:
        if not t.name and t.noun and _hira(t.surface) and len(t.surface) >= 3:
            kana = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in t.surface)
            if _surname_reading(kana, an):
                t = Token(t.surface, t.start, t.end, ("名詞", "固有名詞", "人名", "姓"))
        out.append(t)
    return out


_WRAPPED = re.compile(
    rf"(?<![{_KANJI}ァ-ヺぁ-ゖー])(?=([{_KANJI}ァ-ヺぁ-ゖー]{{1,8}}){_LINE_BREAK}"
    rf"([{_KANJI}ァ-ヺぁ-ゖー]{{1,8}})(?![{_KANJI}ァ-ヺぁ-ゖー]))"
)


def name_spans(
    text: str, an: Analyser, *, protect: bool = True, japanese: bool | None = None, cued: bool = False
) -> list[tuple[int, int]]:
    """``(start, end)`` of every person name the rule takes from the analyser's tags, the positions beside titles and
    labels, and Latin letters. ``japanese``: the caller knows the text is Japanese (the guard decides from the site's
    note language and the text, ``phi_guard.japanese_names``); None: only a text with kana or 歳 is read.
    ``protect=False``: every word the analyser tags as a person name, with no rule (what the analyser alone would mask,
    to show what the rule does). ``cued``: only a name beside a cue (a title or an honorific after it, a label or a role
    before it), never one on the analyser's tags or an age alone (a kana-free note at a site of unknown language)."""
    if not protect:
        return [
            (o + t.start, o + t.end) for o, piece in _pieces(text) if piece.strip() for t in an.tokens(piece) if t.name
        ]
    if not (japanese if japanese is not None else _JAPANESE.search(text) is not None):
        return []
    out: list[tuple[int, int]] = []
    for offset, piece in _pieces(text):
        if not piece.strip():
            continue
        key = (id(an), cued, piece)
        if key not in _PIECE_CACHE:
            if len(_PIECE_CACHE) >= _PIECE_CACHE_MAX:
                _PIECE_CACHE.clear()  # bounded, as the reading cache
            _PIECE_CACHE[key] = _piece_spans(piece, an, cued)
        out.extend((offset + s, offset + e) for s, e in _PIECE_CACHE[key])
    if "\n" in text and not cued:
        out.extend(romaji_spans(text, an))
        for m in _WRAPPED.finditer(text):
            joined = " ".join(m.groups())
            if (0, len(joined)) in _piece_spans(joined, an):
                out.append((m.start(1), m.end(2)))
    return sorted(set(out))


#: a line read once is not read again (a template line, a note's repeated header): bounded
_PIECE_CACHE: dict[tuple[int, bool, str], list[tuple[int, int]]] = {}
_PIECE_CACHE_MAX = 1024


def _piece_spans(piece: str, an: Analyser, cued: bool = False) -> list[tuple[int, int]]:
    """The names of one piece of text (a line, or a part of a long one), relative to the piece; ``cued``: only those
    beside a cue (:func:`name_spans`)."""
    toks = _Words(_retag([t for t in an.tokens(piece) if t.surface not in _DOT], an))
    found = [*_before_title(piece, toks), *_after_label(piece, toks), *_after_cue(piece, toks)]
    if cued:
        return sorted({(s, _with_brackets(piece, toks, s, e)) for s, e in found})
    out = [
        (s, _with_brackets(piece, toks, s, e))
        for s, e, words, run_end in _proposals(piece, toks)
        if not _protected(piece, s, e, words, run_end)
    ]
    found += [*_before_age(piece, toks), *_after_age_sex(piece, toks), *romaji_spans(piece, an)]
    out += [(s, _with_brackets(piece, toks, s, e)) for s, e in found]
    return sorted(set(out))


_ENABLED: dict[str, list[Callable[[str], Any]]] = {}


def enable(an: Analyser) -> None:
    """Put ``an`` in the guard's place (``phi_guard.NAME_RECOGNISERS``), for a test or a measurement: the guard then
    reads names with ``an`` alone. :func:`disable` puts back what was there."""
    saved = _ENABLED.get("saved", list(phi_guard.NAME_RECOGNISERS))
    _ENABLED["saved"] = saved
    phi_guard.NAME_RECOGNISERS[:] = [lambda text: name_spans(text, an)]


def disable() -> None:
    saved = _ENABLED.pop("saved", None)
    if saved is not None:
        phi_guard.NAME_RECOGNISERS[:] = saved
