"""The two public protocols of review test G-8 (plan v7 §7.1) as fixtures: ``tests/fixtures/public_protocols``.

Lane G's ``g8-protocols`` part compiles every ``.json``, ``.txt`` and ``.md`` file of that folder with the production
judge. The files are ClinicalTrials.gov study records (API v2), cut to four modules; the terms of ClinicalTrials.gov
ask that a copy names its source, the date the data were processed and every modification: each file's ``_source``
block does, and this test holds it. No other file may sit in the folder: G-8 would read it as a protocol.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parents[1] / "fixtures" / "public_protocols"
KEPT = {"identificationModule", "statusModule", "conditionsModule", "eligibilityModule"}
# record -> its condition and lines the review's pass rule of G-8 is about (LIFE-002: phases and alternative groups)
RECORDS = {
    "NCT03887455": ("Early Alzheimer's Disease", ("Extension Phase", "Core Study", "Mild Alzheimer's disease dementia",
                                                 "Mild Cognitive Impairment (MCI) due to Alzheimer's disease")),
    "NCT02629159": ("Rheumatoid Arthritis", ("methotrexate (MTX)", "Exclusion Criteria")),
}  # fmt: skip


def test_the_folder_holds_the_two_records_and_nothing_else() -> None:
    assert sorted(f.name for f in FOLDER.iterdir()) == sorted(f"{n}.json" for n in RECORDS)


@pytest.mark.parametrize("nct", sorted(RECORDS))
def test_a_record_reads_as_g8_reads_it_and_says_where_it_is_from(nct: str) -> None:
    doc = json.loads((FOLDER / f"{nct}.json").read_text(encoding="utf-8"))
    ps = doc["protocolSection"]
    assert set(ps) == KEPT and set(doc) == {"_source", "protocolSection"}
    condition, lines = RECORDS[nct]
    assert ps["identificationModule"]["nctId"] == nct and ps["identificationModule"]["briefTitle"]
    assert ps["conditionsModule"]["conditions"] == [condition]
    text = ps["eligibilityModule"]["eligibilityCriteria"]
    assert all(line in text for line in lines)
    src = doc["_source"]
    assert src["registry"] == "ClinicalTrials.gov" and src["url"].endswith(nct)
    assert src["processed_by_clinicaltrials_gov"] and src["downloaded"] and len(src["record_sha256"]) == 64
    assert all(k in src["modifications"] for k in KEPT)
