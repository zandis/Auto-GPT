"""NEW-TRUST-10 (D-707): what a validator said of a patient's bundle stays on that patient's row.

The FHIR validator's sentences quote values of the resource they judge (a gender code, a date, a decimal, each in
quotes; confirmed on the real validator by lane E's #520). TW-PAS keeps them where they belong: in the NAV run's
validation report and on the patient's row of the NAV list, both patient-level outputs for the readers of that
list. A SUBMIT that refused the bundle copied them into the job's error, which is the job's record: the job page
(also for an account that does not read that patient), the Failed mail's text and the audit of the refusal. The
job's error now says how many problems there are and where they are. Synthetic data only."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator.clients import StepFailed
from orchestrator.scenarios import submit

PID = "ab" * 16
VALUE = "A1234567"
SAID = [f"Patient.gender: the value provided ('{VALUE}') is not in the value set", f"birthDate '{VALUE}' is not a date"]


def _ctx(entry: dict[str, Any], validator: str = "hl7-validator") -> tuple[Any, Any]:
    report = {"validator": validator, "bundles": [{"pid": PID, "file": "twpas_GZQO_abababababab.json", **entry}]}
    store = SimpleNamespace(get=lambda key: json.dumps(report).encode())
    nav = SimpleNamespace(job_id="01HZZZZZZZZZZZZZZZZZZZZZZZ",
                          outputs=[SimpleNamespace(filename="twpas_validation_GZQO.json", minio_key="k")])  # fmt: skip
    return SimpleNamespace(store=store), nav


def test_a_refused_bundle_leaves_a_count_in_the_jobs_error_not_the_validators_sentences() -> None:
    ctx, nav = _ctx({"validator_errors": SAID, "precheck": {"passed": False, "issues": [f"age '{VALUE}' too low"]}})
    with pytest.raises(StepFailed) as said:
        submit._check_validation(ctx, nav, "GZQO", PID, live=True)
    text = said.value.message + (said.value.detail or "")
    assert VALUE not in text
    assert "3 problem(s)" in text and "twpas_validation_GZQO.json" in text and nav.job_id in text


def test_a_pre_check_that_failed_without_a_sentence_is_not_said_to_have_problems_listed() -> None:
    ctx, nav = _ctx({"validator_errors": [], "precheck": {"passed": False, "issues": []}})
    with pytest.raises(StepFailed) as said:
        submit._check_validation(ctx, nav, "GZQO", PID, live=True)
    text = said.value.message + (said.value.detail or "")
    assert "0 problem" not in text and "listed" not in text
    assert "gave no reason" in text and "twpas_validation_GZQO.json" in text and nav.job_id in text


def test_a_live_submission_without_a_pre_check_says_so_without_the_engines_words() -> None:
    ctx, nav = _ctx({"validator_errors": [], "precheck": {"passed": None,
                                                           "issues": [f"pre-check evaluation error: bad '{VALUE}'"]}})  # fmt: skip
    with pytest.raises(StepFailed) as said:
        submit._check_validation(ctx, nav, "GZQO", PID, live=True)
    assert VALUE not in said.value.message and "pre-check did not run" in said.value.message
    # a dry run only notes it, in the job's summary (the job page and the mail's text): the same reduced words
    notes = submit._check_validation(ctx, nav, "GZQO", PID, live=False)
    assert any("pre-check did not run" in n for n in notes) and VALUE not in " ".join(notes)


def test_a_bundle_that_passed_is_not_refused() -> None:
    ctx, nav = _ctx({"validator_errors": [], "precheck": {"passed": True, "issues": []}})
    assert submit._check_validation(ctx, nav, "GZQO", PID, live=True) == []
