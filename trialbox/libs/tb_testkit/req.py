"""Requirement IDs of spec v4 for the ``@pytest.mark.req("<ID>")`` marker (§17.4, ENG-05).

An ID is any first cell of a spec table row that looks like ``PREFIX-…`` (``LLM-12``, ``FR-M3-21``, ``C-2′``,
``S1-06``). The set is read once from ``spec/v4/*.md``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

SPEC_DIR = Path(__file__).resolve().parents[2] / "spec" / "v4"
_ROW = re.compile(r"^\| ([A-Z][A-Z0-9-]*-[A-Za-z0-9′-]+) \|", re.M)


@lru_cache(maxsize=1)
def spec_requirement_ids(spec_dir: Path = SPEC_DIR) -> frozenset[str]:
    ids: set[str] = set()
    for f in sorted(spec_dir.glob("*.md")):
        ids.update(_ROW.findall(f.read_text(encoding="utf-8")))
    return frozenset(ids)


def unknown_ids(ids: list[str]) -> list[str]:
    known = spec_requirement_ids()
    return sorted({i for i in ids if i not in known})
