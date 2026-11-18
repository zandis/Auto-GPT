"""D-1003: the nightly public-e2e run opens the studies it creates, and counts missing birth dates as the ingest does.

The run of 2026-11-18 (job 135068320597) crashed at stage 2: WALK-1 (D-1153) made a new study start in start-up, a
list runs only for an open study (D-386), and ``tools/public_e2e.py`` asked for SCREEN on the two studies stage 1
had just created. The journeys open a new study through its SAE check (tests/e2e/journeys/steps.py, J-CRC-08); the
run now does the same, each step a check. Its stage-0 check "missing birth dates reported, not invented" also failed
since B1: a note can state an age its record lacks, and that patient is written with a birth date, but the site's
summary counted ``age is None`` (120 against the ingest's 117 missing Patient.birthDate).
"""

from __future__ import annotations

import re
from pathlib import Path

from tools import public_site

ROOT = Path(__file__).resolve().parents[2]
RUN = (ROOT / "tools" / "public_e2e.py").read_text(encoding="utf-8")


def test_stage_two_opens_both_studies_before_it_asks_for_a_list() -> None:
    stage = RUN[RUN.index('Stage("2 screening') :]
    opened = stage.index("open_study(crc, rs, s)")
    assert "for rs in (TRIAL, COHORT):" in stage[:opened]
    assert opened < stage.index('"kind": "SCREEN"')


def test_it_opens_a_study_as_the_journeys_do() -> None:
    body = RUN[RUN.index("def open_study(") : RUN.index("\ndef ", RUN.index("def open_study(") + 5)]
    journeys = (ROOT / "tests" / "e2e" / "journeys" / "steps.py").read_text(encoding="utf-8")
    for route in ("/setup/sae", "/state"):
        assert route in body and route in journeys
    assert '"rule_set": "tw_trial"' in body and '{"rule_set": "tw_trial"}' in journeys
    assert '"state": "open"' in body and 'data-state="open"' in body
    assert len(re.findall(r"s\.check\(", body)) == 3  # each step says so when it does not hold


def _patient(age: int | None, birth: str) -> dict[str, object]:
    return {"source": "MedTxt-CR", "age": age, "age_approx": False, "birth_date": birth, "sex": None, "dx": []}


def test_the_summary_counts_the_patients_written_with_no_birth_date() -> None:
    patients = [
        _patient(None, ""),  # nothing stated anywhere
        _patient(None, "1960-03-01"),  # the record has no age; the note states one (B1)
        _patient(65, "1959-05-01"),
    ]
    assert public_site.summarise(patients, 0)["age_missing"] == 1
