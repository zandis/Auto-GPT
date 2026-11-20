"""The WHO ICD-10 code of the MEDIS disease-name master, written so it can be compared (D-314, D-1261).

The master stores ＩＣＤ１０‐２０１３ as the release writes it, and this box never changes what is stored. To compare
it with the ICD-10-CM list or with the records the SS-MIX2 reader writes (``E11.9``), :func:`comparable` writes it
one way. The release's shapes (A a capital letter, 9 a digit):

* ``A99`` (a category): as it is (``I10``);
* ``A999`` and ``A9999``: the dot after the third character (``E119`` -> ``E11.9``, ``M1097`` -> ``M10.97``);
* ``A999`` followed by one lower-case letter (a Japanese sub-classification): the letter is left out for the
  comparison only (``E109a`` -> ``E10.9``); the release's own value is what a page shows;
* a value with a hyphen inside (``A99-9``) and an empty value: nothing (""): the master gives no ICD-10 for it, and
  no code is guessed.

A code already written with its dot (``E11.9``, from a site's own table) is kept. Anything else gives "".
The ＩＣＤ１０‐２０１３複数分類コード has the same plain shapes. Standard library only."""

from __future__ import annotations

import re

_PLAIN = re.compile(r"^([A-Z][0-9]{2})([0-9]{1,2})?$")
_DOTTED = re.compile(r"^[A-Z][0-9]{2}\.[0-9]{1,2}$")


def comparable(code: str | None) -> str:
    """The master's ICD-10 value as the ICD-10-CM list writes it, or "" when it gives none."""
    c = (code or "").strip()
    if re.fullmatch(r"[A-Z][0-9]{3}[a-z]", c):
        c = c[:-1]  # a Japanese sub-classification: compared without it
    if _DOTTED.match(c):
        return c
    m = _PLAIN.match(c)
    if not m:
        return ""
    return m.group(1) + (f".{m.group(2)}" if m.group(2) else "")
