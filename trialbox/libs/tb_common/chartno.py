"""The one chart-number normaliser (R-48, D-301): the site's MRN rule, applied wherever a chart number becomes a
pseudonym.

A chart number is hashed into the pseudonym (``tb_common.crypto.pid_for_mrn``); two spellings of one chart number
give two pseudonyms and so a phantom patient whose facts never join the hospital record. The usual spellings: Excel
drops the leading zeros of a numeric cell (``00123456`` becomes ``123456``), a sheet or a scanner writes full-width
digits, and hexadecimal keys come in either case. :func:`normalise` is the only place that handles them; every path
from a chart number to a pseudonym goes through it (the feed's mapping engine and bulk loader, the pid map, site
set-up's sheets and charts, a CRC typing a number).

The site's rule (``TB_CHARTNO_RULE``, set once at installation from the hospital's chart-number format):

* ``asis`` (default): full-width to half-width and surrounding blanks removed, nothing else. A chart number that is
  already written the hospital's way is unchanged, so the default changes no pseudonym the box has made.
* ``digits`` / ``digits:<width>``: an all-digit chart number. Leading zeros are not significant: they are removed,
  and with ``<width>`` the number is zero-padded back to the hospital's fixed width (``digits:8``: ``123456`` and
  ``00123456`` are both ``00123456``). A value that is not all digits is left as written (it joins nothing it did not
  join before; it is never guessed into another patient).
* ``hex`` / ``hex:<width>`` / ``hex:<width>:lower``: a hexadecimal key; the case is made upper (or lower), and
  leading zeros are handled as for ``digits``.

A number longer than ``<width>`` is never cut: two different chart numbers must never become one.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache

ENV = "TB_CHARTNO_RULE"
KINDS = ("asis", "digits", "hex")

_FULL = {c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}
_FULL[0x3000] = 0x20  # ideographic space
_DIGITS = re.compile(r"^[0-9]+$")
_HEX = re.compile(r"^[0-9A-Fa-f]+$")


class ChartNoError(ValueError):
    """A chart-number rule that cannot be read."""


@dataclass(frozen=True)
class Rule:
    kind: str = "asis"
    width: int | None = None
    case: str = "upper"

    def __str__(self) -> str:
        if self.kind == "asis":
            return "asis"
        parts = [self.kind] + ([str(self.width)] if self.width else []) + (["lower"] if self.case == "lower" else [])
        return ":".join(parts)


ASIS = Rule()


@lru_cache(maxsize=32)
def parse_rule(text: str | None) -> Rule:
    """``asis``, ``digits[:<width>]`` or ``hex[:<width>][:upper|lower]``; empty means ``asis``."""
    raw = (text or "").strip().lower()
    if not raw:
        return ASIS
    parts = raw.split(":")
    kind = parts[0]
    if kind not in KINDS:
        raise ChartNoError(f"{ENV}={text!r}: the rule is one of asis, digits[:width], hex[:width][:upper|lower]")
    if kind == "asis":
        if len(parts) > 1:
            raise ChartNoError(f"{ENV}={text!r}: asis takes no options")
        return ASIS
    width: int | None = None
    case = "upper"
    for p in parts[1:]:
        if p.isdigit():
            width = int(p)
            if not 1 <= width <= 64:
                raise ChartNoError(f"{ENV}={text!r}: the width is 1 to 64")
        elif kind == "hex" and p in ("upper", "lower"):
            case = p
        else:
            raise ChartNoError(f"{ENV}={text!r}: {p!r} is not a width" + (" or a case" if kind == "hex" else ""))
    return Rule(kind, width, case)


def site_rule() -> Rule:
    """The box's rule (``TB_CHARTNO_RULE``); read at each call, parsed once per spelling."""
    return parse_rule(os.environ.get(ENV))


_box_rule = site_rule


def normalise(site_rule: Rule | str | None, value: str) -> str:
    """The chart number ``value`` written the site's way (see the module text). ``site_rule`` is a :class:`Rule`, its
    text, or None for the box's rule."""
    if isinstance(site_rule, Rule):
        rule = site_rule
    else:
        rule = parse_rule(site_rule) if site_rule else _box_rule()
    text = str(value).translate(_FULL).strip()
    if rule.kind == "asis" or not text:
        return text
    if rule.kind == "digits":
        if not _DIGITS.match(text):
            return text
    else:
        if not _HEX.match(text):
            return text
        text = text.upper() if rule.case == "upper" else text.lower()
    core = text.lstrip("0") or "0"
    if rule.width and len(core) < rule.width:
        return core.zfill(rule.width)
    return core
