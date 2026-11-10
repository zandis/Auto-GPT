"""T-506 (the PoC part of T-116; CR-078, FIT-006, REG-017, REG-020, UX-017..019, ROLE-023, ROLE-024, ROLE-027): the
forbidden-word list, the one statement source, and a catalogue check that bans the old variants of the clinical
words in every console catalogue."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from console import i18n_flags, i18n_identity
from console.i18n import CATALOGUES
from tb_common.wording import ALLOWED, FORBIDDEN, LATER, STATEMENT, check, check_page

ROOT = Path(__file__).resolve().parents[2]
LABEL = {"en": "English", "ja": "日本語", "zh-TW": "繁體中文"}

# Old variants that the wording pass replaced; none may come back in any catalogue.
BANNED: dict[str, tuple[str, ...]] = {
    "en": ("likely eligible", "Excluded patients and why", "present: excludes", "rules out"),
    "ja": (
        "適格の可能性が高い",  # tier label (REG-017) -> 条件に合う可能性
        "除外された",  # page title (CR-078) -> 基準に合致しない患者
        "該当（除外）",  # verdict (UX-017) -> 該当あり
        "人の確認",  # verdict (UX-017) -> 要確認（担当者）
        "コーディネーター",  # the CRC has one name (UX-018) -> CRC
        "プロトコール",  # one spelling (UX-018) -> プロトコル
        "紹介",  # referral (UX-019) -> 主治医への了承依頼
        "委任リスト",  # delegation log (ROLE-027) -> 治験分担医師・治験協力者リスト
    ),
    "zh-TW": (
        "被排除",  # page title (CR-078) -> 未符合條件之病人
        "（排除）",  # verdict (UX-017) -> 有此情形
        "應排除",  # site verdict -> 有此情形
        "需人工",  # verdict (UX-017) -> 需人員確認
        "協調員",  # the CRC has one name (UX-018) -> 研究護理師（CRC）
        "研究護理師／CRC",
        "知情同意",  # Taiwan usage (UX-018) -> 受試者同意
        "轉介",  # referral (UX-019) -> 徵詢主治醫師同意
        "退出登錄",  # opt-out register read as "log out" (ROLE-023) -> 拒絕研究使用登記
        "登錄退出",
        "病人撤回",  # lift read as a study withdrawal (ROLE-023) -> 取消拒絕（病人改變意願）
    ),
}


def _catalogues() -> dict[str, dict[str, str]]:
    """Every console catalogue, with the two that join only when their page is registered."""
    out = {lang: dict(cat) for lang, cat in CATALOGUES.items()}
    for mod in (i18n_flags, i18n_identity):
        for lang, cat in (("en", mod.EN), ("ja", mod.JA), ("zh-TW", mod.ZH)):
            out[lang].update(cat)
    return out


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_statement_is_the_one_in_the_intended_use_document(lang: str) -> None:
    """REG-020: one statement; the document and the console footer carry the same words."""
    doc = (ROOT / "docs/plan/intended-use.md").read_text(encoding="utf-8")
    m = re.search(r"^> \*\*" + re.escape(LABEL[lang]) + r"\.\*\* (.+)$", doc, re.M)
    assert m and m.group(1).strip() == STATEMENT[lang]


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_footer_key_comes_from_the_statement(lang: str) -> None:
    assert CATALOGUES[lang]["footer.statement"] == STATEMENT[lang]


def test_no_catalogue_string_gives_a_verdict_word() -> None:
    """No console string says "excluded", 除外 or 排除 of a patient, or labels a patient "likely eligible"; the
    protocol's own heading (除外基準, 排除條件) is allowed. Placeholders such as ``{excluded}`` are names, not words."""
    hits = []
    for lang, cat in _catalogues().items():
        for key, text in cat.items():
            hits += [f"{lang} {key}: {h.word} in {h.context}" for h in check(re.sub(r"{\w+}", " ", text))]
    assert hits == []


def test_the_old_variants_are_banned() -> None:
    bad = []
    for lang, cat in _catalogues().items():
        for key, text in cat.items():
            bad += [f"{lang} {key}: {word}" for word in BANNED[lang] if word in text]
    assert bad == []


def test_the_new_terms_are_in_place() -> None:
    cat = _catalogues()
    assert cat["en"]["ex.title"] == "Criteria not matched"
    assert cat["ja"]["ex.title"] == "基準に合致しない患者"
    assert cat["zh-TW"]["ex.title"] == "未符合條件之病人"
    assert (cat["en"]["tier.high"], cat["ja"]["tier.high"], cat["zh-TW"]["tier.high"]) == (
        "may meet the criteria",
        "条件に合う可能性",
        "可能符合條件",
    )
    # ROLE-024: the opt-out table's first column is the pseudonym, not the form's "or pseudonym"
    assert (cat["en"]["team.optout.pid"], cat["ja"]["team.optout.pid"], cat["zh-TW"]["team.optout.pid"]) == (
        "Pseudonym",
        "仮名ID",
        "假名代碼",
    )
    assert cat["ja"]["team.ref.title"] == "主治医への了承依頼" and cat["zh-TW"]["team.ref.title"] == "徵詢主治醫師同意"
    assert cat["zh-TW"]["team.optout.title"] == "拒絕研究使用登記"
    assert cat["ja"]["role.coordinator"] == "CRC" and cat["zh-TW"]["role.coordinator"] == "研究護理師（CRC）"


def test_check_finds_words_and_respects_the_allowed_phrases() -> None:
    assert [h.word for h in check("3 patients excluded")] == ["excluded"]
    assert [h.word for h in check("Likely eligible first")] == ["likely eligible"]
    assert check("excluded_GZQO_v1.0.0.json") == []  # a file name, not prose
    assert check("除外基準 3 件中 3 件に該当なし") == [] and check("排除條件 3 項") == []
    assert [h.word for h in check("除外 4 名")] == ["除外"]
    for text in STATEMENT.values():
        assert check(text, (*FORBIDDEN, *LATER)) == []  # the statement's own negations
    assert [h.word for h in check("疾病の診断", LATER)] == ["診断"]
    assert all(p in ALLOWED for p in STATEMENT.values())


def test_check_page_reads_only_what_a_reader_sees() -> None:
    page = '<a href="/studies/X/excluded" data-testid="to-excluded">Criteria not matched</a><script>"除外"</script>'
    assert check_page(page) == []
    assert [h.word for h in check_page("<p>Excluded &amp; why</p>")] == ["excluded"]
