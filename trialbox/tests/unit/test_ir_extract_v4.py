"""G10 of the integrator's second review of the P1b run (#639, 2026-11-16), D-984: ir_extract v3's line "Use `derived`
= bmi | egfr | das28 | basdai | asdas" was copied into 29 criteria (atoms that are not those scores), 64 "Aged N years
or older" lines put the age in ``value``, and the model added placeholder ages (0-150) to other atoms.

* v4 names the scores only as what a line must say, puts an age in ``age``, and leaves unstated fields out; it is
  registered unqualified (``qualification: null``): PRODUCTION keeps serving the newest qualified version (D-359).
* Its canary is the run's own lines: v3's stored answers fail every one of them; a correct answer passes.

The run's lines (public SIGIR protocols).
"""

from __future__ import annotations

import json
from pathlib import Path

from tb_llm.prompt_registry import default_registry

from tools import ir_extract_canary as canary

ROOT = Path(__file__).resolve().parents[2]


def test_v4_is_registered_unqualified_and_production_keeps_its_version() -> None:
    reg = default_registry()
    assert reg.entry("ir_extract", 4).version == 4
    assert reg.served("ir_extract", "PRODUCTION").version != 4  # not qualified: never served to a hospital yet


def test_v4_lists_no_score_names_to_copy_and_says_where_an_age_goes() -> None:
    text = (ROOT / "libs/tb_llm/prompts/ir_extract_v4.md").read_text(encoding="utf-8")
    assert "bmi | egfr" not in text and "`age` {min, max} in whole years" in text
    assert "leave every other field out" in text


def test_the_canary_fails_v3s_answers_and_passes_a_correct_one() -> None:
    rows = [json.loads(x) for x in canary.CANARY.read_text(encoding="utf-8").splitlines()]
    assert len(rows) >= 100 and all(r["expect"] for r in rows)
    v3 = [{"text": "Aged 18 years or older", "logic": {"domain": "demographic", "concept": "age",
                                                       "value": {"op": ">=", "num": 18}}},
          {"text": "DISEASE CHARACTERISTICS: Histologically confirmed esophageal squamous cell cancer that is stage "
                   "T2-3 Nx M0", "logic": {"domain": "condition", "concept": "escc", "age": {"min": 0, "max": 150},
                                           "derived": "asdas"}}]  # fmt: skip
    good = [{"text": "Aged 18 years or older", "logic": {"domain": "demographic", "age": {"min": 18}}},
            {"text": v3[1]["text"], "logic": {"domain": "condition", "concept": "escc"}}]  # fmt: skip
    for answer, ok in ((v3, False), (good, True)):
        for a in answer:
            row = next(r for r in rows if r["text"] == a["text"])
            assert all(canary.holds(e, a["logic"]) for e in row["expect"]) is ok, a["text"]
