"""SPEC §11.1 LLM layer (not CPU CI: needs a real model).

* ``ir_extract`` on 5 English eligibility texts (ClinicalTrials.gov-style: the four synthetic registry records +
  GZQO) against their gold IR — structural agreement per criterion (class, domains, quantifier, value, window);
* ``concept_map`` on 200 concepts drawn from the terminology tables (ICD-10-CM EN/zh, LOINC EN/zh, ATC) — the top
  choice must be the expected code;
* the ``judge`` set (300 items) is in ``tests/unit/test_judge_tier.py::test_judge_set_agreement_real_model``.

    TB_LLM_EVAL_URL=http://<vllm>:8000/v1 TB_LLM_EVAL_MODEL=<served name> pytest -m llm tests/llm
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.llm
ROOT = Path(__file__).resolve().parents[2]
CASSETTES = ROOT / "services/llm_stub/cassettes/ir_extract"
TERM = ROOT / "services/criteria_compiler/terminology/src"
GOLD = ["NCT99000001", "NCT99000002", "NCT99000003", "NCT99000004", "GZQO"]


@pytest.fixture(scope="module")
def llm() -> Any:
    url = os.environ.get("TB_LLM_EVAL_URL")
    if not url:
        pytest.skip("TB_LLM_EVAL_URL not set (real model required)")
    from tb_common.llm import LlmClient

    return LlmClient(url, os.environ.get("TB_LLM_EVAL_MODEL", "trialbox"))


def _atoms(logic: dict[str, Any]) -> list[dict[str, Any]]:
    if logic.get("op") in ("and", "or", "not"):
        return [a for x in logic.get("args", []) for a in _atoms(x)]
    return [logic]


def _shape(c: dict[str, Any]) -> Any:
    """What must agree: class, and for structured criteria the atoms' domain, quantifier, comparator and window."""
    if c.get("class") != "structured":
        return (c.get("class"),)
    return (
        "structured",
        sorted(
            (
                a.get("domain"),
                a.get("quantifier", "any"),
                (a.get("value") or {}).get("op"),
                (a.get("value") or {}).get("num"),
                (a.get("window") or {}).get("from_days"),
            )
            for a in _atoms(c.get("logic") or {})
        ),
    )


def test_ir_extract_against_gold(llm: Any) -> None:
    from tb_common.phi_guard import scan

    agree = total = 0
    misses: list[str] = []
    for rid in GOLD:
        gold = json.loads((CASSETTES / f"{rid}.json").read_text(encoding="utf-8"))["criteria"]
        lines = [{"text": c["text"], "kind": c["kind"], "source_ref": c["source_ref"]} for c in gold]
        guard = scan("\n".join(x["text"] for x in lines), None)
        out = llm.chat_json(
            "ir_extract",
            {"ruleset": rid, "language": "en", "criteria": lines},
            job_id="LLM-EVAL",
            clearance=guard.clearance,
            phi_guard_hit=guard.hit,
        ).data["criteria"]
        assert len(out) == len(gold), rid
        for g, o in zip(gold, out, strict=True):
            total += 1
            if _shape(g) == _shape(o):
                agree += 1
            else:
                misses.append(f"{rid}: {g['text'][:60]}")
    rate = agree / total
    print(f"ir_extract structural agreement {rate:.1%} ({agree}/{total})")
    assert rate >= 0.80, misses[:10]


def _concepts() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    with (TERM / "icd10cm_tw.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out += [("condition", r["display"], r["code"]), ("condition", r["display_zh"], r["code"])]
    with (TERM / "loinc_tw.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out += [("observation", r["display"], r["code"]), ("observation", r["display_zh"], r["code"])]
    with (TERM / "atc.csv").open(encoding="utf-8") as fh:
        out += [("medication", r["display"], r["code"]) for r in csv.DictReader(fh)]
    with (TERM / "synonyms.csv").open(encoding="utf-8") as fh:  # exact-code synonyms (trial vocabulary)
        out += [(r["domain"], r["name"], r["code"]) for r in csv.DictReader(fh) if r["match"] == "exact"]
    seen: set[tuple[str, str]] = set()
    uniq = []
    for d, n, c in out:
        if n and (d, n) not in seen:
            seen.add((d, n))
            uniq.append((d, n, c))
    return uniq[:200]


def test_concept_map_200(llm: Any) -> None:
    from criteria_compiler.terminology.mapper import Terminology
    from tb_common.phi_guard import scan

    term = Terminology()
    items = _concepts()
    assert len(items) == 200, len(items)
    right = asked = 0
    for domain, name, code in items:
        cands = term.candidates(domain, [name], 10)
        if code not in {c.code for c in cands}:
            continue  # candidate retrieval miss: not the model's error
        variables = {
            "concept": name,
            "domain": domain,
            "candidates": [{"code": c.code, "system": c.system, "display": c.display} for c in cands],
        }
        guard = scan(json.dumps(variables, ensure_ascii=False), None)
        res = llm.chat_json("concept_map", variables, job_id="LLM-EVAL", clearance=guard.clearance)
        choices = res.data.get("choices") or []
        asked += 1
        right += bool(choices) and choices[0]["code"] == code
    print(f"concept_map top-1 {right}/{asked}")
    assert asked >= 100 and right / asked >= 0.90
