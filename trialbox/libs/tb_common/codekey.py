"""The one way a hospital code is compared (D-580; 10B-6, D-1233): the mapping engine's look-up, a site profile's
duplicate check and the night's ``verify`` tag all read a code through :func:`fold_key`.

Standard library only; imports under Python 3.10.
"""

from __future__ import annotations

# full-width ASCII (U+FF01 to U+FF5E) and the ideographic space, to their half-width forms: what a Taiwanese or
# Japanese system writes for the same code. Not Unicode NFKC: that also turns ``㎎`` into ``mg``, ``①`` into ``1``
# and ``Ⅳ`` into ``IV``, which are other signs, not another width of the same code.
HALF_WIDTH = {**{c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}, 0x3000: 0x20}


def fold_key(key: object) -> str:
    """A look-up key as a person reads it (D-580): no blanks around it, full-width letters and digits made
    half-width, lower case."""
    return ("" if key is None else str(key)).translate(HALF_WIDTH).strip().lower()
