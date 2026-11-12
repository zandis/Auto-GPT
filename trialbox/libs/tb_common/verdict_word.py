"""The word a page, a sheet or a count shows for a stored verdict (T-709 review, D-478).

``matching.decision.answer_of`` decides what a verdict means for a run. A console page, a workbook or a count reads
a verdict that was already published or stored, with no criterion and no run policy at hand. It asks :func:`shown_of`:
a note "not met" that was not allowed to exclude when it was given (one model's answer, ``basis: single``; or given
while notes could not exclude, ``final: false``) is **not** printed as "not met". It is an open point with its reason,
exactly as CASE prints it. :func:`held_back` is the one test both functions use.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tb_common.reasons import Reason


def _get(verdict: Any, key: str) -> Any:
    return verdict.get(key) if isinstance(verdict, Mapping) else getattr(verdict, key, None)


def held_back(verdict: Any) -> str | None:
    """Why a "not met" may not exclude, as a reason code, or None when nothing on the verdict holds it back:
    ``single_model`` (one model gave it), ``not_final`` (given while a note answer was not allowed to exclude)."""
    if _get(verdict, "verdict") != "fail":
        return None
    if _get(verdict, "basis") == "single":
        return Reason.SINGLE_MODEL.value
    if _get(verdict, "final") is False:
        return Reason.NOT_FINAL.value
    return None


def shown_of(verdict: Any) -> tuple[str, str | None]:
    """``(word, reason)`` for a stored or published verdict (a model or its JSON): the verdict's own word, except
    that a held-back "not met" is ``unknown`` with the reason a person reads. ``reason`` is None otherwise."""
    why = held_back(verdict)
    if why is not None:
        return "unknown", why
    return str(_get(verdict, "verdict") or ""), None
