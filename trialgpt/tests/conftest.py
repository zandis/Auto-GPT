"""Shared fixtures: an isolated data/results tree and a deterministic mock LLM (no model needed).

The mock answers the three NCBI prompts:
* keyword generation -> a summary and the first nouns of the note as conditions;
* matching -> one verdict per numbered criterion in the prompt: "included"/"not excluded" by default,
  "not included"/"excluded" when the criterion text contains NEGATIVE or ``REQUIRES:<term>`` with a term absent from
  the patient note, invalid labels when it contains GARBLED;
* aggregation -> R = 80 and E = 60 (or -60 when any criterion failed).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

CALLS: list[dict[str, Any]] = []
REAL_CLIENT = httpx.Client  # before any patching


def _criteria_in(user: str) -> list[tuple[str, str]]:
    block = user.split("Here is the clinical trial:", 1)[-1]
    return re.findall(r"^\s*(\d+)\. (.+)$", block, flags=re.M)


def mock_answer(messages: list[dict[str, str]]) -> str:
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
    for idx, text in _criteria_in(user):
        if "GARBLED" in text:
            out[idx] = ["?", [], "maybe"]
        elif (req := re.search(r"REQUIRES:(\S+)", text)) and req.group(1) not in user.split(
            "Here is the clinical trial:"
        )[0]:
            out[idx] = ["mock reasoning", [], "not included" if kind == "inclusion" else "excluded"]
        elif "NEGATIVE" in text:
            out[idx] = ["mock reasoning", [0], "not included" if kind == "inclusion" else "excluded"]
        else:
            out[idx] = ["mock reasoning", [0], "Included" if kind == "inclusion" else "not excluded"]
    return "```json\n" + json.dumps(out) + "\n```"


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    CALLS.append(body)
    text = mock_answer(body["messages"])
    if request.url.path.endswith("/api/chat"):
        return httpx.Response(200, json={"message": {"content": text}, "prompt_eval_count": 500, "eval_count": 50})
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 50},
        },
    )


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Every test gets its own data/results/cache dirs and the mock LLM; nothing touches the network."""
    for k, sub in (("TG_DATA_DIR", "data"), ("TG_RESULTS_DIR", "results"), ("TG_CACHE_DIR", "cache")):
        monkeypatch.setenv(k, str(tmp_path / sub))
    monkeypatch.setenv("TG_LLM_MODEL", "mock-model")
    monkeypatch.setenv("TG_LLM_NUM_CTX", "4096")
    monkeypatch.setattr(httpx, "Client", lambda **kw: REAL_CLIENT(**{"transport": httpx.MockTransport(handler), **kw}))
    CALLS.clear()
    yield tmp_path


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


@pytest.fixture
def mini_cohort(isolated: Path) -> str:
    """A two-patient synthetic 'sigir' cohort in NCBI's layout (fake data, not the real collection)."""
    d = isolated / "data" / "ncbi" / "sigir"
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
        json.dumps({p: {"raw": pats[p], "gpt-4-turbo": {"summary": "", "conditions": ["gout"]}} for p in pats})
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
