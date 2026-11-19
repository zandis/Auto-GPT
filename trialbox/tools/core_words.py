"""core_words: the twenty core words have one spelling per language (card 9k-16, review 09 DS-16, D-1371).

    python -m tools.core_words           # exit 1 on a refused spelling; `python -m tools.text_keys` runs the same

The words are data, ``services/console/core_words.yaml``: per word an id, the one spelling in en, ja and zh-TW, the
spellings refused for it, and the longer correct phrases (``allowed``) that contain a refused spelling. This module
reads that file, checks its shape (twenty words, three languages each, no word refusing another's spelling) and
reads every console catalogue string (``tools.text_keys.definitions``: every definition where it is written, the
loser of an override included) for a refused spelling. Each finding names the key, the language, the place, the
spelling found and the one to write.

Matching: en as whole words, ignoring case (``enroll`` is refused, ``enrolled`` is not); ja and zh-TW anywhere in the
text, since they have no spaces. Before a word's refused spellings are looked for, its own spelling and its
``allowed`` phrases are masked, so a refused spelling inside the right one (授權紀錄 inside 授權紀錄表) or inside a
listed phrase (篩檢 inside 預篩檢查) is not a finding. The longest refused spelling is looked for first and masked
when found, so 責任分担表 is one finding, not two.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "services" / "console" / "core_words.yaml"
LANGS = ("en", "ja", "zh-TW")
COUNT = 20  # review 09 section 1.6: twenty core words
_MASK = "\x00"


class Text(Protocol):
    """A catalogue string as ``tools.text_keys.Definition`` gives it."""

    @property
    def lang(self) -> str: ...
    @property
    def key(self) -> str: ...
    @property
    def text(self) -> str: ...
    @property
    def where(self) -> str: ...


@dataclass(frozen=True)
class Spelling:
    word: str  # the word's id
    lang: str
    spelling: str
    refused: tuple[str, ...]
    allowed: tuple[str, ...]


@dataclass(frozen=True)
class Refused:
    lang: str
    key: str
    where: str
    word: str
    found: str
    spelling: str

    def __str__(self) -> str:
        return (
            f"refused spelling {self.lang} {self.key} at {self.where}: {self.found!r} is not the core word "
            f"{self.word!r}; write {self.spelling!r} (services/console/core_words.yaml)"
        )


def load(path: Path = DATA) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a mapping")
    return data


def shape(data: Mapping[str, Any]) -> list[str]:
    """What is wrong with the data file's shape: an empty list when it is right."""
    out: list[str] = []
    words = data.get("words")
    if data.get("version") != 1 or not isinstance(words, list):
        return ["core_words.yaml: needs version 1 and a list of words"]
    if len(words) != COUNT:
        out.append(f"core_words.yaml: {len(words)} words, not {COUNT}")
    ids = [w.get("id") if isinstance(w, dict) else None for w in words]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
        out.append("core_words.yaml: every word needs an id of its own")
    for w in words:
        if not isinstance(w, dict):
            out.append(f"core_words.yaml: {w!r} is not a word")
            continue
        wid = w.get("id")
        if not isinstance(w.get("concept"), str) or not w["concept"]:
            out.append(f"core_words.yaml {wid}: no concept")
        if not isinstance(w.get("read_by_native_reader"), bool):
            out.append(f"core_words.yaml {wid}: read_by_native_reader must be true or false")
        for lang in LANGS:
            entry = w.get(lang)
            if not isinstance(entry, dict) or not isinstance(entry.get("spelling"), str) or not entry["spelling"]:
                out.append(f"core_words.yaml {wid} {lang}: no spelling")
                continue
            unknown = sorted(set(entry) - {"spelling", "refused", "allowed"})
            if unknown:
                out.append(f"core_words.yaml {wid} {lang}: unknown fields {unknown}")
            for field in ("refused", "allowed"):
                vals = entry.get(field, [])
                if not isinstance(vals, list) or not all(isinstance(v, str) and v for v in vals):
                    out.append(f"core_words.yaml {wid} {lang}: {field} must be a list of spellings")
            refused = [v for v in entry.get("refused", []) if isinstance(v, str)]
            for v in refused:
                if v.casefold() == entry["spelling"].casefold():
                    out.append(f"core_words.yaml {wid} {lang}: refuses its own spelling {v!r}")
            for a in entry.get("allowed", []) if isinstance(entry.get("allowed", []), list) else []:
                if not any(_find(lang, v, a) for v in refused):
                    out.append(f"core_words.yaml {wid} {lang}: allowed {a!r} holds none of its refused spellings")
    if out:
        return out
    # another word's own spelling must never be a finding: a refused spelling inside it needs an `allowed` phrase
    for sp in spellings(data):
        for other in spellings(data):
            if other.lang == sp.lang and other.word != sp.word:
                for v in sp.refused:
                    if _find(sp.lang, v, _masked(sp.lang, other.spelling, (sp.spelling, *sp.allowed))):
                        out.append(
                            f"core_words.yaml {sp.word} {sp.lang}: refuses {v!r}, found in {other.word}'s spelling "
                            f"{other.spelling!r}"
                        )
    return out


def spellings(data: Mapping[str, Any]) -> list[Spelling]:
    return [
        Spelling(
            w["id"],
            lang,
            w[lang]["spelling"],
            tuple(sorted(w[lang].get("refused", []), key=len, reverse=True)),
            tuple(w[lang].get("allowed", [])),
        )
        for w in data["words"]
        for lang in LANGS
    ]


def _pattern(lang: str, phrase: str) -> re.Pattern[str]:
    if lang == "en":
        return re.compile(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", re.IGNORECASE)
    return re.compile(re.escape(phrase))


def _find(lang: str, phrase: str, text: str) -> bool:
    return bool(_pattern(lang, phrase).search(text))


def _masked(lang: str, text: str, phrases: Iterable[str]) -> str:
    for p in sorted(phrases, key=len, reverse=True):
        text = _pattern(lang, p).sub(lambda m: _MASK * len(m.group(0)), text)
    return text


def found_in(sp: Spelling, text: str) -> list[str]:
    """The refused spellings of one word in one text (longest first, each masked when found)."""
    text = _masked(sp.lang, text, (sp.spelling, *sp.allowed))
    out = []
    for v in sp.refused:
        rx = _pattern(sp.lang, v)
        hits = [m.group(0) for m in rx.finditer(text)]
        if hits:
            out.append(hits[0])
            text = rx.sub(lambda m: _MASK * len(m.group(0)), text)
    return out


def refused(texts: Iterable[Text], data: Mapping[str, Any] | None = None) -> list[Refused]:
    """Every refused spelling of a core word in the given catalogue strings."""
    data = data if data is not None else load()
    by_lang: dict[str, list[Spelling]] = {lang: [] for lang in LANGS}
    for sp in spellings(data):
        if sp.refused:
            by_lang[sp.lang].append(sp)
    out: list[Refused] = []
    for d in texts:
        for sp in by_lang.get(d.lang, []):
            out += [Refused(d.lang, d.key, d.where, sp.word, f, sp.spelling) for f in found_in(sp, d.text)]
    return out


def problems(texts: Iterable[Text] | None = None) -> list[str]:
    """The data file's shape problems, else every refused spelling in the console's catalogues."""
    data = load()
    bad = shape(data)
    if bad:
        return bad
    if texts is None:
        from tools.text_keys import definitions

        texts = definitions()
    return [str(r) for r in refused(texts, data)]


def main(argv: list[str] | None = None) -> int:
    found = problems()
    for p in found:
        print(p)
    print(f"core_words: {len(found)} problem(s)", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
