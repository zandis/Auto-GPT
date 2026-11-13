"""Does a NAME finding of the tripwire stand? (NEW-LLM-4, D-647; the owner's choice of 2026-11-13: "B".)

The name recognisers are patterns: a surname, one to three more characters, and a cue beside them (a label, an
honorific, a sex). In running Japanese that shape is everywhere (患者 高血圧の…, 患者連絡…), so the tripwire
refused 72.7 % of a set of ordinary Japanese sentences. This module is a second look at a finding **on a line that
holds kana**. It can only take such a NAME finding away, and only when all of this holds:

* the tokeniser (SudachiPy, split mode C, the pinned dictionary: :data:`DICTIONARY`) tags no token inside the
  match as a proper noun;
* no cue stands beside it: an honorific inside the match or right after it, a sex after it, a surname of more
  than one character;
* the match is plainly Japanese text: one word of the tokeniser's own dictionary, longer than one character,
  covers the match from the surname's place to its end (高血圧, 連絡), or the match itself holds kana (何かを).

Everything else stands as before this card: every finding on a line without kana (so **Chinese text is judged
exactly as before**), every other kind of finding, a name the dictionary does not know, a Chinese name beside a
Japanese drug name (丁子｜涵: 丁子 is a word, but it does not cover the name).

**It fails closed**: when the tokeniser or its dictionary cannot be loaded, raises, or the line is longer than
:data:`MAX_LINE`, the finding stands; :func:`status` says which, for ``doctor``. What was measured, and the wider
rule that was measured and not taken, are in D-647.
"""

from __future__ import annotations

import importlib
import re
import threading
from typing import Any

from tb_common import phi_guard

#: the dictionary the figures of D-647 were measured with; another one is a re-measurement
DICTIONARY = "sudachidict-core 20261015"
#: a line longer than this is not put to the tokeniser: the finding stands. A note line or a criterion is a few
#: hundred characters; one this long is not prose, and the tokeniser's time grows with the line
MAX_LINE = 4000

# kana that says "this line is Japanese": not the middle dot and the double hyphen (punctuation), not the long
# vowel mark alone (it follows kana)
_KANA = re.compile(r"[ぁ-ゟァ-ヺヽ-ヿ]")
_HONORIFIC = re.compile(phi_guard.HONORIFIC)
_FOLLOW = re.compile(rf"^\s?(?:{phi_guard.HONORIFIC}|[，,、\s]*[（(]?(?:男|女)[)）]?)")
_PROPER = "固有名詞"
# a surname of more than one character says "name" by itself: the compound Chinese ones, the Japanese ones
_LONG_SURNAMES = tuple(
    sorted(phi_guard.ROC_COMPOUND | {x for x in phi_guard.JP_SURNAMES if len(x) > 1}, key=len, reverse=True)
)


def _cue(text: str, start: int, end: int) -> bool:
    """What says "a name" whatever the words around it: an honorific inside the match or right after it, a sex
    after it, a surname of more than one character."""
    found = text[start:end]
    return bool(_HONORIFIC.search(found) or _FOLLOW.match(text[end:]) or found.startswith(_LONG_SURNAMES))


class _Tagger:
    """SudachiPy with its dictionary, loaded once, on first use. ``error``: why it is not there, or what its last
    failure was (``failed``: it has failed on a text since it was loaded)."""

    def __init__(self) -> None:
        self.error = ""
        self.failed = False
        self._tok: Any = None
        self._mode: Any = None
        self._lock = threading.Lock()
        self._tried = False

    def load(self) -> bool:
        with self._lock:
            if not self._tried:
                self._tried = True
                try:
                    dictionary = importlib.import_module("sudachipy.dictionary")
                    tokenizer = importlib.import_module("sudachipy.tokenizer")
                    self._tok = dictionary.Dictionary().create()
                    self._mode = tokenizer.Tokenizer.SplitMode.C
                except Exception as exc:  # not installed, no dictionary, a dictionary of another format
                    self.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        return self._tok is not None

    def tokens(self, line: str) -> list[tuple[int, int, str]] | None:
        """The tokens of ``line`` as (start, end, kind): ``proper`` (tagged a proper noun), ``word`` (another word
        of the dictionary) or ``unknown`` (not in the dictionary); None: could not be told."""
        if not self.load():
            return None
        try:
            with self._lock:  # one tokeniser object; the gateway calls from several threads
                return [
                    (
                        m.begin(),
                        m.end(),
                        "proper" if m.part_of_speech()[1] == _PROPER else "unknown" if m.is_oov() else "word",
                    )
                    for m in self._tok.tokenize(line, self._mode)
                ]
        except Exception as exc:
            # the exception's type only: its text may quote the line
            self.error, self.failed = f"{type(exc).__name__} while tokenising a line", True
            return None


_TAGGER = _Tagger()


def _line(text: str, start: int, end: int) -> tuple[str, int, int]:
    a = max(text.rfind("\n", 0, start), text.rfind("\r", 0, start)) + 1
    ends = [x for x in (text.find("\n", end), text.find("\r", end)) if x >= 0]
    b = min(ends) if ends else len(text)
    return text[a:b], start - a, end - a


class Look:
    """The second look of one tripwire call: each line is put to the tokeniser once, and nothing of the text is
    kept after the call."""

    def __init__(self) -> None:
        self._tagged: dict[str, list[tuple[int, int, str]] | None] = {}

    def stands(self, text: str, start: int, end: int) -> bool:
        """Whether the NAME finding ``text[start:end]`` stands. Never raises: whatever goes wrong, it stands."""
        try:
            line, s, e = _line(text, start, end)
            if not _KANA.search(line) or len(line) > MAX_LINE:
                return True  # Chinese, and any line without kana: exactly as before this card
            if line not in self._tagged:
                self._tagged[line] = _TAGGER.tokens(line)
            tokens = self._tagged[line]
            if tokens is None or any(kind == "proper" for b, x, kind in tokens if b < e and x > s):
                return True
            if _cue(text, start, end):
                return True
            covered = any(b <= s and x >= e for b, x, kind in tokens if kind == "word" and x - b > 1)
            return not (covered or _KANA.search(line[s:e]))
        except Exception:
            return True


def stands(text: str, start: int, end: int) -> bool:
    """:meth:`Look.stands` for one finding."""
    return Look().stands(text, start, end)


def status() -> dict[str, Any]:
    """For ``doctor``: is the Japanese tokeniser there and working?"""
    ok = _TAGGER.load() and not _TAGGER.failed
    return {
        "tokeniser": ok,
        "dictionary": DICTIONARY,
        "error": _TAGGER.error,
        "effect": ""
        if ok
        else "name findings the second look cannot check stand: more ordinary Japanese text is refused, "
        "none is let through",
    }


__all__ = ["DICTIONARY", "MAX_LINE", "Look", "stands", "status"]
