"""T-506 and T-116 (CR-078, FIT-006, REG-017, REG-020, UX-017..019, ROLE-023, ROLE-024, ROLE-027): the forbidden-word
list, the one statement source, and a catalogue check that bans the words of TB-IU-01 §2 and the old variants of the
clinical words in every console catalogue, the orchestrator's mail and report catalogue and the console templates."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from console import i18n_flags, i18n_identity
from console.i18n import CATALOGUES
from orchestrator import i18n as orch_i18n
from orchestrator.reports import case_html, consent_html
from tb_common.wording import (
    ALLOWED,
    EXEMPT_PATHS,
    FORBIDDEN,
    LATER,
    STATEMENT,
    check,
    check_file,
    check_page,
    exempt,
    lang_of,
    statement,
    text_lang,
)

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
    """Every console catalogue, with the two that join only when their page is registered, and every module-level
    string table of an ``i18n*`` module (a value that another key shadows in ``CATALOGUES`` is still read)."""
    out = {lang: dict(cat) for lang, cat in CATALOGUES.items()}
    for mod in (i18n_flags, i18n_identity):
        for lang, cat in (("en", mod.EN), ("ja", mod.JA), ("zh-TW", mod.ZH)):
            out[lang].update(cat)
    for path in sorted((ROOT / "services/console").glob("i18n*.py")):
        mod = importlib.import_module(f"console.{path.stem}")
        for name, lang in (("EN", "en"), ("JA", "ja"), ("ZH", "zh-TW")):
            for key, text in getattr(mod, name, {}).items():
                if isinstance(text, str) and out[lang].get(key) != text:
                    out[lang][f"{path.stem}.{name}:{key}"] = text
    return out


def _orchestrator() -> dict[str, dict[str, str]]:
    """The mail and report catalogue of the orchestrator (D-100) and the fixed words of the HTML sheets."""
    out = {lang: dict(cat) for lang, cat in orch_i18n.T.items()}
    for name in ("TITLE", "NOTICE", "HEADLINE"):
        for lang, text in getattr(case_html, name).items():
            out[lang][f"case.{name}"] = text
    for name in ("VERDICT", "KIND", "SOURCE", "HINT", "META"):
        for lang, table in getattr(case_html, name).items():
            for key, text in table.items():
                out[lang][f"case.{name}.{key}"] = text
    for lang in ("en", "ja", "zh-TW"):
        out[lang]["consent.DISCLAIMER"] = consent_html.DISCLAIMER[lang]
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


@pytest.mark.parametrize("source", ["console", "orchestrator"])
def test_no_catalogue_string_gives_a_verdict_word(source: str) -> None:
    """No console, mail or report string says "excluded", 除外 or 排除 of a patient, labels a patient "likely
    eligible", or uses another word of TB-IU-01 §2 (診断, 判定, 対象外, "diagnosis" ...) (T-116); the protocol's own
    heading (除外基準, 排除條件) is allowed. Placeholders such as ``{excluded}`` are names, not words."""
    hits = []
    for lang, cat in (_catalogues() if source == "console" else _orchestrator()).items():
        for key, text in cat.items():
            hits += [f"{lang} {key}: {h.word} in {h.context}" for h in check(re.sub(r"{\w+}", " ", text))]
    assert hits == []


@pytest.mark.parametrize("source", ["console", "orchestrator"])
def test_the_old_variants_are_banned(source: str) -> None:
    bad = []
    for lang, cat in (_catalogues() if source == "console" else _orchestrator()).items():
        for key, text in cat.items():
            bad += [f"{lang} {key}: {word}" for word in BANNED[lang] if word in text]
    assert bad == []


def test_no_console_template_shows_a_verdict_word() -> None:
    """T-116 acceptance (1), read as the reader sees it: the visible text of every console template (Jinja tags out)
    has no word of the list. Attribute values such as ``data-testid="excluded"`` and route names are not prose."""
    hits = []
    for path in sorted((ROOT / "services/console/templates").rglob("*.html")):
        text = re.sub(r"{[{%#].*?[}%#]}", " ", path.read_text(encoding="utf-8"), flags=re.S)
        hits += [f"{path.name}: {h.word} in {h.context}" for h in check_page(text)]
    assert hits == []


def test_the_orchestrator_uses_the_new_terms() -> None:
    t = orch_i18n.t
    assert (
        t("en", "pdf.tier.high") == "may meet the criteria" and t("en", "pdf.tier.excluded") == "criteria not matched"
    )
    assert t("ja", "pdf.tier.high") == "条件に合う可能性" and t("ja", "pdf.tier.excluded") == "基準に合致しない"
    assert t("zh-TW", "pdf.tier.high") == "可能符合條件" and t("zh-TW", "pdf.tier.excluded") == "未符合條件"
    done = {
        lang: t(
            lang,
            "screen.done",
            rs="X",
            ver="1",
            scoped=9,
            high=1,
            review=2,
            excluded=6,
            to="t",
            referrals="",
            judging="",
        )
        for lang in ("en", "ja", "zh-TW")
    }
    assert "6 with criteria not matched" in done["en"]
    assert "基準に合致しない 6 名" in done["ja"] and "6 位未符合條件" in done["zh-TW"]
    for lang in ("en", "ja", "zh-TW"):  # the three languages stay in step: one key set
        assert set(orch_i18n.T[lang]) == set(orch_i18n.T["en"]), lang


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
        assert check(text) == []  # the statement's own negations
    assert [h.word for h in check("疾病の診断")] == ["診断"]  # T-116: one list, checked everywhere by default
    assert [h.word for h in check("3 diagnoses")] == ["diagnoses"]
    assert LATER == () and {"診断", "判定", "対象外", "見逃し", "診斷", "diagnosis", "abnormal", "risk score"} <= set(
        FORBIDDEN
    )
    assert all(p in ALLOWED for p in STATEMENT.values())


def test_the_risk_file_is_exempt_by_design() -> None:
    """Negative, by design (TB-IU-01 §2: "only the risk file names the hazard plainly"): ``check_file`` skips the
    plan folder, where the risk file names the hazard "wrong exclusion"; the same text anywhere else is a hit."""
    text = "Hazard: wrong exclusion; a patient excluded by a model error (除外)."
    assert exempt("docs/plan/25-risk.md") and exempt("./docs/plan/sites/x.md") and not exempt("docs/USER_GUIDE.md")
    assert check_file("docs/plan/25-risk.md", text) == []
    assert [h.word for h in check_file("services/console/templates/x.html", text)] == ["excluded", "除外"]
    assert all(e.startswith("docs/") for e in EXEMPT_PATHS)  # code is never exempt


def test_statement_and_language_helpers() -> None:
    assert [lang_of(x) for x in ("ja-JP", "zh-Hant-TW", "zh", "en-GB", None, "fr")] == [
        "ja",
        "zh-TW",
        "zh-TW",
        "en",
        "en",
        "en",
    ]
    assert statement("ja-JP") == STATEMENT["ja"] and statement(None) == STATEMENT["en"]
    assert [text_lang(x) for x in ("候補者リスト", "候選名單已寄出給您", "list sent", "痛風")] == [
        "ja",
        "zh-TW",
        "en",
        "en",
    ]


def test_check_page_reads_only_what_a_reader_sees() -> None:
    page = '<a href="/studies/X/excluded" data-testid="to-excluded">Criteria not matched</a><script>"除外"</script>'
    assert check_page(page) == []
    assert [h.word for h in check_page("<p>Excluded &amp; why</p>")] == ["excluded"]
