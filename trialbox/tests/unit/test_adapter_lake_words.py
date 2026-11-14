"""NEW-B-28 (D-669): the adapter keeps the lake's safe answer also when the lake runs in the adapter's own process,
and the night's validation messages name the element and the kind of problem, not the validator's sentence.

D-664 made the lake service answer a failed build without the engine's text; D-668 left one path open: with
``TB_ADAPTER_LAKE=local`` the lake is a library call, and its raw error went into ``lake rebuild failed: ...``.
The HL7 validator's sentences quote what they refuse (``Unknown Code 'N18.30'``); up to 200 of them went into the
night's report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from adapter import cli, run_job, runs
from adapter.validate.validator import Hl7Validator
from lake import store

from tests.unit.test_adapter_run_job_main import NIGHT, _handed, lake_dir  # noqa: F401 (fixture)
from tests.unit.test_site_inputs import site  # noqa: F401 (fixture)

VALUE = "WANG XIAOMING"  # a made-up name, standing for a value of a row


class EngineError(Exception):
    """Stands for the engine's own error class: its text quotes the value it could not convert."""


def _engine(*_a: Any, **_k: Any) -> Any:
    raise EngineError(f"Conversion Error: Could not convert string '{VALUE}' to DATE")


@pytest.fixture
def local(lake_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    monkeypatch.setenv("TB_ADAPTER_LAKE", "local")
    return cli.build_config()[0]


# ------------------------------------------------------------------------------------------- the lake in this process
@pytest.mark.parametrize("call", ["rebuild", "build", "promote"])
def test_an_engine_error_of_the_local_lake_reaches_the_adapter_as_the_lakes_safe_answer(
    local: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, call: str, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(store.Lake, "rebuild", _engine)
    monkeypatch.setattr(store.Lake, "promote_built", _engine)
    with pytest.raises(Exception) as got:
        local.promote(NIGHT) if call == "promote" else getattr(local, call)(NIGHT, tmp_path)
    said = f"{type(got.value).__name__}: {got.value} {got.value.args!r}"
    assert VALUE not in said and "WANG" not in said
    assert "EngineError" in said and "LAKE-BUILD" in said  # the type, and the lake's own sentence for it
    assert (got.value.__cause__ is None and got.value.__context__ is None) or got.value.__suppress_context__
    assert VALUE not in caplog.text and "EngineError" in caplog.text  # the log: the type and where, not the text


@pytest.mark.parametrize(
    "exc",
    [
        store.RebuildError(f"lake snapshot {NIGHT} would drop 9 records of CURRENT 2026-10-03 (limit 50 %)"),
        store.SnapshotBuilding(f"lake snapshot {NIGHT} is being built"),
        store.LakeSaid(f"lake snapshot {NIGHT} is g2 now, not g1: it was built again since; nothing is promoted"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_the_lakes_own_refusals_pass_as_they_are_class_and_words(
    local: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exc: Exception
) -> None:
    def refuses(*_a: Any, **_k: Any) -> Any:
        raise exc

    monkeypatch.setattr(store.Lake, "rebuild", refuses)
    monkeypatch.setattr(store.Lake, "promote_built", refuses)
    with pytest.raises(type(exc)) as got:
        local.build(NIGHT, tmp_path)
    assert got.value is exc  # the publish reads the class (busy, refused) and the words ("built again since")
    with pytest.raises(type(exc)) as got:
        local.promote(NIGHT, "g1")
    assert got.value is exc


def test_a_night_whose_local_lake_failed_keeps_the_safe_answer_in_its_report(
    lake_dir: Path,  # noqa: F811
    site: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TB_ADAPTER_LAKE", "local")
    monkeypatch.setattr(store.Lake, "rebuild", _engine)
    argv, state = _handed(lake_dir, path=str(site["feed"]))
    assert run_job.main(argv) == 0
    end = runs.read(lake_dir, state["run"])
    assert end is not None and VALUE not in str(end)
    errors = (end.get("report") or {}).get("errors") or []
    assert any(e.startswith("lake rebuild failed: ") and "EngineError" in e and "LAKE-BUILD" in e for e in errors), end


# ------------------------------------------------------------------------------------------- the HL7 validator's words
def _outcome(issues: list[dict[str, Any]], fname: str = "r00003-Condition.json") -> dict[str, Any]:
    return {"resourceType": "Bundle", "entry": [{"resource": {
        "resourceType": "OperationOutcome",
        "extension": [{"url": "http://hl7.org/fhir/StructureDefinition/operationoutcome-file", "valueString": fname}],
        "issue": issues}}]}  # fmt: skip


MSG_ID = "http://hl7.org/fhir/StructureDefinition/operationoutcome-message-id"


def test_the_nights_validation_messages_name_the_element_and_the_kind_never_the_validators_sentence() -> None:
    doc = _outcome([
        {"severity": "error", "code": "code-invalid", "expression": ["Condition.code.coding[1].code"],
         "details": {"text": f"Unknown Code '{VALUE}'"},
         "extension": [{"url": MSG_ID, "valueCode": "Terminology_PassThrough_TX_Message"}]},
        {"severity": "error", "code": "invalid", "location": ["Condition.onsetDateTime"],
         "diagnostics": f"Not a valid date/time ({VALUE})"},
        {"severity": "fatal", "expression": ["Condition"], "details": {"text": f"cannot read {VALUE}"}},
    ])  # fmt: skip
    res = Hl7Validator._parse(doc, 4)
    assert res.errors == 1
    assert res.messages == [
        "r00003-Condition.json Condition.code.coding[1].code: code-invalid (Terminology_PassThrough_TX_Message)",
        "r00003-Condition.json Condition.onsetDateTime: invalid",
        "r00003-Condition.json Condition: error",
    ]
    assert VALUE not in str(res.messages)


def test_a_kind_or_message_id_that_is_not_a_plain_token_is_not_kept() -> None:
    doc = _outcome([
        {"severity": "error", "code": f"x {VALUE}", "expression": ["Patient.name"],
         "extension": [{"url": MSG_ID, "valueCode": f"id '{VALUE}'"}], "details": {"text": VALUE}},
    ])  # fmt: skip
    res = Hl7Validator._parse(doc, 4)
    assert res.messages == ["r00003-Condition.json Patient.name: error"] and VALUE not in str(res.messages)


def test_the_file_name_and_the_place_are_kept_only_in_their_own_shapes() -> None:
    doc = _outcome(
        [{"severity": "error", "code": "invalid", "expression": [f"Patient.name.where(family = '{VALUE}')"]}],
        fname=f"/tmp/{VALUE}.json",
    )
    res = Hl7Validator._parse(doc, 4)
    assert VALUE not in str(res.messages) and res.messages == ["? ?: invalid"]


def test_the_claim_checks_own_lines_per_file_are_as_before() -> None:
    doc = _outcome([{"severity": "error", "expression": ["Bundle.entry[0]"], "details": {"text": "error"}}],
                   fname="r00001-Bundle.json")  # fmt: skip
    assert Hl7Validator._parse(doc, 3).per_file == {1: ["Bundle.entry[0]: error"]}  # TW-PAS reads these: not this card


# ------------------------------------------------------------------------------------------- the review's findings
def test_a_missing_snapshot_keeps_the_lakes_own_words_as_the_service_answers_it(
    local: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError(f"no lake snapshot {NIGHT}")

    monkeypatch.setattr(store.Lake, "promote_built", missing)
    with pytest.raises(FileNotFoundError, match=f"no lake snapshot {NIGHT}"):
        local.promote(NIGHT)


def test_a_wrong_setting_of_the_adapter_is_said_in_its_own_words_not_as_a_failed_build(
    local: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import embed_service.embedder as embedder

    def wrong(_name: str) -> Any:
        raise ValueError("TB_LAKE_EMBEDDER=nope: not an embedder this box has")

    monkeypatch.setattr(embedder, "from_env", wrong)
    with pytest.raises(ValueError, match="TB_LAKE_EMBEDDER=nope"):
        local.rebuild(NIGHT, tmp_path)


@pytest.mark.parametrize("extension", [3, True, "x", {"url": MSG_ID}, [3, "x", None]])
def test_an_issue_of_an_unexpected_shape_never_fails_the_validation_step(extension: Any) -> None:
    doc = _outcome([{"severity": "error", "code": "invalid", "expression": ["Patient.name"], "extension": extension}])
    assert Hl7Validator._parse(doc, 4).messages == ["r00003-Condition.json Patient.name: invalid"]


@pytest.mark.parametrize(
    ("place", "kept"),
    [
        ("Bundle.entry[0].resource.code.coding[12].code", True),
        (f"Patient.name[{VALUE.replace(' ', '-')}]", False),
        ("Patient.identifier:WANG", False),
        ("Patient.name.where(family = 'x')", False),
    ],
)
def test_an_element_is_kept_only_as_names_dots_and_numbered_places(place: str, kept: bool) -> None:
    doc = _outcome([{"severity": "error", "code": "invalid", "expression": [place]}])
    assert Hl7Validator._parse(doc, 4).messages == [f"r00003-Condition.json {place if kept else '?'}: invalid"]


def test_the_jp_core_code_checks_name_the_problem_never_the_code() -> None:
    from adapter.validate.jpcore import LOINC, JpCoreValidator

    res = {"resourceType": "Observation", "id": "o1", "status": "final",
           "code": {"coding": [{"system": LOINC, "code": VALUE}]}}  # fmt: skip
    out = JpCoreValidator().check(res)
    texts = [i.text for i in out.issues]
    assert any("not a valid LOINC code" in t for t in texts), texts
    assert VALUE not in str(texts)


def test_the_structural_validators_line_is_the_count_of_problems_or_the_errors_type() -> None:
    from adapter.validate.validator import StructuralValidator

    res = StructuralValidator().validate([
        {"resourceType": "Patient", "id": "p1", "birthDate": VALUE},
        {"resourceType": "Patient", "id": "p2", "contained": [{"resourceType": f"{VALUE}"}]},
    ])  # fmt: skip
    assert res.errors == 2 and VALUE not in str(res.messages), res.messages
