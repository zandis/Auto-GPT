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


def _client(monkeypatch: pytest.MonkeyPatch, protect_reads: bool = False) -> TestClient:
    monkeypatch.setenv("TB_ENV", "TEST")
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    app = make_app("logsvc", protect_reads=protect_reads)
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


def _paths(lines: _Lines) -> list[str]:
    return [str(getattr(r, "path", None)) for r in lines.records if r.getMessage() == "request"]


def test_a_request_refused_before_its_handler_is_still_named_by_its_route(monkeypatch: pytest.MonkeyPatch,
                                                                          lines: _Lines) -> None:  # fmt: skip
    """The review: with a token asked for, a call without one never reaches a route, and the routes of an included
    router were then written "(no route)", the same as a scan of paths that do not exist."""
    c = _client(monkeypatch, protect_reads=True)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setenv("TB_SERVICE_TOKEN", "a-token-of-this-test-only-0123456789")
    assert c.get(f"/studies/GZQO/records/{CHART}").status_code in (401, 403)  # a route of the app itself
    assert c.get(f"/v1/jobs/{CHART}").status_code in (401, 403)  # a route of an included router
    assert c.get(f"/nowhere/{CHART}").status_code in (401, 403)
    assert _paths(lines) == ["/studies/{rs}/records/{record}", "/v1/jobs/{job_id}", "(no route)"]
    assert CHART not in _said(lines)


def test_a_prefix_with_a_parameter_and_a_mounted_app_keep_what_was_sent_out(monkeypatch: pytest.MonkeyPatch,
                                                                             lines: _Lines) -> None:  # fmt: skip
    """The review: the first version put a router's prefix back from the path that was sent, so a parameter of the
    prefix whose value is spelled otherwise once converted (12345678 -> 12345678.0, a UUID in capitals) came
    back with it. Nothing is taken from the sent path now."""
    from fastapi import FastAPI

    monkeypatch.setenv("TB_ENV", "TEST")
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    app = make_app("logsvc")
    by_visit, by_site, by_study, inner = APIRouter(), APIRouter(), APIRouter(), FastAPI()

    @by_visit.get("/r/{rec}")
    def visit(n: float, rec: str) -> dict[str, str]:
        return {}

    @by_site.get("/r/{rec}")
    def site(u: str, rec: str) -> dict[str, str]:
        return {}

    @by_study.get("/r/{rec}")
    def study(rs: str, rec: str) -> dict[str, str]:
        return {}

    @inner.get("/x/{thing}")
    def thing(thing: str) -> dict[str, str]:
        return {}

    app.include_router(by_visit, prefix="/visit/{n:float}")
    app.include_router(by_site, prefix="/site/{u:uuid}")
    app.include_router(by_study, prefix="/study/{rs}")
    app.mount("/sub", inner)
    c = TestClient(app, raise_server_exceptions=False)
    uuid = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    for path in ("/visit/12345678/r/abc", f"/site/{uuid}/r/abc", f"/study/{CHART}/r/{CHART}", f"/sub/x/{CHART}",
                 "/v1/r/v1"):  # fmt: skip
        c.get(path)
    got = _paths(lines)
    assert got[:3] == ["/visit/{n:float}/r/{rec}", "/site/{u:uuid}/r/{rec}", "/study/{rs}/r/{rec}"]
    assert got[3] in ("/sub", "/x/{thing}", "/sub/x/{thing}") and got[4] == "(no route)"
    said = _said(lines)
    assert "12345678" not in said and uuid not in said and uuid.lower() not in said and CHART not in said


def test_the_route_that_takes_the_method_is_named_before_one_that_only_fits_the_path(
    monkeypatch: pytest.MonkeyPatch, lines: _Lines
) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setenv("TB_SERVICE_TOKEN", "a-token-of-this-test-only-0123456789")
    app = make_app("logsvc")

    @app.get("/jobs/{job_id}")
    def job(job_id: str) -> dict[str, str]:
        return {}

    @app.post("/jobs/cancel")
    def cancel() -> dict[str, str]:
        return {}

    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/jobs/cancel").status_code in (401, 403)
    assert _paths(lines) == ["/jobs/cancel"]


def test_an_unhandled_errors_line_holds_its_type_and_where_not_its_text(monkeypatch: pytest.MonkeyPatch,
                                                                         lines: _Lines) -> None:  # fmt: skip
    """NEW-TRUST-5 (D-557): the line logged the whole traceback, whose last line is the error's own text: a
    database error quotes its values, a validation error prints its input, an f-string holds a path's value. The
    line now holds the error's type (and its cause's), and the frames: file, line, function."""
    c = _client(monkeypatch)
    assert c.get("/boom/Q9Z-77-Q").status_code == 500
    (err,) = [r for r in lines.records if r.getMessage() == "unhandled error"]
    assert getattr(err, "error", None) == "RuntimeError" and err.exc_info is None
    trace = str(getattr(err, "trace", ""))
    assert "in boom" in trace and "test_access_log_route.py" in trace and "RuntimeError" in trace
    whole = " ".join(str(v) for v in err.__dict__.values())
    # the frame shows the line of code (its f-string as written), never what the f-string made of it
    assert "Q9Z-77-Q" not in whole and "no row for Q9Z" not in whole and "no row for {what}" in whole
