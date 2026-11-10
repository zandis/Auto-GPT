"""Criterion labels, criterion text and to-dos that a ruleset ships in the site's languages (T-507, D-309).

A PoC ruleset carries ``rulesets/<id>/labels.yaml``: per criterion the protocol's own text (``source``), the to-do it
writes (``todo_source``, the IR's ``action``) and, per language, a short ``label``, the ``text`` and the ``todo``.
A translation is used only while the approved criterion still has exactly the ``source`` text (whitespace aside), so
an amended criterion falls back to the protocol's words until someone gives it a label again (the approval page asks
for one, D-309). A label the site gives at approval (D-120) wins over the shipped one.

The file is read from the box's rulesets folder first and, when that copy has none (an approved version written by
the compiler), from the rulesets that ship with the product.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SHIPPED = Path(__file__).resolve().parents[2] / "rulesets"
LANGS = ("en", "ja", "zh-TW")
_ID = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,63}$")


def same(a: object, b: object) -> bool:
    """The same protocol words, whitespace aside."""
    return " ".join(str(a or "").split()) == " ".join(str(b or "").split())


@lru_cache(maxsize=64)
def _read(path: Path, mtime: float) -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, dict[str, Any]] = {}
    for cid, entry in (data.get("criteria") or {}).items():
        if isinstance(entry, dict) and _ID.match(str(cid)):
            out[str(cid)] = entry
    return out


def shipped(ruleset: str, rulesets_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """The ruleset's ``labels.yaml`` entries by criterion id; empty when the ruleset ships none."""
    rid = ruleset.strip().upper()
    if not _ID.match(rid):
        return {}
    for base in (rulesets_dir, SHIPPED):
        if base is None:
            continue
        path = base / rid / "labels.yaml"
        if path.is_file():
            return _read(path, path.stat().st_mtime)
    return {}


def words(entry: dict[str, Any] | None, text: str, action: str = "") -> dict[str, dict[str, str]]:
    """Per language, the label, text and to-do of one criterion whose protocol text is ``text``; nothing when the
    entry was written for other words (the criterion changed since)."""
    if not entry or not same(entry.get("source"), text):
        return {}
    out: dict[str, dict[str, str]] = {}
    for lang in LANGS:
        tr = entry.get(lang)
        if not isinstance(tr, dict):
            continue
        got = {k: " ".join(str(tr.get(k) or "").split()) for k in ("label", "text")}
        if tr.get("todo") and action and same(entry.get("todo_source"), action):
            got["todo"] = " ".join(str(tr["todo"]).split())
        got = {k: v for k, v in got.items() if v}
        if got:
            out[lang] = got
    return out


def labels_for(ruleset: str, lang: str, texts: dict[str, str], rulesets_dir: Path | None = None) -> dict[str, str]:
    """The shipped short label in ``lang`` of each criterion whose current text is ``texts[id]``."""
    entries = shipped(ruleset, rulesets_dir)
    out = {}
    for cid, text in texts.items():
        label = words(entries.get(cid), text).get(lang, {}).get("label")
        if label:
            out[cid] = label
    return out
