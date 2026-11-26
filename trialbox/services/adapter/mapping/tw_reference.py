"""Reference-only mapping logic for the Taiwan SQL-view door."""

import re
from collections import defaultdict
from collections.abc import Iterable


def drug_pairs(records: Iterable[list[str]]) -> dict[str, str]:
    """Read NHI column 1 and ATC column 16; omit names, missing and ambiguous mappings."""
    answers: dict[str, set[str]] = defaultdict(set)
    for row in records:
        if len(row) >= 17 and row[1].strip():
            answers[row[1].strip().upper()].add(row[16].strip().upper())
    return {
        code: next(iter(targets))
        for code, targets in answers.items()
        if len(targets) == 1 and re.fullmatch(r"[A-Z][0-9]{2}[A-Z]{2}[0-9]{2}", next(iter(targets)))
    }
