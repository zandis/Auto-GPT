"""core_words: the twenty core words have one spelling per language (card 9k-16, review 09 DS-16, D-1371).

    python -m tools.core_words           # exit 1 on a refused spelling; `python -m tools.text_keys` runs the same

The words are data, ``services/console/core_words.yaml``: per word an id, the one spelling in en, ja and zh-TW, the
spellings refused for it, and the longer correct phrases (``allowed``) that contain a refused spelling. This module
reads that file, checks its shape (twenty words, three languages each, no word refusing another's spelling) and
reads every console catalogue string (``tools.text_keys.definitions``: every definition where it is written, the
loser of an override included) for a refused spelling. Each finding names the key, the language, the place, the
spelling found and the one to write.

It also reads the catalogues of user-visible text outside the console's i18n modules (``SERVICE_CATALOGUES``: the
refusal sentences, the job mails with the report and PDF titles, the eligibility sheet, the opportunity board and
the site-setup sheet's help), from the source with ``ast`` only.

Matching: every text and every spelling is first folded to NFKC, so a full-width or half-width form (ｽﾎﾟﾝｻｰ,
ｅｎｒｏｌｌ) is the same as the plain one. en is matched as whole words, ignoring case, a plural ``s``/``es`` included and
a hyphen counting as a word boundary (``Sub-Is``, ``re-enroll`` and ``enrollment-based`` are found; ``enrolled`` and
``sub-investigator`` are not); ja and zh-TW anywhere in the text, since they have no spaces. Before a word's refused spellings are looked for, its own spelling and its
``allowed`` phrases are masked, so a refused spelling inside the right one (授權紀錄 inside 授權紀錄表) or inside a
listed phrase (篩檢 inside 預篩檢查) is not a finding. The longest refused spelling is looked for first and masked
when found, so 責任分担表 is one finding, not two.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import unicodedata
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
#: user-visible text outside the console's i18n modules (``tools.text_keys`` reads those). Not read, and why: the
#: command palette's search words (``services/console/command.py``: what a user may type, the refused spellings on
#: purpose), the stub model's canned answers (``services/llm_stub``: test data, never shown), the detection lists
#: (``libs/tb_common/wording.py``, ``phi_guard.py``, ``services/guard``: words looked for, not shown) and the e2e walk
#: plans' step texts (test prose).
SERVICE_CATALOGUES = (
    "services/console/refusals.py",
    "services/orchestrator/i18n.py",
    "services/orchestrator/reports/case_html.py",
    "services/opportunity_hub/dashboard.py",
    "services/sitesetup/help.py",
)


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


@dataclass(frozen=True)
class ServiceText:
    """A text of one of the ``SERVICE_CATALOGUES``, shaped like a catalogue definition."""

    lang: str
    key: str
    text: str
    where: str


def load(path: Path = DATA) -> dict[str, Any]:
    """The data file as a mapping; ``ValueError`` with one plain line when it cannot be read, is empty, is not YAML
    or is not a mapping."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"{path.name}: cannot be read ({e.strerror or e})") from None
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        at = f" at line {mark.line + 1}" if mark is not None else ""
        why = getattr(e, "problem", None) or type(e).__name__
        raise ValueError(f"{path.name}: not valid YAML{at} ({why})") from None
    if data is None:
        raise ValueError(f"{path.name}: the file is empty")
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: not a mapping")
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
            lists: dict[str, list[str]] = {}
            for field in ("refused", "allowed"):
                vals = entry.get(field, [])
                if not isinstance(vals, list) or not all(isinstance(v, str) and v for v in vals):
                    out.append(f"core_words.yaml {wid} {lang}: {field} must be a list of spellings")
                    vals = []
                lists[field] = vals
            refused = lists["refused"]
            for v in refused:
                if _fold(v).casefold() == _fold(entry["spelling"]).casefold():
                    out.append(f"core_words.yaml {wid} {lang}: refuses its own spelling {v!r}")
            for a in lists["allowed"]:
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


def _fold(text: str) -> str:
    """NFKC: a full-width or half-width form (ｽﾎﾟﾝｻｰ, ｅｎｒｏｌｌ) compares as the plain one."""
    return unicodedata.normalize("NFKC", text)


def _pattern(lang: str, phrase: str) -> re.Pattern[str]:
    phrase = _fold(phrase)
    if lang == "en":
        # a whole word: a hyphen is a boundary (re-enroll, enrollment-based), a plural ending belongs to it (Sub-Is)
        return re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?:e?s)?(?!\w)", re.IGNORECASE)
    return re.compile(re.escape(phrase))


def _find(lang: str, phrase: str, text: str) -> bool:
    return bool(_pattern(lang, phrase).search(_fold(text)))


def _masked(lang: str, text: str, phrases: Iterable[str]) -> str:
    text = _fold(text)
    for p in sorted(phrases, key=lambda p: len(_fold(p)), reverse=True):
        text = _pattern(lang, p).sub(lambda m: _MASK * len(m.group(0)), text)
    return text


def found_in(sp: Spelling, text: str) -> list[str]:
    """The refused spellings of one word in one text (longest first, each masked when found), as found after the
    NFKC fold."""
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


def _module_texts(rel: str, tree: ast.Module) -> list[ServiceText]:
    """The texts of one module: every module-level ``NAME = {"en": ..., "ja": ..., "zh-TW": ...}`` whose values are a
    text or a ``{key: text}`` dict, and ``REFUSALS`` (English sentence -> (Japanese, Chinese)). Literals only, read
    with ``ast.literal_eval``; a value that is not a literal is not read."""

    def lit(node: ast.expr) -> Any:
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            return None

    out: list[ServiceText] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target, value = stmt.target, stmt.value
        else:
            continue
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Dict):
            continue
        name = target.id
        keys = [lit(k) if k is not None else None for k in value.keys]
        if name == "REFUSALS":
            for k, v in zip(value.keys, value.values, strict=True):
                en, pair = lit(k) if k is not None else None, lit(v)
                if not isinstance(en, str) or not (isinstance(pair, tuple) and len(pair) == 2):
                    continue
                key = f"REFUSALS[{en!r}]"
                out.append(ServiceText("en", key, en, f"{rel}:{k.lineno}" if k is not None else rel))
                out += [ServiceText(lang, key, t, f"{rel}:{v.lineno}") for lang, t in zip(("ja", "zh-TW"), pair, strict=True)]
            continue
        if len(keys) < 2 or not all(isinstance(k, str) and k in LANGS for k in keys):
            continue
        for lang, v in zip(keys, value.values, strict=True):
            if isinstance(v, ast.Dict):
                for kk, vv in zip(v.keys, v.values, strict=True):
                    key, text = (lit(kk) if kk is not None else None), lit(vv)
                    if isinstance(key, str) and isinstance(text, str):
                        out.append(ServiceText(lang, f"{name}.{key}", text, f"{rel}:{vv.lineno}"))
            elif isinstance(text := lit(v), str):
                out.append(ServiceText(lang, name, text, f"{rel}:{v.lineno}"))
    return out


def service_texts(paths: Iterable[str] = SERVICE_CATALOGUES, root: Path = ROOT) -> list[ServiceText]:
    """Every text of the ``SERVICE_CATALOGUES`` (read from the source, no code runs)."""
    out: list[ServiceText] = []
    for rel in paths:
        out += _module_texts(rel, ast.parse((root / rel).read_text(encoding="utf-8")))
    return out


def problems(texts: Iterable[Text] | None = None, *, path: Path = DATA, services: bool = True) -> list[str]:
    """The data file's problems (one plain line each: unreadable, empty, not YAML, a wrong shape), else every refused
    spelling in the console's catalogues (``texts``, else every ``tools.text_keys`` definition) and, with
    ``services``, in the ``SERVICE_CATALOGUES``."""
    try:
        data = load(path)
    except ValueError as e:
        return [f"core_words: {e}"]
    bad = shape(data)
    if bad:
        return bad
    if texts is None:
        from tools.text_keys import definitions

        texts = definitions()
    rows: list[Text] = list(texts)
    if services:
        rows += service_texts()
    return [str(r) for r in refused(rows, data)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.core_words", description=__doc__.split("\n")[0])
    ap.add_argument("--data", type=Path, default=DATA, help="the data file (default: services/console/core_words.yaml)")
    args = ap.parse_args(argv)
    found = problems(path=args.data)
    for p in found:
        print(p)
    print(f"core_words: {len(found)} problem(s)", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
