"""Card 10C-5b (D-1247): the Traditional Chinese (zh-TW) device-claims guard, through D-1228's one rule.

The Japanese tests of D-1228 (``tests/unit/test_wording.py``) run unchanged; this file mirrors them for zh-TW. For
every refused class there are near-misses that must pass, and for every allowed context the closest real claim that
must still be refused. ``FRESH_1`` (60 sentences) was written before the zh-TW rule was final, ``FRESH_2`` (40) after;
both are kept as written, and the PR reports how many each way the rule got right at each point.
"""

from __future__ import annotations

import re

import pytest
from console.i18n import CATALOGUES
from orchestrator import i18n as orch_i18n
from tb_common.wording import (
    CLAIM_ALLOWED_ZH,
    CLAIM_OUTRIGHT_ZH,
    CLAIM_TABLES,
    STATEMENT,
    Hit,
    check,
    check_claims,
    check_claims_ja,
    check_page,
    deny_masked,
)

from tests.unit.test_wording import _source


def zh(text: str, **kw: object) -> list[Hit]:
    """:func:`check` on text the caller names zh-TW, as a zh-TW catalogue's test does."""
    return check(text, lang="zh-TW", **kw)  # type: ignore[arg-type]


def zh_page(page: str) -> list[Hit]:
    return check_page(page, lang="zh-TW")


def zh_claims(text: str) -> list[Hit]:
    return check_claims(text, "zh-TW")


# Written before the zh-TW rule was final (card 10C-5b step 4): 30 claims, then 30 legitimate lines. Kept as written.
FRESH_1_CLAIMS = [
    "本系統可偵測早期肺癌病人。",
    "AI 能從病歷中找出尚未確診的糖尿病患者。",
    "TrialBox 會預測每位病人的住院風險。",
    "系統自動計算病人的死亡機率。",
    "本軟體提供疾病風險評分。",
    "協助醫師及早發現潛在病人。",
    "透過 AI 篩檢罕見疾病。",
    "模型判斷病人是否罹患心衰竭。",
    "列出疑似肺炎的病人清單。",
    "本產品可辨識有中風徵兆的病人。",
    "系統會針對每位受試者給出風險分數。",
    "AI 預後分析協助醫師。",
    "自動偵測病人病情惡化。",
    "本工具能早期檢出癌症。",
    "本軟體提供高危險群病人名單。",
    "TrialBox 找出可能有未診斷疾病的人。",
    "依 AI 評分排序病人。",
    "系統判別病人是否有腫瘤。",
    "演算法估算病人復發的機率。",
    "本系統能偵測敗血症前兆。",
    "我們的 AI 會發現醫師遺漏的疾病。",
    "為每位病患計算風險。",
    "AI 分數高的病人優先聯絡。",
    "篩檢出慢性腎病的高風險族群。",
    "本軟體可以早期篩檢失智症。",
    "系統會識別出病情可能加重的個案。",
    "本產品提供疾病預測服務。",
    "模型能判斷受試者的疾病嚴重度。",
    "利用人工智慧找出隱藏的病人。",
    "AI 會告訴您哪位病人最可能發病。",
]
FRESH_1_LEGITIMATE = [
    "本軟體不用於疾病之篩檢或診斷。",
    "系統找出近期回診的候選者。",
    "預測本月收案人數。",
    "依過去趨勢預測未來六個月的收案數。",
    "本研究的主要風險與好處請見同意書。",
    "試驗可能的風險已寫在受試者同意書中。",
    "無法辨識此檔案的文字編碼。",
    "低於偵測極限的數值維持不明。",
    "系統偵測到備份檔案不完整。",
    "請為此頁面評分。",
    "本軟體不預測病人的風險，也不給予任何分數。",
    "本工具並非用於發現疾病。",
    "是否符合研究資格由試驗主持人判斷。",
    "模型只讀取紀錄，參加與否由醫師判斷。",
    "計畫書中的 eGFR 分數由系統依公式計算。",
    "這份文獻的偏差風險為低。",
    "資料外洩的風險由資訊室管理。",
    "監測訪視的發現事項以新紀錄保存。",
    "識別編號已儲存。",
    "標記為識別資料的欄位會被捨棄。",
    "篩選結果顯示 12 位候選者符合條件。",
    "檢出率是合格病人中被找到的比例。",
    "系統沒有疾病預測功能。",
    "本軟體未提供任何風險評分。",
    "疾病代碼系統無法辨識時，條件列為未知。",
    "預測隨機分派人數需要篩選失敗率。",
    "分數定義變更後需重新核准。",
    "以 DAS28 分數核對病人的條件。",
    "試驗主持人判斷病人是否參加；TrialBox 僅列出紀錄。",
    "本軟體不做診斷、預測或風險分層。",
]


# Written after the zh-TW rule was final (card 10C-5b step 4): 20 claims, then 20 legitimate lines. Kept as written.
FRESH_2_CLAIMS = [
    "透過機器學習，系統能提前發現病人的急性腎損傷。",
    "TrialBox 可協助醫院找出罹患罕病卻未被診斷的病人。",
    "本產品為每位病人產生心血管事件風險。",
    "系統會依據檢驗值推估病人的存活期。",
    "AI 判讀胸部 X 光並標示可能的肺結節。",
    "我們的演算法能比醫師更早察覺敗血症。",
    "本軟體能分辨哪些病人有憂鬱傾向。",
    "系統自動標記高風險病人供醫師追蹤。",
    "提供每位受試者的疾病進展預測。",
    "本工具可篩出可能罹患糖尿病的民眾。",
    "AI 計算每位病人的再住院機率。",
    "系統能早期辨識心房顫動。",
    "演算法會判斷病人是否需要轉診。",
    "本軟體可偵測藥物不良反應的徵兆。",
    "TrialBox 的評分模型可區分輕症與重症病人。",
    "讓 AI 揪出被忽略的癌症個案。",
    "根據病歷預測病人未來一年發生中風的可能。",
    "系統提供個人化的疾病風險報告。",
    "本系統可協助診斷早期阿茲海默症。",
    "AI 會自動找出病歷中被漏掉的癌前病變。",
]
FRESH_2_LEGITIMATE = [
    "系統找出符合年齡與檢驗條件的候選者，交由主持人確認。",
    "本月預測可收案 8 位受試者。",
    "同意書說明參與研究可能的不適與風險。",
    "若無法辨識病歷號，請聯絡管理員。",
    "系統偵測到磁碟空間不足，已暫停匯入。",
    "研究護理師判斷病人是否已簽署同意書。",
    "請勿將本軟體用於臨床診斷。",
    "這不是疾病篩檢工具，而是研究收案輔助軟體。",
    "監測人員記錄訪視時發現的問題。",
    "分數欄位僅接受 0 到 10 的整數。",
    "請匯入計畫書中的 NIHSS 評分項目。",
    "本系統不會產生任何病人風險分數。",
    "收案預測依過去十二個月的就診人數計算。",
    "資安風險評估每年進行一次。",
    "主持人可在名單中找到每位病人的依據紀錄。",
    "試驗結束後，系統識別碼仍保留十年。",
    "備份檢查未發現任何問題。",
    "篩選漏斗顯示各階段的候選者人數。",
    "若模型無法判斷，該條件列為需要更多資訊。",
    "研究可能為受試者帶來的風險，由 IRB 審查。",
]


# Written after the review's round, with the rule final (card 10C-5b): 20 claims (two in Simplified), then 20
# legitimate lines (one in Simplified). Kept as written; the PR reports the first run before any change.
FRESH_3_CLAIMS = [
    "本系統能自動辨識罹患早期乳癌的女性。",
    "AI 模型會預測住院病人七天內的跌倒風險。",
    "透過演算法，及早找出可能失智的長者。",
    "本機可在急診分流時判斷病人的嚴重程度。",
    "系统能够自动发现隐藏的心脏病患者。",
    "我們的 AI 提供每位病人的再入院評分。",
    "本產品可篩檢出尚未確診的 C 型肝炎個案。",
    "系統會即時警示醫師哪些病人可能發生敗血症。",
    "AI 根據檢驗結果研判病人是否感染新冠肺炎。",
    "模型推估每位受試者的疾病進展機率。",
    "本平台可偵測心律不整並通知醫師。",
    "本软件可对高危人群进行早期筛查。",
    "系統會標示影像中可疑的病灶。",
    "TrialBox 能找出被醫師漏診的病人。",
    "本系統提供個人化的腎衰竭風險評估。",
    "AI 自動判別病患的癌症分期。",
    "本工具可提早發現術後併發症。",
    "我們用 AI 預測哪些民眾會罹患高血壓。",
    "系統能從病歷中挖掘潛在的罕見疾病病人。",
    "本機會針對惡化中的病人發出預警。",
]
FRESH_3_LEGITIMATE = [
    "系統依計畫書條件找出可能符合資格的候選者，交由主持人判斷。",
    "本機不會判斷病人是否患病，也不提供任何風險分數。",
    "收案預測顯示本季可納入 12 位受試者。",
    "篩選結果中有 5 位病人的條件尚待確認。",
    "系統偵測到網路連線中斷，已自動重試。",
    "同意書說明參加試驗的風險與可能的好處。",
    "ECOG 分數與 eGFR 由研究人員輸入。",
    "本软件不提供诊断，也不预测患者的风险。",
    "匯入時無法辨識的欄位會列為未知。",
    "監測報告的發現事項已寄給主持人。",
    "收案進度落後時，系統會發出提醒。",
    "名單中的每位病人都附有病歷依據段落。",
    "試驗主持人判斷是否邀請病人參加。",
    "系統識別碼與病歷號分開保存。",
    "每月預估人數依過去門診量計算。",
    "本工具並非用於篩檢疾病，而是協助收案。",
    "病名欄位依院內代碼對應。",
    "篩選前 28 天內的檢驗值會被讀取。",
    "系統警示：備份未完成。",
    "這份文獻的偏倚風險已由研究人員評估。",
]


@pytest.mark.parametrize("source", ["console", "orchestrator", "opportunity_hub"])
def test_no_zh_tw_catalogue_string_makes_a_device_claim(source: str) -> None:
    """Every zh-TW string of the console, orchestrator and opportunity-hub catalogues, read as zh-TW (the catalogue's
    language key names it; D-1228's own test reads every catalogue with no language, so as Japanese, as before)."""
    hits = []
    for key, text in _source(source)["zh-TW"].items():
        hits += [f"{key}: {h.word} in {h.context}" for h in zh(re.sub(r"{\w+}", " ", text))]
    assert hits == []


# The rule's classes in zh-TW, one or more sentences per form (D-1228's classes; D-1247's table). Each must fail.
CLAIMING_ZH = [
    # compound claim nouns, refused outright
    ("協助早期發現罕見疾病。", "早期發現"),
    ("本軟體提供風險預測。", "風險預測"),
    ("提供病人的預後資訊。", "預後"),
    ("列出未診斷的病人。", "未診斷"),
    ("找出尚未確診的病人。", "未確診"),
    ("協助醫師找出潛在病人。", "潛在病人"),
    ("產生疑似病例清單。", "疑似病例"),
    ("系統自動偵測異常。", "自動偵測"),
    ("顯示每位病人的風險分數。", "風險分數"),
    ("本軟體可用於診斷。", "診斷"),  # 診斷 was refused outright before 10C-5b and still is
    # finding words with a disease or an early / latent object
    ("AI 可偵測疾病的徵兆。", "偵測"),
    ("系統能篩檢癌症。", "篩檢"),
    ("從紀錄中發現病人的病情惡化。", "發現"),
    ("早期檢出病人的病變。", "檢出"),
    ("找出隱藏在紀錄中的中風病人。", "找出"),
    ("辨識有失智症狀的長者。", "辨識"),
    # rate words with a patient or disease object, or the product straight before them
    ("預測病人是否住院。", "預測"),
    ("顯示病人的死亡機率。", "機率"),
    ("依病人的危險程度排序。", "危險"),
    ("ＡＩ評分高者優先聯絡。", "評分"),  # full-width ＡＩ, NFKC-normalised first
    ("系統分數高的名單先處理。", "分數"),
    ("列出疑似罹患肺癌的民眾。", "疑似"),
    ("AI 預測病人風險，並且不提供治療建議。", "預測"),  # a negation in a later clause does not excuse it
    # a judgement whose subject is the product
    ("AI 判斷病人是否符合研究資格。", "判斷"),
    ("系統會判斷參加與否。", "判斷"),
    ("醫師參考後，由模型判斷。", "判斷"),
]
# The closest allowed sentence to each refused class (near-misses). Each must pass.
LEGITIMATE_ZH = [
    "找出近期回診的候選者。",  # the product's purpose: candidates for a study, by its written criteria
    "系統找出候選者，研究護理師確認。",
    "檢出率（合格病人中被找到的比例）。",  # a patient found for a study is no disease finding
    "系統偵測到服務異常狀態。",
    "監測訪視的發現事項。",
    "無法辨識文字編碼。",
    "資料外洩的風險由資訊室管理。",
    "偏差風險為低。",
    "ECOG 分數由研究人員輸入。",
    "依已儲存分數（eGFR、DAS28、CDAI、SDAI）核對。",
    "低於偵測極限的值維持不明。",
    "預測隨機分派數。",
    "預測月數。",
    "參加與否由試驗主持人判斷。",
    "模型只讀取紀錄，由人員判斷。",
    "本軟體不做診斷、預測或風險分層。",  # a real denial: a list of claim words with one negator
    "TrialBox 不會發現疾病。",
    "AI 不預測病人的風險。",
    "本工具並非用於篩檢疾病。",
    "系統沒有疾病預測功能。",
    "您對此頁面的評分（選填）。",
]


@pytest.mark.parametrize(("text", "word"), CLAIMING_ZH)
def test_a_zh_tw_device_claim_fails(text: str, word: str) -> None:
    assert word in [h.word for h in zh(text)]
    assert word in [h.word for h in zh_page(f"<p>{text}</p>")]  # the page walk calls the same check


@pytest.mark.parametrize("text", LEGITIMATE_ZH)
def test_a_legitimate_zh_tw_use_passes(text: str) -> None:
    assert zh(text) == []


def test_a_mixed_zh_tw_sentence_fails_only_on_the_claim() -> None:
    hits = zh("ECOG 分數由研究人員輸入，但 AI 會預測病人的風險。")
    assert sorted(h.word for h in hits) == ["預測", "風險"]
    assert zh("AI 讀取紀錄。偏差風險另行評估。") == []


# The five false alarms of the 10C-5 survey (master 73835e62), resolved by the rule's structure, not by an exemption:
# each passes as written, and the closest sentence without that structure is refused.
SURVEY = [
    # the statement: every claim word in it is denied by 不 / 非 + verb
    ("console", "footer.statement", "本軟體用於疾病之診斷。"),
    # a study's risks to the participant (the object is the study, its risks and benefits)
    ("console", "consent.help", "說明每位受試者的主要風險。"),
    # an enrolment forecast (the object is a count)
    ("console", "feas.s6", "每月新病人的發病預測"),
    # a code system that cannot be identified (無法 + the verb)
    ("console", "feas.bridge.unknown_system", "可辨識疾病的代碼系統。"),
    ("orchestrator", "screen.unknown_system", "可辨識疾病的代碼系統。"),
]


@pytest.mark.parametrize(("source", "key", "closest_claim"), SURVEY)
def test_the_surveys_false_alarms_pass_by_structure(source: str, key: str, closest_claim: str) -> None:
    cat = CATALOGUES["zh-TW"] if source == "console" else orch_i18n.T["zh-TW"]
    assert zh_claims(re.sub(r"{\w+}", " ", cat[key])) == []  # the claim rule alone: no help from ALLOWED
    assert zh(closest_claim) != []


def test_the_statement_passes_the_claim_rule_on_its_own() -> None:
    """The zh-TW statement is in ALLOWED, but it needs no mask: its claim words are denied."""
    assert zh_claims(STATEMENT["zh-TW"]) == []
    assert zh(STATEMENT["zh-TW"], allowed=()) == []


# Each allowed context is pinned: the sentence passes only because of its context, and fails without it. Beside each,
# the closest real claim, which the context must not let through.
PINNED_ZH = [
    ("分數", "病人的 ECOG 分數由研究人員輸入。", "病人的 AI 分數由系統計算。"),
    ("分數", "病人的分數定義已變更。", "病人的分數已變更。"),
    ("風險", "說明試驗的主要風險與好處給受試者。", "說明受試者的主要風險。"),
    ("風險", "病人研究的偏差風險為低。", "病人的風險為低。"),
    ("預測", "每月新病人與收案預測", "每月新病人與發病預測"),
    ("預測", "預測隨機分派病人數。", "預測病人數值的惡化。"),
    ("預測", "符合條件的病人數，以及每月預估人數。", "每月預估病人的死亡人數。"),
    ("偵測", "腫瘤標記低於偵測極限。", "偵測腫瘤標記的異常。"),
    ("篩選", "篩選前 90 日內發生中風。", "AI 篩選出中風的病人。"),
]


@pytest.mark.parametrize(("term", "allowed", "claim"), PINNED_ZH)
def test_each_zh_tw_allowed_context_is_what_lets_its_sentence_pass(
    term: str, allowed: str, claim: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert zh(allowed) == []
    assert zh(claim) != []
    monkeypatch.setitem(CLAIM_ALLOWED_ZH, term, ())
    assert zh_claims(allowed) != []


def test_an_actor_word_is_what_makes_a_zh_tw_judgement_a_claim() -> None:
    assert zh("判斷參加與否。") == []  # no actor: the product's words have a person judge
    for actor in ("系統", "AI", "模型", "TrialBox", "本軟體", "演算法"):
        assert [h.word for h in zh(f"{actor}判斷參加與否。")] == ["判斷"], actor
    assert zh("醫師參考 AI 的讀取結果判斷。") == []  # an attributive 的: the AI is not the subject
    assert zh("系統性回顧由研究人員判斷。") == []  # 系統性 (systematic) is not the system


@pytest.mark.parametrize(
    "text",
    [
        "本軟體不做診斷、預測或風險分層。",  # a list of claim words, denied together
        "本軟體不用於疾病之篩檢或診斷。",  # 不 + a light verb covers its object
        "本系統沒有疾病預測功能。",  # an existential negator covers the rest of its clause
        "本產品並非疾病篩檢工具。",  # a copular negator
        "本軟體非疾病篩檢工具。",  # 非 straight after the product's name
        "TrialBox 無法辨識疾病代碼時，條件列為未知。",
        "本工具不會預測病人的風險，也不給予任何分數。",
        "系統不提供風險評分。",
        "本產品不具疾病篩檢功能。",  # 不具 is one negator, not 不 and 具 counted twice
        "這不是疾病篩檢工具。",
        "請勿將本軟體用於診斷。",  # a prohibition
    ],
)
def test_a_zh_tw_denial_in_its_common_forms_passes(text: str) -> None:
    assert zh(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "AI 沒有一天不發現疾病。",  # two negatives deny nothing
        "本軟體不只預測疾病，也預測死亡。",  # 不只 (not only) is no negator
        "未符合條件之病人的發病風險由 AI 預測。",  # 未 negates 符合, not the claim
        "AI 偵測非小細胞肺癌。",  # 非 inside a disease name is no negator
        "AI 顯示病人沒有風險。",  # said about the patient: no denial of the product's claim
        "本軟體不提供治療建議，但會預測病人的風險。",  # the negator's clause ends at the comma
        "AI 預測未來的疾病。",  # 未來 (future) is no negator
    ],
)
def test_zh_tw_false_negatives_are_not_a_denial(text: str) -> None:
    assert zh(text) != []


def test_on_a_page_a_block_ends_a_zh_tw_sentence_and_an_inline_tag_does_not() -> None:
    assert zh_page("<ul><li>AI 讀取</li><li>判斷參加與否</li></ul>") == []
    assert [h.word for h in zh("AI 讀取 判斷參加與否")] == ["判斷"]  # the same words in one sentence
    assert [h.word for h in zh_page("<p><b>AI</b><b>偵測</b>疾病</p>")] == ["偵測"]
    assert [h.word for h in zh_page("<p>AI\n    偵測疾病</p>")] == ["偵測"]


def test_invisible_characters_do_not_hide_a_zh_tw_claim() -> None:
    for c in ("\u200b", "\u200d", "\u2060", "\ufeff", "\u00ad", "\u3164", "\u034f"):
        assert [h.word for h in zh(f"AI 偵{c}測疾{c}病。")] == ["偵測"], repr(c)


def test_a_candidate_is_not_a_zh_tw_patient_word() -> None:
    assert zh("候選者的條件符合分數。") == []
    assert zh("病人的條件符合分數。") != []


def test_one_rule_two_tables() -> None:
    """One rule (D-1228), one table per language (D-1247): the caller names the language. Text named zh-TW is read by
    the zh-TW table too; text with no language, or named ja or en, by the Japanese table only, as before D-1247."""
    assert [t.lang for t in CLAIM_TABLES] == ["ja", "zh-TW"]
    assert check_claims("AIが疾患を発見します。") == check_claims_ja("AIが疾患を発見します。") != []
    assert zh_claims("AI 預測病人的風險。") != [] and check_claims("AI 預測病人的風險。") == []
    assert deny_masked("本軟體不預測風險。", "zh-TW") != "本軟體不預測風險。"
    assert deny_masked("本軟體不預測風險。") == "本軟體不預測風險。"  # not named zh-TW: no zh-TW denial either
    assert deny_masked("本製品は予測を行いません。") != "本製品は予測を行いません。"
    assert {"早期發現", "風險預測", "未診斷", "潛在病人", "預後"} <= set(CLAIM_OUTRIGHT_ZH)


@pytest.mark.parametrize("text", ["症例識別番号", "症例識別子", "症状評分", "疑似乱数で患者の表示順を決めます。"])
def test_japanese_text_is_never_read_by_the_zh_tw_table(text: str) -> None:
    """The review's regression: a Japanese line in kanji only (症例識別番号) was read by the zh-TW table when the
    language was guessed from the script. The caller names the language; the script is never used."""
    assert check(text) == [] and check(text, lang="ja") == []
    assert check_page(f'<html lang="ja"><p>{text}</p></html>') == []


def test_a_page_names_its_own_language() -> None:
    page = '<html lang="zh-TW"><body><p>本系統可偵測疾病。</p></body></html>'
    assert [h.word for h in check_page(page)] == ["偵測"]
    assert check_page(page.replace('lang="zh-TW"', 'lang="ja"')) == []  # the same words named Japanese
    assert check_page(page, lang="ja") == []  # the caller's language wins


@pytest.mark.parametrize("text", FRESH_1_CLAIMS)
def test_every_fresh_claim_of_the_first_set_fails(text: str) -> None:
    """A real claim that passes is a blocker (card 10C-5b)."""
    assert zh(text) != []
    assert zh_page(f"<p>{text}</p>") != []


@pytest.mark.parametrize("text", FRESH_1_LEGITIMATE)
def test_every_fresh_legitimate_line_of_the_first_set_passes(text: str) -> None:
    assert zh(text) == []


@pytest.mark.parametrize("text", FRESH_2_CLAIMS)
def test_every_fresh_claim_of_the_second_set_fails(text: str) -> None:
    assert zh(text) != []
    assert zh_page(f"<p>{text}</p>") != []


@pytest.mark.parametrize("text", FRESH_2_LEGITIMATE)
def test_every_fresh_legitimate_line_of_the_second_set_passes(text: str) -> None:
    assert zh(text) == []


# The review of cc197e3b (lane J): each finding, its claims and its near-misses both ways.
REVIEW_CLAIMS = [
    # a disease object by its class, not only from a list
    ("本系統可偵測糖尿病。", "偵測"),
    ("模型能識別心衰竭。", "識別"),
    ("系統可找出肺炎病人。", "找出"),
    ("找出糖尿病病人。", "找出"),
    ("AI 可辨識高血壓與氣喘。", "辨識"),
    ("系統能偵測急性心肌梗塞。", "偵測"),
    # Simplified Chinese, read through the same table
    ("本系统可自动检测糖尿病患者。", "检测"),
    ("本系统可辅助诊断肺癌。", "诊断"),
    ("模型能预测患者的发病风险。", "预测"),
    ("可自动识别高风险人群。", "风险"),
    ("本产品可对患者进行风险分层。", "风险分层"),
    ("人工智能早期发现潜在患者。", "早期发现"),
    # early warning about a patient's condition
    ("本系統提供敗血症早期預警。", "早期預警"),
    ("系統會針對急性腎損傷提前示警。", "提前示警"),
    ("TrialBox 可在病人惡化前發出警示。", "警示"),
    ("智慧預警，防患未然。", "預警"),
    # the box's own name and "we" as actors
    ("本機能輔助判斷病人病情。", "判斷"),
    ("本機判斷病人罹患糖尿病。", "判斷"),
    ("我們判斷病人是否符合資格。", "判斷"),
    # a denial covers its own clause and the verb it negates only
    ("本機不提供診斷但會偵測疾病。", "偵測"),
    ("本機不提供診斷，卻會預測病人的風險。", "預測"),
    ("本機沒有漏掉任何一位疑似病人。", "疑似病人"),
    ("系統不會遺漏任何癌症病人。", "癌"),
    # an allowed context never swallows a longer claim
    ("本系統提供研究風險預測。", "風險預測"),
    ("系統提供試驗風險評分。", "風險評分"),
    # claim nouns in a list or a heading
    ("功能包括：名單匯出、疾病預測、資料清洗。", "疾病預測"),
    ("本機支援：條件比對、早期預警、匯出 CSV。", "早期預警"),
    ("疾病篩查與預後預測解決方案。", "預後"),
    # triage of patients by their condition (TFDA guidance section 五(五))
    ("系統依病情分流急診病人。", "分流"),
]
REVIEW_NEAR_MISSES = [
    "找出符合納入條件的病人。",
    "找出近期回診的病人與其病歷號。",
    "依病名篩選候選者。",
    "病程紀錄由研究護理師閱讀。",
    "系統警示：資料匯入失敗。",
    "匯入完成後系統會發出提醒。",
    "本機現以新版本計算。",
    "本機不提供診斷。",
    "本机不提供诊断，也不预测患者的风险。",
    "研究的風險與好處請見同意書。",
    "本系统可自动检索符合纳入条件的患者。",
    "找出适合参加研究的候选者。",
    "藥品適應症篩選。",
    "請勿將本機用於篩檢疾病或預測病人風險。",
]


@pytest.mark.parametrize(("text", "word"), REVIEW_CLAIMS)
def test_a_claim_the_review_found_fails(text: str, word: str) -> None:
    hits = zh(text)
    assert hits and any(word in h.word or word in h.context for h in hits), hits
    assert zh_page(f"<p>{text}</p>") != []


@pytest.mark.parametrize("text", REVIEW_NEAR_MISSES)
def test_a_near_miss_of_the_review_passes(text: str) -> None:
    assert zh(text) == []


def test_the_simplified_map_covers_every_character_the_table_uses() -> None:
    """Every Chinese character of the zh-TW table is either mapped to its Simplified form or declared the same in
    both scripts, so a new term cannot slip through in Simplified."""
    import tb_common.wording as w

    words = (
        *w.CLAIM_OUTRIGHT_ZH,
        *w.FORBIDDEN_SIMPLIFIED_ZH,
        *w.CLAIM_FIND_ZH,
        *w.CLAIM_RATE_ZH,
        *w.CLAIM_WARN_ZH,
        *w.CLAIM_JUDGE_ZH,
        *w.CLAIM_REMIND_ZH,
        *w.CLAIM_ACT_ZH,
        *w._ACT_RECORD_BEFORE_ZH,
        *w._ACT_RECORD_AFTER_ZH,
        *w.CLAIM_STATE_ZH,
        *w._STATE_WORDS_ZH,
        *w.CLAIM_DECIDE_ZH,
        *w._TREATMENT_ZH,
        *w.CLAIM_DISEASE_ZH,
        *w.CLAIM_EARLY_ZH,
        *w.CLAIM_PATIENTS_ZH,
        *w.CLAIM_ACTORS_ZH,
        *w.CLAIM_PERSONS_ZH,
        *w._CLAIM_CONTINUES_ZH,
        *w._NEG_VERBAL_LIST_ZH,
        *w._NEG_WHOLE_LIST_ZH,
        *w._AUX_LIST_ZH,
        *w._LIGHT_LIST_ZH,
        *w._MISS_LIST_ZH,
        *w._CLAUSE_WORDS_ZH,
        *w._ATTRIBUTIVE_LIST_ZH,
        w._DISEASE_CLASS_ZH,
        *(p for ps in w.CLAIM_ALLOWED_ZH.values() for p in ps),
    )
    used = {c for word in words for c in word if "一" <= c <= "鿿"}
    # the disease class is written in both scripts at once, so its Simplified characters are values of the map
    assert used - set(w._SIMPLIFIED) - set(w._SIMPLIFIED.values()) - set(w._SAME_ZH) == set()
    assert not set(w._SIMPLIFIED) & set(w._SAME_ZH)
    assert all(t != s for t, s in w._SIMPLIFIED.items())
    assert w._simplified("人工智慧早期發現潛在病人") == "人工智能早期发现潜在病人"


def test_the_known_limits_are_what_d1247_says() -> None:
    """D-1247's known limits, recorded so that a change to them is seen: the window's false alarm on 疑似 near a
    patient word; a claim split across sentences; a metaphor with no claim word."""
    assert zh("以疑似亂數決定患者的顯示順序。") != []  # a false alarm (pseudo-random numbers), refused
    assert zh("病人是否罹患肺癌？系統會告訴您。") == []  # a claim split across two sentences, not seen
    assert zh("揪出藏在病歷裡的病人。") == []  # a metaphor with no claim word, not seen
    assert zh("可治療憂鬱症。") == []  # an act on a disease with no subject, not seen
    assert zh("已診斷類風濕關節炎。") != []  # a criterion's 診斷 with no subject, still refused by FORBIDDEN


def test_a_catalogue_instrument_is_named_by_its_own_name() -> None:
    """The page walk reads /data/instruments in zh-TW: an instrument's catalogue name (伯明罕血管炎活動度評分, FRAX
    十年主要骨鬆性骨折機率) is a record value's name, not the product scoring a patient (D-351). Every zh-TW name in the
    catalogue passes the claim rule, each listed name is in the catalogue, and the closest real claims fail."""
    import csv
    from pathlib import Path

    from tb_common.wording import NAMED_INSTRUMENTS_ZH

    rows = list(csv.DictReader((Path(__file__).parents[2] / "catalogue/items.csv").open(encoding="utf-8")))
    names = [r["name_zh_tw"] for r in rows]
    assert [n for n in names if zh_claims(n)] == []
    assert [n for n in NAMED_INSTRUMENTS_ZH if not any(n in name for name in names)] == []
    for claim in ("AI 計算病人的骨折機率。", "系統預估病人的存活期。", "本機給出病人的預後指數。", "AI 為病人評分。"):
        assert zh(claim) != [], claim


@pytest.mark.parametrize("text", FRESH_3_CLAIMS)
def test_every_fresh_claim_of_the_third_set_fails(text: str) -> None:
    assert zh(text) != []
    assert zh_page(f"<p>{text}</p>") != []


@pytest.mark.parametrize("text", FRESH_3_LEGITIMATE)
def test_every_fresh_legitimate_line_of_the_third_set_passes(text: str) -> None:
    assert zh(text) == []


# The second review (lane J, an independent set of 300 sentences on 8f2bc3db): its sentences and more in kind, by
# class. Claims first (each with a word its hit names), then the honest lines that must pass.
REVIEW_2_CLAIMS = [
    # treat, cure, efficacy (醫療器材管理法 第 3 條; TFDA guidance 三(三))
    ("這套工具可治療憂鬱症。", "治療"),
    ("TrialBox 可協助醫師治療氣喘病人。", "治療"),
    ("TrialBox 能幫助病人治癒 C 型肝炎。", "治癒"),
    ("本產品的療效已經臨床證實。", "療效"),
    ("本系统可治疗高血压。", "治疗"),
    # prevent or reduce an outcome
    ("使用本系統可預防心肌梗塞。", "預防"),
    ("本系統能預防院內感染。", "預防"),
    ("使用 TrialBox，可減少中風復發。", "減少"),
    ("研究顯示，本系統可降低死亡率。", "降低"),
    ("本系統雖非醫療器材，仍能有效預防中風。", "預防"),
    ("本系統不用於治療，但用於預防糖尿病。", "預防"),
    ("本系统能预防心肌梗塞。", "预防"),
    # decide or recommend for the clinician
    ("系統會自動決定病人應接受哪種治療。", "決定"),
    ("由 AI 決定病人是否需要開刀。", "決定"),
    ("系統直接替醫師做出臨床決策。", "臨床決策"),
    ("本系統建議最適合病人的治療方案。", "建議"),
    ("本系統會為每位病人推薦用藥劑量。", "推薦"),
    # 提醒 with a condition is a warning
    ("系統會提醒醫師哪些病人可能罹患敗血症。", "提醒"),
    ("系統提醒醫師注意病人可能的心臟衰竭。", "提醒"),
    # verbs that are a claim with their object
    ("本系統可確診早期肺癌。", "確診"),
    ("系統可以確定病人是否感染流感。", "確定"),
    ("AI 能預知病人何時中風。", "預知"),
    ("模型可區分良性與惡性腫瘤。", "區分"),
    ("系統會告訴您是否罹患糖尿病。", "告訴"),
    ("本系統可大幅減少誤診。", "誤診"),
    ("系統會評估每位病人的病情。", "評估"),
    ("系統依病歷算出病人罹患心臟病的可能性。", "算出"),
    ("系統可偵測肝硬化。", "偵測"),
    ("AI 能及時辨識肺纖維化。", "辨識"),
    # a space inside a word
    ("本系統可協助診　斷肺癌。", "診斷"),
    ("本系統可協助診 斷肺癌。", "診斷"),
    ("系統可早 期 發 現癌症。", "早期發現"),
]
REVIEW_2_LEGITIMATE = [
    # a denial whose list continues after 、 or 或
    "本系統不做診斷、風險分層。",
    "本軟體不用於篩檢、偵測疾病。",
    "本系統不做診斷或風險分層。",
    "本軟體不用於篩檢或偵測疾病。",
    "本系統不提供診斷、治療或預後資訊。",
    "本系統不能「診斷癌症」。",
    "本欄位與病人的疾病風險無關。",
    "本系統不用於預防或治療疾病。",
    "本系統不會告訴病人任何診斷結果。",
    # a person judges, decides or diagnoses
    "本系統不取代醫師的判斷。",
    "本系統顯示的內容不是結論，而是供參考的醫師的判斷紀錄。",
    "本系統只列出醫師的判斷。",
    "本系統僅顯示資料，判斷由人負責。",
    "本系統列出紀錄，醫師再自行判斷。",
    "醫師參考病歷後自行判斷是否收案。",
    "研究團隊會依計畫書判定受試者是否完成試驗。",
    "由醫師決定是否給予治療。",
    "本系統提供資料，由醫師決定治療方式。",
    # 診斷 as a record field, a criterion, or a person's act
    "請填寫診斷日期。",
    "納入條件：經診斷為第二型糖尿病至少一年。",
    "醫師依病歷診斷後，再由研究人員確認。",
    # finding candidates, not disease
    "本系統不篩檢疾病，只篩選候選受試者。",
    "本系統幫助研究團隊更早找到可能符合條件的受試者。",
    # the new classes' ordinary words
    "列出正在接受糖尿病治療的病人。",
    "顯示病人的治療紀錄與用藥。",
    "本系統列出正在接受糖尿病治療的病人。",
    "本系統顯示糖尿病病人的治療紀錄。",
    "本系統可減少研究人員抄寫資料的時間。",
    "系統會提醒您於回診前確認病人的同意書。",
    "系統建議您先匯出名單再寄送。",
    "試驗計畫書規定的治療方案請見附件。",
    "研究團隊會評估受試者是否符合收案條件。",
    "系統計算符合條件的病人數。",
    "系统会提醒研究人员核对患者的同意书。",
]


@pytest.mark.parametrize(("text", "word"), REVIEW_2_CLAIMS)
def test_a_claim_of_the_second_review_fails(text: str, word: str) -> None:
    hits = zh(text)
    assert hits and any(word in h.word or word in h.context.replace(" ", "").replace("　", "") for h in hits), hits
    assert zh_page(f"<p>{text}</p>") != []


@pytest.mark.parametrize("text", REVIEW_2_LEGITIMATE)
def test_an_honest_line_of_the_second_review_passes(text: str) -> None:
    assert zh(text) == []
    assert zh_page(f"<p>{text}</p>") == []


def test_the_new_classes_are_zh_tw_only_and_the_japanese_table_lacks_them() -> None:
    """D-1247: treat / prevent (act), a patient's state, deciding a treatment and 提醒 are classes of the zh-TW table
    only. The Japanese table (D-1228) has none of them, and English has no claim table at all; widening those is
    outside card 10C-5b, so the gap is recorded here and in D-1247."""
    ja, zh_table = CLAIM_TABLES
    assert (ja.act, ja.state, ja.decide, ja.remind, ja.warn) == ((), (), (), (), ())
    assert zh_table.act and zh_table.state and zh_table.decide and zh_table.remind
    assert check_claims_ja("本システムは糖尿病を治療します。") == []  # recorded: a Japanese treat claim is not seen


def test_a_person_clears_a_judgement_only_as_the_nearest_subject() -> None:
    """The nearest subject before the word decides; the product helping a person judge is still the product's."""
    assert zh("本系統提供資料，由醫師判斷。") == []
    assert zh("醫師的判斷優先。") == []
    assert zh("AI 協助醫師判斷病情。") != []
    assert zh("本系統判斷，醫師確認。") != []
    assert zh("醫師使用本系統判斷病情。") != []


def test_a_diagnosis_is_the_products_only_with_the_product_as_subject() -> None:
    """FORBIDDEN's 診斷 / 判定 in text named zh-TW: a record field, a passive by a qualified person and a person's own
    act pass; the product as the subject is refused. Text not named zh-TW reads 診斷 as before (refused)."""
    for text in ("診斷碼與診斷日期。", "經醫師診斷為肺炎。", "研究人員依計畫書判定。"):
        assert zh(text) == [], text
        assert check(text) != [], text  # unnamed: FORBIDDEN as before
    for text in ("本系統依病歷診斷肺炎。", "AI 判定病人是否符合。", "AI 協助醫師診斷肺炎。"):
        assert zh(text) != [], text
