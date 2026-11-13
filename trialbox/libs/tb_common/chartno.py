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

A number longer than ``<width>`` is never cut and keeps its leading zeros (D-591): two different chart numbers must
never become one.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
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
    if rule.width and len(text) > rule.width:
        # D-591: wider than the site's width, so its zeros are part of it. ``012345678`` under ``digits:8`` is not
        # ``12345678``: that is another patient's number, and the two would share one pseudonym
        return text
    core = text.lstrip("0") or "0"
    if rule.width and len(core) < rule.width:
        return core.zfill(rule.width)
    return core


def same_number(site_rule: Rule | str | None, a: str, b: str) -> bool:
    """Whether two chart numbers as written are one chart number under the rule. Decided here from the rule's
    words alone, NOT through :func:`normalise`: the pid map uses it to check what the normaliser did (D-591), so
    a fault in one is caught by the other. One number: the same text once full-width and blanks are folded; or,
    under ``digits`` / ``hex``, both all digits (hexadecimal digits), neither wider than the width, and equal
    without their leading zeros (and whatever the case of a hexadecimal key)."""
    if isinstance(site_rule, Rule):
        rule = site_rule
    else:
        rule = parse_rule(site_rule) if site_rule else _box_rule()
    x, y = str(a).translate(_FULL).strip(), str(b).translate(_FULL).strip()
    if x == y:
        return True
    if rule.kind == "asis":
        return False
    shape = _DIGITS if rule.kind == "digits" else _HEX
    if not (shape.match(x) and shape.match(y)):
        return False
    x, y = x.upper(), y.upper()
    if x == y:
        return True
    if rule.width and (len(x) > rule.width or len(y) > rule.width):
        return False
    return (x.lstrip("0") or "0") == (y.lstrip("0") or "0")


# FIT-U09 (T-629, D-415): a chart-number column that Excel turned into numbers is refused at import, never read.
# Excel stores a number, so ``00123456`` is saved as ``123456``; a long one is written ``1.23457E+11``; a CSV saved
# from it may write ``123456.0``. Each would hash to another pseudonym and quietly split one patient in two.
_EXCEL_NUMBER = re.compile(r"^[0-9]+\.0+$|^[0-9](\.[0-9]+)?[Ee][+]?[0-9]+$")
REFUSALS = ("excel_number", "lost_zeros")


def column_refusal(values: Iterable[str], pattern: str | None = None, rule: Rule | str | None = None) -> str | None:
    """Why a chart-number column must be refused, or None when it may be read.

    * ``excel_number``: a value is written the way Excel writes a number (``123456.0``, ``1.23457E+11``);
    * ``lost_zeros``: with the site's chart-number pattern (``settings.mrn_regex``), an all-digit value that does not
      match it, written the site's way (:func:`normalise`), but does once leading zeros are put back.

    A value that fails the pattern for another reason is not this check's business (the import's own row checks).
    Without a pattern only the first sign can be seen: a CSV keeps no cell types."""
    pat = re.compile(pattern) if pattern else None
    for raw in values:
        v = str(raw).translate(_FULL).strip()
        if not v:
            continue
        if _EXCEL_NUMBER.match(v):
            return "excel_number"
        if pat is None or not _DIGITS.match(v):
            continue
        norm = normalise(rule, v)
        if pat.fullmatch(norm) or pat.fullmatch(v):
            continue
        if any(pat.fullmatch("0" * k + v) for k in range(1, 17)):
            return "lost_zeros"
    return None
