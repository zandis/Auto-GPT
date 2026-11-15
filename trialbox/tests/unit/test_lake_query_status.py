"""NEW-B-34 (D-675): the status of a failed lake query says who failed: the question (4xx) or the lake (5xx).

``/query`` answered its own failures (an I/O error, a stale snapshot, a limit) and the engine's complaint about
the question both with 422, and a snapshot that is not there with 404. A caller could not tell "my question is
wrong" (a fault of the code: stop) from "the lake is failing" (say so, try later, never read it as no data)."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient
from lake import app as lake_app
from lake import store
from lake.client import LakeHttp, LakeQueryFailed
from lake.sqlguard import SqlRejected

ROOT = Path(__file__).resolve().parents[2]
VALUE = "WANG XIAOMING"  # a made-up name, standing for a value of a row

#: what the lake's query can raise -> (status, a part of the answer)
QUESTION: list[tuple[BaseException, int, str]] = [
    (SqlRejected("only one SELECT is allowed"), 400, "only one SELECT"),
    (
        duckdb.CatalogException("Catalog Error: Table with name site_fact does not exist!"),
        422,
        "Table with name site_fact does not exist!",
    ),
    (
        duckdb.BinderException('Binder Error: Referenced column "contact_ok" not found in FROM clause!'),
        422,
        'Referenced column "contact_ok" not found',
    ),
    (duckdb.ParserException(f"Parser Error: syntax error at or near '{VALUE}'"), 422, "LAKE-QUERY"),
    (duckdb.ConversionException(f"Conversion Error: Could not convert string '{VALUE}' to DATE"), 422, "LAKE-QUERY"),
    (duckdb.InvalidInputException("Invalid Input Error: wrong number of parameters"), 422, "LAKE-QUERY"),
    (duckdb.NotImplementedException("Not implemented Error: this join"), 422, "LAKE-QUERY"),
]
LAKE: list[tuple[BaseException, int, str]] = [
    (FileNotFoundError("no lake snapshot 2026-10-04"), 503, "no lake snapshot 2026-10-04"),
    (FileNotFoundError("lake has no snapshot yet (run adapter / rebuild)"), 503, "no snapshot yet"),
    (store.StaleSnapshotError("LAKE-STALE: the snapshot 2026-10-01 is 9 days old"), 503, "LAKE-STALE"),
    (store.LakeLimitError("LAKE-LIMIT: the query needed more memory than the box allows"), 503, "LAKE-LIMIT"),
    (store.LakeSchemaError("LAKE-SCHEMA: the snapshot was built with layout 9"), 503, "LAKE-SCHEMA"),
    (duckdb.InterruptException("INTERRUPT Error: Interrupted!"), 503, "LAKE-QUERY"),
    (duckdb.IOException(f"IO Error: Could not read from file near '{VALUE}'"), 500, "LAKE-QUERY"),
    (duckdb.InternalException(f"INTERNAL Error: Attempted to access {VALUE}"), 500, "LAKE-QUERY"),
    (duckdb.FatalException("FATAL Error: the database is invalidated"), 500, "LAKE-QUERY"),
    (OSError(5, "Input/output error"), 500, "LAKE-QUERY"),
    (TypeError(f"'NoneType' object is not iterable: {VALUE}"), 500, "LAKE-QUERY"),
    (RuntimeError(f"something nobody expected about {VALUE}"), 500, "LAKE-QUERY"),
]


def _service(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> LakeHttp:
    class Fails:
        def query(self, *_a: Any, **_k: Any) -> Any:
            raise exc

    monkeypatch.setattr(lake_app, "lake", Fails)
    http = LakeHttp("http://testserver")
    http.client = TestClient(lake_app.app)
    return http


def _ids(case: Any) -> str:
    return type(case).__name__ if isinstance(case, BaseException) else ""


@pytest.mark.parametrize(("exc", "status", "says"), QUESTION, ids=_ids)
def test_a_fault_of_the_question_is_4xx_with_the_sentence_the_callers_read(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException, status: int, says: str
) -> None:
    with pytest.raises(LakeQueryFailed) as got:
        _service(monkeypatch, exc).query("SELECT 1")
    assert got.value.status == status and 400 <= got.value.status < 500
    assert says in str(got.value) and VALUE not in str(got.value)


@pytest.mark.parametrize(("exc", "status", "says"), LAKE, ids=_ids)
def test_a_failure_of_the_lake_is_5xx_503_where_it_cannot_serve_500_where_it_broke(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException, status: int, says: str
) -> None:
    with pytest.raises(LakeQueryFailed) as got:
        _service(monkeypatch, exc).query("SELECT 1")
    assert got.value.status == status and got.value.status >= 500  # the caller's rule: >= 500 is "the lake failed"
    assert says in str(got.value) and VALUE not in str(got.value)


def test_every_error_class_of_the_engine_is_placed_by_the_engines_own_grouping() -> None:
    """Not a list kept by hand: what the engine files under a wrong statement or wrong data is the question's;
    the rest is the lake's. A class the engine adds later is placed by its parent."""
    question = (duckdb.ProgrammingError, duckdb.DataError, duckdb.NotSupportedError, duckdb.IntegrityError)
    seen = 0
    for name in dir(duckdb):
        cls = getattr(duckdb, name)
        if not (isinstance(cls, type) and issubclass(cls, duckdb.Error)) or cls is duckdb.Error:
            continue
        seen += 1
        status = store.query_failure_status(cls("x"))
        if issubclass(cls, question):
            assert status == 422, name
        elif cls in (duckdb.InterruptException, duckdb.OutOfMemoryException):  # D-742: the box's limit too
            assert status == 503, name
        else:
            assert status == 500, name
    assert seen > 20


def test_a_real_lake_answers_a_wrong_question_with_422_and_a_snapshot_that_is_not_there_with_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from embed_service.embedder import HashEmbedder

    from tests.unit.test_polled_jobs import NIGHT, TZ, _patients

    lake_dir = tmp_path / "lake"
    _patients(lake_dir, NIGHT, 3)
    real = store.Lake(lake_dir, TZ)
    real.rebuild(NIGHT, HashEmbedder())
    monkeypatch.setattr(lake_app, "lake", lambda: real)
    http = LakeHttp("http://testserver")
    http.client = TestClient(lake_app.app)
    assert http.query("SELECT count(*) AS n FROM patient").to_pylist()[0]["n"] > 0
    for sql, status in (
        ("SELECT * FROM no_such_table", 400),  # the guard knows the lake's tables: refused before the engine
        ("SELECT no_such_column FROM patient", 422),
        ("SELECT CAST('x' AS DATE)", 422),
        ("DROP TABLE patient", 400),
    ):
        with pytest.raises(LakeQueryFailed) as got:
            http.query(sql)
        assert got.value.status == status, (sql, str(got.value))
    with pytest.raises(LakeQueryFailed) as gone:
        http.query("SELECT 1", snapshot="2031-01-01")
    assert gone.value.status == 503 and "no lake snapshot 2031-01-01" in str(gone.value)


def test_a_generation_header_that_is_none_is_the_requests_fault_not_a_broken_lake(tmp_path: Path) -> None:
    """Found by this card's review by running: the route's own 400 was raised inside the handler that turns every
    error into the lake's, and came out as 500 "the lake broke" (422 before this card)."""
    client = TestClient(lake_app.app)
    for headers, body in (
        ({"X-TB-Lake-Generation": "x"}, {"sql": "SELECT 1", "snapshot": "2026-10-04"}),
        ({"X-TB-Lake-Generation": "2"}, {"sql": "SELECT 1"}),  # a generation without its date
    ):
        r = client.post("/query", json=body, headers=headers)
        assert r.status_code == 400, (headers, r.status_code, r.text)


# ------------------------------------------------------------------------------------------- every caller of query()
GOES_ON = "no handler: the error goes on and the job or the request fails (5xx: the lake failed; 4xx: the code)"
NOT_THE_LAKE = "not the lake's client"
OPEN = "OPEN (its lane): catches every error, a 5xx too, and reads it as "
#: after train 14 (D-649 to D-652, lane A2): whether a table is there is asked of the lake, and a failure is said
UNREAD = "handler: any failure is said as 'could not be read' (D-652), never as none"
PROBE = "handler: a failure of the probe's own question answers 'not known'; the first failure then stops the run"
ASKS = "handler: only the lake's plain 0 for the table is 'no such table' (D-649); every other failure is raised"

#: (file under services/, function) -> what it does when the lake's query() raises. A new caller must be put here
#: by someone who read what it does with a 5xx (never "no data") and with a 4xx (a fault of the code: it stops).
CALLERS: dict[tuple[str, str], str] = {
    ("lake/app.py", "query"): "the route: answers the status this card is about",
    ("tb_common/derived_store.py", "rows_from_lake"): GOES_ON,
    ("tb_common/derived_store.py", "mapping_version_of"): GOES_ON,
    ("lake/client.py", "LakeLocal.query"): GOES_ON,
    ("lake/store.py", "Lake.vec_s2b"): GOES_ON,
    ("orchestrator/jobs.py", "PinnedLake.query"): GOES_ON,
    ("orchestrator/rerun.py", "PinnedLake.query"): GOES_ON,
    ("orchestrator/scenarios/case.py", "resolve_subject"): GOES_ON,
    ("orchestrator/scenarios/cohort.py", "items_at"): GOES_ON,
    ("orchestrator/scenarios/evaluate.py", "NoteJudge.window"): GOES_ON,
    ("orchestrator/scenarios/evaluate.py", "SqlEngine.evaluate"): GOES_ON,
    ("orchestrator/scenarios/facts.py", "_das28"): GOES_ON,
    ("orchestrator/scenarios/facts.py", "collect"): GOES_ON,
    ("orchestrator/scenarios/feas_compute.py", "compute"): GOES_ON,
    ("orchestrator/scenarios/microbatch.py", "run"): GOES_ON,
    ("orchestrator/scenarios/nav.py", "run"): GOES_ON,
    ("orchestrator/scenarios/screen.py", "deceased_now"): GOES_ON,
    ("orchestrator/scenarios/screen.py", "scope_patients"): GOES_ON,
    ("orchestrator/scenarios/screen_cascade.py", "held_in_snapshot"): GOES_ON,
    ("orchestrator/scenarios/twpas.py", "_latest"): GOES_ON,
    ("edc/prefill.py", "LakeFacts._q"): GOES_ON,
    ("matching/cascade/engine.py", "_Run.s0"): GOES_ON,
    ("matching/cascade/engine.py", "_Run.s1"): GOES_ON,
    ("matching/coverage.py", "Coverage.load"): GOES_ON,
    ("patient_profile/twin.py", "read_lake"): GOES_ON,
    ("vec/index.py", "snapshot_notes"): GOES_ON,
    ("criteria_compiler/equivalence/gate.py", "sql_evaluations"): GOES_ON,
    ("console/audit_page.py", "audit_patient"): NOT_THE_LAKE,  # a filter's query string
    ("matching/coded_values.py", "attach"): OPEN + "no coded value to show (display only; the answers stand)",
    ("orchestrator/scenarios/feas_profile.py", "build"): GOES_ON,
    ("orchestrator/scenarios/feas_profile.py", "data_facts"): UNREAD,
    ("tb_common/lakeprobe.py", "no_table"): PROBE,
    ("tb_common/lakeprobe.py", "rows_or_no_table"): ASKS,
    ("orchestrator/scenarios/screen.py", "practitioner_names"): OPEN + "no names (the settings' ids are shown)",
    # NEW-B-35 (D-676): asks the lake for the column, no handler. Its one caller in the services, the night step
    # ``twin.after_ingest``, never fails the ingest: it logs the error's type and keeps no twin (the same for
    # ``read_lake`` below)
    ("patient_profile/twin.py", "lake_schema"): GOES_ON,
    ("sitesetup/readiness.py", "unknown_share"): OPEN + "(0, 0), a lake with no diagnosis",
    ("sitesetup/readiness.py", "feed_loaded"): OPEN + "no feed loaded",
}


def _query_callers() -> dict[tuple[str, str], bool]:
    """Every ``x.query(...)`` call in ``services/`` and ``libs/``: (file under it, function) -> a ``try`` with a
    handler stands around at least one of the function's calls. The tools (``tools/``) are not listed: each fails
    with the error."""
    found: dict[tuple[str, str], bool] = {}
    files = [(f, root) for root in (ROOT / "services", ROOT / "libs") for f in sorted(root.rglob("*.py"))]
    for f, root in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        parent: dict[ast.AST, ast.AST] = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "query"):
                continue
            fn, cls, handled = "", "", False
            p: ast.AST = n
            while p in parent:
                child: ast.AST = p
                p = parent[p]
                if isinstance(p, ast.Try) and child in p.body and p.handlers and not fn:
                    handled = True
                if isinstance(p, ast.With) and "suppress" in ast.unparse(p.items[0].context_expr) and not fn:
                    handled = True
                if isinstance(p, ast.FunctionDef | ast.AsyncFunctionDef) and not fn:
                    fn = p.name
                if isinstance(p, ast.ClassDef) and not cls:
                    cls = p.name
            key = (f.relative_to(root).as_posix(), f"{cls}.{fn}" if cls else fn or "<module>")
            found[key] = found.get(key, False) or handled
    return found


def test_every_caller_of_query_is_listed_with_what_it_does_when_the_lake_fails() -> None:
    found = _query_callers()
    assert set(found) - set(CALLERS) == set(), "a new caller of query(): read what it does on a 5xx and a 4xx"
    assert set(CALLERS) - set(found) == set(), "no longer there: take them off the list"


def test_the_callers_listed_as_going_on_have_no_handler_and_the_others_have_one() -> None:
    found = _query_callers()
    skip = {("lake/app.py", "query"), *(k for k, what in CALLERS.items() if what == NOT_THE_LAKE)}
    wrong = [k for k, what in CALLERS.items() if (what == GOES_ON) == found[k] and k not in skip]
    assert wrong == [], "the list and the code disagree about a handler around the call: read it again"
