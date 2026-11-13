"""NEW-B-31 (D-672): the lake client's ``snapshot()`` says "no snapshot" only for a healthy lake that has none.

It read the lake's ``/healthz`` without looking at the status, and answered None for any body without
``checks.snapshot``. When the lake's own snapshot check raises, ``/healthz`` answers 503 without that key, and the
client said None: "this lake holds no data". Callers took a lake that could not answer for an empty one (the
opt-out worker skipped the registry on that tick and named nothing as failed)."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import httpx
import pytest
from lake.client import LakeHttp, LakeUnhealthy

ROOT = Path(__file__).resolve().parents[2]


def _client(status: int, body: Any = None, text: str | None = None) -> LakeHttp:
    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/healthz"
        return httpx.Response(status, text=text) if text is not None else httpx.Response(status, json=body)

    lake = LakeHttp("http://lake")
    lake.client = httpx.Client(transport=httpx.MockTransport(answer))
    return lake


def _health(status: str, **checks: Any) -> dict[str, Any]:
    return {"status": status, "service": "lake", "version": "1.0.0", "checks": checks}


def test_a_healthy_lake_names_its_snapshot_and_a_healthy_empty_one_has_none() -> None:
    assert _client(200, _health("ok", snapshot="2026-10-04", vec="ok")).snapshot() == "2026-10-04"
    assert _client(200, _health("ok", snapshot="2026-10-04.g2")).snapshot() == "2026-10-04.g2"
    assert _client(200, _health("ok", snapshot="none")).snapshot() is None


def test_a_lake_whose_snapshot_check_failed_is_not_an_empty_lake() -> None:
    # what make_app's /healthz answers when the check raised: 503, and the check's name in place of its key
    lake = _client(503, _health("degraded", **{"<lambda>": "error: OSError"}, vec="ok"))
    with pytest.raises(LakeUnhealthy) as got:
        lake.snapshot()
    assert "503" in str(got.value) and "snapshot" in str(got.value)


def test_a_degraded_lake_that_still_names_its_snapshot_is_read_and_one_that_says_none_is_not_believed() -> None:
    """Another check of the lake failed (503), its snapshot check did not: the name it gives is the served night.
    "none" from a lake that is not healthy is not taken for "holds no data"."""
    degraded = _health("degraded", snapshot="2026-10-04", _vec_check="error: RuntimeError")
    assert _client(503, degraded).snapshot() == "2026-10-04"
    with pytest.raises(LakeUnhealthy):
        _client(503, _health("degraded", snapshot="none", _vec_check="error: RuntimeError")).snapshot()


@pytest.mark.parametrize(
    ("status", "body", "text"),
    [
        (200, {"status": "ok"}, None),  # no checks at all
        (200, _health("ok"), None),  # checks without the snapshot's
        (200, _health("ok", snapshot=None), None),
        (200, _health("ok", snapshot=7), None),
        (200, _health("ok", snapshot=""), None),
        (200, ["ok"], None),
        (200, {"checks": "ok"}, None),
        (200, None, "<html>a proxy's page</html>"),
        (200, None, ""),
        (500, None, "Internal Server Error"),
        (502, None, "<html>Bad Gateway</html>"),
        (404, {"detail": "Not Found"}, None),
        (401, {"detail": "service token required"}, None),
    ],
)
def test_an_answer_that_is_not_a_health_answer_with_a_snapshot_is_never_no_data(
    status: int, body: Any, text: str | None
) -> None:
    with pytest.raises(LakeUnhealthy) as got:
        _client(status, body, text).snapshot()
    said = str(got.value)
    assert str(status) in said and "proxy" not in said and "Bad Gateway" not in said  # the status, not the body


def test_a_lake_that_cannot_be_reached_raises_as_before() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    lake = LakeHttp("http://lake")
    lake.client = httpx.Client(transport=httpx.MockTransport(refused))
    with pytest.raises(httpx.ConnectError):
        lake.snapshot()


def test_the_real_lake_service_whose_snapshot_cannot_be_read_makes_the_client_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient
    from lake import app as lake_app

    class Broken:
        def current(self) -> str:
            raise OSError(5, "Input/output error")

    monkeypatch.setattr(lake_app, "lake", Broken)
    http = LakeHttp("http://testserver")
    http.client = TestClient(lake_app.app)
    assert http.client.get("/healthz").status_code == 503
    with pytest.raises(LakeUnhealthy):
        http.snapshot()
    with pytest.raises(LakeUnhealthy):  # the two calls that ask for the snapshot first
        http.generation()
    with pytest.raises(LakeUnhealthy):
        http.site_in_sync()


# ------------------------------------------------------------------------------------------- every caller
RAISES = "the error goes on: the job, the request or the publish fails; nothing is read as no data"
NOT_THE_LAKE = "not the lake's client"

#: (file under services/, function) -> what it does when the lake's snapshot() raises. A new caller must be put
#: here, by someone who read what it does with the raise.
CALLERS: dict[tuple[str, str], str] = {
    ("lake/client.py", "LakeHttp.generation"): RAISES,
    ("lake/client.py", "LakeHttp.site_in_sync"): RAISES,
    ("orchestrator/decision_context.py", "DecisionContext.snapshot"): RAISES,
    ("orchestrator/rerun.py", "PinnedLake.snapshot"): RAISES,
    ("orchestrator/scenarios/case.py", "resolve_subject"): RAISES,
    ("orchestrator/scenarios/cohort.py", "run_cohort"): RAISES,
    ("orchestrator/scenarios/feas.py", "run"): RAISES,
    ("orchestrator/scenarios/microbatch.py", "run"): RAISES,
    ("orchestrator/scenarios/nav.py", "run"): RAISES,
    ("orchestrator/scenarios/screen.py", "run"): RAISES,
    ("sitesetup/readiness.py", "feasibility"): RAISES,
    ("sitesetup/readiness.py", "readiness"): RAISES,
    ("sitesetup/readiness.py", "patient_check"): RAISES,
    ("sitesetup/service.py", "SiteSetup.publish"): RAISES,
    ("edc/prefill.py", "LakeFacts.__init__"): RAISES,
    # caught, and read as "nothing": OPEN, each for its own lane (D-672 lists them; this card is the client's)
    ("orchestrator/derive.py", "status"): "OPEN: caught; the derive status line shows no current snapshot",
    ("sitesetup/readiness.py", "unknown_share"): "OPEN: caught; answers (0, 0), as for a lake with no diagnosis",
    ("sitesetup/readiness.py", "scores_unverified"): "OPEN: caught; answers None, as for scores that are verified",
    ("sitesetup/readiness.py", "feed_loaded"): "OPEN: caught; answers None, which the page reads as no feed loaded",
    # caught, and said
    ("datacore/optout_worker.py", "run_once"): "caught: the registry is named as failed; the next tick tries again",
    # other objects that have a snapshot() of their own
    ("edc/prefill.py", "build"): NOT_THE_LAKE,
    ("gateway/app.py", "readyz"): NOT_THE_LAKE,
    ("gateway/load.py", "Endpoint.snapshot"): NOT_THE_LAKE,
    ("gateway/load.py", "LoadControl.snapshot"): NOT_THE_LAKE,
}


def _callers() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    services = ROOT / "services"
    for f in sorted(services.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        parent: dict[ast.AST, ast.AST] = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "snapshot"):
                continue
            if n.args or n.keywords:
                continue
            fn, cls = "", ""
            p: ast.AST = n
            while p in parent:
                p = parent[p]
                if isinstance(p, ast.FunctionDef | ast.AsyncFunctionDef) and not fn:
                    fn = p.name
                if isinstance(p, ast.ClassDef) and not cls:
                    cls = p.name
            found.add((f.relative_to(services).as_posix(), f"{cls}.{fn}" if cls else fn or "<module>"))
    return found


def test_every_caller_of_snapshot_is_listed_with_what_it_does_when_the_lake_cannot_answer() -> None:
    found = _callers()
    assert found - set(CALLERS) == set(), "a new caller of snapshot(): read what it does on the raise, then list it"
    assert set(CALLERS) - found == set(), "no longer there: take them off the list"


def test_the_callers_listed_as_raising_have_no_handler_around_the_call() -> None:
    """The list says "the error goes on" only where no ``try`` stands between the call and its function."""
    services = ROOT / "services"
    wrong: list[tuple[str, str]] = []
    for (name, func), what in CALLERS.items():
        if what != RAISES:
            continue
        tree = ast.parse((services / name).read_text(encoding="utf-8"))
        parent: dict[ast.AST, ast.AST] = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "snapshot"):
                continue
            if n.args or n.keywords:
                continue
            chain: list[ast.Try] = []
            fn, cls = "", ""
            p: ast.AST = n
            while p in parent:
                child: ast.AST = p
                p = parent[p]
                if isinstance(p, ast.Try) and child in p.body and not fn:
                    chain.append(p)
                if isinstance(p, ast.FunctionDef | ast.AsyncFunctionDef) and not fn:
                    fn = p.name
                if isinstance(p, ast.ClassDef) and not cls:
                    cls = p.name
            if (f"{cls}.{fn}" if cls else fn) == func and any(t.handlers for t in chain):
                wrong.append((name, func))
    assert wrong == [], "listed as raising, but a handler stands around the call: read it and list what it does"


# ------------------------------------------------------------------------------------------- another body is not kept
VALUE = "WANG XIAOMING"  # a made-up name, standing for a value of a row


def _answers(status: int, body: Any = None, text: str | None = None, headers: dict[str, str] | None = None) -> LakeHttp:
    def answer(request: httpx.Request) -> httpx.Response:
        if text is not None:
            return httpx.Response(status, text=text, headers=headers)
        return httpx.Response(status, json=body, headers=headers)

    lake = LakeHttp("http://lake")
    lake.client = httpx.Client(transport=httpx.MockTransport(answer))
    return lake


@pytest.mark.parametrize(
    ("status", "body", "text"),
    [
        (502, None, f"<html>Bad Gateway {VALUE}</html>"),
        (500, None, f"Traceback ... {VALUE}"),
        (500, [f"{VALUE}"], None),
        (500, {"detail": {"rows": [VALUE]}}, None),
        (500, {"error": VALUE}, None),
    ],
)
def test_an_answer_that_is_not_the_lakes_own_sentence_is_named_by_its_status_never_by_its_body(
    status: int, body: Any, text: str | None
) -> None:
    """Found by the review of NEW-B-30 by running: a proxy's page came through whole in the error of a rebuild,
    and from there into "lake rebuild failed: ..." in a night's report."""
    with pytest.raises(RuntimeError) as query:
        _answers(status, body, text).query("SELECT 1")
    with pytest.raises(RuntimeError) as rebuild:
        _answers(status, body, text).rebuild("2026-10-04")
    for got in (query, rebuild):
        assert VALUE not in str(got.value) and str(status) in str(got.value)


def test_the_lakes_own_sentence_is_kept_whole_as_before() -> None:
    said = "CatalogException: Catalog Error: Table with name site_fact does not exist!"
    with pytest.raises(RuntimeError) as got:
        _answers(422, {"detail": said}).query("SELECT 1")
    assert str(got.value) == f"lake query failed (422): {said}"
    from lake.store import BUSY_HEADER, RebuildError, SnapshotBuilding

    with pytest.raises(RebuildError) as refused:
        _answers(409, {"detail": "lake snapshot 2026-10-04 would drop 9 records"}).rebuild("2026-10-04")
    assert str(refused.value) == "lake snapshot 2026-10-04 would drop 9 records"
    with pytest.raises(SnapshotBuilding):
        _answers(409, {"detail": "already building"}, headers={BUSY_HEADER: "building"}).rebuild("2026-10-04")
