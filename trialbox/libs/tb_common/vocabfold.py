"""One way to compare vocabulary labels (cards 22-2, 22-4): the Athena loader, the licence register's check and the
bundle check all fold a label with :func:`fold` before they compare it, so ``'SNOMED CT'``, ``' snomed-ct '``,
``'ＳＮＯＭＥＤ ＣＴ'`` (full-width) and ``'SNОMED CT'`` (a Cyrillic O) are one name.

Folding: Unicode NFKC (full-width and compatibility forms), Cyrillic and Greek letters that look like Latin ones
mapped to them, case folded, and everything but letters and digits dropped.
"""

from __future__ import annotations

import unicodedata

# Cyrillic and Greek letters drawn like Latin ones (upper and lower case), mapped after NFKC and before casefold
_LOOK_ALIKE = str.maketrans({
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "І": "I", "Ј": "J", "К": "K", "М": "M", "О": "O", "Р": "P",
    "Ѕ": "S", "Т": "T", "Х": "X", "У": "Y", "а": "a", "с": "c", "е": "e", "і": "i", "ј": "j", "о": "o", "р": "p",
    "ѕ": "s", "х": "x", "у": "y", "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M",
    "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X", "ο": "o", "ν": "v", "ρ": "p",
})  # fmt: skip


def fold(name: str) -> str:
    """The comparable form of a vocabulary label (letters and digits only, see the module text)."""
    text = unicodedata.normalize("NFKC", name).translate(_LOOK_ALIKE).casefold()
    return "".join(ch for ch in text if ch.isalnum())
