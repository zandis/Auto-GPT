"""A written reason as a reader sees it (10C-19, D-1232): the length rule of a note must not be met by characters that
show nothing.

:func:`visible` takes out format and invisible characters (Unicode category Cf: zero-width spaces and joiners, the
byte-order mark, bidirectional marks) and the Hangul and braille fillers, then collapses white space as the product
already does (``" ".join(text.split())``). A note made of letters is unchanged; a note of nothing but invisible
characters is empty. Standard library only.
"""

from __future__ import annotations

import unicodedata

FILLERS = frozenset({"ᅟ", "ᅠ", "ㅤ", "ﾠ", "⠀"})


def visible(text: str) -> str:
    """``text`` without the characters that show nothing, its white space collapsed."""
    kept = "".join(c for c in text or "" if unicodedata.category(c) != "Cf" and c not in FILLERS)
    return " ".join(kept.split())
