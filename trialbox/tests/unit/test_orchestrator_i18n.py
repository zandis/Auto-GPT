"""D-100: the language of a job's mail and reports."""

from __future__ import annotations

from orchestrator.i18n import LANGS, T, detect_lang, job_lang, norm_lang, t


def test_catalogues_have_the_same_keys_and_placeholders() -> None:
    import re

    for lang in LANGS:
        assert set(T[lang]) == set(T["en"]), lang
        for key, text in T["en"].items():
            assert set(re.findall(r"{(\w+)}", text)) == set(re.findall(r"{(\w+)}", T[lang][key])), (lang, key)


def test_job_language_option_then_site_locale() -> None:
    assert job_lang({"lang": "ja"}, "zh-TW") == "ja"
    assert job_lang({"lang": "en,ja"}, "zh-TW") == "en"  # CONSENT lists several: the first one
    assert job_lang({}, "zh-TW") == "zh-TW" and job_lang(None, "ja-JP") == "ja" and job_lang(None, None) == "en"
    assert norm_lang("zh-Hant") == "zh-TW" and norm_lang("fr") == "en"


def test_chart_language_is_detected_from_its_script() -> None:
    assert detect_lang("Patient has a history of gout; two flares in 2026.") == "en"
    assert detect_lang("痛風の既往があり、2026年に2回の発作。") == "ja"
    assert detect_lang("病人有痛風病史，2026 年發作兩次，目前服用降尿酸藥物。") == "zh-TW"


def test_translation_falls_back_to_english() -> None:
    assert t("ja", "pdf.answer") == "結論" and t("xx", "pdf.answer") == "Answer"
    assert "3 名" in t("ja", "screen.list.headline", n=3)
