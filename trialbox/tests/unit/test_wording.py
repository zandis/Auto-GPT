"""T-506 and T-116 (CR-078, FIT-006, REG-017, REG-020, UX-017..019, ROLE-023, ROLE-024, ROLE-027): the forbidden-word
list, the one statement source, and a catalogue check that bans the words of TB-IU-01 §2 and the old variants of the
clinical words in every console catalogue, the orchestrator's mail and report catalogue and the console templates."""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest
from console import i18n_flags, i18n_identity
from console.i18n import CATALOGUES
from opportunity_hub import dashboard as hub_dashboard
from orchestrator import i18n as orch_i18n
from orchestrator.reports import case_html, consent_html
from tb_common.wording import (
    ALLOWED,
    CLAIM_ALLOWED_JA,
    CLAIM_OUTRIGHT_JA,
    EXEMPT_PATHS,
    FORBIDDEN,
    LATER,
    STATEMENT,
    check,
    check_claims_ja,
    check_file,
    check_page,
    exempt,
    lang_of,
    statement,
    text_lang,
    visible_text,
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


def _hub() -> dict[str, dict[str, str]]:
    """The trial-opportunity board's labels (D-467): the hub's page speaks the product's words too."""
    return {lang: dict(cat) for lang, cat in hub_dashboard.LABELS.items()}


def _source(name: str) -> dict[str, dict[str, str]]:
    return {"console": _catalogues, "orchestrator": _orchestrator, "opportunity_hub": _hub}[name]()


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_statement_is_the_one_in_the_intended_use_document(lang: str) -> None:
    """REG-020: one statement; the document and the console footer carry the same words."""
    doc = (ROOT / "docs/plan/intended-use.md").read_text(encoding="utf-8")
    m = re.search(r"^> \*\*" + re.escape(LABEL[lang]) + r"\.\*\* (.+)$", doc, re.M)
    assert m and m.group(1).strip() == STATEMENT[lang]


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_footer_key_comes_from_the_statement(lang: str) -> None:
    assert CATALOGUES[lang]["footer.statement"] == STATEMENT[lang]


@pytest.mark.parametrize("source", ["console", "orchestrator", "opportunity_hub"])
def test_no_catalogue_string_gives_a_verdict_word(source: str) -> None:
    """No console, mail or report string says "excluded", 除外 or 排除 of a patient, labels a patient "likely
    eligible", or uses another word of TB-IU-01 §2 (診断, 判定, 対象外, "diagnosis" ...) (T-116); the protocol's own
    heading (除外基準, 排除條件) is allowed. Placeholders such as ``{excluded}`` are names, not words."""
    hits = []
    for lang, cat in _source(source).items():
        for key, text in cat.items():
            hits += [f"{lang} {key}: {h.word} in {h.context}" for h in check(re.sub(r"{\w+}", " ", text))]
    assert hits == []


@pytest.mark.parametrize("source", ["console", "orchestrator", "opportunity_hub"])
def test_the_old_variants_are_banned(source: str) -> None:
    bad = []
    for lang, cat in _source(source).items():
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


# 10C-5 (JP-4, D-1228): the Japanese device-claims guard. The sentences are built from the claim forms of the rule
# (docs/plan/intended-use-jp.md section 3), one or more per form; each must fail, and each legitimate use must pass.
CLAIMING_JA = [
    # compound claim nouns, refused outright
    ("早期発見を支援します。", "早期発見"),
    ("早期検知に役立ちます。", "早期検知"),
    ("AIによるリスク予測", "リスク予測"),
    ("予後予測を行います。", "予後"),
    ("重症度スコアリング", "スコアリング"),
    ("画像から自動検出します。", "自動検出"),
    ("潜在患者を掘り起こします。", "潜在患者"),
    ("見落とされた患者を拾い上げます。", "拾い上げ"),
    ("未診断の患者を一覧にします。", "未診断"),
    ("疑い患者の一覧", "疑い患者"),
    ("診断支援のためのソフトウェアです。", "診断"),  # 診断 was refused outright before 10C-5 and still is
    # finding words with a disease or "early / latent" object
    ("疾患の兆候を自動で検出します。", "検出"),
    ("AIの病変検出感度は98%です。", "検出"),
    ("希少疾患のスクリーニングを自動化します。", "スクリーニング"),
    ("患者を早期に発見します。", "発見"),
    ("がんを見つけます。", "見つけ"),
    ("発症前の変化を検知します。", "検知"),
    ("AIが疾患を発見しない日はない。", "発見"),  # a double negative is not a denial
    # rate words with a patient or disease object, or the AI straight before them
    ("疾患を予測します。", "予測"),
    ("本ソフトウェアは患者ごとのリスクを示します。", "リスク"),
    ("ﾘｽｸの高い患者を表示します。", "リスク"),  # half-width katakana, NFKC-normalised first
    ("患者の危険度を一覧にします。", "危険度"),
    ("患者のAIスコアで並べ替えます。", "スコア"),
    ("患者のRiskスコアで並べ替えます。", "スコア"),
    ("ＡＩスコアで並べ替えます。", "スコア"),
    ("患者が発症する確率を示します。", "確率"),
    ("AIが患者のリスクを示し、治療は推奨しません。", "リスク"),  # a negation elsewhere does not excuse it
    # a judgement whose nearest subject is the product
    ("AIが参加の可否を判断します。", "判断"),
    ("システムが参加の可否を判断します。", "判断"),
    ("医師は判断しますが、TrialBox が最終判断します。", "判断"),
]
LEGITIMATE_JA = [
    "治験に必要な患者を見つける",  # the product's purpose: candidates for a study, by its written criteria
    "システムが候補者を見つけ、担当者が確認します。",
    "スクリーニングで見つかり、まだ判断していない患者。",
    "システムが設定の変更を検出しました。",
    "情報漏えいのリスクを低減します。",
    "バイアスのリスクを評価します。",
    "ECOG スコアは担当者が入力します。",
    "保存済みスコア（eGFR、DAS28、CDAI、SDAI）を照合します。",
    "ユーザー名にはアンダースコアが使えます。",
    "検出限界の外です",
    "予測される無作為化数",
    "予測期間（か月）",
    "参加の可否は治験責任医師が判断します。",
    "モデルが記録を読むのは残りだけで、S5 で人が判断します。",
    "本製品は診断、予測、スコアリングを行いません。",  # a real denial
    "TrialBox は患者を発見しません。",
    "AIは患者のリスクを予測しません。",
    "予後予測ではありません。",
]


@pytest.mark.parametrize(("text", "word"), CLAIMING_JA)
def test_a_japanese_device_claim_fails(text: str, word: str) -> None:
    assert word in [h.word for h in check(text)]
    assert word in [h.word for h in check_page(f"<p>{text}</p>")]  # the page walk calls the same check


@pytest.mark.parametrize("text", LEGITIMATE_JA)
def test_a_legitimate_japanese_use_passes(text: str) -> None:
    assert check(text) == []


def test_a_mixed_japanese_sentence_fails_only_on_the_claim() -> None:
    hits = check("ECOG スコアは担当者が入力しますが、AIが患者のリスクを予測します。")
    assert sorted(h.word for h in hits) == ["リスク", "予測"]
    assert [h.word for h in check("AIが記録を読みます。バイアスのリスクは別に評価します。")] == []


# Each allowed context is pinned: the sentence puts a patient or disease word within the window, so it passes only
# because of its allowed context, and fails when that context is taken away.
PINNED = [
    ("スコア", "患者のECOGスコアは担当者が入力します。"),
    ("スコア", "患者のDAS28スコアを照合します。"),
    ("スコア", "患者のスコア定義が変わりました。"),
    ("リスク", "患者研究のバイアスのリスクを評価します。"),
    ("予測", "月ごとの新規患者と登録予測"),
    ("検出", "がんマーカーの検出限界の外です。"),
]


@pytest.mark.parametrize(("term", "text"), PINNED)
def test_each_allowed_context_is_what_lets_its_sentence_pass(
    term: str, text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert check(text) == []
    monkeypatch.setitem(CLAIM_ALLOWED_JA, term, ())
    assert term in [h.word for h in check_claims_ja(text)]


def test_an_actor_word_is_what_makes_a_judgement_a_claim() -> None:
    assert check("参加の可否を判断します。") == []  # no actor: the product's words have a person judge
    for actor in ("システム", "AI", "モデル", "TrialBox", "本製品"):
        assert [h.word for h in check(f"{actor}が参加の可否を判断します。")] == ["判断"], actor


def test_on_a_page_a_block_ends_a_sentence_and_an_inline_tag_does_not() -> None:
    """A list item's actor is not the subject of the next item; an inline tag, or the template's line break inside a
    paragraph, does not split a subject from its verb."""
    assert check_page("<ul><li>AIで読む</li><li>参加の可否を判断</li></ul>") == []
    assert [h.word for h in check("AIで読む 参加の可否を判断")] == ["判断"]  # the same words in one sentence
    assert [h.word for h in check_page("<p><b>AIが</b><b>疾患</b>を発見します</p>")] == ["発見"]
    assert [h.word for h in check_page("<p>AIが\n    疾患を発見します</p>")] == ["発見"]


def test_invisible_characters_do_not_hide_a_claim() -> None:
    # format characters, and fillers that are letters or marks to Unicode (Hangul filler, combining grapheme joiner)
    for c in ("\u200b", "\u200d", "\u2060", "\ufeff", "\u00ad", "\u3164", "\u034f"):
        assert [h.word for h in check(f"AIが疾{c}患を発{c}見します。")] == ["発見"], repr(c)


@pytest.mark.parametrize(
    "text",
    [
        "本製品は診断、予測、スコアリングを行いません。",  # a list of claim words, denied together
        "疾患の発見機能はありません。",  # "has no ... function"
        "診断支援機能もありません。",
        "患者の参加可否を判断するものではありません。",  # "is not something that ..."
        "スコアリングのためのツールではありません。",  # "is not a tool for ..."
        "医学的な判断を行いません。",
        "疾患のリスクを予測せず、記録を一覧にします。",
    ],
)
def test_a_denial_in_its_common_forms_passes(text: str) -> None:
    assert check(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "AIが疾患を発見しない日はない。",  # two negatives deny nothing
        "「疾患を発見しません」という日はない。",  # a quoted denial inside a double negative
        "AIが疾患を検出します（必ず）。",  # 必ず after the claim word is not a negative
    ],
)
def test_two_negatives_or_a_false_negative_are_not_a_denial(text: str) -> None:
    assert check(text) != []


def test_a_candidate_is_not_a_patient_word() -> None:
    """候補者 is the product's own word for a person who may meet a study's criteria (the review's false alarm)."""
    assert check("候補者の基準一致スコアを表示します。") == []


def test_the_claim_words_are_data_beside_the_list() -> None:
    assert {"早期発見", "リスク予測", "スコアリング", "未診断", "潜在患者"} <= set(CLAIM_OUTRIGHT_JA)
    assert "疑い患者" in FORBIDDEN
    assert check("AIが疾患を発見", claims=False) == []  # the claims can be left out explicitly, never by default


def _site_ja() -> dict[str, str]:
    """The Japanese text of the public site: the Japanese page, the demo and docs pages, the site's text table."""
    out: dict[str, str] = {}
    for name in ("index.ja.html", "demo.html", "docs.html", "screens.html", "report.html", "consent.html"):
        out[f"site/pages/{name}"] = visible_text((ROOT / "site/pages" / name).read_text(encoding="utf-8"))

    def walk(x: object, path: str) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{path}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]")
        elif isinstance(x, str):
            out[path] = x

    for name in ("site_text.json", "criteria_ja.json"):
        walk(json.loads((ROOT / "site/i18n" / name).read_text(encoding="utf-8")), f"site/i18n/{name}")
    return out


def test_the_public_site_makes_no_japanese_device_claim() -> None:
    """The Japanese device claims on the public site (10C-5): its pages and text tables. The site's other words (the
    verdict list of TB-IU-01 section 2) are not checked here: that is outside this card."""
    hits = [f"{where}: {h.word} in {h.context}" for where, text in _site_ja().items() for h in check_claims_ja(text)]
    assert hits == []


def test_a_seeded_claim_on_the_site_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    text = _site_ja()
    text["site/pages/index.ja.html"] += " AIが未診断の患者を早期発見します。"
    hits = [h.word for t in text.values() for h in check_claims_ja(t)]
    assert {"未診断", "早期発見"} <= set(hits)
