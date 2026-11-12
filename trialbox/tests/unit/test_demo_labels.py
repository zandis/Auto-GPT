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


def test_the_stub_reads_japanese_notes_only_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEMO-JA item 2: the Japanese site's notes (tools/synth/notes_ja.py) are read by the stub judge only with
    TB_LLM_STUB_NOTE_LANGS listing ja, so a default run (and its goldens) is unchanged."""
    from llm_stub import handlers

    two = {"note_question": "At least 2 gout flares within the 12 months before screening?", "index_date": "2026-11-10",
           "excerpts": [{"date": "2026-09-01", "text": "2026年8月30日に右足関節の発赤・腫脹・熱感・疼痛あり、急性痛風発作と診断しコルヒチンで改善した。"},
                        {"date": "2026-05-01", "text": "令和8年4月28日に左膝関節の発赤・腫脹・熱感・疼痛あり、急性痛風発作と診断しコルヒチンで改善した。"}]}  # fmt: skip
    now = {"note_question": "Current gout flare (ongoing)?", "index_date": "2026-11-10",
           "excerpts": [{"date": "2026-11-08", "text": "現在、急性痛風発作はなく、関節の発赤・圧痛は認めない。"}]}  # fmt: skip
    monkeypatch.delenv(handlers.NOTE_LANGS_ENV, raising=False)
    assert handlers.judge(two)["verdict"] == handlers.judge(now)["verdict"] == "unknown"
    monkeypatch.setenv(handlers.NOTE_LANGS_ENV, "zh-TW,ja")
    assert handlers.judge(two)["verdict"] == "pass"  # one western date, one 令和 date
    assert handlers.judge(now)["verdict"] == "fail"
    one = dict(
        two,
        excerpts=[
            {"date": "2026-09-01", "text": "過去一年間の痛風発作は2026年8月30日の一回のみで、その後の再発はない。"}
        ],
    )
    assert handlers.judge(one)["verdict"] == "fail"


def test_the_japanese_site_turns_the_stub_reading_on() -> None:
    from tools import feas_demo as fd

    env = {fd.SITE_LANG_ENV: "ja"}
    fd.stub_reads_site_lang(env)
    assert env["TB_LLM_STUB_NOTE_LANGS"] == "zh-TW,ja"
    for value in ("", "zh-TW"):
        env = {fd.SITE_LANG_ENV: value}
        fd.stub_reads_site_lang(env)
        assert "TB_LLM_STUB_NOTE_LANGS" not in env
    assert fd.site_profile("ci", {fd.SITE_LANG_ENV: "ja"}) == "ci-ja"
    assert fd.site_profile("ci", {fd.SITE_LANG_ENV: "zh-TW"}) == "ci-zh-TW"
    assert fd.site_profile("ci", {}) == "ci" and fd.site_profile("jp-ad", {fd.SITE_LANG_ENV: "zh-TW"}) == "jp-ad"
    with pytest.raises(SystemExit, match="TB_DEMO_SITE_LANG"):
        fd.site_profile("ci", {fd.SITE_LANG_ENV: "fr"})
