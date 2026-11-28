"""E2E P-05: at about 47,000 candidates every contact of the study was blocked. Each list and patient page asks the
orchestrator ``POST /patients/deceased`` with every listed pid; the orchestrator takes at most 20,000 in one request and
refused the rest (422), so the console (rightly, fail-closed) stopped Approach and calls on every patient. The console
now asks in pages the orchestrator takes. Synthetic pseudonyms only."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from console.backend import HttpBackend, Unavailable
from orchestrator.app import DeceasedRequest
from pydantic import ValidationError
from tb_common.http import ServiceError

pytestmark = pytest.mark.nodb

STUDY = [f"pseudo{i:06d}" for i in range(47_177)]  # the GOUT-301 study of the walk: 47,177 candidates


class _Orchestrator:
    """``POST /patients/deceased`` with the orchestrator's own request model (and so its limit)."""

    def __init__(self, dead: set[str], down_at: int | None = None) -> None:
        self.dead, self.down_at = dead, down_at
        self.sizes: list[int] = []

    def post_raw(self, path: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> httpx.Response:
        assert path == "/patients/deceased"
        try:
            req = DeceasedRequest.model_validate(body)
        except ValidationError as exc:
            raise ServiceError("orchestrator", 422, "pids: too long") from exc
        if self.down_at is not None and len(self.sizes) == self.down_at:
            raise ServiceError("orchestrator", 503, "the lake could not be read")
        self.sizes.append(len(req.pids))
        return httpx.Response(200, json={"deceased": sorted(set(req.pids) & self.dead)})


def _console(orch: _Orchestrator) -> HttpBackend:
    bk = HttpBackend.__new__(HttpBackend)  # only the orchestrator client is used by the death check
    bk.orch = orch  # type: ignore[assignment]
    return bk


def test_the_death_check_of_a_47k_candidate_study_is_answered() -> None:
    dead = {STUDY[3], STUDY[25_000], STUDY[47_176]}  # one on each page
    orch = _Orchestrator(dead)
    assert _console(orch).deceased(STUDY) == dead
    assert sum(orch.sizes) == len(STUDY) and max(orch.sizes) <= 20_000, orch.sizes


def test_one_page_not_answered_stops_contacts_never_a_partial_no_deaths() -> None:
    orch = _Orchestrator({STUDY[25_000]}, down_at=1)
    with pytest.raises(Unavailable):
        _console(orch).deceased(STUDY)


class _Malformed(_Orchestrator):
    """The first page answered as the orchestrator does; the second answered 200 with ``body``."""

    def __init__(self, body: Any) -> None:
        super().__init__({STUDY[3], STUDY[25_000]})
        self.body = body

    def post_raw(self, path: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> httpx.Response:
        resp = super().post_raw(path, body, headers)
        # json.dumps, not json=: a body of None must reach the console as the valid JSON `null`, not as an empty body
        return resp if len(self.sizes) == 1 else httpx.Response(200, content=json.dumps(self.body))


@pytest.mark.parametrize(
    "body",
    [
        {"deceased": None},
        {},
        {"deceased": STUDY[25_000]},
        [STUDY[25_000]],
        None,
        {"deceased": [STUDY[25_000], 7]},
    ],
    ids=["null", "missing-key", "not-a-list", "list-body", "null-body", "non-string-pid"],
)
def test_a_page_answered_200_in_the_wrong_shape_stops_contacts(body: Any) -> None:
    """P05-1: a malformed page is not "no deaths" on that page; the dead patient of page two must not pass."""
    with pytest.raises(Unavailable):
        _console(_Malformed(body)).deceased(STUDY)


@pytest.mark.parametrize("content", [b"", b"<html>proxy</html>"], ids=["empty-body", "html-body"])
def test_a_page_answered_200_without_json_stops_contacts(content: bytes) -> None:
    class _NotJson(_Orchestrator):
        def post_raw(self, path: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> httpx.Response:
            resp = super().post_raw(path, body, headers)
            return resp if len(self.sizes) == 1 else httpx.Response(200, content=content)

    with pytest.raises(Unavailable):
        _console(_NotJson({STUDY[25_000]})).deceased(STUDY)
