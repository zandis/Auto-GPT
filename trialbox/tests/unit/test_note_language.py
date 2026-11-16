"""NOTE-LANGUAGE-THRESHOLDS (D-983): the screening cascade took the site's report locale as the language of the
notes; the owner confirmed (2026-11-16) that a Taiwan site's charts are mainly English. The language is read from the
notes, by script, and every language-dependent choice of the cascade takes it.

* ``note_language``: English, Chinese, Japanese; a Taiwan chart with English text under Chinese headings and Chinese
  drug names is English; Japanese with English drug names is Japanese; a text too short is None.
* A declared site setting wins; ``auto`` reads the notes; with nothing to read, the report locale.
* The S2b threshold is the one for the note's language, not the report's.
* Fail safe: the index sweep never excludes on a threshold not fitted to the notes' language, and a certified zero hit
  counts only with a term in the notes' script.

Synthetic text; no patient data.
"""

from __future__ import annotations

import pytest
from matching.cascade.engine import has_term_for
from matching.cascade.s2b_semantic import MIN_JUDGED_POSITIVES, ThresholdTable
from matching.notelang import main_language, note_language, notes_language

TAIWAN_CHART = (
    "【現病史】 Patient is a 62-year-old man presented with exertional chest pain for 2 days. No dyspnea, no fever. "
    "【理學檢查】 BP 132/80, HR 78, lungs clear. 【用藥】 阿斯匹靈 100mg qd, 保栓通 75mg qd, atorvastatin 40mg hs. "
    "【評估】 Unstable angina, rule out NSTEMI. Plan: cardiology consult, serial troponin."
)


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Patient with gout flare, on colchicine 0.5 mg twice daily. Uric acid 9.2 mg/dL.", "en"),
        ("病人痛風急性發作，服用秋水仙素，尿酸 9.2 mg/dL，無發燒。", "zh-TW"),
        ("痛風発作があり、コルヒチンを服用中。尿酸値は 9.2 mg/dL で、発熱はない。", "ja"),
        (TAIWAN_CHART, "en"),  # the expected case at a Taiwan site (the owner, 2026-11-16)
        ("高血圧で Amlodipine 5mg を服用している。浮腫はない。", "ja"),
        ("病人有高血壓，服用 Amlodipine 5mg，血壓控制良好。", "zh-TW"),
        # D-983's review: Japanese in kanji, Chinese full of abbreviations
        ("既往歴：高血圧、糖尿病。内服薬なし。", "ja"),
        ("肺腺癌、EGFR変異陽性。化学療法施行中。", "ja"),
        ("主訴：SOB x3d，發燒，給予 Augmentin，追蹤 CBC/CRP，胸部X光右下肺浸潤。", "zh-TW"),
        ("BP 120/80", None),
        ("", None),
    ],
)
def test_the_language_of_a_note_is_read_from_its_script(text: str, lang: str | None) -> None:
    assert note_language(text) == lang


def test_a_patient_has_the_language_most_of_their_notes_are_in() -> None:
    assert main_language([TAIWAN_CHART, TAIWAN_CHART, "病人無發燒，食慾可。"], "zh-TW") == "en"
    assert main_language(["BP 120/80", ""], "zh-TW") == "zh-TW"  # nothing to tell: the report locale


@pytest.mark.parametrize(
    ("setting", "lang"), [("en", "en"), ("ja", "ja"), ("auto", "en"), (None, "en"), ("klingon", "en")]
)
def test_a_declared_site_language_wins_else_the_notes_tell(setting: str | None, lang: str) -> None:
    assert notes_language(setting, [TAIWAN_CHART], "zh-TW") == lang


def test_the_s2b_threshold_is_the_one_fitted_to_the_notes_language() -> None:
    table = ThresholdTable(site={"inclusion|en": (0.31, MIN_JUDGED_POSITIVES), "inclusion|zh-TW": (0.22, 500)})
    lang = notes_language("auto", [TAIWAN_CHART], "zh-TW")
    thr = table.get("inclusion", lang)
    assert (thr.value, thr.source, thr.stratum) == (0.31, "ltt_site", "inclusion|en")  # not the zh-TW fit
    assert table.get("inclusion", "ja").source == "public_prior"  # no fit for Japanese: the placeholder


@pytest.mark.parametrize(
    ("keys", "lang", "ok"),
    [(["gout", "痛風"], "en", True), (["痛風"], "en", False), (["gout"], "zh-TW", False), (["痛風"], "ja", True),
     ([], "en", False)],
)  # fmt: skip
def test_a_zero_hit_counts_only_with_a_term_in_the_notes_script(keys: list[str], lang: str, ok: bool) -> None:
    assert has_term_for(keys, lang) is ok


def _index_run(text: str, **cfg: object) -> object:
    from tests.unit.test_safety_properties import INDEX_RS, _cascade, _Embedder, _FakeLake, _note

    lake = _FakeLake(INDEX_RS, {"I-1": {"X-INC-01": False}}, notes=[_note("I-1", text, offset=-200)])
    return _cascade(lake, semantics="affirmative", lexicon={"X-INC-01": ["gout"]}, absence_semantics=True,
                    embedder=_Embedder(above=False), language="zh-TW", **cfg)  # fmt: skip


EN_NOTE = "Patient seen in the clinic today for follow up of chronic conditions, stable, no new complaints."
ZH_NOTE = "病人今日門診追蹤慢性病，狀況穩定，無新的不適主訴，持續原本治療。"


def test_english_notes_at_a_zh_tw_site_never_exclude_on_a_threshold_not_fitted_to_them() -> None:
    t = _index_run(EN_NOTE).traces["I-1"]  # type: ignore[attr-defined]
    o = t.outcomes["X-INC-01"]
    assert t.exit_stage is None and o.status == "unknown" and not o.hard
    assert o.reason == "index condition not found in the notes; no fitted threshold for en notes; review"


@pytest.mark.parametrize(("text", "setting"), [(ZH_NOTE, "auto"), (EN_NOTE, "zh-TW")])
def test_notes_in_the_sites_own_language_keep_the_earlier_rule(text: str, setting: str) -> None:
    t = _index_run(text, notes_language=setting).traces["I-1"]  # type: ignore[attr-defined]
    assert t.exit_stage == "S2b" and t.outcomes["X-INC-01"].hard  # as before D-983 (CAS-11, CAS-18)


def test_a_long_lab_table_does_not_outweigh_the_narrative() -> None:
    lab = "WBC 12.3 Hb 10.2 PLT 230 Na 135 K 4.1 Cr 1.2 BUN 20 " * 20
    assert main_language([lab, "病人今日出院，狀況穩定，門診追蹤，持續服藥，無發燒。"], "en") == "zh-TW"


@pytest.mark.parametrize(
    ("locale", "lang"), [("ja-JP", "ja"), ("zh-Hant", "zh-TW"), ("zh-TW", "zh-TW"), ("en-US", "en")]
)
def test_a_locale_is_read_as_its_language(locale: str, lang: str) -> None:
    from matching.notelang import family

    assert family(locale) == lang


def test_a_patients_language_is_read_from_all_their_notes_not_one_window() -> None:
    from datetime import date

    from matching.cascade.engine import _Note, _Run

    run = _Run.__new__(_Run)
    run._notes_lang = {}
    run.cfg = type("C", (), {"notes_language": "auto", "language": "zh-TW"})()
    short = _Note("d1", date(2026, 10, 1), "progress", "DM, HTN", ["DM, HTN"])
    long = _Note("d2", date(2025, 1, 1), "progress", EN_NOTE, [EN_NOTE])
    run._learn_language("P1", [short, long])  # what S2 does with all the patient's notes, before any criterion
    assert run.language_of("P1", [short]) == "en" and run.mismatched("P1", [short]) == "en"
