"""NEW-TRUST-4 (D-556): a service's log writes the route, not the path that was sent.

A path carries what the caller put in it: a record (``/studies/GZQO/records/<record>``), a job, or anything typed
where a ruleset id belongs. The request line of every service made by ``tb_common.http.make_app`` wrote that path,
so a chart number typed into a path was kept in the log. The line now holds the route's template; a path that
matches no route is written as "(no route)". The line of an unhandled error likewise. Synthetic data only."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from tb_common.http import make_app

CHART = "A1234567"


class _Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def lines() -> Iterator[_Lines]:
    h, lg = _Lines(), logging.getLogger("logsvc")
    lg.addHandler(h)
    old = lg.level
    lg.setLevel(logging.INFO)
    try:
        yield h
    finally:
        lg.removeHandler(h)
        lg.setLevel(old)


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TB_ENV", "TEST")
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    app = make_app("logsvc")
    sub = APIRouter()

    @app.get("/studies/{rs}/records/{record}")
    def record(rs: str, record: str) -> dict[str, str]:
        return {"rs": rs}

    @sub.get("/jobs/{job_id}")
    def job(job_id: str) -> dict[str, str]:
        return {}

    @app.get("/boom/{what}")
    def boom(what: str) -> dict[str, str]:
        raise RuntimeError(f"no row for {what}")

    app.include_router(sub, prefix="/v1")
    return TestClient(app, raise_server_exceptions=False)


def _said(lines: _Lines) -> str:
    return " | ".join(f"{r.getMessage()} {getattr(r, 'path', '')} {getattr(r, 'route', '')}" for r in lines.records)


def test_the_request_line_holds_the_routes_template(monkeypatch: pytest.MonkeyPatch, lines: _Lines) -> None:
    c = _client(monkeypatch)
    assert c.get(f"/studies/GZQO/records/{CHART}").status_code == 200
    assert c.get(f"/v1/jobs/{CHART}").status_code == 200
    reqs = [r for r in lines.records if r.getMessage() == "request"]
    assert [getattr(r, "path", None) for r in reqs] == ["/studies/{rs}/records/{record}", "/v1/jobs/{job_id}"]
    assert [getattr(r, "status", None) for r in reqs] == [200, 200]
    assert CHART not in _said(lines)


def test_a_path_of_no_route_and_a_refused_method_are_not_written(monkeypatch: pytest.MonkeyPatch,
                                                                 lines: _Lines) -> None:  # fmt: skip
    c = _client(monkeypatch)
    assert c.get(f"/nowhere/{CHART}").status_code == 404
    assert c.post(f"/studies/GZQO/records/{CHART}").status_code == 405
    reqs = [r for r in lines.records if r.getMessage() == "request"]
    assert [getattr(r, "path", None) for r in reqs] == ["(no route)", "/studies/{rs}/records/{record}"]
    assert CHART not in _said(lines)


def test_an_unhandled_errors_line_names_the_route(monkeypatch: pytest.MonkeyPatch, lines: _Lines) -> None:
    c = _client(monkeypatch)
    assert c.get(f"/boom/{CHART}").status_code == 500
    err = [r for r in lines.records if r.getMessage() == "unhandled error"]
    assert len(err) == 1 and getattr(err[0], "path", None) == "/boom/{what}"
