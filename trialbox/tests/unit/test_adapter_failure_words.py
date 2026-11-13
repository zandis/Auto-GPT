"""NEW-B-27 (D-668): what the adapter keeps of a failure it did not expect is the error's type, never its text.

An unexpected error's text is written by code the adapter does not own (a driver, a parser, the standard library),
and such a text quotes the thing it choked on: a row's value. The run record is read by the orchestrator and goes
into the job's error and the mail; the ingest report's errors go the same way. The adapter's own sentences, which it
wrote knowing what they hold, stay whole. The full text and the traceback stay in the adapter's log."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from adapter import failure, pipeline, publish, run_job, runs
from adapter.mapping.engine import MappingError
from adapter.validate.validator import StructuralValidator
from tb_common import feedguard
from tb_common.crypto import KeyMissingError

from tests.unit.test_adapter_run_job_main import _handed, lake_dir  # noqa: F401 (fixture)
from tests.unit.test_site_inputs import site  # noqa: F401 (fixture)

VALUE = "WANG XIAOMING"  # a made-up name, standing for a value of a row


def _unexpected() -> list[BaseException]:
    return [
        ValueError(f"could not convert string to float: '{VALUE}'"),
        KeyError(VALUE),
        RuntimeError(f"fhir-store transaction failed (422): the family name {VALUE} is not valid"),
        UnicodeDecodeError("utf-8", VALUE.encode(), 0, 1, f"invalid start byte near {VALUE}"),
        Exception(f"row 7 {VALUE} without quote marks"),
        OSError(5, f"Input/output error reading {VALUE}"),
    ]


@pytest.mark.parametrize("exc", _unexpected(), ids=lambda e: type(e).__name__)
def test_an_unexpected_errors_text_is_never_kept_and_its_type_is(exc: BaseException) -> None:
    said = failure.words(exc)
    assert VALUE not in said and "WANG" not in said
    assert said.startswith(type(exc).__name__)
    assert "log" in said  # where the rest is


@pytest.mark.parametrize(
    "exc",
    [
        pipeline.SiteKeyError("the site key is not the one this lake was written with (fingerprint ab12)"),
        pipeline.FutureNight("night 2031-01-01 is dated after today (2026-11-13 at the site): it is not ingested"),
        publish.NothingToPublish("no held night 2026-10-04 on this box (its folder has no held.json)"),
        runs.RunLockHeld("an ingest is already running (another process holds the run lock)"),
        feedguard.FeedGuardError("TB_FEED_MAX_DROP_PCT='x': give a number from 0 to 100"),
        KeyMissingError("key file /run/secrets/trialbox/site.key is missing"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_the_adapters_own_sentences_stay_whole(exc: BaseException) -> None:
    assert failure.words(exc) == f"{type(exc).__name__}: {exc}"


def test_a_mapping_error_keeps_its_words_up_to_the_first_value() -> None:
    said = failure.words(MappingError(f"lab.csv: the unit of {VALUE!r} is not in the look-up"))
    assert said == "MappingError: lab.csv: the unit of <value>"  # the form D-520 decided for a rejected row's key


def test_a_subclass_of_an_own_class_made_elsewhere_is_not_taken_for_the_adapters_own() -> None:
    class Odd(ValueError):
        pass

    assert VALUE not in failure.words(Odd(VALUE))


# ------------------------------------------------------------------------------------------- the run record, both forms
def _boom(*_a: Any, **_k: Any) -> Any:
    raise ValueError(f"could not convert string to float: '{VALUE}'")


def test_the_run_record_of_a_night_in_its_own_process_keeps_the_type_only(
    lake_dir: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "run_ingest", _boom)
    argv, state = _handed(lake_dir)
    assert run_job.main(argv) == 0
    end = runs.read(lake_dir, state["run"])
    assert end is not None and end["state"] == "failed"
    assert VALUE not in str(end) and end["detail"].startswith("ValueError")
    assert state["run"] in end["detail"]  # the run to look for in the log


def test_a_refused_night_keeps_its_sentence_in_the_run_record(
    lake_dir: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_a: Any, **_k: Any) -> Any:
        raise pipeline.SiteKeyError("the site key is not the one this lake was written with")

    monkeypatch.setattr(pipeline, "run_ingest", refuse)
    argv, state = _handed(lake_dir)
    assert run_job.main(argv) == 0
    end = runs.read(lake_dir, state["run"])
    assert end is not None and end["state"] == "refused"
    assert end["detail"] == "night refused: the site key is not the one this lake was written with"


def test_the_run_record_of_a_night_in_the_services_thread_keeps_the_type_only(
    site: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from adapter import app as adapter_app
    from adapter import cli
    from fastapi.testclient import TestClient

    assert cli.main(["keys-init"]) == 0
    monkeypatch.setenv("TB_ADAPTER_RUN", "thread")
    monkeypatch.setattr(adapter_app, "_runs", {})
    monkeypatch.setattr(adapter_app, "_running", threading.Lock())
    monkeypatch.setattr(adapter_app, "run_ingest", _boom)
    client = TestClient(adapter_app.app)
    started = client.post("/run", json={"source": "csv", "snapshot": "2026-10-04", "load_fhir": False})
    assert started.status_code == 202, started.text
    rid = started.json()["run"]
    for _ in range(2400):
        st = client.get(f"/run/{rid}").json()
        if st["state"] != "running":
            break
        threading.Event().wait(0.05)
    assert st["state"] == "failed"
    assert VALUE not in str(st) and st["detail"].startswith("ValueError") and rid in st["detail"]


# ------------------------------------------------------------------------------------------- the ingest report
def test_the_reports_line_for_a_validation_that_did_not_run_keeps_the_type_only(tmp_path: Path) -> None:
    from tests.unit.test_dataflow_lake_p0 import _cfg, _Lakes, _row
    from tests.unit.test_t723_publish_night import N1, _night

    class Chokes(StructuralValidator):
        def validate(self, *_a: Any, **_k: Any) -> Any:
            raise ValueError(f"could not convert string to float: '{VALUE}'")

    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    rep = pipeline.run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validator=Chokes()
    )
    lines = [e for e in rep.errors or [] if e.startswith("validation failed to run")]
    assert lines and not rep.passed
    assert VALUE not in str(rep.model_dump()) and "ValueError" in lines[0]


def test_the_reports_line_for_a_fhir_store_that_refused_keeps_the_type_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_dataflow_lake_p0 import _Lakes, _row
    from tests.unit.test_t723_publish_night import N1, _fhir_cfg, _night

    def refuses(*_a: Any, **_k: Any) -> Any:  # the store's answer names what it refused
        raise RuntimeError(f"fhir-store transaction failed (422): the family name {VALUE} is not valid")

    monkeypatch.setattr(publish, "sync_snapshot", refuses)
    cfg = _fhir_cfg(tmp_path, _Lakes(tmp_path / "lake"))
    rep = pipeline.run_ingest(
        cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")]), snapshot=N1, validate=False
    )
    lines = [e for e in rep.errors or [] if e.startswith("fhir-store")]
    assert lines and not rep.passed
    assert VALUE not in str(rep.model_dump()) and all("RuntimeError" in e for e in lines)
