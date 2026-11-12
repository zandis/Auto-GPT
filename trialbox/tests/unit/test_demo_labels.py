"""DEMO-JA item 1 (D-309): the demo's investigator labels a criterion with the shipped rulesets' own words, never a
placeholder such as "GZQO-EXC-15 label"."""

from __future__ import annotations

import pytest

from tools import e2e_simple
from tools import list_demo as ld


@pytest.mark.parametrize("lang", ["ja", "zh-TW", "en"])
def test_the_added_exclusion_takes_the_shipped_label_of_the_same_criterion(lang: str) -> None:
    got = ld.given_label("GZQO", "GZQO-EXC-15", lang)  # the exclusion list_demo adds: another trial within 30 days
    assert got == ld.shipped_label("GZQO", "GZQO-EXC-14", lang) != ""
    assert "label" not in got and "GZQO-EXC" not in got
    assert ld.given_label("AD-MAB", "AD-MAB-EXC-05", lang) == got  # the J1 scenario adds the same exclusion


def test_a_reworded_criterion_keeps_its_own_label_in_each_language() -> None:
    assert ld.given_label("GOUT-COH", "GOUT-COH-INC-01", "ja") == "痛風"
    assert ld.given_label("GOUT-COH", "GOUT-COH-INC-01", "zh-TW") == "痛風診斷"  # the IR's label: protocol in zh-TW
    assert ld.given_label("GOUT-COH", "GOUT-COH-INC-01", "en") == "Gout"
    assert ld.given_label("GZQO", "GZQO-INC-03", "ja") == "BMI 27以上"


def test_the_new_site_labels_cover_every_pasted_criterion() -> None:
    ids = {"SITE5B-INC-01", "SITE5B-INC-02", "SITE5B-INC-03", "SITE5B-EXC-01"}
    for lang in ("ja", "zh-TW"):
        labels = e2e_simple.SITE_LABELS[lang]
        assert set(labels) == ids
        assert all(v and "label" not in v and "SITE5B" not in v for v in labels.values())
    assert e2e_simple.SITE_LABELS["ja"]["SITE5B-INC-01"] == ld.shipped_label("GZQO", "GZQO-INC-01", "ja")
    assert e2e_simple.SITE_LABELS["zh-TW"]["SITE5B-INC-02"] == ld.shipped_label("GOUT-COH", "GOUT-COH-INC-01", "zh-TW")


def test_a_shipped_criterion_never_borrows_another_label(tmp_path: object) -> None:
    assert ld.given_label("GZQO", "GZQO-INC-01", "zh-TW") == "年滿18歲"
    # GOUT-COH's protocol is zh-TW and its labels.yaml has no zh-TW: the IR's own label, not GZQO-EXC-14's
    assert ld.given_label("GOUT-COH", "GOUT-COH-INC-02", "zh-TW") != ld.shipped_label("GZQO", "GZQO-EXC-14", "zh-TW")
