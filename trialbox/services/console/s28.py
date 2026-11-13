"""The console's reads and writes of the orchestrator's S-28 study store (D-109).

From step 3 the per-study settings (study type, cohort kind, "Not suitable" reasons, screening-number format) live
in the orchestrator's ``studies.db`` and are edited on S21 through the orchestrator API. Until a study is saved on
S21, a value the console kept in its own site store in step 2 still applies, then the defaults by ruleset; S21's
first save moves it. Screening numbers themselves stay in the console's site store, which issues them.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from console.backend import Problem, Unavailable
from console.sitestore import SiteStore, StudySettings

TTL = 5.0  # seconds a read is reused within one page build (the list asks once per row)


def _cache(bk: object) -> dict[str, tuple[float, StudySettings]]:
    """Reads kept on the backend object itself, so two consoles (or two tests) never share them."""
    c = getattr(bk, "_s28_cache", None)
    if c is None:
        c = {}
        with contextlib.suppress(AttributeError):
            setattr(bk, "_s28_cache", c)  # noqa: B010
    return c


def has_api(bk: object) -> bool:
    return callable(getattr(bk, "study_api", None))


def call(bk: object, method: str, path: str, body: dict[str, Any] | None = None,
         headers: dict[str, str] | None = None) -> Any:  # fmt: skip
    fn = getattr(bk, "study_api", None)
    if not callable(fn):
        raise Unavailable("this backend has no study store")
    if headers:
        return fn(method, path, body, headers=headers)
    return fn(method, path, body)


def from_row(row: dict[str, Any], base: StudySettings) -> StudySettings:
    return StudySettings(
        study_type=str(row.get("study_type") or base.study_type),
        cohort_kind=str(row.get("cohort_kind") or base.cohort_kind),
        reasons=tuple(row.get("not_suitable_reasons") or base.reasons),
        screening_prefix=str(row.get("screening_no_format") or ""),
        first_no=int(row.get("screening_no_next") or 1),
    )


def to_body(s: StudySettings, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """The settings as the route takes them. No person: T-715d (D-554), the route reads the signed one."""
    return {
        "study_type": s.study_type,
        "cohort_kind": s.cohort_kind,
        "not_suitable_reasons": list(s.reasons),
        "screening_no_format": s.screening_prefix,
        "screening_no_next": s.first_no,
        **(extra or {}),
    }


def remote(bk: object, rs: str) -> dict[str, Any] | None:
    """The S-28 row, or None when the study was never saved there (or the store does not answer)."""
    try:
        row = call(bk, "GET", f"/studies/{rs}/settings")
    except (Problem, Unavailable):
        return None
    return row if isinstance(row, dict) else None


def load(bk: object, store: SiteStore, rs: str, default: StudySettings) -> StudySettings:
    if not has_api(bk):
        return store.study_settings(rs, default)
    cache = _cache(bk)
    hit = cache.get(rs)
    if hit is not None and time.monotonic() - hit[0] < TTL:
        return hit[1]
    row = remote(bk, rs)
    out = from_row(row, default) if row else store.study_settings(rs, default)
    cache[rs] = (time.monotonic(), out)
    return out


def save(bk: object, rs: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    """The study's settings: ``body`` is ``to_body(...)`` and ``headers`` the signed person over exactly that body
    (T-715d, D-554: the route refuses a call without one, so every call site mints it with
    ``console.actor.assert_for``). The body that was signed is the body that is sent."""
    _cache(bk).pop(rs, None)
    out = call(bk, "PUT", f"/studies/{rs}/settings", body, headers=headers)
    _cache(bk).pop(rs, None)
    return dict(out)
