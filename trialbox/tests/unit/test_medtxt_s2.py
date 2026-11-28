"""The S2 miss rate on MedTxt (H3-NLP §3.5 (2)): per positive finding, does any of S2's own keys hit the sentence
that holds it, in Japanese and in English. The two reports below are written for this test in MedTxt's tag form;
no corpus text is committed."""

from __future__ import annotations

from tools import medtxt_s2

JA = {
    "CR:1": '<article id="1">関節炎を認めた。<d certainty="positive">胸水</d>を認めた。'
    '<d certainty="negative">痛風</d>はない。</article>',
    "CR:2": '<article id="2"><d certainty="positive">関節炎</d>あり。</article>',
    "CR:3": '<article id="3"><d certainty="positive">痛風</d>。<d certainty="positive">腫瘍</d>。</article>',
}
EN = {
    "CR:1": '<article id="1">Arthritis was seen. <d certainty="positive">Pleural effusion</d> was seen. '
    '<d certainty="negative">gout</d> was absent.</article>',
    "CR:2": '<article id="2"><d certainty="positive">arthritis</d> present.</article>',
    "CR:3": '<article id="3"><d certainty="positive">gout</d>.</article>',  # one tag short: not aligned
}


def test_each_positive_finding_is_a_hit_a_miss_or_has_no_key_in_each_language() -> None:
    res = medtxt_s2.misses(JA, EN)
    # CR:1 pleural effusion: no shipped key at all; CR:2 arthritis: 関節炎 and "arthritis" hit; CR:3 is not aligned
    assert res["ja"] == {"findings": 2, "hit": 1, "missed": 0, "no_key": 1, "miss_rate": 0.5}
    assert res["en"] == {"findings": 2, "hit": 1, "missed": 0, "no_key": 1, "miss_rate": 0.5}
    assert res["fix_list_ja"] == [{"ja": "胸水", "en": "pleural effusion", "n": 1}]


def test_a_key_elsewhere_in_the_report_is_not_a_hit_on_the_findings_sentence() -> None:
    ja = {"CR:1": '<article id="1">関節炎。\n<d certainty="positive">リウマチ性の炎症</d>あり。</article>'}
    en = {"CR:1": '<article id="1">Arthritis.\n<d certainty="positive">arthritis</d> again.</article>'}
    res = medtxt_s2.misses(ja, en)
    assert (res["ja"]["missed"], res["ja"]["hit"]) == (1, 0)  # 関節炎 is a key but sits in the sentence before
    assert res["en"]["hit"] == 1
