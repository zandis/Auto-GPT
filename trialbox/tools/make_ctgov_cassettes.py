"""Synthetic ClinicalTrials.gov data for COHORT trial simulation (SPEC §8.3) in CI and on the demo box.

Writes, from one definition:

* ``services/criteria_compiler/cassettes/ctgov/<condition-slug>.json`` — API v2 ``/studies`` responses (the shape of
  ``https://clinicaltrials.gov/api/v2/studies?query.cond=…&filter.overallStatus=RECRUITING&query.locn=…``) replayed
  by the compiler's CT.gov client when ``TB_CTGOV_MODE=cassette``;
* ``services/llm_stub/cassettes/ir_extract/<NCT id>.json`` — the gold extraction for each trial's eligibility text
  (stub LLM, like the protocol cassettes).

The four trials are fictional (``NCT990000xx`` ids are far beyond the registry's current range, titles carry
``[SYNTHETIC]``); their eligibility criteria use the concepts of the synthetic hospital so the simulation is
meaningful on the fixtures.

    python tools/make_ctgov_cassettes.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CTGOV_DIR = ROOT / "services" / "criteria_compiler" / "cassettes" / "ctgov"
IR_DIR = ROOT / "services" / "llm_stub" / "cassettes" / "ir_extract"

Rule = tuple[str, str, str, dict[str, Any], dict[str, Any]]  # kind, text, label, logic, extra


def _w(lo: int | None, hi: int | None = 0) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if lo is not None:
        out["from_days"] = lo
    if hi is not None:
        out["to_days"] = hi
    return out


def _cand(domain: str, name: str) -> dict[str, Any]:
    return {"cand": (domain, name, [])}


GOUT = {"domain": "condition", "concept": "gout", "quantifier": "any"}
SUA = {"domain": "observation", "concept": "serum urate", "quantifier": "latest"}
EGFR = {"domain": "observation", "derived": "egfr", "quantifier": "latest", "window": _w(-365)}
HUMAN = {"domain": "demographic"}

TRIALS: list[dict[str, Any]] = [
    {
        "nct": "NCT99000001",
        "title": "[SYNTHETIC] Phase 3 Study of a URAT1 Inhibitor in Gout With Inadequate Response to Allopurinol",
        "condition": "Gout",
        "phases": ["PHASE3"],
        "enrollment": 240,
        "sponsor": "Synthetic Pharma Co. (fictional)",
        "last_update": "2026-08-15",
        "min_age": "20 Years",
        "max_age": "75 Years",
        "locations": [("Synthetic Medical Center Taipei", "Taipei", "Taiwan"), ("Synthetic Clinic", "Tokyo", "Japan")],
        "rules": [
            (
                "inclusion",
                "Male or female aged 20 to 75 years.",
                "Age 20–75",
                {"domain": "demographic", "age": {"min": 20, "max": 75}},
                {},
            ),
            (
                "inclusion",
                "Diagnosis of gout according to the 2015 ACR/EULAR classification criteria.",
                "Gout",
                GOUT,
                _cand("condition", "gout"),
            ),
            (
                "inclusion",
                "Serum urate of 7.0 mg/dL or higher within 90 days before screening.",
                "sUA ≥7.0",
                {**SUA, "value": {"op": ">=", "num": 7.0, "unit": "mg/dL"}, "window": _w(-90)},
                _cand("observation", "serum urate"),
            ),
            (
                "inclusion",
                "Receiving urate-lowering therapy for at least 3 months.",
                "ULT ≥3 months",
                {
                    "domain": "medication",
                    "concept": "urate-lowering therapy",
                    "duration": {"min_days": 90, "gap_days": 30},
                    "window": _w(-180),
                },
                _cand("medication", "urate-lowering therapy"),
            ),
            (
                "inclusion",
                "At least 2 gout flares in the past 12 months.",
                "≥2 flares / 12 mo",
                {"domain": "condition", "concept": "gout", "quantifier": "count>=", "count": 2, "window": _w(-365)},
                _cand("condition", "gout"),
            ),
            (
                "exclusion",
                "Estimated GFR below 30 mL/min/1.73 m2.",
                "eGFR <30",
                {**EGFR, "value": {"op": "<", "num": 30, "unit": "mL/min/{1.73_m2}"}},
                {},
            ),
            (
                "exclusion",
                "ALT greater than 3 times the upper limit of normal.",
                "ALT >3×ULN",
                {
                    "domain": "observation",
                    "concept": "alt",
                    "quantifier": "latest",
                    "value": {"op": ">", "num": 120, "unit": "U/L"},
                    "window": _w(-180),
                },
                _cand("observation", "alt"),
            ),
            (
                "exclusion",
                "Malignancy within the past 5 years.",
                "Malignancy ≤5 y",
                {"domain": "condition", "concept": "malignancy", "quantifier": "any", "window": _w(-1825)},
                _cand("condition", "malignancy"),
            ),
            (
                "exclusion",
                "Pregnant or breastfeeding women.",
                "Pregnancy",
                {"domain": "condition", "concept": "pregnancy", "quantifier": "any", "window": _w(-280)},
                _cand("condition", "pregnancy"),
            ),
            (
                "exclusion",
                "Participation in another interventional study within 30 days.",
                "Other trial ≤30 d",
                HUMAN,
                {
                    "class": "human",
                    "human_question": "Has the patient joined another interventional study in the last 30 days?",
                },
            ),
        ],
    },
    {
        "nct": "NCT99000002",
        "title": "[SYNTHETIC] Interleukin-1 Beta Antibody for Flare Prophylaxis When Starting Urate-Lowering Therapy",
        "condition": "Gout",
        "phases": ["PHASE2"],
        "enrollment": 120,
        "sponsor": "Synthetic Biologics (fictional)",
        "last_update": "2026-07-01",
        "min_age": "18 Years",
        "max_age": None,
        "locations": [("Synthetic University Hospital", "Taichung", "Taiwan")],
        "rules": [
            (
                "inclusion",
                "Adults 18 years of age or older.",
                "Age ≥18",
                {"domain": "demographic", "age": {"min": 18}},
                {},
            ),
            ("inclusion", "Documented diagnosis of gout.", "Gout", GOUT, _cand("condition", "gout")),
            (
                "inclusion",
                "Serum urate of 6.8 mg/dL or higher.",
                "sUA ≥6.8",
                {**SUA, "value": {"op": ">=", "num": 6.8, "unit": "mg/dL"}, "window": _w(-365)},
                _cand("observation", "serum urate"),
            ),
            (
                "inclusion",
                "At least one gout flare in the past 6 months.",
                "≥1 flare / 6 mo",
                {"domain": "condition", "concept": "gout", "quantifier": "count>=", "count": 1, "window": _w(-180)},
                _cand("condition", "gout"),
            ),
            (
                "exclusion",
                "Active tuberculosis.",
                "Active TB",
                {"domain": "condition", "concept": "active tuberculosis", "quantifier": "any", "window": _w(-365)},
                _cand("condition", "active tuberculosis"),
            ),
            (
                "exclusion",
                "Chronic hepatitis B infection.",
                "Chronic HBV",
                {"domain": "condition", "concept": "chronic hepatitis b", "quantifier": "any"},
                _cand("condition", "chronic hepatitis b"),
            ),
            (
                "exclusion",
                "Serious infection within 30 days before randomization.",
                "Serious infection ≤30 d",
                {"domain": "condition", "concept": "serious infection", "quantifier": "any", "window": _w(-30)},
                _cand("condition", "serious infection"),
            ),
            (
                "exclusion",
                "Estimated GFR below 30 mL/min/1.73 m2.",
                "eGFR <30",
                {**EGFR, "value": {"op": "<", "num": 30, "unit": "mL/min/{1.73_m2}"}},
                {},
            ),
            (
                "exclusion",
                "History of heart failure.",
                "Heart failure",
                {"domain": "condition", "concept": "heart failure", "quantifier": "any"},
                _cand("condition", "heart failure"),
            ),
        ],
    },
    {
        "nct": "NCT99000003",
        "title": "[SYNTHETIC] Febuxostat Dose Titration in Gout With Chronic Kidney Disease Stage 3",
        "condition": "Gout",
        "phases": ["PHASE4"],
        "enrollment": 80,
        "sponsor": "Synthetic Kidney Research Group (fictional)",
        "last_update": "2026-06-20",
        "min_age": "20 Years",
        "max_age": None,
        "locations": [("Synthetic Kidney Center", "Osaka", "Japan")],
        "rules": [
            ("inclusion", "Age 20 years or older.", "Age ≥20", {"domain": "demographic", "age": {"min": 20}}, {}),
            ("inclusion", "Gout diagnosed by a physician.", "Gout", GOUT, _cand("condition", "gout")),
            (
                "inclusion",
                "Estimated GFR between 30 and 59 mL/min/1.73 m2.",
                "eGFR 30–59",
                {
                    "op": "and",
                    "args": [
                        {**EGFR, "value": {"op": ">=", "num": 30, "unit": "mL/min/{1.73_m2}"}},
                        {**EGFR, "value": {"op": "<", "num": 60, "unit": "mL/min/{1.73_m2}"}},
                    ],
                },
                {},
            ),
            (
                "inclusion",
                "Serum urate of 8.0 mg/dL or higher.",
                "sUA ≥8.0",
                {**SUA, "value": {"op": ">=", "num": 8.0, "unit": "mg/dL"}, "window": _w(-365)},
                _cand("observation", "serum urate"),
            ),
            (
                "exclusion",
                "Myocardial infarction or stroke within 6 months.",
                "MI/stroke ≤6 mo",
                {
                    "op": "or",
                    "args": [
                        {
                            "domain": "condition",
                            "concept": "myocardial infarction",
                            "quantifier": "any",
                            "window": _w(-180),
                        },
                        {"domain": "condition", "concept": "stroke", "quantifier": "any", "window": _w(-180)},
                    ],
                },
                {"cand": [("condition", "myocardial infarction", []), ("condition", "stroke", [])]},
            ),
            (
                "exclusion",
                "Malignancy within the past 5 years.",
                "Malignancy ≤5 y",
                {"domain": "condition", "concept": "malignancy", "quantifier": "any", "window": _w(-1825)},
                _cand("condition", "malignancy"),
            ),
            (
                "exclusion",
                "ALT greater than 3 times the upper limit of normal.",
                "ALT >3×ULN",
                {
                    "domain": "observation",
                    "concept": "alt",
                    "quantifier": "latest",
                    "value": {"op": ">", "num": 120, "unit": "U/L"},
                    "window": _w(-180),
                },
                _cand("observation", "alt"),
            ),
        ],
    },
    {
        "nct": "NCT99000004",
        "title": "[SYNTHETIC] JAK Inhibitor Versus Placebo in Rheumatoid Arthritis With Inadequate Response to MTX",
        "condition": "Rheumatoid Arthritis",
        "phases": ["PHASE3"],
        "enrollment": 300,
        "sponsor": "Synthetic Immunology Inc. (fictional)",
        "last_update": "2026-09-01",
        "min_age": "18 Years",
        "max_age": "75 Years",
        "locations": [
            ("Synthetic General Hospital", "Kaohsiung", "Taiwan"),
            ("Synthetic RA Clinic", "Nagoya", "Japan"),
        ],
        "rules": [
            (
                "inclusion",
                "Aged 18 to 75 years.",
                "Age 18–75",
                {"domain": "demographic", "age": {"min": 18, "max": 75}},
                {},
            ),
            (
                "inclusion",
                "Rheumatoid arthritis diagnosed at least 6 months before screening.",
                "RA ≥6 months",
                {
                    "domain": "condition",
                    "concept": "rheumatoid arthritis",
                    "quantifier": "any",
                    "window": {"to_days": -180},
                },
                _cand("condition", "rheumatoid arthritis"),
            ),
            (
                "inclusion",
                "Methotrexate for at least 3 months.",
                "MTX ≥3 months",
                {
                    "domain": "medication",
                    "concept": "methotrexate",
                    "duration": {"min_days": 90, "gap_days": 30},
                    "window": _w(-365),
                },
                _cand("medication", "methotrexate"),
            ),
            (
                "inclusion",
                "DAS28 greater than 5.1 within 90 days.",
                "DAS28 >5.1",
                {
                    "domain": "observation",
                    "derived": "das28",
                    "quantifier": "latest",
                    "value": {"op": ">", "num": 5.1},
                    "window": _w(-90),
                },
                {},
            ),
            (
                "exclusion",
                "Active tuberculosis within 1 year.",
                "Active TB",
                {"domain": "condition", "concept": "active tuberculosis", "quantifier": "any", "window": _w(-365)},
                _cand("condition", "active tuberculosis"),
            ),
            (
                "exclusion",
                "Positive hepatitis B surface antigen.",
                "HBsAg positive",
                {
                    "domain": "observation",
                    "concept": "hbsag",
                    "quantifier": "latest",
                    "value": {"op": "in", "codes": ["LA6576-8"]},
                },
                _cand("observation", "hbsag"),
            ),
            (
                "exclusion",
                "Malignancy within the past 5 years.",
                "Malignancy ≤5 y",
                {"domain": "condition", "concept": "malignancy", "quantifier": "any", "window": _w(-1825)},
                _cand("condition", "malignancy"),
            ),
            (
                "exclusion",
                "Serious infection within 30 days.",
                "Serious infection ≤30 d",
                {"domain": "condition", "concept": "serious infection", "quantifier": "any", "window": _w(-30)},
                _cand("condition", "serious infection"),
            ),
            (
                "exclusion",
                "Prior biologic DMARD within 1 year.",
                "Biologic ≤1 y",
                {"domain": "medication", "concept": "ra biologic", "quantifier": "any", "window": _w(-365)},
                _cand("medication", "ra biologic"),
            ),
        ],
    },
]


def eligibility_text(trial: dict[str, Any]) -> str:
    """CT.gov markdown-ish eligibility text: ``Inclusion Criteria:`` / ``Exclusion Criteria:`` with ``*`` bullets."""
    inc = [r[1] for r in trial["rules"] if r[0] == "inclusion"]
    exc = [r[1] for r in trial["rules"] if r[0] == "exclusion"]
    return (
        "Inclusion Criteria:\n\n"
        + "\n".join(f"* {t}" for t in inc)
        + "\n\nExclusion Criteria:\n\n"
        + "\n".join(f"* {t}" for t in exc)
    )


def study(trial: dict[str, Any]) -> dict[str, Any]:
    elig: dict[str, Any] = {
        "eligibilityCriteria": eligibility_text(trial),
        "healthyVolunteers": False,
        "sex": "ALL",
        "minimumAge": trial["min_age"],
        "stdAges": ["ADULT", "OLDER_ADULT"],
    }
    if trial["max_age"]:
        elig["maximumAge"] = trial["max_age"]
    return {
        "protocolSection": {
            "identificationModule": {"nctId": trial["nct"], "briefTitle": trial["title"]},
            "statusModule": {
                "overallStatus": "RECRUITING",
                "lastUpdatePostDateStruct": {"date": trial["last_update"], "type": "ACTUAL"},
            },
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": trial["sponsor"], "class": "INDUSTRY"}},
            "conditionsModule": {"conditions": [trial["condition"]]},
            "designModule": {
                "studyType": "INTERVENTIONAL",
                "phases": trial["phases"],
                "enrollmentInfo": {"count": trial["enrollment"], "type": "ESTIMATED"},
            },
            "eligibilityModule": elig,
            "contactsLocationsModule": {
                "locations": [
                    {"facility": f, "status": "RECRUITING", "city": c, "country": n} for f, c, n in trial["locations"]
                ]
            },
        },
        "hasResults": False,
    }


def slug(condition: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", condition.lower()).strip("-")


def cassette(trial: dict[str, Any]) -> dict[str, Any]:
    crit = []
    counts: dict[str, int] = {}
    for kind, text, label, logic, ex in trial["rules"]:
        counts[kind] = counts.get(kind, 0) + 1
        cands = ex.get("cand") or []
        if isinstance(cands, tuple):
            cands = [cands]
        c: dict[str, Any] = {
            "text": text,
            "label": label,
            "source_ref": f"{'Inclusion' if kind == 'inclusion' else 'Exclusion'} Criteria #{counts[kind]}",
            "kind": kind,
            "class": ex.get("class", "structured"),
            "time_sensitive": False,
            "logic": logic,
            "concept_candidates": [{"domain": d, "name": n, "synonyms": s} for d, n, s in cands],
        }
        for k in ("note_question", "fallback", "human_question"):
            if ex.get(k):
                c[k] = ex[k]
        crit.append(c)
    return {"criteria": crit}


def main() -> int:
    CTGOV_DIR.mkdir(parents=True, exist_ok=True)
    by_cond: dict[str, list[dict[str, Any]]] = {}
    for t in TRIALS:
        by_cond.setdefault(slug(t["condition"]), []).append(study(t))
        (IR_DIR / f"{t['nct']}.json").write_text(
            json.dumps(cassette(t), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    for s, studies in by_cond.items():
        (CTGOV_DIR / f"{s}.json").write_text(
            json.dumps({"studies": studies}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    print(f"wrote {len(TRIALS)} trials in {len(by_cond)} condition cassettes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
