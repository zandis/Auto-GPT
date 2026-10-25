"""Offline helpers for the registry_match tests: a deterministic mock chat client and a synthetic NCBI-style cohort.

The mock answers the three NCBI prompts:
* keyword generation -> a summary and the first long words of the note as conditions;
* matching -> one verdict per numbered criterion in the prompt: "included"/"not excluded" by default,
  "not included"/"excluded" when the criterion text contains NEGATIVE or ``REQUIRES:<term>`` with a term absent from
  the patient note, invalid labels when it contains GARBLED;
* aggregation -> R = 80 and E = 60 (or -60 when any criterion failed).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from matching.registry_match.llm import ChatReply, Messages


def _criteria_in(user: str) -> list[tuple[str, str]]:
    block = user.split("Here is the clinical trial:", 1)[-1]
    return re.findall(r"^\s*(\d+)\. (.+)$", block, flags=re.M)


def mock_answer(messages: Messages) -> str:
    system, user = messages[0]["content"], messages[1]["content"]
    if "key conditions" in system:
        words = re.findall(r"[a-z]{6,}", user.lower())[:3]
        return json.dumps({"summary": "mock summary", "conditions": words or ["condition"]})
    if "relevance score (R)" in system:
        failed = "not included" in user or "Patient eligibility: excluded" in user
        return json.dumps(
            {
                "relevance_explanation": "mock",
                "relevance_score_R": 80,
                "eligibility_explanation": "mock",
                "eligibility_score_E": -60 if failed else 60,
            }
        )
    kind = "inclusion" if "inclusion criteria of a clinical trial" in system else "exclusion"
    out: dict[str, list[Any]] = {}
    patient = user.split("Here is the clinical trial:")[0]
    for idx, text in _criteria_in(user):
        req = re.search(r"REQUIRES:(\S+)", text)
        if "GARBLED" in text:
            out[idx] = ["?", [], "maybe"]
        elif req and req.group(1) not in patient:
            out[idx] = ["mock reasoning", [], "not included" if kind == "inclusion" else "excluded"]
        elif "NEGATIVE" in text:
            out[idx] = ["mock reasoning", [0], "not included" if kind == "inclusion" else "excluded"]
        else:
            out[idx] = ["mock reasoning", [0], "Included" if kind == "inclusion" else "not excluded"]
    return "```json\n" + json.dumps(out) + "\n```"


class MockChat:
    """A :class:`matching.registry_match.llm.ChatClient` that answers with :func:`mock_answer` and records calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, messages: Messages, *, json_mode: bool) -> ChatReply:
        self.calls.append({"messages": messages, "json_mode": json_mode})
        return ChatReply(mock_answer(messages), "mock-model", 500, 50)


def trial(nct: str, inc: list[str], exc: list[str], **kw: Any) -> dict[str, Any]:
    return {
        "NCTID": nct,
        "brief_title": f"Trial {nct}",
        "diseases_list": ["gout"],
        "drugs_list": ["drug x"],
        "brief_summary": "A trial.",
        "inclusion_criteria": "Inclusion Criteria:\n\n" + "\n\n".join(inc),
        "exclusion_criteria": "Exclusion Criteria:\n\n" + "\n\n".join(exc),
        "phase": "",
        "drugs": "",
        "diseases": "",
        "enrollment": "",
        **kw,
    }


def study(nct: str, title: str, conditions: list[str], criteria: str, **kw: Any) -> dict[str, Any]:
    """A minimal ClinicalTrials.gov API v2 study record (synthetic)."""
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": title},
            "statusModule": {"overallStatus": kw.get("status", "RECRUITING")},
            "conditionsModule": {"conditions": conditions},
            "eligibilityModule": {
                "eligibilityCriteria": criteria,
                "minimumAge": kw.get("min_age", "18 Years"),
                "sex": kw.get("sex", "ALL"),
            },
            "contactsLocationsModule": {"locations": [{"country": c} for c in kw.get("countries", [])]},
        }
    }


def make_mini_cohort(data_dir: Path) -> str:
    """A two-patient synthetic 'sigir' cohort in NCBI's layout (fake data, not the real collection)."""
    d = data_dir / "ncbi" / "sigir"
    (d / "qrels").mkdir(parents=True)
    pats = {
        "sigir-1": "A 60-year-old man with gout. He takes allopurinol.",
        "sigir-2": "A 45-year-old woman with rheumatoid arthritis on methotrexate.",
    }
    (d / "queries.jsonl").write_text("\n".join(json.dumps({"_id": k, "text": v}) for k, v in pats.items()))
    ts = {
        "NCT1": trial("NCT1", ["Adults with gout", "Serum urate above 6"], ["Pregnancy"]),
        "NCT2": trial("NCT2", ["Adults with gout", "NEGATIVE prior biologic"], ["Pregnancy"]),
        "NCT3": trial("NCT3", ["Adults", "Rheumatoid arthritis"], ["NEGATIVE active infection"]),
        "NCT4": trial("NCT4", ["GARBLED criterion", "Adults with lupus"], ["Pregnancy"]),
    }
    rel = {"sigir-1": {"NCT1": 2, "NCT2": 1, "NCT4": 0}, "sigir-2": {"NCT3": 1, "NCT4": 0, "NCT1": 0}}
    (d / "qrels" / "test.tsv").write_text(
        "query-id\tcorpus-id\tscore\n" + "".join(f"{p}\t{n}\t{s}\n" for p, r in rel.items() for n, s in r.items())
    )
    retrieved = [
        {
            "patient_id": p,
            "patient": pats[p],
            **{lab: [ts[n] for n, s in r.items() if str(s) == lab] for lab in ("0", "1", "2")},
        }
        for p, r in rel.items()
    ]
    (d / "retrieved_trials.json").write_text(json.dumps(retrieved))
    (d / "id2queries.json").write_text(
        json.dumps({p: {"raw": pats[p], "paper": {"summary": "", "conditions": ["gout"]}} for p in pats})
    )
    (d / "corpus.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "_id": n,
                    "title": t["brief_title"],
                    "text": t["brief_summary"],
                    "metadata": {k: v for k, v in t.items() if k != "NCTID"},
                }
            )
            for n, t in ts.items()
        )
    )
    return "sigir"
