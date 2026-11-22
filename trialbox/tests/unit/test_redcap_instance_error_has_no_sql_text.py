from pathlib import Path
from typing import Any

import pytest

# Import the RealAdmin class from the tool under test.
from tools.redcap_instance import RealAdmin


def test_sql_exception_leaks_statement(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    The RealAdmin.sql method catches a RuntimeError from ``compose()`` and
    re‑raises a RuntimeError that includes the beginning of the raw SQL
    statement. If that statement contains patient identifiers, the exception
    message leaks private health data.

    This test forces ``compose()`` to raise a RuntimeError and then checks that
    the resulting exception message does **not** contain a synthetic patient
    identifier. The test will FAIL if the identifier appears in the message,
    proving the claim.
    """
    # Create a RealAdmin instance with a temporary work directory.
    admin = RealAdmin(work=Path(tmp_path))

    # Monkey‑patch the compose method so that it always raises a RuntimeError.
    def fake_compose(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("simulated compose failure")

    monkeypatch.setattr(admin, "compose", fake_compose)

    # A synthetic SQL statement that includes a patient identifier.
    patient_id = "MRN-12345"
    statement = f"INSERT INTO patients (mrn) VALUES ('{patient_id}')"

    # Call sql() and capture the raised RuntimeError.
    with pytest.raises(RuntimeError) as exc_info:
        admin.sql(statement)

    # The exception message should NOT contain the patient identifier.
    # If it does, the test fails, providing proof of the defect.
    assert patient_id not in str(exc_info.value), (
        f"Exception message leaks patient identifier: found '{patient_id}' in '{exc_info.value}'"
    )
