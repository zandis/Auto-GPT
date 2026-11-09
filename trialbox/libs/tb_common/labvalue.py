"""Lab result text as a number (D-142, review B-01): one reader for every input (the mapping engine for CSV, CGRD and
SS-MIX2 OBX-5, and the lake for FHIR ``valueString``).

A result such as ``"75 H"`` is the number 75 with an abnormal flag; ``"<0.3"`` and ``"0.3未満"`` are *censored*: the
true value is below 0.3, so only a comparison that holds (or fails) for every value below 0.3 can be decided. Text that
is none of these (``"検出せず"``, ``"陰性"``, ``"see note"``) is not a number: the screening engine treats it as
unknown, never as a failed comparison.

:func:`parse` returns ``(value, comparator)`` with ``comparator`` one of ``None`` (exact), ``"<"``, ``"<="``, ``">"``,
``">="`` (the FHIR ``Quantity.comparator`` codes), or ``None`` when the text is not a readable number.
"""

from __future__ import annotations

import re
import unicodedata

# abnormal flags written after (or, less often, before) the number: HL7 table 0078 and the usual JP / TW marks
_FLAG = r"(?:HH|LL|H|L|N|A|AA|\*+|↑+|↓+|高|低|\(H\)|\(L\)|\[H\]|\[L\])"
_NUM = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|[+-]?\.\d+"
_PREFIX = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "≦": "<=", "≤": "<=", "≧": ">=", "≥": ">=", "=<": "<="}
_PREFIX["=>"] = ">="
_SUFFIX = {"未満": "<", "以下": "<=", "以上": ">=", "超": ">", "より大きい": ">", "より小さい": "<"}
_RE = re.compile(
    rf"^(?:{_FLAG}\s*)?(?P<pre><=|>=|=<|=>|<|>|≦|≤|≧|≥)?\s*(?P<num>{_NUM})\s*"
    rf"(?P<suf>未満|以下|以上|超|より大きい|より小さい)?\s*(?:{_FLAG})?$"
)


def parse(text: object) -> tuple[float, str | None] | None:
    """``(value, comparator)`` for a readable result, else None. Full-width forms are folded first (NFKC)."""
    if text is None or isinstance(text, bool):
        return None
    if isinstance(text, int | float):
        return float(text), None
    s = unicodedata.normalize("NFKC", str(text)).strip()
    if not s:
        return None
    m = _RE.match(s)
    if m is None:
        return None
    pre, suf = m.group("pre"), m.group("suf")
    if pre and suf:
        return None  # "<0.3未満": two comparators, not a form anyone writes on purpose
    try:
        value = float(m.group("num").replace(",", ""))
    except ValueError:
        return None
    return value, (_PREFIX[pre] if pre else _SUFFIX[suf] if suf else None)
