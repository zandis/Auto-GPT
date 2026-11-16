"""G11 of the integrator's second review of the P1b run (#639, 2026-11-16), D-959: D-910 kept only the error's type
and status when the FHIR server refused a ruleset ("FhirEvalError, HTTP 422"), and the 422 left no log line: 16 of the
run's protocols failed with nothing to act on (an id over 64 characters, an encounter atom).

* The job's error and the log hold what the server said, masked by ``server_said``: a patient reference
  (``Patient/…``, ``subject=…``), an identifying key (``mrn=…``) and an identifier-shaped token are never kept.
* Long text is cut.

Synthetic server messages; no patient data.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from criteria_compiler.service import CompileFailed
from tb_common.fhir import FhirEvalError, server_said

from tests.unit.test_compiler_service import _compile, env  # noqa: F401


@pytest.mark.parametrize(
    ("raw", "kept", "gone"),
    [
        ("PUT ValueSet/SM2NCT00163709-VS-HISTOLOGICALLY-CONFIRMED-ESOPHAGEAL-SQUAMOUS-CELL-CARCINOMA: 422 "
         "HAPI-0450: Failed to parse request body as JSON resource. Error was: id too long",
         "HAPI-0450: Failed to parse request body", ""),
        ("$evaluate P123: 500 Patient/70000054 has no birthDate; subject=Patient/70000054", "has no birthDate",
         "70000054"),
        ("$evaluate: 422 mrn=70000054 not found", "not found", "70000054"),
    ],
)  # fmt: skip
def test_the_server_text_is_kept_and_masked(raw: str, kept: str, gone: str) -> None:
    said = server_said(FhirEvalError(raw))
    assert kept in said
    if gone:
        assert gone not in said


def test_long_text_is_cut() -> None:
    assert len(server_said(FhirEvalError("x " * 1000))) <= 300


class _Fhir:
    def load(self, libraries: list[dict[str, Any]], valuesets: Any) -> None:
        raise FhirEvalError("PUT ValueSet/X-VS-Y: 422 HAPI-0450: id too long; subject=Patient/70000054")


def test_an_equivalence_refusal_says_what_the_server_said_and_logs_it(
    env: dict[str, Any],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    deps = env["deps"]
    deps.equivalence, deps.fhir, deps.lake = None, _Fhir(), object()
    with caplog.at_level(logging.WARNING, logger="criteria-compiler"), pytest.raises(CompileFailed) as exc:
        _compile(env)
    msg = str(exc.value)
    assert exc.value.step == "equivalence" and "HAPI-0450: id too long" in msg and "70000054" not in msg
    assert any("HAPI-0450" in r.getMessage() and "70000054" not in r.getMessage() for r in caplog.records)
