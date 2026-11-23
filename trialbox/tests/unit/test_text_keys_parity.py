"""R22-54 (review 2026-11-22 E-M3): ja and zh-TW are held to the English catalogue by ``tools.text_keys``.

``console.i18n.lookup`` falls back to English without a word when ja or zh-TW lacks a key, and ``translate`` raises
on the ja or zh-TW page only when a placeholder there is not the English one. ``tools.text_keys`` (``make lint``; the
suite holds its findings at zero, ``test_text_keys.py``) now names a key one language lacks or has alone, a
placeholder set that differs from the English text's, and a Simplified-only character in a zh-TW text. Each mistake
is planted in a tiny catalogue here and must be named.
"""

from __future__ import annotations

import pytest

from tools import text_keys as tk

pytestmark = [pytest.mark.nodb]


def _clean() -> dict[str, dict[str, str]]:
    return {
        "en": {"wb.n_open": "{n} open", "verdict.fail": "not met", "dev.when": "Visit {visit} on {done}"},
        "ja": {"wb.n_open": "未決 {n} 件", "verdict.fail": "満たさない", "dev.when": "{done} に来院 {visit}"},
        "zh-TW": {"wb.n_open": "{n} 項未決", "verdict.fail": "未符合", "dev.when": "{done} 回診 {visit}"},
    }


def test_a_clean_catalogue_has_no_problem() -> None:
    assert tk.parity_problems(_clean(), "fake.py") == []


def test_a_key_deleted_from_ja_is_named() -> None:
    cats = _clean()
    del cats["ja"]["verdict.fail"]
    assert tk.parity_problems(cats, "fake.py") == ["ja verdict.fail: in en, missing in ja (fake.py)"]


def test_a_key_only_zh_tw_has_is_named() -> None:
    cats = _clean()
    cats["zh-TW"]["verdict.extra"] = "多餘"
    assert tk.parity_problems(cats, "fake.py") == ["zh-TW verdict.extra: in zh-TW, missing in en (fake.py)"]


def test_a_renamed_ja_placeholder_is_named() -> None:
    cats = _clean()
    cats["ja"]["wb.n_open"] = "未決 {count} 件"
    assert tk.parity_problems(cats, "fake.py") == ["ja wb.n_open: placeholders {count} differ from en's {n} (fake.py)"]


def test_placeholders_are_compared_by_name_not_order_and_escaped_braces_are_text() -> None:
    cats = _clean()
    cats["en"]["dev.when"] = "Visit {visit} on {done} {{as planned}}"
    cats["ja"]["dev.when"] = "{done} に来院 {visit!s}（{{予定}}）"
    assert tk.parity_problems(cats, "fake.py") == []
    cats["zh-TW"]["dev.when"] = "{done} 回診 {{visit}}"  # the escape is text: {visit} is gone
    assert tk.parity_problems(cats, "fake.py") == [
        "zh-TW dev.when: placeholders {done} differ from en's {done} {visit} (fake.py)"
    ]


def test_a_text_that_is_no_format_text_is_named() -> None:
    cats = _clean()
    cats["ja"]["wb.n_open"] = "未決 {n 件"
    found = tk.parity_problems(cats, "fake.py")
    assert len(found) == 1 and found[0].startswith("ja wb.n_open: not a format text (")


def test_a_simplified_character_in_zh_tw_is_named() -> None:
    cats = _clean()
    cats["zh-TW"]["verdict.fail"] = "未符合条件"  # 条 is the Simplified form of 條
    assert tk.parity_problems(cats, "fake.py") == ["zh-TW verdict.fail: Simplified-only character(s) 条 (fake.py)"]


def test_the_place_of_each_problem_is_named_when_known() -> None:
    cats = _clean()
    del cats["ja"]["verdict.fail"]
    where = {("en", "verdict.fail"): "services/console/i18n.py:540"}
    assert tk.parity_problems(cats, "the served catalogue", where) == [
        "ja verdict.fail: in en, missing in ja (services/console/i18n.py:540)"
    ]


def test_a_quoted_japanese_term_is_allowed_only_in_its_own_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(tk.QUOTED_JAPANESE, "cmt.irb", ("治験審査委員会", "the Japanese committee's own name"))
    cats = _clean()
    for lang, text in (("en", "IRB"), ("ja", "治験審査委員会"), ("zh-TW", "IRB（治験審査委員会）")):
        cats[lang]["cmt.irb"] = text
    assert tk.parity_problems(cats, "fake.py") == []
    cats["zh-TW"]["cmt.other"] = cats["en"]["cmt.other"] = cats["ja"]["cmt.other"] = "治験審査委員会"
    assert tk.parity_problems(cats, "fake.py") == ["zh-TW cmt.other: Simplified-only character(s) 会 (fake.py)"]
    cats["zh-TW"]["cmt.irb"] = "IRB（人體試驗委員會）"  # the term is gone: the exception is stale
    assert tk.parity_problems(cats, "fake.py")[0] == (
        "zh-TW cmt.irb: QUOTED_JAPANESE lists 治験審査委員会, which the text no longer quotes (fake.py)"
    )


def test_every_exception_names_its_reason() -> None:
    for key, (term, reason) in tk.QUOTED_JAPANESE.items():
        assert term and reason, key
        assert any(c in tk.SIMPLIFIED_ONLY for c in term), f"{key}: {term} trips nothing, so it needs no exception"
    for key, reason in tk.ONLY_TRANSLATED.items():
        assert reason, key
    assert len(set(tk.SIMPLIFIED_ONLY)) == len(tk.SIMPLIFIED_ONLY) >= 150


def test_the_checks_run_on_the_console_and_the_service_catalogues(monkeypatch: pytest.MonkeyPatch) -> None:
    """``problems()`` (``python -m tools.text_keys``) reads the served console catalogue and every service catalogue
    ``tools.core_words`` reads; on master both are clean."""
    assert tk.language_problems() == []
    served = tk.served_catalogue()
    monkeypatch.delitem(served["ja"], "verdict.fail")
    found = [p for p in tk.problems() if p.startswith("ja verdict.fail:")]
    assert len(found) == 1 and "missing in ja (services/console/" in found[0]
