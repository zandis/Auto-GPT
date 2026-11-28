"""U4 (valclass; REAL100K §3, REAL2 Q2): a Patient with no birthDate is its own validator class, not a validation
error. On the twin 7.1 % of persons have none; with the 0.5 % gate that one field decided every night's hold (a delta
night 3.6 %, a full night 0.399-0.568 % by sampling chance). The class is counted against the sampled Patients and
holds a night only above its own limit; a Patient with no birthDate and another error still counts as an error.
Synthetic resources only."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest
from adapter.pipeline import run_ingest
from adapter.validate.validator import (
    NO_BIRTHDATE_MAX_PCT,
    StructuralValidator,
    no_birthdate_hold,
    validate_sample,
)

from tests.unit.test_dataflow_lake_p0 import _cfg, _Lakes


def _patients(n: int, without: int, *, no_gender: int = 0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(n):
        p: dict[str, Any] = {"resourceType": "Patient", "id": f"p{i}", "gender": "female", "birthDate": "1960-03-01"}
        if i < without:
            del p["birthDate"]
        if i < no_gender:
            del p["gender"]
        out.append(p)
    return out


@pytest.mark.nodb
def test_an_absent_birthdate_is_its_own_class_and_not_an_error() -> None:
    res = validate_sample(StructuralValidator(), _patients(100, 7))
    assert (res.errors, res.no_birthdate, res.patients) == (0, 7, 100)
    assert res.error_pct == 0.0 and no_birthdate_hold(res) is None


@pytest.mark.nodb
def test_a_planted_real_error_still_counts() -> None:
    res = validate_sample(StructuralValidator(), _patients(100, 7, no_gender=1))
    assert (res.errors, res.no_birthdate) == (1, 7)
    assert "gender" in res.messages[0] and "birthDate" not in res.messages[0]


@pytest.mark.nodb
def test_the_class_holds_above_its_own_limit() -> None:
    over = int(NO_BIRTHDATE_MAX_PCT) + 1
    res = validate_sample(StructuralValidator(), _patients(100, over))
    assert res.errors == 0
    assert no_birthdate_hold(res) == (
        f"Patient.birthDate absent on {float(over):.2f}% of sampled patients exceeds {NO_BIRTHDATE_MAX_PCT}%"
    )
    assert no_birthdate_hold(validate_sample(StructuralValidator(), [])) is None


def _night(path: Path, without: int, total: int = 40) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with (path / "patient.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["mrn", "sex", "birth_date"])
        w.writeheader()
        for i in range(total):
            w.writerow({"mrn": f"{10000001 + i}", "sex": "F", "birth_date": "" if i < without else "1960-03-01"})


def test_a_night_with_absent_birthdates_passes_and_reports_the_class(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    cfg.sample_fraction = 1.0
    _night(tmp_path / "n1", without=3)
    rep = run_ingest(
        cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False, validator=StructuralValidator()
    )
    assert rep.passed, rep.errors
    assert rep.validation.errors == 0
    assert (rep.validation.no_birthdate, rep.validation.patients_sampled) == (3, 40)
    _night(tmp_path / "n2", without=30)
    rep = run_ingest(
        cfg, "csv", str(tmp_path / "n2"), snapshot="2026-10-02", load_fhir=False, validator=StructuralValidator()
    )
    assert not rep.passed and any("Patient.birthDate absent" in e for e in rep.errors or [])
