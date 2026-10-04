"""Synthetic alliance cohort definitions (SPEC §8.3): GOUT-COH and RA-COH.

Writes, per cohort, a fictional zh-TW definition document (PDF + DOCX) in ``tests/fixtures/protocols/`` and the gold
extraction cassette for the stub LLM; ``tools/build_rulesets.py --kind cohort`` then compiles and approves them through
the real pipeline. Section 1 (世代定義) holds the population criterion, section 2 (計數條件) the characteristics
counted inside the population (both parse as inclusion criteria; the manifest's ``cohort.population_criterion``
names the population, DECISIONS D-71).

    python tools/make_cohort_docs.py && python tools/make_cohort_docs.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.make_nhi_docs import cassette, write_docx, write_pdf  # noqa: E402

SECTIONS = {"inclusion": "1 世代定義", "inclusion2": "2 計數條件"}
FRONT_NOTE = "本文件為 TrialBox 測試用之虛構聯盟世代定義，用於季度「主要條件 × 人數」統計，並非任何機構之正式文件。"


def _w(lo: int) -> dict[str, int]:
    return {"from_days": lo, "to_days": 0}


GOUT_RULES: list[tuple[str, str, str, dict[str, Any], dict[str, Any]]] = [
    (
        "inclusion",
        "曾經診斷痛風（ICD-10-CM M10 或 M1A）之病人。",
        "痛風診斷",
        {"domain": "condition", "concept": "gout", "quantifier": "any"},
        {"cand": ("condition", "gout", ["痛風"])},
    ),
    (
        "inclusion2",
        "一年內最近一次血清尿酸值大於或等於 6.0 mg/dL。",
        "尿酸≥6.0",
        {
            "domain": "observation",
            "concept": "serum urate",
            "quantifier": "latest",
            "value": {"op": ">=", "num": 6.0, "unit": "mg/dL"},
            "window": _w(-365),
        },
        {"cand": ("observation", "serum urate", ["尿酸"])},
    ),
    (
        "inclusion2",
        "六個月內曾使用降尿酸藥物。",
        "降尿酸藥物",
        {"domain": "medication", "concept": "urate-lowering therapy", "quantifier": "any", "window": _w(-180)},
        {"cand": ("medication", "urate-lowering therapy", ["allopurinol", "febuxostat", "benzbromarone"])},
    ),
    (
        "inclusion2",
        "一年內因痛風就診二次以上。",
        "一年痛風就診≥2",
        {"domain": "condition", "concept": "gout", "quantifier": "count>=", "count": 2, "window": _w(-365)},
        {"cand": ("condition", "gout", ["痛風"])},
    ),
    (
        "inclusion2",
        "一年內最近一次 eGFR 小於 60 mL/min/1.73m²（慢性腎臟病第三期以上）。",
        "eGFR<60",
        {
            "domain": "observation",
            "derived": "egfr",
            "quantifier": "latest",
            "value": {"op": "<", "num": 60, "unit": "mL/min/{1.73_m2}"},
            "window": _w(-365),
        },
        {},
    ),
    (
        "inclusion2",
        "一年內最近一次身體質量指數大於或等於 27 kg/m²。",
        "BMI≥27",
        {
            "domain": "observation",
            "derived": "bmi",
            "quantifier": "latest",
            "value": {"op": ">=", "num": 27, "unit": "kg/m2"},
            "window": _w(-365),
        },
        {},
    ),
    (
        "inclusion2",
        "合併第二型糖尿病診斷。",
        "第二型糖尿病",
        {"domain": "condition", "concept": "type 2 diabetes mellitus", "quantifier": "any"},
        {"cand": ("condition", "type 2 diabetes mellitus", ["第二型糖尿病"])},
    ),
]

RA_RULES: list[tuple[str, str, str, dict[str, Any], dict[str, Any]]] = [
    (
        "inclusion",
        "曾經診斷類風濕性關節炎（ICD-10-CM M05 或 M06）之病人。",
        "RA 診斷",
        {"domain": "condition", "concept": "rheumatoid arthritis", "quantifier": "any"},
        {"cand": ("condition", "rheumatoid arthritis", ["類風濕性關節炎"])},
    ),
    (
        "inclusion2",
        "一年內曾使用 methotrexate。",
        "MTX 使用",
        {"domain": "medication", "concept": "methotrexate", "quantifier": "any", "window": _w(-365)},
        {"cand": ("medication", "methotrexate", ["MTX"])},
    ),
    (
        "inclusion2",
        "九十日內最近一次 DAS28 大於 5.1（高疾病活動度）。",
        "DAS28>5.1",
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
        "inclusion2",
        "九十日內最近一次 DAS28 小於或等於 3.2（低疾病活動度）。",
        "DAS28≤3.2",
        {
            "domain": "observation",
            "derived": "das28",
            "quantifier": "latest",
            "value": {"op": "<=", "num": 3.2},
            "window": _w(-90),
        },
        {},
    ),
    (
        "inclusion2",
        "最近一次 B 型肝炎表面抗原（HBsAg）陽性。",
        "HBsAg 陽性",
        {
            "domain": "observation",
            "concept": "hbsag",
            "quantifier": "latest",
            "value": {"op": "in", "codes": ["LA6576-8"]},
        },
        {"cand": ("observation", "hbsag", ["B型肝炎表面抗原"])},
    ),
    (
        "inclusion2",
        "一年內曾使用生物製劑。",
        "生物製劑",
        {"domain": "medication", "concept": "ra biologic", "quantifier": "any", "window": _w(-365)},
        {"cand": ("medication", "ra biologic", ["生物製劑"])},
    ),
]

SPECS: dict[str, dict[str, Any]] = {
    "GOUT-COH": {
        "title": "台灣風濕免疫聯盟 痛風世代定義 v1（合成範例）",
        "front": [("聯盟世代", FRONT_NOTE)],
        "sections": SECTIONS,
        "rules": GOUT_RULES,
        "pdf": "GOUT-COH_世代定義_v1.pdf",
        "template": None,
    },
    "RA-COH": {
        "title": "台灣風濕免疫聯盟 類風濕性關節炎世代定義 v1（合成範例）",
        "front": [("聯盟世代", FRONT_NOTE)],
        "sections": SECTIONS,
        "rules": RA_RULES,
        "pdf": "RA-COH_世代定義_v1.pdf",
        "template": None,
    },
}


def gold(spec: dict[str, Any]) -> dict[str, Any]:
    """The make_nhi_docs cassette with section 2 items reported as inclusion criteria (how the parser reads them)."""
    out = cassette(spec)
    for c in out["criteria"]:
        c["kind"] = "inclusion"
    return out


def check(pdf: Path, spec: dict[str, Any]) -> int:
    """Both sections must parse, in order, as the inclusion list (population first)."""
    from doc_parser.parser import parse
    from llm_stub.handlers import norm

    parsed = parse(pdf.read_bytes(), pdf.name)
    have = [norm(x) for x in parsed.ie_block.inclusion]
    want = [norm(r[1]) for r in spec["rules"]]
    ok = have == want and not parsed.ie_block.exclusion
    print(f"{pdf.name}: language={parsed.language}; criteria {'ok' if ok else 'MISMATCH'} ({len(have)}/{len(want)})")
    if not ok:
        print(f"  parsed {parsed.ie_block.inclusion!r}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    rc = 0
    for rid, spec in SPECS.items():
        pdf = ROOT / "tests/fixtures/protocols" / spec["pdf"]
        if not args.check:
            write_pdf(pdf, spec)
            write_docx(pdf.with_suffix(".docx"), spec)
            (ROOT / f"services/llm_stub/cassettes/ir_extract/{rid}.json").write_text(
                json.dumps(gold(spec), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
        rc |= check(pdf, spec)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
