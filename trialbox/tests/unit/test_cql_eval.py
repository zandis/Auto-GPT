"""tools/cql_eval.py (T-504, D-321): the local CQL engine answers as the HAPI FHIR 8.12 recordings do.

The engine needs a JDK and its jars (``python -m tools.cql_eval --fetch``); without them only the pure parts run.
"""

from __future__ import annotations

import json

import pytest

from tools import cql_eval


def test_patient_references_are_found_anywhere_in_a_resource() -> None:
    r = {"resourceType": "Observation", "subject": {"reference": "Patient/p-1"},
         "performer": [{"reference": "Practitioner/x"}], "focus": [{"reference": "Patient/p-2"}]}  # fmt: skip
    assert cql_eval._patient_refs(r) == {"p-1", "p-2"}
    assert cql_eval._patient_refs({"resourceType": "ValueSet", "id": "v"}) == set()


def test_the_engine_is_reported_missing_not_guessed(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    monkeypatch.setattr(cql_eval, "LIB", tmp_path)
    assert not cql_eval.available()
    with pytest.raises(RuntimeError, match="--fetch"):
        cql_eval.run([], "X", "1.0.0", __import__("datetime").date(2026, 11, 2), ["A"], ["p"])


@pytest.mark.skipif(not cql_eval.available(), reason="local CQL engine not fetched (python -m tools.cql_eval --fetch)")
def test_the_engine_reproduces_the_hapi_recording_of_ra_coh() -> None:
    agree, total, bad = cql_eval.check("RA-COH")
    assert total >= 1200 and agree == total, bad[:5]


def test_ra_jak_records_its_engine_and_known_differences() -> None:
    exp = json.loads((cql_eval.ROOT / "rulesets/RA-JAK/tests/expected.json").read_text(encoding="utf-8"))
    assert exp["engine"] == cql_eval.ENGINE
    assert exp["agreement"]["known_differences"] == {} and exp["agreement"]["all_equal"]  # UnitOf fixed (D-321)


@pytest.mark.skipif(not cql_eval.available(), reason="local CQL engine not fetched (python -m tools.cql_eval --fetch)")
def test_the_unit_of_a_result_is_recognised_under_the_engine() -> None:
    """The recompiled RA-BIO and GZQO (DAS28, unit conversions) answer as their HAPI recordings did (D-321)."""
    for rid in ("RA-BIO", "GZQO"):
        agree, total, bad = cql_eval.check(rid)
        assert total >= 3600 and agree == total, (rid, bad[:5])
