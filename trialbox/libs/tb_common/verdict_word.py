"""The word a page, a sheet or a count shows for a stored verdict (T-709 review, D-478).

``matching.decision.answer_of`` decides what a verdict means for a run. A console page, a workbook or a count reads
a verdict that was already published or stored, with no criterion and no run policy at hand. It asks :func:`shown_of`:
a note "not met" that was not allowed to exclude when it was given (one model's answer, ``basis: single``; or given
while notes could not exclude, ``final: false``) is **not** printed as "not met". It is an open point with its reason,
exactly as CASE prints it. :func:`held_back` is the one test both functions use.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from tb_common.reasons import Reason, code_of


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


# INT-S-B (D-1072): a note reading that speaks against a criterion is review, never an exclusion. The page and the
# workbook say it in these words; the patient stays on the list. Display only: nothing here changes a status.
NOTE_AGAINST = {
    "en": "A note may speak against {criterion}. Not excluded. Please check.",
    "ja": "記録の文章が{criterion}に反する可能性があります。除外していません。確認してください。",
    "zh-TW": "病歷文字可能不利於{criterion}。未排除。請確認。",
}
NOTE_AGAINST_COUNT = {
    "en": "Patients with a note that may speak against a criterion: {n}. None is excluded.",
    "ja": "記録の文章が基準に反する可能性がある患者：{n}名。いずれも除外していません。",
    "zh-TW": "病歷文字可能不利於某項條件的病人：{n} 位。皆未排除。",
}


def notes_against(verdict: Any) -> bool:
    """A pair's note "not met" that was not allowed to exclude (``not_final``): what the page and the sheet print as
    "a note may speak against" the criterion, with its quotes and dates, instead of ``unknown``. Also a pair's ring-0
    "not met" stored ``final: true`` (reason ``notes_suggest_not_eligible``): D-1072, no note answer excludes, whatever
    the run's policy said when it was given."""
    why = held_back(verdict)
    if why is not None:
        return why == "not_final"
    reason = _get(_get(verdict, "evidence"), "reason")
    return code_of(str(reason or ""), "fail") == Reason.NOTES_SUGGEST_NOT_ELIGIBLE.value


def against_ids(criteria: Any) -> list[str]:
    return [str(_get(v, "id")) for v in criteria or [] if notes_against(v)]


def flagged_last[T](
    rows: list[T], day: Callable[[T], str], review: Callable[[T], bool], flagged: Callable[[T], bool]
) -> list[T]:
    """``rows`` in their order, except that on each appointment day the review rows that are ``flagged`` take the last
    of that day's review places, in their own order. Nothing else moves; no row is added or dropped."""
    slots: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        if review(r):
            slots.setdefault(day(r), []).append(i)
    out = list(rows)
    for idx in slots.values():
        group = [rows[i] for i in idx]
        for i, r in zip(idx, [r for r in group if not flagged(r)] + [r for r in group if flagged(r)], strict=True):
            out[i] = r
    return out
