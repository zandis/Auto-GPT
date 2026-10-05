from __future__ import annotations

import math

from tb_common import derived as d
from tb_common.phi_guard import scan


def test_bmi() -> None:
    assert round(d.bmi(70, 175), 2) == 22.86


def test_egfr_ckd_epi_2021_published_examples() -> None:
    # NKF CKD-EPI 2021 calculator: (Scr, age, sex) -> eGFR
    assert round(d.egfr(1.0, 50, female=False)) == 92
    assert round(d.egfr(0.8, 60, female=True)) == 84
    assert round(d.egfr(2.0, 70, female=False)) == 35
    assert round(d.egfr(0.6, 30, female=True)) == 124


def test_das28_published_example() -> None:
    # DAS28-ESR (TJC 4, SJC 2, ESR 30, GH 50) = 4.60 ; DAS28-CRP (same, CRP 10 mg/L) = 3.92
    assert round(d.das28_esr(4, 2, 50, 30), 2) == 4.60
    assert round(d.das28_crp(4, 2, 50, 10), 2) == round(
        0.56 * 2 + 0.28 * math.sqrt(2) + 0.36 * math.log(11) + 0.7 + 0.96, 2
    )


def test_basdai_asdas() -> None:
    assert d.basdai(5, 5, 5, 5, 5, 5) == 5.0
    assert round(d.asdas_crp(5, 5, 50, 5, 10), 2) == round(
        0.12 * 5 + 0.06 * 5 + 0.11 * 5 + 0.07 * 5 + 0.58 * math.log(11), 2
    )


def test_phi_guard_clean_protocol_text() -> None:
    text = (
        "Male or female participants aged 18 years or older at screening. HbA1c >10% at screening. "
        "Serum urate ≥6.8 mg/dL. 痛風發作兩次以上。高血壓病人需控制良好。陳述病史時應參考病歷。"
    )
    res = scan(text, r"^\d{8}$")
    assert not res.hit, res.findings
    assert res.clearance is not None


def test_phi_guard_hits() -> None:
    cases = [
        "Example patient A123456789 had gout.",
        "病歷號：12345678，痛風",
        "聯絡電話 0912-345-678",
        "王小明先生於門診追蹤",
        "病人陳美玲，女，65歲，痛風發作",
        "Mr. John Smith presented with gout",
        "林大同 1958/03/04 出生",
        "佐藤花子さんは痛風",
    ]
    for text in cases:
        res = scan(text, r"^\d{8}$")
        assert res.hit and res.clearance is None, text
