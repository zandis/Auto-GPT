"""NEW-LIFE-18 (plan v7, LIFE-002), D-919: the public RA trial NCT02629159 (upadacitinib, SELECT-COMPARE) as a fixture
whose structure is written down by reading the protocol, never copied from a model's output (lane G's validation
reset, 2026-11-14). The early-AD trial NCT03887455 is held the same way by ``test_protocol_structure`` and
``test_any_of_groups``.

Reading it found two shapes the compiler did not see, each now sent to a person:

* **A permission, not a requirement.** "Subjects with prior exposure to only one bDMARD … may be enrolled (up to 20 %
  of total study population)". Made a required inclusion, it excluded every bDMARD-naive patient, most of them,
  silently. "History of secondary Sjogren's Syndrome is permitted" is an exception inside an exclusion.
* **A line for part of the population** ("… criteria - does not apply to safety cohort", the early-AD trial
  TRAILBLAZER-ALZ 2's wording), shown on a synthetic line.

Public text (ClinicalTrials.gov, the fixture's ``_source``) and synthetic lines; no model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from criteria_compiler import structure
from doc_parser.parser import parse

ROOT = Path(__file__).resolve().parents[2]
RA = ROOT / "tests/fixtures/public_protocols/NCT02629159.json"

# read from the protocol: (kind, the line's opening words, what a person reads it as)
EXPECTED = [
    ("inclusion", "Adult male or female, at least 18 years old.", None),
    ("inclusion", "Diagnosis of RA for greater than or equal to 3 months.", None),
    ("inclusion", "Subjects must have been on oral or parenteral methotrexate", None),
    ("inclusion", "Meets the following minimum disease activity criteria", None),
    ("inclusion", "At least one of the following at Screening", {"alternatives_in_line"}),  # erosions OR RF OR ACPA
    ("inclusion", "Subjects with prior exposure to only one biological", {"permission"}),  # may be enrolled, up to 20 %
    ("inclusion", "Except for MTX, subject must have discontinued", None),
    ("exclusion", "Prior exposure to any Janus kinase (JAK) inhibitor", None),
    ("exclusion", "Subjects who have been exposed to adalimumab", None),
    ("exclusion", "History of inflammatory joint disease other than RA.", {"permission"}),  # Sjogren's permitted
]


def _lines() -> list[dict[str, str]]:
    doc = json.loads(RA.read_text(encoding="utf-8"))
    text = doc["protocolSection"]["eligibilityModule"]["eligibilityCriteria"]
    block = parse(text.encode(), "NCT02629159.txt").ie_block
    return [{"text": str(x), "kind": k} for k in ("inclusion", "exclusion") for x in getattr(block, k)]


def test_the_parser_reads_the_ra_trial_as_a_person_does() -> None:
    lines = _lines()
    assert [(ln["kind"], ln["text"][: len(start)]) for ln, (_, start, _) in zip(lines, EXPECTED, strict=True)] == [
        (kind, start) for kind, start, _ in EXPECTED
    ]


def test_the_structure_check_sends_the_permissions_and_the_alternatives_to_a_person() -> None:
    rep = structure.check(_lines())
    got = {i: {f.flag for f in fs} for i, fs in rep.by_index().items()}
    assert got == {i: flags for i, (_, _, flags) in enumerate(EXPECTED) if flags}
    assert all(q for flag, q in structure.QUESTIONS if flag in ("permission", "part_population"))


@pytest.mark.parametrize(
    ("text", "flag"),
    [
        ("Meet 18F flortaucipir PET scan (central read) criteria - does not apply to safety cohort", "part_population"),
        ("Applies only to participants in the open-label part", "part_population"),
        ("Patients previously treated with one TNF inhibitor may be enrolled", "permission"),
        ("Stable low-dose prednisone (≤ 10 mg/day) is allowed", "permission"),
        ("曾使用一種生物製劑者可納入", "permission"),
        ("前治療が1剤までの患者は組み入れ可とする", "permission"),
    ],
)
def test_a_permission_or_a_part_of_the_population_is_found(text: str, flag: str) -> None:
    rep = structure.check([{"text": text, "kind": "inclusion"}])
    assert flag in {f.flag for f in rep.findings}, text


@pytest.mark.parametrize(
    "text",
    [
        "Diagnosis of RA for greater than or equal to 3 months.",
        "Must be willing and able to comply with the protocol",
        "Women of childbearing potential must use contraception",
        "Prior exposure to any Janus kinase (JAK) inhibitor",
        "The patient may have received methotrexate",  # "may have", not "may be enrolled"
    ],
)
def test_a_plain_requirement_is_left_alone(text: str) -> None:
    assert not structure.check([{"text": text, "kind": "inclusion"}]).findings
