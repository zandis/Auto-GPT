"""NEW-B-23 (D-664): the lake's error answers carry no value of a row.

A finding of lane C2's review: the lake answered a failed query with the engine's own message, and the engine quotes
what it could not handle ("Could not convert string 'female' to INT32"). That text travels: into a job's failure, its
mail, the audit log. The answer now says what failed in a fixed sentence; only messages that name tables and
columns (which callers read, e.g. "a missing table") are passed on, without the query's text."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.sqlguard import SqlRejected, check_select
from lake.store import Lake

NIGHT = "2026-10-04"
SECRET = "Tanaka-san"  # stands for a value of a row, or a literal in a caller's query


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from fastapi.testclient import TestClient
    from lake import app as lake_app

    d = tmp_path / "lake"
    nd = d / "ndjson" / NIGHT
    nd.mkdir(parents=True)
    pats = [{"resourceType": "Patient", "id": f"{SECRET}-{i}", "gender": "female"} for i in range(3)]
    (nd / "Patient.ndjson").write_text("".join(json.dumps(p) + "\n" for p in pats), encoding="utf-8")
    lake = Lake(d, "Asia/Taipei")
    lake.rebuild(NIGHT, HashEmbedder())
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    return TestClient(lake_app.app)


def test_an_engine_error_that_quotes_a_rows_value_is_answered_without_it(
    api: Any, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        r = api.post("/query", json={"sql": "SELECT CAST(pid AS INTEGER) AS n FROM patient"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert SECRET not in r.text
    assert detail.startswith("ConversionException: LAKE-QUERY: the lake's engine could not run the query")
    assert SECRET not in caplog.text  # nor in the log: it has the error's type and kind, not the engine's sentence
    assert "lake query failed: ConversionException (Conversion Error)" in caplog.text


def test_a_missing_column_is_still_named_and_the_querys_text_is_not_sent(api: Any) -> None:
    """Callers read these (a table or a column that is not there: "this lake has no such data"). The engine adds
    the query's own line under its message; a literal the caller wrote is in it."""
    r = api.post("/query", json={"sql": f"SELECT nosuch FROM patient WHERE pid = '{SECRET}'"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail.startswith("BinderException: Binder Error:") and '"nosuch"' in detail
    assert SECRET not in r.text and "LINE 1" not in detail and "\n" not in detail


def test_the_lakes_own_refusals_are_passed_on_whole(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from lake import app as lake_app
    from lake.store import LakeLimitError

    def limit(*a: Any, **kw: Any) -> Any:
        raise LakeLimitError("LAKE-LIMIT: the lake query needed more than the box allows (memory_limit 1GB)")

    monkeypatch.setattr(lake_app.lake(), "query", limit)
    r = api.post("/query", json={"sql": "SELECT 1"})
    assert r.status_code == 422 and r.json()["detail"] == (
        "LakeLimitError: LAKE-LIMIT: the lake query needed more than the box allows (memory_limit 1GB)"
    )


def test_sql_that_cannot_be_parsed_is_refused_without_its_text(api: Any) -> None:
    with pytest.raises(SqlRejected) as exc:
        check_select(f"SELEC '{SECRET}' FROM")
    assert SECRET not in str(exc.value) and str(exc.value).startswith("unparseable SQL")
    r = api.post("/query", json={"sql": f"SELEC '{SECRET}' FROM"})
    assert r.status_code == 400 and SECRET not in r.text


def test_a_build_that_fails_in_the_engine_says_so_without_a_rows_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rebuild job's ``failed`` detail goes into the night's errors, the audit event and a mail."""
    d = tmp_path / "lake"
    nd = d / "ndjson" / NIGHT
    nd.mkdir(parents=True)
    (nd / "Patient.ndjson").write_text(json.dumps({"resourceType": "Patient", "id": "p1"}) + "\n")
    lake = Lake(d, "Asia/Taipei")

    class ConversionException(Exception):
        pass

    def boom(*a: Any, **kw: Any) -> Any:
        raise ConversionException(f"Conversion Error: Could not convert string '{SECRET}' to INT32")

    monkeypatch.setattr(lake, "_rebuild", boom)
    job = lake.start_rebuild(NIGHT, HashEmbedder())
    assert job["state"] == "failed" and SECRET not in json.dumps(job)
    assert job["detail"].startswith("ConversionException: LAKE-BUILD:")


# ------------------------------------------------------------------------------------------------ review fixes
@pytest.mark.parametrize("sql", [
    # a PIVOT without a list of values takes its column names from the rows: each pid becomes a column name, and
    # an ordinary mistake then names them in the error's first line
    "SELECT * FROM (PIVOT patient ON pid USING count(*)) GROUP BY sex",
    "SELECT a + 1 FROM (PIVOT patient ON pid USING count(*)) a",
    # literals of the caller that the engine repeats in the first line of a Binder or Catalog error
    f"SELECT nextval('{SECRET}')",
    f"SELECT COLUMNS('{SECRET}') FROM patient",
    f"SELECT struct_extract({{'a': 1}}, '{SECRET}')",
    # values the engine prints without quotation marks, or with an apostrophe inside
    "SELECT strptime(pid, '%Y') FROM patient",
    "SELECT error(pid) FROM patient",
    "SELECT regexp_matches('x', pid || '(') FROM patient",
])  # fmt: skip
def test_no_engine_error_carries_a_value_or_a_literal_in_the_answer_or_the_log(
    api: Any, caplog: pytest.LogCaptureFixture, sql: str
) -> None:
    with caplog.at_level(logging.DEBUG):
        r = api.post("/query", json={"sql": sql})
    assert r.status_code in (400, 422), r.text
    for text in (r.text, caplog.text):
        assert "Tanaka" not in text and "tanaka" not in text, text[:600]


def test_only_the_two_sentences_callers_read_are_passed_on(api: Any) -> None:
    """A table or a column that is not there, named by an identifier (what a caller wrote, and what the cascade and
    the opt-out reader look for). Any other sentence of those error classes is the fixed one."""
    from lake.store import error_answer

    class CatalogException(Exception):
        pass

    class BinderException(Exception):
        pass

    assert error_answer(
        CatalogException("Catalog Error: Table with name document does not exist!\nDid you mean x")
    ) == ("CatalogException: Catalog Error: Table with name document does not exist!")
    assert error_answer(
        BinderException('Binder Error: Referenced column "nosuch" not found in FROM clause!\nLINE 1')
    ) == ('BinderException: Binder Error: Referenced column "nosuch" not found in FROM clause!')
    for text in (
        f"Catalog Error: Sequence with name {SECRET} does not exist!",
        f'Binder Error: column "{SECRET}" must appear in the GROUP BY clause',
        f"Catalog Error: Table with name {SECRET} x does not exist!",
    ):
        for kind in (CatalogException, BinderException):
            got = error_answer(kind(text))
            assert SECRET not in got and "LAKE-QUERY" in got


def test_sql_the_tokenizer_cannot_read_is_refused_as_unparseable_without_its_text(api: Any) -> None:
    r = api.post("/query", json={"sql": f"SELECT '{SECRET}"})  # an unterminated string
    assert r.status_code == 400 and r.json()["detail"].startswith("unparseable SQL") and SECRET not in r.text


def test_a_literal_used_as_a_table_is_refused_without_it(api: Any) -> None:
    r = api.post("/query", json={"sql": f"SELECT * FROM '{SECRET}.csv'"})
    assert r.status_code == 400 and SECRET not in r.text
    r = api.post("/query", json={"sql": "SELECT * FROM nosuchtable"})
    assert r.status_code == 400 and "nosuchtable" in r.json()["detail"]  # a name is still named


def test_a_failed_build_says_what_kind_of_failure_and_its_log_holds_no_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    d = tmp_path / "lake"
    nd = d / "ndjson" / NIGHT
    nd.mkdir(parents=True)
    (nd / "Patient.ndjson").write_text(json.dumps({"resourceType": "Patient", "id": "p1"}) + "\n")
    lake = Lake(d, "Asia/Taipei")

    class ConversionException(Exception):
        pass

    def engine(*a: Any, **kw: Any) -> Any:
        raise ConversionException(f"Conversion Error: Could not convert string '{SECRET}' to INT32")

    monkeypatch.setattr(lake, "_rebuild", engine)
    with caplog.at_level(logging.DEBUG):
        job = lake.start_rebuild(NIGHT, HashEmbedder())
    assert job["state"] == "failed" and job["detail"].startswith("ConversionException: LAKE-BUILD:")
    assert SECRET not in caplog.text and "lake rebuild of 2026-10-04 failed: ConversionException" in caplog.text
    assert "engine" in caplog.text  # where it failed (the frames), without the message

    def disk(*a: Any, **kw: Any) -> Any:
        raise OSError(28, "No space left on device", str(d / f"{SECRET}.parquet"))

    monkeypatch.setattr(lake, "_rebuild", disk)
    job = lake.start_rebuild(NIGHT, HashEmbedder())
    assert job["detail"] == "OSError: LAKE-BUILD: the lake could not build the snapshot: No space left on device"


def test_a_sentence_the_lake_wrote_itself_about_a_build_is_passed_on(
    tmp_path: Path,
) -> None:
    """Found by the whole suite: a build without promote of the served date is refused by a sentence of the lake's
    own ("... is served ..."); the job's detail must still say it. Only what the lake did not write is withheld."""
    d = tmp_path / "lake"
    nd = d / "ndjson" / NIGHT
    nd.mkdir(parents=True)
    (nd / "Patient.ndjson").write_text(json.dumps({"resourceType": "Patient", "id": "p1"}) + "\n")
    lake = Lake(d, "Asia/Taipei")
    lake.rebuild(NIGHT, HashEmbedder())
    job = lake.start_rebuild(NIGHT, HashEmbedder(), promote=False)
    assert job["state"] == "failed" and "is served: it is not built without promote" in job["detail"]
