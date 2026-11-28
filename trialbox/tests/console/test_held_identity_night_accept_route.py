# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""H34-06 + M1 on a VALIDATION box, through the steward's real accept route (ruling of #1561, round 2, B).

A night held because a chart number arrived as another person than the one the lake serves is listed on
``/data-ops``, its page counts the held chart numbers (within the night / against the served night), and the
steward's accept with a reason, posted to the console's ``/data-ops/batches/<id>/decide``, goes through the
orchestrator's ``dataops`` route to the adapter's own ``POST /publish`` (the orchestrator's token) and the night is
then published and served. A night with two people within it is refused by the same route (the adapter's 409) and
stays held, the served night untouched. The adapter's ingest is the real one; the lake's rebuild is the stand-in of
``test_one_chart_two_people``. Synthetic data only (site A's fixture and made-up values)."""

from __future__ import annotations

import html
import os
import time
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import IDENTITY_CONFLICT
from datacore.dataops import HELD, PUBLISHED, DataOps
from fastapi.testclient import TestClient
from tb_common.http import ServiceError

from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import _csrf, _user
from tests.unit.test_one_chart_two_people import (
    GOOD,
    NEXT,
    _cfg,
    _feed,
    _night,
    _other_person,
    _rows,
    _write,
)
from tests.unit.test_the_publish_of_a_held_night_checks_the_steward import _auth, _registry

REASON = "checked with the ward: the same person, birth date and sex corrected in the hospital system"


class _AdapterWire:
    """What the orchestrator's ``AdapterHttp`` sends, to the adapter's real app with the orchestrator's token."""

    def __init__(self, http: TestClient) -> None:
        self.http = http
        self.refused: list[int] = []

    def _answer(self, r: Any) -> Any:
        if r.status_code >= 400:
            self.refused.append(r.status_code)
            raise ServiceError("adapter", r.status_code, r.text)
        return r

    def post_raw(self, path: str, body: Any, headers: dict[str, str] | None = None) -> Any:
        return self._answer(self.http.post(path, json=body, headers=_auth("orchestrator")))

    def get_json(self, path: str) -> Any:
        return self._answer(self.http.get(path, headers=_auth("orchestrator"))).json()


@pytest.fixture
def held_box(box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A VALIDATION box: the console, the orchestrator's ``dataops`` routes and the adapter's app, one store (the
    test's ``TB_DB_URL``), one good night of site A served."""
    from adapter import app as adapter_app
    from orchestrator.clients import AdapterHttp

    from tests.console.dataops_orch import attach

    monkeypatch.setenv("TB_ENV", "VALIDATION")
    monkeypatch.setenv("TB_ADAPTER_RUN", "thread")
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    _registry(tmp_path, monkeypatch)
    (tmp_path / "site").mkdir()
    cfg, rb = _cfg(tmp_path / "site", os.environ["TB_DB_URL"])
    rep = _night(cfg, _feed(tmp_path / "site"), GOOD)
    assert rep.passed and not rep.held
    monkeypatch.setattr(adapter_app, "build_config", lambda: (cfg, None))
    wire = _AdapterWire(TestClient(adapter_app.app, raise_server_exceptions=False))
    adapter = AdapterHttp("http://adapter.invalid")
    adapter.c = wire
    attach(box["backend"], box["audit"], adapter)
    return {"cfg": cfg, "rb": rb, "wire": wire, "feed": _feed(tmp_path)}


def _held_batch() -> int:
    ops = DataOps()
    try:
        (b,) = [b for b in ops.held() if b.snapshot == NEXT]
        return int(b.id)
    finally:
        ops.close()


def _state(bid: int) -> str:
    ops = DataOps()
    try:
        got = ops.batch(bid)
        assert got is not None
        return str(got.state)
    finally:
        ops.close()


def _until_published(bid: int) -> str:
    """The accept's publish runs on the orchestrator's thread after the answer (202 ``publishing``)."""
    end = time.monotonic() + 120
    while (st := _state(bid)) == HELD and time.monotonic() < end:
        time.sleep(0.2)
    return st


def test_the_steward_accepts_a_night_held_against_the_served_one_and_it_is_published(
    held_box: dict[str, Any], box: dict[str, Any]
) -> None:
    cfg, rb, feed = held_box["cfg"], held_box["rb"], held_box["feed"]
    rows = _rows(feed / "patient.csv")
    _write(feed / "patient.csv", [_other_person(rows[0]), *rows[1:]])  # one row: another person under a served chart
    rep = _night(cfg, feed, NEXT)
    assert rep.held and not rep.passed and (snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).exists()
    bid = _held_batch()
    c = _user(box, "stwacc", "steward")
    listing = c.get("/data-ops").text
    assert f'data-batch="{bid}"' in listing and 'value="accept"' in listing  # listed, and accept is offered
    page = html.unescape(c.get(f"/data-ops/batches/{bid}").text)
    assert 'data-testid="batch-identity-conflict-counts" data-tonight="0" data-against="1"' in page
    assert rows[0]["mrn"] not in page and rows[0]["name"] not in page  # counts only, never the chart or a name
    r = c.post(f"/data-ops/batches/{bid}/decide", data={"csrf": _csrf(listing), "decision": "accept",
                                                      "reason": REASON}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"].split("done=")[-1] in ("accept", "publishing"), r.headers
    assert _until_published(bid) == PUBLISHED
    assert held_box["wire"].refused == [] and rb.calls == [NEXT]
    assert (cfg.lake_dir / "CURRENT").read_text().strip() == NEXT  # the night is served
    ops = DataOps()
    try:
        last = ops.steps(bid)[-1]
    finally:
        ops.close()
    assert last["new"] == PUBLISHED and last["reason"] == REASON and last["who"]


def test_the_same_route_refuses_a_night_with_two_people_within_it(
    held_box: dict[str, Any], box: dict[str, Any]
) -> None:
    cfg, rb, feed = held_box["cfg"], held_box["rb"], held_box["feed"]
    rows = _rows(feed / "patient.csv")
    _write(feed / "patient.csv", [*rows, _other_person(rows[0])])  # two people under one chart in one night
    rep = _night(cfg, feed, NEXT)
    assert rep.held and not rep.passed
    bid = _held_batch()
    c = _user(box, "stwref", "steward")
    listing = c.get("/data-ops").text
    page = html.unescape(c.get(f"/data-ops/batches/{bid}").text)
    assert 'data-testid="batch-identity-conflict-counts" data-tonight="1" data-against="0"' in page
    r = c.post(f"/data-ops/batches/{bid}/decide", data={"csrf": _csrf(listing), "decision": "accept",
                                                      "reason": REASON}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"].endswith("err=promote"), r.headers
    assert held_box["wire"].refused == [409]  # the adapter's refuse_two_people, before the publish starts anything
    assert _state(bid) == HELD and rb.calls == []
    assert (cfg.lake_dir / "CURRENT").read_text().strip() == GOOD  # the served night untouched
