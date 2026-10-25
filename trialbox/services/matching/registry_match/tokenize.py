"""Sentence and word tokenizers: NLTK's (what NCBI used) when it and its ``punkt`` data are installed, else a small
regular-expression fallback.

The fallback keeps the package usable without NLTK (unit tests, a box without the extra), but sentence numbering and
BM25 tokens can then differ slightly from NCBI's, so benchmark runs record :data:`BACKEND` and only ``nltk`` runs are
comparable with the paper.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable
from typing import Any

_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_WORD = re.compile(r"\w+(?:[-']\w+)*|[^\w\s]", re.UNICODE)


def _regex_sent_tokenize(text: str) -> list[str]:
    return [s.strip() for s in _SENT_END.split(text.strip()) if s.strip()]


def _regex_word_tokenize(text: str) -> list[str]:
    return _WORD.findall(text)


def _load() -> tuple[str, Callable[[str], list[str]], Callable[[str], list[str]]]:
    try:
        nltk: Any = importlib.import_module("nltk.tokenize")
        nltk.sent_tokenize("Probe. Sentence.")  # raises LookupError when the punkt data is missing
        nltk.word_tokenize("probe")
    except (ImportError, LookupError):
        return "regex", _regex_sent_tokenize, _regex_word_tokenize
    return "nltk", nltk.sent_tokenize, nltk.word_tokenize


BACKEND, sent_tokenize, word_tokenize = _load()
