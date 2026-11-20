"""A WHO ICD-10 code written one way (D-314, D-1261): upper case, no blanks, the dagger / asterisk / plus mark
dropped, and the dot after the three-character category. The MEDIS disease-name master writes its ICD-10 2013 codes
without the dot (``E119``); the ICD-10-CM list and the records the SS-MIX2 reader writes have it (``E11.9``), so a
code from the master is written this way before it is compared with either. Standard library only."""

from __future__ import annotations

import re

_BARE = re.compile(r"[A-Z][0-9]{3,4}")


def dotted(code: str | None) -> str:
    """``e119`` -> ``E11.9``, ``I10`` -> ``I10``, ``E11.9`` as it is; anything else stripped and upper-cased."""
    c = re.sub(r"\s+", "", code or "").upper().rstrip("*+†")
    if _BARE.fullmatch(c):
        c = f"{c[:3]}.{c[3:]}"
    return c
