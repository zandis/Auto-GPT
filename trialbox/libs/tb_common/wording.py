"""The product's own words (TB-IU-01 §2, WS-13.7; card T-506, the PoC part of T-116).

One place for three things:

* ``STATEMENT``: the intended-use statement of TB-IU-01 §1 in three languages. The console footer renders it from
  here; ``tests/unit/test_wording.py`` checks that ``docs/plan/intended-use.md`` carries the same text, so the
  document and the product cannot drift apart (REG-020).
* ``FORBIDDEN``: words that give a verdict about a patient. A patient's records "did not match criterion X"; the
  product never says the patient was "excluded" (除外, 排除), and never labels a patient "likely eligible" (REG-017).
  The walk over the investigator's and the coordinator's pages calls :func:`check_page` on every page.
* ``ALLOWED``: exact phrases that contain a forbidden word but give no verdict: the statement itself (its own
  negations) and the protocol's name for a kind of criterion (除外基準, 排除條件), the heading a site's protocol
  uses (field research, ``docs/reviews/2026-11-08-field-research-tw-jp-sites.md``). They are masked before the check.

Card T-116 (the rest after T-506) makes the whole TB-IU-01 §2 list one list: the walk checks every page in every role
and language against it, a catalogue test checks every console and orchestrator string, and the report writers and the
mail gateway print :func:`statement` on every PDF, XLSX, HTML sheet and mail (decision D-351). A record's own field is
not a verdict, so the product names it with a word that is not on the list ("condition", 病名, 疾病) rather than
widening ``ALLOWED``. Protocol and chart text that the product quotes (a criterion's own words, a note passage) is the
source's wording, not the product's; it is shown as written.

``EXEMPT_PATHS`` names the files that may name the hazard plainly (TB-IU-01 §2: "only the risk file names the hazard
plainly"); :func:`check_file` skips them by design.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

LANGS = ("en", "ja", "zh-TW")

STATEMENT: dict[str, str] = {
    "en": (
        "TrialBox supports clinical research operations at a hospital. It builds a pseudonymised research repository "
        "from the hospital's own records, estimates how many patients may meet a research study's eligibility "
        "criteria, prepares lists of possible candidates with the record passages they rest on, lists the patients "
        "whose records do not match a criterion for the investigator's review, writes cited patient summaries for "
        "research staff, and drafts research-record values for a qualified person to confirm. TrialBox does not "
        "diagnose, treat or prevent disease, does not decide whether a patient is eligible for a study, does not "
        "recommend treatment, gives no clinical alerts, and sends nothing to patients (staff may hand a patient a "
        "printed visit reminder). A qualified person decides on every output before it is acted on. TrialBox is not "
        "a medical device."
    ),
    "ja": (
        "TrialBox は病院における臨床研究業務を支援するソフトウェアです。病院自身の記録から仮名化"
        "された研究用データベースを作成し、研究の参加条件に合う可能性のある患者数を見積もり、根拠となる記"
        "録の該当箇所を添えて候補者一覧を作成し、条件に合致しない患者を研究責任者の確認のために一覧にし、"
        "研究担当者向けに出典付きの患者要約を作成し、資格のある担当者が確認するための研究記録の値の下書き"
        "を作成します。疾病の診断・治療・予防は行わず、研究参加の可否を判断せず、治療を推奨せず、臨床上の"
        "警告を出さず、患者へは何も送信しません（担当者が印刷した来院案内を患者に渡すことはあります）。す"
        "べての出力は、資格のある担当者が判断してから用いられます。本ソフトウェアは医療機器ではありません"
        "。"
    ),
    "zh-TW": (
        "TrialBox 為支援醫院臨床研究作業之軟體。本軟體以醫院自身之紀錄建立假名化研究資料庫，估計"
        "可能符合研究收案條件之病人數，產生附有依據紀錄段落之候選名單，列出紀錄未符合某條件之病人供研究主"
        "持人覆核，為研究人員撰寫附出處之病人摘要，並產生研究紀錄數值之草稿供合格人員確認。本軟體不用於疾"
        "病之診斷、治療或預防，不判定病人是否符合研究資格，不提供治療建議，不發出臨床警示，亦不傳送任何訊"
        "息給病人（工作人員可交給病人紙本回診提醒）。所有輸出皆由合格人員判斷後方予採用。本軟體非醫療器材"
        "，不作為診斷依據。"
    ),
}

# Verdict words about a patient. Latin terms match whole words in any case (an identifier such as
# ``excluded_GZQO.json`` is not prose and does not match); CJK terms match anywhere.
FORBIDDEN: tuple[str, ...] = (
    "excluded",
    "除外",
    "排除",
    "likely eligible",
    "eligible patient",
    "適格の可能性が高い",
    # the rest of TB-IU-01 §2 (T-116): every page, every role, every catalogue, reports and mail
    "診断",
    "判定",
    "対象外",
    "見逃し",
    "診斷",
    "diagnosis",
    "diagnoses",
    "abnormal",
    "risk score",
    "AI decides",
    "AIが判定",
    "建議治療",
    "疑い患者",  # 10C-5 (JP-4): a "suspected" patient is a diagnosis-side label (case database No.243)
)
# Not on the list: 不符合 (zh-TW "not met") names a criterion's answer against a record, the counterpart of "not met"
# and 非該当; the patient-level name is 未符合條件 ("criteria not matched"). D-351 records why.

# Kept for callers written before T-116: the words that were checked only on request are now in FORBIDDEN.
LATER: tuple[str, ...] = ()

# Files that may name the hazard plainly (TB-IU-01 §2). Paths relative to the trialbox folder; a folder ends in "/".
EXEMPT_PATHS: tuple[str, ...] = (
    "docs/plan/",  # the risk file and the plans name the hazard ("wrong exclusion") and quote the old words
    "docs/reviews/",  # reviews quote the words they found
    "docs/decisions/",  # decisions quote the words they changed
)

# Exact phrases that contain a forbidden word and give no verdict. Longest first, so a longer phrase is masked whole.
ALLOWED: tuple[str, ...] = tuple(
    sorted(
        {
            *STATEMENT.values(),
            "除外基準",  # ja: the protocol's "exclusion criteria" heading (a kind of criterion, not a patient outcome)
            "排除條件",  # zh-TW: the same heading
            "排除標準",  # zh-TW: the same heading, in the form some protocols use
        },
        key=len,
        reverse=True,
    )
)

# Japanese device claims (JP-4, card 10C-5, D-1228; the reasoning is docs/plan/intended-use-jp.md).
#
# WHAT THIS IS: a lint over the project's OWN Japanese texts that catches common claim forms. It is NOT a guarantee
# that a text makes no device claim, and every new Japanese public text still needs a human reading. Measured on an
# independent set of unseen sentences at commit 0a5b7170 it missed 14 of 40 claims and raised 7 false alarms on 40
# legitimate lines (at 82f4c721: 10 of 35 missed, 5 of 25 false alarms); the known limits are listed in
# docs/plan/intended-use-jp.md section 5. Lemma matching with a morphological analyser and a disease test from the
# product's own vocabulary are a follow-up card, waiting on the owner's decision about a library.
#
# Under the MHLW guideline a program is a device by what it says it does: finding, detecting or predicting disease, or
# giving a patient a risk, a score or a prognosis (case database No.74, No.243). Finding trial CANDIDATES by a
# study's written criteria is the product's purpose and no such claim. So the rule refuses the claim, not the word,
# and tells the two apart by the OBJECT of the word:
#
# * CLAIM_OUTRIGHT_JA: compound claim nouns that are a claim whatever surrounds them (早期発見, リスク予測, 予後,
#   スコアリング, 潜在患者 ...).
# * CLAIM_FIND_JA (発見, 検出, 見つけ, スクリーニング ...): a claim when a disease word (CLAIM_DISEASE_JA: 疾患, 兆候,
#   発症 ...) or an "early / latent" word (CLAIM_EARLY_JA: 早期, 潜在, 見逃) is within CLAIM_WINDOW characters; finding
#   patients or candidates for a study is not.
# * CLAIM_RATE_JA (予測, リスク, 危険度, スコア, 確率): a claim when a patient word (CLAIM_PATIENTS_JA) or a
#   disease word is within the window, or the AI / the product / a model stands straight before it (AIスコア,
#   AIによる予測).
# * 判断: a claim when the product, the system, the AI or a model is its subject in the same clause, or in an earlier
#   clause with no person as subject in between (モデルが読み、人が判断します is no claim: CLAIM_PERSONS_JA). A
#   judgement in the product's own words has a person as subject; what a model does is 読み取り (D-1228).
#
# Before matching: NFKC (half-width ﾘｽｸ, full-width ＡＩ) and zero-width / invisible characters removed (clean_ja);
# the allowed contexts masked (named clinical scales, a lab's detection limit, バイアスのリスク, a study's enrolment
# forecast); and every DENIED claim word masked by structure: the rest of its clause carries an odd number of negative
# endings (行いません, 機能はありません, ものではありません, ツールではありません; two negatives cancel). A clause
# ends at 。！？, a line end, or a comma that does not continue a list of claim words; a closing bracket does not end
# it. A sentence ends at 。！？ or a line end; on a page a block element ends a line and an inline tag joins
# (sentences_of_page). 診断 and 判定 stay refused outright in FORBIDDEN, and 疑い患者 joins them; a denial of them is
# masked too. Protocol and chart text the product quotes is not the product's wording (D-351): the catalogue holds
# none, the page walk leaves out cells marked data-wording="source", but criterion text shown elsewhere on a page, and
# the site's criterion labels (site/i18n/criteria_ja.json), do reach the rule.

CLAIM_OUTRIGHT_JA: tuple[str, ...] = (
    "未診断",
    "早期発見",
    "早期検知",
    "早期検出",
    "リスク予測",
    "リスク層別",
    "予後",
    "発症予測",
    "疾患予測",
    "疾病予測",
    "重症化予測",
    "スコアリング",
    "自動検出",
    "自動検知",
    "潜在患者",
    "掘り起こ",
    "拾い上げ",
)
CLAIM_FIND_JA: tuple[str, ...] = (
    "発見",
    "見つけ",
    "見つか",
    "検出",
    "検知",
    "探し出",
    "スクリーニング",
    "特定",
    "判別",
    "識別",
)
CLAIM_RATE_JA: tuple[str, ...] = ("予測", "リスク", "危険度", "スコア", "確率")
CLAIM_JUDGE_JA: tuple[str, ...] = ("判断",)

CLAIM_DISEASE_JA: tuple[str, ...] = (
    "疾患",
    "病気",
    "疾病",
    "兆候",
    "徴候",
    "予兆",
    "病変",
    "発症",
    "重症",
    "病態",
    "悪化",
    "がん",
    "癌",
    "腫瘍",
)
CLAIM_EARLY_JA: tuple[str, ...] = ("早期", "早く", "潜在", "見逃")
# not 候補者: a candidate for a study is the product's own word (候補者の基準一致スコア is no claim about a patient)
CLAIM_PATIENTS_JA: tuple[str, ...] = ("患者", "被験者", "受診者", "対象者", "症例", "個人")
CLAIM_ACTORS_JA: tuple[str, ...] = (
    "TrialBox",
    "本ソフトウェア",
    "本システム",
    "システム",
    "本製品",
    "本ツール",
    "AI",
    "人工知能",
    "モデル",
    "アルゴリズム",
)
# a person as the subject of a judgement: 医師が判断します is the product's own rule, not a claim
CLAIM_PERSONS_JA: tuple[str, ...] = (
    "人",
    "医師",
    "担当者",
    "責任医師",
    "研究者",
    "CRC",
    "あなた",
    "スタッフ",
    "職員",
    "スチュワード",
)
CLAIM_WINDOW = 12

# The named clinical scales whose score a clinician enters or the box computes by its published formula for a
# criterion (eGFR, DAS28, CDAI, SDAI nightly): a scale's score is a record value, not the product scoring a patient.
NAMED_SCALES: tuple[str, ...] = (
    "ECOG",
    "Karnofsky",
    "KPS",
    "NIHSS",
    "MMSE",
    "MoCA",
    "CDR",
    "ADAS-Cog",
    "DAS28",
    "CDAI",
    "SDAI",
    "HAQ",
    "eGFR",
    "APACHE",
    "SOFA",
    "Child-Pugh",
    "MELD",
    "CHA2DS2-VASc",
    "HAS-BLED",
    "Gleason",
    "NYHA",
    "PHQ-9",
    "GAD-7",
    "EDSS",
    "PASI",
    "EASI",
    "GCS",
    "mRS",
)

# Allowed contexts, per term: regular expressions masked before the rule looks. Each is pinned by a test.
CLAIM_ALLOWED_JA: dict[str, tuple[str, ...]] = {
    "スコア": (
        r"(?:"
        + "|".join(re.escape(s) for s in sorted(NAMED_SCALES, key=len, reverse=True))
        + r")(?:\s*PS)?\s*(?:の)?スコア",
        r"アンダースコア",
        r"スコア定義",
    ),
    "リスク": (r"バイアスのリスク", r"リスク・?オブ・?バイアス"),
    # a study's enrolment forecast (feasibility) is a count, not a patient's outcome
    "予測": (r"(?:登録|組み入れ|無作為化|同意取得)(?:数の|の)?予測", r"予測される(?:登録|無作為化|同意取得)"),
    "検出": (r"検出(?:限界|下限)",),
}

# Japanese, the classes D-1247 gave zh-TW (card 10C-5c, D-1256). Each is a claim only with its object, and the
# act, state and decide classes only with the product as the subject (GRAMMAR_JA); the words differ, the rule is one.
# A disease is judged by its class, as in zh-TW: a noun ending in 病 / 症 / 炎 / 癌 / 腫 / 不全 / 梗塞 / 卒中 / 細動 /
# 硬化 is a disease (糖尿病, 認知症, 肺炎, 心不全), while 病院, 病名, 病歴, 病棟, 病床, 病理, 病室, 症例 and 適応症 are
# not; CLAIM_DISEASE_MORE_JA adds the names that do not end so (喘息, 高血圧, 再入院).
CLAIM_DISEASE_MORE_JA: tuple[str, ...] = (
    "喘息",
    "高血圧",
    "疼痛",
    "結核",
    "骨折",
    "転倒",
    "死亡",
    "再入院",
    "再発",
    "感染",
    "罹患",
    "コロナ",
    "COPD",
    "不整脈",
    "転帰",
)
_DISEASE_CLASS_JA = r"(?:病(?![院棟名歴床理室])|(?<!適応)症(?!例)|炎|癌|腫|不全|梗塞|卒中|細動|硬化)"
CLAIM_OUTRIGHT_MORE_JA: tuple[str, ...] = ("早期警告", "早期診断", "疑い例", "疑い症例", "誤診", "臨床判断支援")
CLAIM_FIND_MORE_JA: tuple[str, ...] = ("フラグ", "見落と", "見過ご", "捉え", "洗い出")
# "miss": a negated miss (見落とすことはありません) claims completeness; it denies nothing
CLAIM_MISS_JA: tuple[str, ...] = ("見落と", "見過ご", "見逃")
CLAIM_EARLY_MORE_JA: tuple[str, ...] = ("隠れ", "未受診")
# rate words that are a claim only about a disease (敗血症の可能性がある患者): 参加条件に合う可能性のある患者 is the
# product's statement
CLAIM_POSSIBLE_JA: tuple[str, ...] = ("可能性", "疑い", "疑う", "疑わ", "おそれ", "恐れ")
CLAIM_WARN_JA: tuple[str, ...] = ("警告", "警報", "アラート", "注意喚起")
# a reminder or a notice is the product's own word (来院のお知らせ, 同意書の確認をリマインド): a warning only about a
# disease or an early case in its clause
CLAIM_REMIND_JA: tuple[str, ...] = ("通知", "知らせ", "リマインド")
CLAIM_ACT_JA: tuple[str, ...] = (
    "治療",
    "治す",
    "治し",
    "治せ",
    "治癒",
    "完治",
    "改善",
    "有効性",
    "予防",
    "防ぐ",
    "防ぎ",
    "防げ",
    "防止",
    "低減",
    "減ら",
    "減少",
    "下げ",
    "下が",
    "抑制",
    "抑え",
    "回避",
)
_ACT_RECORD_BEFORE_JA: tuple[str, ...] = ("既", "前", "初回", "過去の", "これまでの", "現在の")
_ACT_RECORD_AFTER_JA: tuple[str, ...] = (
    "歴",
    "中",
    "群",
    "日",
    "期間",
    "ライン",
    "経験",
    "を受け",
    "を受けて",
    "を受けた",
    "の記録",
    "の有無",
)
CLAIM_STATE_JA: tuple[str, ...] = ("教え", "伝え", "評価", "確定", "見極め", "算出", "判明", "判別")
_STATE_WORDS_JA: tuple[str, ...] = (
    "罹患",
    "感染",
    "かかって",
    "かかる",
    "再発",
    "重症度",
    "病状",
    "病気",
    "発症",
    "悪化",
    "病態",
)
CLAIM_DECIDE_JA: tuple[str, ...] = (
    "推奨",
    "提案",
    "決定",
    "決め",
    "選択",
    "選ぶ",
    "選び",
    "提示",
    "指示",
    "勧め",
    "すすめ",
)
# what a decision for the clinician is about: a treatment, or whether a patient takes part (参加の可否, 適格性)
_TREATMENT_JA: tuple[str, ...] = (
    "治療",
    "療法",
    "投与",
    "用量",
    "投薬",
    "処方",
    "薬",
    "手術",
    "インスリン",
    "可否",
    "適格",
)

# D-1228's deniable words and clause ends, kept for text not named ja (zh-TW, en, or no language): D-1256's classes
# read only text named ja, so the Japanese table reads every other text exactly as before
_DENIABLE_D1228 = sorted(
    {*CLAIM_OUTRIGHT_JA, *CLAIM_FIND_JA, *CLAIM_RATE_JA, *CLAIM_JUDGE_JA, "診断支援", "診断", "判定", "疑い患者"},
    key=len,
    reverse=True,
)
_DENIABLE_D1228_RX = re.compile("|".join(re.escape(w) for w in _DENIABLE_D1228))
_CLAUSE_END_D1228 = re.compile(r"[。！？!?\n]|[、，,](?!\s*(?:" + _DENIABLE_D1228_RX.pattern + r"))")
_DENIABLE = sorted(
    {
        *CLAIM_OUTRIGHT_JA,
        *CLAIM_FIND_JA,
        *CLAIM_RATE_JA,
        *CLAIM_JUDGE_JA,
        "診断支援",
        "診断",
        "判定",
        "疑い患者",
        *CLAIM_OUTRIGHT_MORE_JA,
        *CLAIM_FIND_MORE_JA,
        *CLAIM_POSSIBLE_JA,
        *CLAIM_WARN_JA,
        *CLAIM_REMIND_JA,
        *CLAIM_ACT_JA,
        *CLAIM_STATE_JA,
        *CLAIM_DECIDE_JA,
    },
    key=len,
    reverse=True,
)
_DENIABLE_RX = re.compile("|".join(re.escape(w) for w in _DENIABLE))
_MISS_RX_JA = re.compile("|".join(re.escape(w) for w in CLAIM_MISS_JA))
# A clause ends at 。！？, a line end, or a comma that does not join two claim words of a list (診断、予測、…). A
# closing bracket does not end it: 「発見しません」という日はない is still one clause. A comma after a verb
# (AIが患者のリスクを示し、治療は推奨しません) ends the clause even when a claim word follows it.
_CLAUSE_END = re.compile(r"[。！？!?\n]|[、，,]")
_DENIABLE_END_RX = re.compile("(?:" + _DENIABLE_RX.pattern + r")\s*$")
_DENIABLE_NEXT_RX = re.compile(r"\s*(?:" + _DENIABLE_RX.pattern + ")")
# negative endings: ません, ない (not 少ない, 危ない), なかった, なく, a clause-final ず (not 必ず, まず)
_NEGATION = re.compile(r"ません|(?<![少危幼切汚])な(?:い|かった|く)|(?<![必まわ])ず(?=$|[、。,，\s」）)]|に|とも)")
# D-1256: a hedge is no denial (予測できるかもしれません: "may be able to predict"), for text named ja
_NEGATION_JA = re.compile(r"(?<!しれ)(?<!かね)(?:" + _NEGATION.pattern + ")")
_SUBJECT = r"\s*(?:が|は|により|による|によって|で|を用いて|を使って|を使い)"
_ACTORS = "(?<![A-Za-z])(?:" + "|".join(re.escape(a) for a in CLAIM_ACTORS_JA) + ")"
_ACTOR_SUBJECT = re.compile(_ACTORS + _SUBJECT)
_PERSON_SUBJECT = re.compile("(?:" + "|".join(re.escape(p) for p in CLAIM_PERSONS_JA) + ")" + _SUBJECT)
_ACTOR_BEFORE = _ACTORS + r"\s*(?:による|の|が|で)?\s*$"
_SENTENCE = re.compile(r"[^。！？!?\n]+[。！？!?]?")
_INVISIBLE = re.compile(
    r"[\u00ad\u034f\u115f\u1160\u17b4\u17b5\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\u3164\ufeff\uffa0]"
)
_MASK = "　"


def _alt(words: Iterable[str]) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(w) for w in words))


_DISEASE = _alt(CLAIM_DISEASE_JA)
_EARLY = _alt(CLAIM_EARLY_JA)
_PATIENT = _alt(CLAIM_PATIENTS_JA)


def _blank(m: re.Match[str]) -> str:
    return _MASK * len(m.group(0))


def clean_ja(text: str) -> str:
    """``text`` NFKC-normalised (half-width ﾘｽｸ, full-width ＡＩ) with zero-width and other invisible characters
    removed, so that a hidden character cannot split a word from the rule."""
    text = unicodedata.normalize("NFKC", text)
    return "".join(c for c in _INVISIBLE.sub("", text) if unicodedata.category(c) != "Cf")


def _clause_end_ja(text: str, at: int) -> int:
    """Where the clause that runs on from ``at`` ends: at 。！？, a line end, or a comma that does not join two claim
    words of a list (本製品は診断、予測、スコアリングを行いません is one clause; in
    AIが患者のリスクを示し、治療は推奨しません the comma after a verb ends the clause though a claim word follows
    it)."""
    for e in _CLAUSE_END.finditer(text, at):
        if e.group(0) not in "、，,":
            return e.start()
        if not _DENIABLE_NEXT_RX.match(text, e.end()) or not _DENIABLE_END_RX.search(text, 0, e.start()):
            return e.start()
    return len(text)


def deny_masked_ja(text: str, *, d1228: bool = False) -> str:
    """``text`` with every denied claim word blanked. A claim word is denied when the rest of its clause carries an
    odd number of negative endings: 本製品は診断、予測、スコアリングを行いません, 疾患の発見機能はありません,
    スコアリングのためのツールではありません, 判断するものではありません. Two negatives cancel (発見しない日はない, and
    a quoted denial inside one), so they deny nothing. A negated miss (見落とすことはありません) claims completeness, so
    it denies nothing (D-1256). ``d1228`` reads with D-1228's words and clause ends only, as for text not named ja."""
    out = list(text)
    for m in (_DENIABLE_D1228_RX if d1228 else _DENIABLE_RX).finditer(text):
        if d1228:
            end = _CLAUSE_END_D1228.search(text, m.end())
            rest = text[m.end() : end.start() if end else len(text)]
        elif _MISS_RX_JA.match(m.group(0)):
            continue
        else:
            rest = text[m.end() : _clause_end_ja(text, m.end())]
        if len((_NEGATION if d1228 else _NEGATION_JA).findall(rest)) % 2 == 1:
            out[m.start() : m.end()] = _MASK * (m.end() - m.start())
    return "".join(out)


# Chinese device claims (card 10C-5b, D-1247): the SAME rule, with a zh-TW term table.
#
# The classes are D-1228's: outright compound claim nouns; finding words that are a claim when their object is a
# disease or an early / latent case; rate words (and 疑似, "suspected") that are a claim when they are about a patient
# or a disease or the product stands straight before them; 判斷 with the product, the AI or a model as its subject.
# zh-TW adds one class the Japanese table does not have yet: warning words (警示, 示警, 警訊) that are a claim when
# they are about a patient, a disease or an early case, and 預警 (early warning) outright. Finding patients or
# candidates for a study is not a claim (找出近期回診的候選者, 找出符合納入條件的病人, 檢出率 of eligible patients).
#
# WHICH TEXT IT READS: the caller names the language (``lang``). Text named zh-TW (or zh, zh-Hant ...) is read by the
# zh-TW table, and by the Japanese table as before; text with no language, or named ja or en, is read by the Japanese
# table only, exactly as before D-1247. The language is never guessed from the script (a Japanese line in kanji only,
# 症例識別番号, is Japanese). A page names its own language (<html lang>), and check_page reads it from there.
#
# Only the language-specific parts differ, and each is data in the table below:
# * the words (CLAIM_*_ZH) and the allowed contexts (CLAIM_ALLOWED_ZH). A disease object is judged by its CLASS, not
#   only from a list: a noun that ends in 病 / 症 / 炎 / 癌 / 瘤 / 衰竭 / 梗塞 / 感染 is a disease (糖尿病, 肺炎,
#   心衰竭), while 病人, 病患, 病歷, 病史, 病房, 病名, 病床, 病例, 病號, 病友 and 適應症 are not; a short list adds
#   the names that do not end so (高血壓, 氣喘). An allowed context never swallows a longer claim: it does not apply
#   when a rate word follows it (研究風險預測 is refused; 研究的風險 is not).
# * Simplified Chinese: every term is written once, in Traditional; _zh_both() adds the Simplified form through the
#   character map _SIMPLIFIED beside the table (a test holds that the map covers every character the table uses), and
#   _ZH_LEXICAL adds the few words that differ by more than their characters (人工智能, 算法, 筛查).
# * the subject: Chinese marks a subject by position, so an actor or a person is a subject unless an attributive
#   的 / 之 / 所 follows it (AI的讀取結果 is not the AI judging). 本機 is the catalogue's own word for the box.
# * the denial: Chinese negates BEFORE the verb. A claim word is denied when the part of its clause before it carries
#   an odd number of negators. A verbal negator (不, 未, 無法, 並未 ...) counts only when, after its auxiliaries,
#   a light verb (用於, 提供, 進行, 做, 給予, 產生, 發出 ...) or a claim word follows it, so 未符合條件之病人的風險
#   denies nothing. An existential, copular or prohibitive negator (沒有, 毫無, 不具, 不是, 並非, 請勿, 不得) covers
#   the rest of its clause, once (不是 is not also 不 + 是), but not when a patient or a disease stands straight
#   before it (病人沒有風險 is said about the patient). A negated "miss" (沒有漏掉, 不會遺漏) is a claim of
#   completeness, not a denial, so it counts for nothing. A clause ends at 。！？；, a line end, 但 / 卻 / 然而 /
#   而 (not 而非), or a comma that does not continue a list of claim words (不做診斷、預測或風險分層 is one denial).
#
# The normalisation is D-1228's (clean_ja: NFKC, invisible characters removed); sentences are split the same way.
# Like the Japanese table it is a lint, not a guarantee (D-1247 gives the measured rates and the limits).

CLAIM_OUTRIGHT_ZH: tuple[str, ...] = (
    "未診斷",
    "未確診",
    "未經診斷",
    "未被診斷",
    "漏診",
    "早期發現",
    "及早發現",
    "早期偵測",
    "早期檢出",
    "早期篩檢",
    "早期預警",
    "預警",
    "提前示警",
    "臨床警示",
    "風險預測",
    "風險分層",
    "風險評分",
    "風險分數",
    "危險分數",
    "預後",
    "發病預測",
    "疾病預測",
    "惡化預測",
    "重症預測",
    "自動偵測",
    "自動檢出",
    "自動篩檢",
    "潛在病人",
    "潛在病患",
    "潛在患者",
    "潛在個案",
    "疑似病人",
    "疑似病患",
    "疑似患者",
    "疑似個案",
    "疑似病例",
    "可能發病",
    "誤診",
    "臨床決策",
)
# FORBIDDEN's zh-TW words, refused there in Traditional; the zh-TW table refuses their Simplified forms (诊断)
FORBIDDEN_SIMPLIFIED_ZH: tuple[str, ...] = ("診斷", "建議治療")
CLAIM_FIND_ZH: tuple[str, ...] = (
    "偵測",
    "檢出",
    "檢測",
    "發現",
    "找出",
    "找到",
    "篩檢",
    "篩查",
    "篩選",
    "篩出",
    "辨識",
    "識別",
    "判別",
    "揪出",
    "挖掘",
    "察覺",
    "發覺",
    "分辨",
    "區分",
    "標示",
    "分流",
    # "miss": 不會遺漏任何癌症病人 claims completeness (a negated miss denies nothing, see deny_masked_zh)
    "漏掉",
    "遺漏",
    "錯過",
    "漏看",
    "放過",
)
CLAIM_RATE_ZH: tuple[str, ...] = ("預測", "推估", "預估", "預知", "風險", "危險", "評分", "分數", "機率", "疑似")
CLAIM_WARN_ZH: tuple[str, ...] = ("警示", "示警", "警訊", "警報")
# 提醒 (remind) is the product's own word for a visit or a task (回診提醒, 提醒您確認同意書), so it is a warning only
# about a disease or an early case in the rest of its clause, never about a patient alone
CLAIM_REMIND_ZH: tuple[str, ...] = ("提醒",)
CLAIM_JUDGE_ZH: tuple[str, ...] = ("判斷", "研判")
# acting on a disease (醫療器材管理法 第 3 條: diagnosis, treatment, mitigation, prevention): a claim when the product
# is a subject before it and its object is a disease or an early case, or the product stands straight before it
# (本產品的療效). A treatment the record holds is not the product's act (接受治療, 治療紀錄, 治療組).
CLAIM_ACT_ZH: tuple[str, ...] = (
    "治療",
    "治癒",
    "醫治",
    "根治",
    "治好",
    "療效",
    "預防",
    "防止",
    "避免",
    "減少",
    "降低",
    "減低",
    "確診",
)
_ACT_RECORD_BEFORE_ZH: tuple[str, ...] = ("接受", "正在", "曾", "已", "先前", "過去", "既往", "之前", "尚未")
_ACT_RECORD_AFTER_ZH: tuple[str, ...] = (
    "組",
    "史",
    "紀錄",
    "記錄",
    "線",
    "經驗",
    "期間",
    "中的",
    "中之",
    "日期",
    "名稱",
)
# telling a patient's state (確定是否罹患, 告訴您是否罹患, 評估病情, 算出罹患的可能性): a claim when the product is
# the subject and a word of the patient's state follows within the window; 確定收案人數, 評估可行性 are not
CLAIM_STATE_ZH: tuple[str, ...] = ("確定", "告訴", "算出", "評估", "得知")
_STATE_WORDS_ZH: tuple[str, ...] = (
    "罹患",
    "罹病",
    "患有",
    "得了",
    "會得",
    "有沒有得",
    "是否得",
    "感染",
    "發病",
    "病情",
    "病況",
    "復發",
    "惡化",
    "生病",
)
# deciding or recommending for the clinician: a claim when the product is the subject and a treatment is its object;
# 系統建議您先匯出名單 is not
CLAIM_DECIDE_ZH: tuple[str, ...] = ("決定", "決策", "建議", "推薦", "選擇", "指示")
_TREATMENT_ZH: tuple[str, ...] = (
    "治療",
    "療法",
    "療程",
    "用藥",
    "藥物",
    "劑量",
    "開刀",
    "手術",
    "處方",
    "處置",
    "開藥",
)

CLAIM_DISEASE_ZH: tuple[str, ...] = (
    "疾病",
    "疾患",
    "病症",
    "病變",
    "病情",
    "病況",
    "病灶",
    "罹患",
    "罹病",
    "發病",
    "生病",
    "復發",
    "惡化",
    "重症",
    "徵兆",
    "徵候",
    "前兆",
    "症狀",
    "腫瘤",
    "中風",
    "失智",
    "死亡",
    "存活",
    "結節",
    "低血糖",
    "高血壓",
    "氣喘",
    "糖尿",
    "憂鬱",
    "骨折",
    "貧血",
    "損傷",
    "心律不整",
    "心律不齊",
    "心房顫動",
)
# a noun of the disease class: it ends in one of these (糖尿病, 肺炎, 心衰竭, 肺癌); the words that only look so are
# excluded by what follows 病 (病人, 病歷, 病程 ...) or precedes 症 (適應症, the indication of a drug); the class is
# written in both scripts at once
_DISEASE_CLASS_ZH = (
    r"(?:病(?![人患歷历史房名床例號号友理程])|(?<!適應)(?<!适应)症|炎|癌|瘤|衰竭|梗塞|感染|(?:硬|纖維|纤维|鈣|钙)化)"
)
CLAIM_EARLY_ZH: tuple[str, ...] = ("早期", "及早", "提早", "提前", "更早", "潛在", "隱藏", "漏診", "傾向")
# not 候選者 / 候選人: a candidate for a study is the product's own word, as in Japanese
CLAIM_PATIENTS_ZH: tuple[str, ...] = (
    "病人",
    "病患",
    "患者",
    "受試者",
    "個案",
    "病例",
    "病友",
    "就診者",
    "民眾",
    "族群",
    "人群",
)
CLAIM_ACTORS_ZH: tuple[str, ...] = (
    "TrialBox",
    "本軟體",
    "本系統",
    "系統",
    "本產品",
    "本工具",
    "本機",
    "本平台",
    "這套工具",
    "這個工具",
    "此工具",
    "我們",
    "AI",
    "人工智慧",
    "模型",
    "演算法",
)
CLAIM_PERSONS_ZH: tuple[str, ...] = (
    "人員",
    "團隊",
    "醫師",
    "醫生",
    "主持人",
    "研究護理師",
    "護理師",
    "CRC",
    "您",
    "專員",
    "管理員",
    "人",
)
# a rate or score word straight after an allowed context makes it a longer claim (研究風險預測), so the context
# does not apply there
_CLAIM_CONTINUES_ZH: tuple[str, ...] = ("預測", "預估", "推估", "評分", "評估", "分數", "分層", "模型", "預後", "等級")

# The zh-TW names of the published instruments and measured items the catalogue holds (catalogue/items.csv,
# name_zh_tw) whose name carries a rate word: a record value named by its own name (D-351), as NAMED_SCALES is for a
# scale named in Latin letters. A test holds that each is in the catalogue and that every catalogue name passes.
NAMED_INSTRUMENTS_ZH: tuple[str, ...] = (
    "類風濕性關節炎分類評分",
    "伯明罕血管炎活動度評分",
    "腫瘤比例分數",
    "國際預後指數",
    "Mayo 評分",
    "十年主要骨鬆性骨折機率",
    "冠狀動脈 z 分數",
    "預估存活期",
)

CLAIM_ALLOWED_ZH: dict[str, tuple[str, ...]] = {
    "instrument": tuple(re.escape(n) for n in NAMED_INSTRUMENTS_ZH),
    "分數": (
        r"(?:"
        + "|".join(re.escape(s) for s in sorted(NAMED_SCALES, key=len, reverse=True))
        + r")(?:\s*PS)?\s*(?:的|之)?\s*(?:分數|評分)",
        r"分數定義",
    ),
    # risk of bias; a study's own risks to the participant, as a consent form states them (the study is the object)
    "風險": (
        r"(?:偏差|偏倚|偏誤)風險",
        r"(?:試驗|研究|參與|參加|計畫)(?:可能|主要|潛在)?(?:的|之)?(?:主要|可能|潛在)?風險",
        r"(?:試驗|研究)(?:可能|可|會|將)?(?:為|對|給)(?:受試者|參與者|病人)(?:帶來|造成)(?:的|之)?風險",
        r"風險\s*(?:與|和|及|、)\s*(?:好處|益處|利益)",
        r"(?:好處|益處|利益)\s*(?:與|和|及|、)\s*(?:主要|可能|潛在)?風險",
    ),
    # a study's enrolment forecast (feasibility) and a head count are counts, not a patient's outcome
    "預測": (
        r"(?:收案|招募|納入|隨機分派|同意)(?:人?數)?(?:的|之)?預(?:測|估)",
        r"預(?:測|估)(?:的是)?(?:可|將|可以)?(?:收案|招募|納入|隨機分派|同意)",
        r"預(?:測|估)(?:的)?人數",
    ),
    # a lab's detection limit
    "偵測": (r"(?:偵測|檢測|檢出)(?:極限|下限|上限|限值)",),
    # the study's screening visit as a point in time (a protocol's 篩選前 90 日內), not finding a disease
    "篩選": (r"篩選(?:前|後|期間|期|時|日|當日|當天|訪視)",),
}

_NEG_VERBAL_LIST_ZH = ("並未", "並不", "絕不", "從不", "從未", "不再", "無法", "不", "未", "無")
_NEG_WHOLE_LIST_ZH = (
    "並不是",
    "不是",
    "並非",
    "絕非",
    "而非",
    "亦非",
    "也非",
    "沒有",
    "並無",
    "毫無",
    "不具",
    "不含",
    "不包含",
    "請勿",
    "切勿",
    "勿",
    "不得",
    "禁止",
)
_AUX_LIST_ZH = (
    "會",
    "能夠",
    "能",
    "可以",
    "可",
    "得",
    "再",
    "曾",
    "將",
    "應",
    "須",
    "被",
    "主動",
    "自動",
    "直接",
    "另外",
    "任何",
    "為",
    "自行",
)
_LIGHT_LIST_ZH = (
    "用於",
    "用來",
    "用以",
    "作為",
    "做為",
    "作",
    "做",
    "進行",
    "提供",
    "給予",
    "給出",
    "產生",
    "輸出",
    "顯示",
    "發出",
    "發送",
    "執行",
    "具備",
    "具有",
    "具",
    "包含",
    "含",
    "支援",
    "協助",
    "涉及",
    "參與",
    "取代",
    "代替",
    "屬於",
    "是",
    "有",
)
# "miss": a negated miss (沒有漏掉, 不會遺漏) claims completeness, it denies nothing
_MISS_LIST_ZH = ("漏掉", "遺漏", "錯過", "漏看", "放過", "漏", "誤診")
_CLAUSE_WORDS_ZH = ("但", "卻", "然而")
_ATTRIBUTIVE_LIST_ZH = ("的", "之", "所", "產生", "輸出", "結果")


# Traditional -> Simplified for every character of the zh-TW table that differs, as pairs (each Traditional character
# followed by its Simplified form); _SAME_ZH holds the
# characters the table uses that are written the same in both. A test holds that the two cover every character the
# table uses, so a new term cannot slip through in its Simplified form. No new dependency.
_SIMPLIFIED_PAIRS = (
    "並并來来個个們们偵侦備备傷伤傾倾別别動动協协卻却參参員员執执報报壓压夠够將将專专對对層层屬属師师帶带"
    "後后從从復复徵征惡恶憂忧應应損损數数斷断於于時时會会極极標标機机檢检歷历氣气沒没況况測测潛潜為为無无"
    "狀状現现產产畫画當当療疗發发眾众確确節节篩筛納纳級级結结絕绝給给統统經经義义腫肿臨临與与處处號号視视"
    "覺觉計计訊讯訪访診诊評评試试誤误請请識识議议護护變变貧贫軟软輸输進进過过適适選选遺遗醫医錯错間间隨随"
    "險险隱隐須须預预顯显風风驗验體体鬱郁國国濕湿脈脉關关際际類类鬆松齊齐顫颤"
    "劑剂區区團团擇择決决減减癒愈稱称紀纪組组維维線线纖纤薦荐藥药術术記记訴诉這这錄录鈣钙開开隊队"
)
_SIMPLIFIED: dict[str, str] = dict(zip(_SIMPLIFIED_PAIRS[::2], _SIMPLIFIED_PAIRS[1::2], strict=True))
_SAME_ZH = (
    "上下不中主之也予亡亦人以任伯估似但何作例供候倚值偏做兆入具再冠出分切判利到前加助募勿包化十危及友受另"
    "可台史同名向含和品喘在型塞外天失好存定察就尿工差平年床度建律得心性患您情意感慧成我房所找折招持指挖掉"
    "掘接推提揪援支收放整族日早明是智更曾有期未本果染查案梗模止死比毫民治法活派流涉漏演灶炎然率理生用疑疾"
    "病症瘤癌的益直看研示禁程究竭等算管糖系罕罹群者而能自藏血行衰被要警辨送造重限非骨高"
    "了代低先免刀去取告套少尚已往手效方既替根正此知硬物策置醒量防降避否"
)
# words that differ in Simplified by more than their characters
_ZH_LEXICAL: dict[str, str] = {"人工智慧": "人工智能", "演算法": "算法", "軟體": "软件", "醫師": "医生", "篩檢": "筛查"}
_TO_SIMPLIFIED = str.maketrans(_SIMPLIFIED)


def _simplified(text: str) -> str:
    """``text`` (Traditional) in Simplified: the lexical differences first, then character by character."""
    for trad, simp in _ZH_LEXICAL.items():
        text = text.replace(trad, simp)
    return text.translate(_TO_SIMPLIFIED)


def _zh_both(words: Iterable[str]) -> tuple[str, ...]:
    """``words`` and their Simplified forms, longest first, each once."""
    out = {w for w in words} | {_simplified(w) for w in words}
    return tuple(sorted(out, key=lambda w: (-len(w), w)))


def _zh_alt(words: Iterable[str]) -> str:
    return "(?:" + "|".join(re.escape(w) for w in _zh_both(words)) + ")"


_DENIABLE_ZH_RX = re.compile(
    _zh_alt(
        (
            *CLAIM_OUTRIGHT_ZH,
            *FORBIDDEN_SIMPLIFIED_ZH,
            *CLAIM_FIND_ZH,
            *CLAIM_RATE_ZH,
            *CLAIM_WARN_ZH,
            *CLAIM_REMIND_ZH,
            *CLAIM_JUDGE_ZH,
            *CLAIM_ACT_ZH,
            *CLAIM_STATE_ZH,
            *CLAIM_DECIDE_ZH,
            "判定",
        )
    )
)
_CLAUSE_END_ZH = re.compile(
    r"[。！？!?\n；;]|" + _zh_alt(_CLAUSE_WORDS_ZH) + r"|而(?!非)|[、，,](?!\s*" + _DENIABLE_ZH_RX.pattern + ")"
)
_AUX_ZH = _zh_alt(_AUX_LIST_ZH) + "*"
_LIGHT_ZH = "(?:" + _zh_alt(_LIGHT_LIST_ZH) + "|" + _DENIABLE_ZH_RX.pattern + ")"
_MISS_ZH = re.compile(r"\s*" + _AUX_ZH + r"\s*" + _zh_alt(_MISS_LIST_ZH))
# a verbal negator counts only when a light verb or a claim word follows it (after its auxiliaries, and an opening
# quote: 不能「診斷癌症」)
_NEG_VERBAL_ZH = re.compile(
    _zh_alt(_NEG_VERBAL_LIST_ZH) + r"(?=\s*" + _AUX_ZH + r"\s*[「『“\"'(]*\s*" + _LIGHT_ZH + ")"
)
# an existential, copular or prohibitive negator covers the rest of its clause
_NEG_WHOLE_ZH = re.compile(_zh_alt(_NEG_WHOLE_LIST_ZH))
# a negator AFTER the claim word, at the end of its clause: 與病人的疾病風險無關
_A_NOT_A_ZH = re.compile(r"(能|會|会|可|是|有|要)(?:不|沒|没)\1")
_NEG_AFTER_ZH = re.compile(_zh_alt(("無關", "無涉", "不相關", "沒有關係", "毫無關係")))
_ACTORS_ZH = "(?<![A-Za-z])" + _zh_alt(CLAIM_ACTORS_ZH) + "(?!性)"
_NOT_ATTRIBUTIVE_ZH = r"(?!\s*" + _zh_alt(_ATTRIBUTIVE_LIST_ZH) + ")"
_PERSONS_ZH = "(?:" + _zh_alt(p for p in CLAIM_PERSONS_ZH if p != "人") + r"|(?<![病個个選选])人)"
_ACTOR_SUBJECT_ZH = re.compile(_ACTORS_ZH + _NOT_ATTRIBUTIVE_ZH)
_PERSON_SUBJECT_ZH = re.compile(_PERSONS_ZH + _NOT_ATTRIBUTIVE_ZH)
# a person's own judgement or diagnosis: 醫師的判斷
_PERSON_POSSESSOR_ZH = re.compile(_PERSONS_ZH + r"\s*" + _zh_alt(("的", "之")) + r"\s*$")
# the product helping a person (協助醫師判斷) is still the product's act
_HELPS_ZH = re.compile(_zh_alt(("協助", "輔助", "幫助", "幫", "支援")))
# a person as the subject yields to a product that does the judgement in the same sentence: as the subject of
# the word's own clause (本系統可取代醫師做出診斷), by replacing the person (系統全部代勞), as a cause
# (讓 AI 為您判斷) or as the source of the judgement (依本系統的判斷); a product that only shows or reads what a
# person recorded
# (本系統顯示的病歷, 本系統只讀取), or is denied (本系統不取代醫師的判斷), does nothing
_ACTOR_IDLE_ZH = re.compile(
    r"\s*"
    + _zh_alt(("只", "僅", "只會", "僅會", "並", "也", "亦"))
    + r"?\s*"
    + _AUX_ZH
    + r"\s*(?:"
    + _zh_alt(("顯示", "讀取", "原文顯示", "列出", "呈現", *_NEG_WHOLE_LIST_ZH, *_NEG_VERBAL_LIST_ZH))
    + ")"
)
_ACTOR_SHOWS_ZH = re.compile(
    r"\s*"
    + _zh_alt(("只", "僅", "只會", "僅會"))
    + r"?\s*"
    + _AUX_ZH
    + r"\s*"
    + _zh_alt(("顯示", "讀取", "原文顯示", "列出", "呈現"))
)
_REPLACES_ZH = re.compile(_zh_alt(("取代", "代替", "替代", "代勞")))
_CAUSES_ZH = re.compile(_zh_alt(("讓",)) + r"\s*" + _ACTORS_ZH)
_ACTOR_POSSESSOR_ZH = re.compile(_ACTORS_ZH + r"\s*" + _zh_alt(("的", "之")) + r"\s*$")
_SENTENCE_MARKS_ZH = "。！？!?\n"
_DISEASE_ZH = re.compile(_zh_alt(CLAIM_DISEASE_ZH) + "|" + _DISEASE_CLASS_ZH)  # the class names both scripts
_EARLY_ZH = re.compile(_zh_alt(CLAIM_EARLY_ZH))
# a patient or a disease straight before an existential negator: 病人沒有風險 is said about the patient
_ABOUT_ZH = re.compile("(?:" + _zh_alt(CLAIM_PATIENTS_ZH) + "|" + _DISEASE_ZH.pattern + r")\s*$")
_ACTOR_NON_ZH = re.compile(_ACTORS_ZH + r"\s*" + _zh_alt(("非",)) + "(?!常)")
_CLAUSE_MARKS_ZH = "、，,；;。！？!?\n"
# FORBIDDEN's 診斷 and 判定 in text named zh-TW are not the product's verdict when they name a record field
# (診斷日期, 診斷碼), a passive by a qualified person (經診斷為, 經醫師診斷) or a person's own act (醫師依病歷診斷,
# 研究團隊依計畫書判定); D-351 names a record's own field so
_VERDICT_ZH = re.compile(_zh_alt(("診斷", "判定")))
_FIELD_AFTER_ZH = re.compile(
    r"\s*" + _zh_alt(("日期", "碼", "代碼", "名稱", "紀錄", "記錄", "欄位", "欄", "時間", "年齡", "年份", "類別"))
)
_PASSIVE_BEFORE_ZH = re.compile(
    _zh_alt(("經由", "經過", "經")) + r"\s*(?:" + _PERSONS_ZH + "|" + _zh_alt(("病理", "影像", "臨床")) + r")?\s*$"
)


def _zh_allowed() -> dict[str, tuple[str, ...]]:
    """The allowed contexts in both scripts, each closed so that it never swallows a longer claim (研究風險預測)."""
    tail = r"(?!\s*" + _zh_alt(_CLAIM_CONTINUES_ZH) + ")"
    return {
        term: tuple(dict.fromkeys(f"(?:{rx}){tail}" for p in patterns for rx in (p, _simplified(p))))
        for term, patterns in CLAIM_ALLOWED_ZH.items()
    }


@dataclass(frozen=True)
class Grammar:
    """How one language marks who does an act (D-1256): the one subject reading of D-1247, with each language's
    words and particles as data. Chinese and English mark a subject by position before the verb; Japanese by a
    particle (が, は, により ...), so its actor and person patterns carry the particle."""

    clause_marks: str
    sentence_marks: str
    actor_subject: re.Pattern[str]
    person_subject: re.Pattern[str]
    actor_possessor: re.Pattern[str]  # straight before the word: 依本系統的判斷, the system's judgement
    person_possessor: re.Pattern[str]  # 醫師的判斷, the physician's diagnosis
    helps: re.Pattern[str]  # the product helping a person is still the product's act
    replaces: re.Pattern[str]
    causes: re.Pattern[str]
    idle: re.Pattern[str]  # after an actor: it only shows or reads, or is denied
    shows: re.Pattern[str]  # after an actor: it only shows or reads
    replace_negated: Callable[[str, int, int, re.Match[str]], bool]
    # a subject after the word when none stands before it: a passive's agent (determined by the system), a
    # Japanese topic or cleft (診断は医師が行い, 診断を下すのはAIです); groups "actor" and "person"
    agent_after: re.Pattern[str] | None = None
    idle_in_clause: bool = False  # Japanese: the actor's verb ends its clause, so idle is read to the clause end
    # Japanese: a topic (本システムは) holds over every clause of its sentence, so an earlier clause's actor that only
    # shows yields only to a person in the word's own clause (本システムは記録を表示せず、糖尿病を治療します is a claim)
    shows_yields_only_to_a_person: bool = False


def _clause_start(g: Grammar, s: str, start: int) -> int:
    return max(s.rfind(c, 0, start) for c in g.clause_marks) + 1


def _clause_end(g: Grammar, s: str, end: int) -> int:
    return min((i for i in (s.find(c, end) for c in g.clause_marks) if i >= 0), default=len(s))


def _subject(g: Grammar, s: str, start: int, end: int) -> str | None:
    """Who does the act of the word at ``s[start:end]``: "actor" (the product, the AI, a model), "person", or None.
    The nearest subject before the word in its clause decides; an actor of an earlier clause holds unless a person is
    a subject in the word's own clause (本系統僅顯示資料，判斷由人負責). A person's own act (醫師的判斷) is the
    person's; the product helping a person (協助醫師判斷) is still the product's. With no subject before the word, a
    subject after it decides where the language puts one there (a passive's agent, a Japanese topic)."""
    cs = _clause_start(g, s, start)
    if g.actor_possessor.search(s, cs, start):
        return "actor"  # 依本系統的判斷
    who = _subject_by_position(g, s, start, end, cs)
    if who is None and g.agent_after is not None:
        m = g.agent_after.match(s, end, _clause_end(g, s, end))
        if m:
            who = "actor" if m.group("actor") else "person"
    if who is None and _product_acts(g, s, start, cs):
        return "actor"  # a cause with no subject: AIに決めさせましょう, let the AI decide
    if who == "person" and _product_acts(g, s, start, cs):
        return "actor"
    return who


def _acting(g: Grammar, s: str, a: re.Match[str]) -> bool:
    if g.idle_in_clause:
        return not g.idle.search(s, a.end(), _clause_end(g, s, a.end()))
    return not g.idle.match(s, a.end())


def _shows_only(g: Grammar, s: str, at: int) -> bool:
    if g.idle_in_clause:
        return g.shows.search(s, at, _clause_end(g, s, at)) is not None
    return g.shows.match(s, at) is not None


def _product_acts(g: Grammar, s: str, start: int, cs: int) -> bool:
    """Whether a product does the judgement at ``start`` although a person is its nearest subject: an acting product
    in the word's own clause before it, or anywhere in its sentence with a verb of replacing, or as a cause."""
    ss = max(s.rfind(c, 0, start) for c in g.sentence_marks) + 1
    se = min((i for i in (s.find(c, start) for c in g.sentence_marks) if i >= 0), default=len(s))
    if any(_acting(g, s, a) for a in g.actor_subject.finditer(s, cs, start)):
        return True
    if g.causes.search(s, ss, se):
        return True
    acting = any(_acting(g, s, a) for a in g.actor_subject.finditer(s, ss, se))
    return acting and any(not g.replace_negated(s, ss, se, r) for r in g.replaces.finditer(s, ss, se))


def _subject_by_position(g: Grammar, s: str, start: int, end: int, cs: int) -> str | None:
    if g.person_possessor.search(s, 0, start):
        return "person"
    ce = _clause_end(g, s, end)
    found = list(g.actor_subject.finditer(s, 0, start))
    # an actor of an earlier clause that only shows or reads holds nothing (本系統顯示病歷，醫師參考後自行判斷)
    persons = [p.end() for p in g.person_subject.finditer(s, cs, start)]
    yields = persons or not g.shows_yields_only_to_a_person
    actors = [a.end() for a in found if a.end() > cs or not (yields and _shows_only(g, s, a.end()))]
    last_actor = actors[-1] if actors else -1
    if persons and persons[-1] > last_actor:
        helps = last_actor >= 0 and g.helps.search(s, last_actor, persons[-1])
        return "actor" if helps else "person"
    if last_actor < 0:
        return None
    if last_actor > cs or not g.person_subject.search(s, end, ce):
        return "actor"
    return "person"


GRAMMAR_ZH = Grammar(
    clause_marks=_CLAUSE_MARKS_ZH,
    sentence_marks=_SENTENCE_MARKS_ZH,
    actor_subject=_ACTOR_SUBJECT_ZH,
    person_subject=_PERSON_SUBJECT_ZH,
    actor_possessor=_ACTOR_POSSESSOR_ZH,
    person_possessor=_PERSON_POSSESSOR_ZH,
    helps=_HELPS_ZH,
    replaces=_REPLACES_ZH,
    causes=_CAUSES_ZH,
    idle=_ACTOR_IDLE_ZH,
    shows=_ACTOR_SHOWS_ZH,
    replace_negated=lambda s, ss, se, r: bool(
        re.search(_zh_alt(_NEG_VERBAL_LIST_ZH + _NEG_WHOLE_LIST_ZH) + r"\s*$", s[ss : r.start()])
    ),
)


def _zh_subject(s: str, start: int, end: int) -> str | None:
    """:func:`_subject` read with the zh-TW grammar (D-1247)."""
    return _subject(GRAMMAR_ZH, s, start, end)


def _record_masked(
    text: str,
    verdict: re.Pattern[str],
    field_after: re.Pattern[str],
    passive: Callable[[str, int, re.Match[str]], bool],
    g: Grammar,
) -> str:
    """``text`` with FORBIDDEN's verdict words blanked where they are not the product's verdict: a record field
    (診斷日期, 診断名, diagnosis code), a passive by a qualified person (經醫師診斷為, 専門医によって…と診断された) or a
    person as the subject (醫師依病歷診斷, 診断は医師が行い, the physician makes the diagnosis). The product as the
    subject (本系統依病歷診斷, AIが診断します, the tool's diagnosis) is not blanked. One mechanism, three languages
    (D-1247, D-1256)."""
    out = list(text)
    for m in verdict.finditer(text):
        cs = _clause_start(g, text, m.start())
        if (
            field_after.match(text, m.end())
            or passive(text, cs, m)
            or _subject(g, text, m.start(), m.end()) == "person"
        ):
            out[m.start() : m.end()] = _MASK * (m.end() - m.start())
    return "".join(out)


def _record_masked_zh(text: str) -> str:
    """:func:`_record_masked` with zh-TW's 診斷 and 判定 (D-1247)."""
    return _record_masked(
        text,
        _VERDICT_ZH,
        _FIELD_AFTER_ZH,
        lambda t, cs, m: bool(_PASSIVE_BEFORE_ZH.search(t, cs, m.start())),
        GRAMMAR_ZH,
    )


def deny_masked_zh(text: str) -> str:
    """``text`` with every denied zh claim word blanked: the part of its clause before it carries an odd number of
    attached negators (本軟體不用於疾病之篩檢或診斷, 不做診斷、預測或風險分層, 無法辨識的代碼系統, 系統沒有疾病預測功能,
    本工具並非用於發現疾病), or its clause ends in one (與病人的疾病風險無關). Two negatives cancel; a negated miss
    (沒有漏掉) counts for nothing. The disease and early words of a denied clause are blanked with it
    (本系統不篩檢疾病，只篩選候選受試者: 疾病 is the object of the denial, not of 篩選). Read only for text the caller
    names zh-TW (:func:`deny_masked`)."""
    out = list(text)
    ends = [(e.start(), e.end()) for e in _CLAUSE_END_ZH.finditer(text)]  # read on the whole text: 、 continues a list
    for m in _DENIABLE_ZH_RX.finditer(text):
        start = max((b for _, b in ends if b <= m.start()), default=0)
        stop = min((a for a, _ in ends if a >= m.end()), default=len(text))
        before = text[start : m.start()]
        whole = [(w.start() + start, w.end() + start) for w in _NEG_WHOLE_ZH.finditer(before)]
        # the negator's verb may be the claim word itself (無法辨識), so its lookahead reads past ``before``; a verbal
        # negator inside an existential or copular one (不 of 不是, 不具) is that one, counted once below
        n = sum(
            1
            for neg in _NEG_VERBAL_ZH.finditer(text, start, m.end())
            if neg.start() < m.start()
            and not any(a <= neg.start() < b for a, b in whole)
            and not _MISS_ZH.match(text, neg.end())
            and not _A_NOT_A_ZH.match(text, max(0, neg.start() - 1))
        )
        for neg in _NEG_WHOLE_ZH.finditer(before):
            # 病人沒有風險 is said about the patient; 沒有漏掉 (did not miss) is a claim, not a denial
            if (
                not _ABOUT_ZH.search(before[: neg.start()])
                and not _MISS_ZH.match(text, start + neg.end())
                and not _A_NOT_A_ZH.match(text, max(0, start + neg.start() - 1))
            ):
                n += 1
        # 非 alone is copular only straight after the product's name (本軟體非醫療器材); 非小細胞肺癌 is a disease name
        n += len(_ACTOR_NON_ZH.findall(before))
        n += len(_NEG_AFTER_ZH.findall(text, m.end(), stop))
        if n % 2 == 1:
            out[m.start() : m.end()] = _MASK * (m.end() - m.start())
            for rx in (_DISEASE_ZH, _EARLY_ZH):
                for o in rx.finditer(text, m.end(), stop):
                    out[o.start() : o.end()] = _MASK * (o.end() - o.start())
    return "".join(out)


# The Japanese grammar for the classes D-1256 adds (act, state, decide, warn, remind, and 判断 itself): the one
# subject reading above, with the subject marked by its particle. A person as the subject includes a physician
# named by a 医 compound (専門医, 循環器医, 主治医; not 医療, 医薬). The product as a means (TrialBoxを使うと,
# TrialBoxにより, TrialBoxのおかげで) is the subject of what follows. A topic or a cleft after the word names its
# subject there (診断は医師が行い, 診断を下すのはAIです), read only when no subject stands before the word.
_JA_PARTICLES = (
    r"\s*(?:が|は|も|により|による|によって|で|では|を用いて|を使って|を使い|を使うと|を使えば|なら|のおかげで)"
)
_ACTORS_JA = "(?<![A-Za-z])(?:" + "|".join(re.escape(a) for a in CLAIM_ACTORS_JA) + ")(?![A-Za-z])"
_PERSONS_JA = "(?:" + "|".join(re.escape(p) for p in CLAIM_PERSONS_JA) + r"|[一-鿿]{0,4}医(?![療薬学院]))"
GRAMMAR_JA = Grammar(
    clause_marks="、，,；;。！？!?\n",
    sentence_marks="。！？!?\n",
    actor_subject=re.compile(_ACTORS_JA + _JA_PARTICLES),
    person_subject=re.compile(_PERSONS_JA + _JA_PARTICLES),
    # the product's own noun phrase before the word (TrialBoxの糖尿病改善, システムの判断)
    actor_possessor=re.compile(_ACTORS_JA + r"\s*の[^、。，,をがはにでと]{0,8}$"),
    person_possessor=re.compile(_PERSONS_JA + r"\s*の\s*$"),
    helps=re.compile("支援|補助|手助け|サポート|援助|助け"),
    replaces=re.compile("代わ|代行|置き換|不要|任せ|なしに|なしで"),
    causes=re.compile(_ACTORS_JA + r"\s*に[^、。，,]{0,20}?させ"),
    idle=re.compile("表示|一覧|読み|読む|読ん|読ま|引用|並べ|ません|ない|なく|せず|関与"),
    shows=re.compile("表示|一覧|読み|読む|読ん|読ま|引用|並べ"),
    replace_negated=lambda s, ss, se, r: bool(
        _NEGATION_JA.search(
            s, r.end(), min((i for i in (s.find(c, r.end()) for c in "、，,。！？!?\n") if i >= 0), default=se)
        )
    ),
    agent_after=re.compile(
        r"[^。、，,]*?(?:のは|は|も)\s*(?:(?P<actor>"
        + _ACTORS_JA
        + r")|(?P<person>"
        + _PERSONS_JA
        + r"))\s*(?:です|だ|が|で|によって|により)"
    ),
    idle_in_clause=True,
    shows_yields_only_to_a_person=True,
)
_DISEASE_JA = re.compile(
    "|".join(re.escape(w) for w in sorted({*CLAIM_DISEASE_JA, *CLAIM_DISEASE_MORE_JA}, key=len, reverse=True))
    + "|"
    + _DISEASE_CLASS_JA
)
# FORBIDDEN's 診断 and 判定 in text named ja are not the product's verdict as a record field (診断名, 診断日), a passive
# with no product as its agent (関節リウマチと診断された患者) or a person's own act (医師の診断, 診断は医師が行い)
_VERDICT_JA = re.compile("診断|判定")
_FIELD_AFTER_JA = re.compile(r"\s*(?:名|日|コード|基準|書|時|年月日|年齢|名称|欄|区分|年)")


def _passive_ja(text: str, cs: int, m: re.Match[str]) -> bool:
    return (
        text[max(0, m.start() - 1) : m.start()] == "と"
        and text.startswith("され", m.end())
        and (_subject(GRAMMAR_JA, text, m.start(), m.end()) != "actor")
    )


def _record_masked_ja(text: str) -> str:
    """:func:`_record_masked` with Japanese 診断 and 判定 (D-1256)."""
    return _record_masked(text, _VERDICT_JA, _FIELD_AFTER_JA, _passive_ja, GRAMMAR_JA)


# English device claims (card 10C-5c, D-1256): the same rule, with an English table. Before D-1256 English had no claim
# table: only FORBIDDEN's words (diagnosis, risk score, AI decides ...). The classes are zh-TW's and Japanese's, said
# in English: outright claim phrases (early detection, undiagnosed, risk prediction, prognosis, clinical decision
# support); finding a disease (diagnose, detect, identify, recognise, spot, screen for, flag, catch, miss); rating a
# patient or a disease (predict, forecast, risk, likelihood, probability, score, stratify; possible / likely / suspected
# only about a disease); warning about a patient or a disease (warn, alert, alarm), reminding or notifying about a
# disease; acting on a disease (treat, cure, efficacy, prevent, reduce, lower, avoid) with the product as the subject;
# telling a patient's state (tell, determine, assess, work out whether a patient is infected); deciding or recommending
# a treatment or a patient's taking part for the clinician; and judging or diagnosing with the product as the subject.
#
# English differs as data: the words are patterns with their inflections, matched as whole words in any case; a
# subject stands before its verb (as in Chinese) or after a passive's "by" (determined by the system); a denial stands
# before the verb (does not, never, no, neither ... nor, without; not "not only", "not unusual"), and two cancel
# (never fails to spot). A negated miss (not a single case is missed) claims completeness and denies nothing.


def _en(words: Iterable[str]) -> str:
    return r"(?<![A-Za-z])(?:" + "|".join(words) + r")(?![A-Za-z])"


CLAIM_OUTRIGHT_EN: tuple[str, ...] = (
    r"early[- ](?:detection|diagnosis|identification|recognition|warnings?|screening)",
    r"undiagnosed",
    r"undetected",
    r"misdiagnos\w*",
    r"suspected\s+(?:cases?|patients?)",
    r"risk[- ](?:prediction|predictions|stratification|scores?|scoring|models?)",
    r"prognos(?:is|es|tic)",
    r"(?:disease|mortality|readmission|relapse|outcome)\s+(?:prediction|predictions|forecasts?)",
    r"clinical\s+decision\s+support",
    r"at[- ]risk\s+(?:patients?|individuals?|people|groups?)",
    r"high[- ]risk\s+(?:patients?|individuals?|people|groups?)",
)
CLAIM_FIND_EN: tuple[str, ...] = (
    r"diagnos(?:e|es|ed|ing|tic)",
    r"detect(?:s|ed|ing|ion)?",
    r"identif(?:y|ies|ied|ying|ication)",
    r"recogni[sz](?:e|es|ed|ing)",
    r"spot(?:s|ted|ting)?",
    r"uncover(?:s|ed|ing)?",
    r"discover(?:s|ed|ing|y)?",
    r"find(?:s|ing)?",
    r"found",
    r"flag(?:s|ged|ging)?",
    r"catch(?:es|ing)?",
    r"caught",
    r"screen(?:s|ed|ing)?",
    r"pick(?:s|ed)?\s+up",
    r"pinpoint(?:s|ed|ing)?",
    r"distinguish(?:es|ed|ing)?",
    r"triag(?:e|es|ed|ing)",
    r"rul(?:e|es|ed)\s+out",
    r"reveal(?:s|ed|ing)?",
    r"miss(?:es|ed)?",
    r"overlook(?:s|ed)?",
)
# a negated miss (is never missed, not a single case is missed) is a claim of completeness, not a denial
CLAIM_MISS_EN: tuple[str, ...] = (r"miss(?:es|ed)?", r"overlook(?:s|ed)?")
CLAIM_RATE_EN: tuple[str, ...] = (
    r"predict(?:s|ed|ing|ion|ions|ive)?",
    r"forecast(?:s|ed|ing)?",
    r"risks?",
    r"risky",
    r"likelihood",
    r"probabilit(?:y|ies)",
    r"scores?",
    r"scored",
    r"scoring",
    r"stratif(?:y|ies|ied|ying|ication)",
    r"odds",
)
CLAIM_POSSIBLE_EN: tuple[str, ...] = (
    r"possible",
    r"possibly",
    r"probable",
    r"probably",
    r"likely",
    r"suspect(?:s|ed)?",
    r"(?:may|might|could)\s+have",
)
CLAIM_WARN_EN: tuple[str, ...] = (r"warn(?:s|ed|ing|ings)?", r"alert(?:s|ed|ing)?", r"alarms?")
CLAIM_REMIND_EN: tuple[str, ...] = (r"remind(?:s|ed|ing|ers?)?", r"notif(?:y|ies|ied|ying|ications?)")
CLAIM_ACT_EN: tuple[str, ...] = (
    r"treat(?:s|ed|ing|ments?)?",
    r"cur(?:e|es|ed|ing)",
    r"heal(?:s|ed|ing)?",
    r"therap(?:y|ies|eutic)",
    r"efficacy",
    r"improv(?:e|es|ed|ing)",
    r"prevent(?:s|ed|ing|ion|ive)?",
    r"avert(?:s|ed|ing)?",
    r"avoid(?:s|ed|ing)?",
    r"reduc(?:e|es|ed|ing|tion)",
    r"lower(?:s|ed|ing)?",
    r"decreas(?:e|es|ed|ing)",
    r"mitigat(?:e|es|ed|ing)",
    r"alleviat(?:e|es|ed|ing)",
    r"manag(?:e|es|ed|ing)",
)
# a treatment the record holds (received treatment, treatment arm, treated with metformin) is not the product's act
_ACT_RECORD_BEFORE_EN = re.compile(
    r"(?:(?<![A-Za-z])(?:receiv\w*|undergo\w*|underwent|prior|previous(?:ly)?|history\s+of|already|currently|first|"
    r"ongoing|current|started|starting|on|any|no)(?![A-Za-z])[^,;:.]{0,25}?)\s*$",
    re.I,
)
_ACT_RECORD_AFTER_EN = re.compile(
    r"\s+(?:arms?|groups?|history|lines?|dates?|naive|naïve|periods?|duration|start|names?|plans?|experience|"
    r"for\s+(?:at\s+least|\d))(?![A-Za-z])|(?<=treated)\s+with(?![A-Za-z])",
    re.I,
)
CLAIM_STATE_EN: tuple[str, ...] = (
    r"tell(?:s|ing)?",
    r"told",
    r"determin(?:e|es|ed|ing)",
    r"assess(?:es|ed|ing)?",
    r"works?\s+out",
    r"establish(?:es|ed|ing)?",
    r"evaluat(?:e|es|ed|ing)",
)
CLAIM_DECIDE_EN: tuple[str, ...] = (
    r"recommend(?:s|ed|ing|ations?)?",
    r"suggest(?:s|ed|ing|ions?)?",
    r"propos(?:e|es|ed|als?)",
    r"choos(?:e|es|ing)",
    r"chose",
    r"decid(?:e|es|ed|ing)",
    r"decisions?",
    r"prescrib(?:e|es|ed|ing)",
    r"advis(?:e|es|ed|ing)",
    r"advice",
    r"select(?:s|ing)?",
    r"tell(?:s)?",
)
CLAIM_JUDGE_EN: tuple[str, ...] = (r"judg(?:e|es|ed|ing|ments?|ements?)", r"diagnos(?:e|es|ed|ing|is)")
_DISEASE_EN = re.compile(
    _en(
        (
            r"diseases?",
            r"illness(?:es)?",
            r"disorders?",
            r"syndromes?",
            r"cancers?",
            r"tumou?rs?",
            r"carcinomas?",
            r"lesions?",
            r"nodules?",
            r"infections?",
            r"infected",
            r"sepsis",
            r"strokes?",
            r"dementia",
            r"depression",
            r"diabetes",
            r"asthma",
            r"hypertension",
            r"COPD",
            r"COVID(?:-19)?",
            r"pneumonia",
            r"hepatitis",
            r"tuberculosis",
            r"Alzheimer['’]?s?",
            r"Parkinson['’]?s?",
            r"fibrillation",
            r"arrhythmias?",
            r"heart\s+attacks?",
            r"(?:heart|kidney|renal|liver|respiratory|cardiac)\s+failure",
            r"relapses?",
            r"relapsed",
            r"deteriorat\w*",
            r"mortality",
            r"deaths?",
            r"readmissions?",
            r"readmitted",
            r"complications?",
            r"fractures?",
            r"falls",
            r"symptoms?",
            r"pain",
            r"insomnia",
            r"(?:clinical|treatment|health|patient|patients['’])\s+outcomes?",
            r"sick(?:ness)?",
            r"ill",
            r"\w+(?:itis|omas?|emia|aemia|pathy|pathies)",
            r"(?!diagnos|prognos)\w+osis",
        )
    )
    # a disease that names a study (the asthma study, a diabetes trial) is the study's name, not an object
    + r"(?!\s+(?:stud(?:y|ies)|trials?|cohorts?|registry|registries|protocols?)(?![A-Za-z]))",
    re.I,
)
_EARLY_EN = re.compile(
    _en(
        (
            r"early",
            r"earlier",
            r"sooner",
            r"before\s+symptoms",
            r"hidden",
            r"latent",
            r"undiagnosed",
            r"undetected",
            r"unrecogni[sz]ed",
            r"pre-?symptomatic",
        )
    ),
    re.I,
)
# not "candidate" and not "participant": a candidate for a study is the product's own word, and a consent form's
# "risks to the participant" are the study's
_PATIENT_EN = re.compile(
    _en((r"patients?", r"patient['’]s", r"patients['’]", r"individuals?", r"people", r"persons?")), re.I
)
# finding candidates who meet a study's criteria early is the product's purpose, not an early case
_CANDIDATE_EN = re.compile(
    _en((r"candidates?", r"criteri(?:a|on)", r"eligib\w*", r"match(?:es|ed|ing)?", r"meets?", r"stud(?:y|ies)")), re.I
)
_STATE_EN = re.compile(
    _DISEASE_EN.pattern
    + "|"
    + _en((r"infected", r"suffering", r"severity", r"eligib\w*", r"take\s+part", r"taking\s+part")),
    re.I,
)
_TREATMENT_EN = re.compile(
    _en(
        (
            r"treatments?",
            r"therap(?:y|ies)",
            r"drugs?",
            r"doses?",
            r"dosage",
            r"dosing",
            r"medications?",
            r"insulin",
            r"surgery",
            r"prescriptions?",
            r"regimens?",
            r"eligib\w*",
            r"take\s+part",
            r"taking\s+part",
        )
    ),
    re.I,
)
_ACTOR_CORE_EN = (
    r"TrialBox|(?:the|this|our|a)\s+(?:system|software|product|tool|box|model|algorithm|platform|engine|program|"
    r"application|app|AI)|AI|artificial\s+intelligence"
)
_PERSON_CORE_EN = (
    r"physicians?|doctors?|clinicians?|investigators?|nurses?|coordinators?|staff|you|"
    r"(?:a|the|each)\s+(?:qualified\s+|named\s+)?(?:person|reviewer|human)|people|researchers?|"
    r"(?:review|research|study|care)\s+teams?|teams?|stewards?|CRCs?|PIs?|humans?|\w+ologists?|specialists?|"
    r"reviewers?|users?"
)
_ACTORS_EN = r"(?<![A-Za-z])(?:" + _ACTOR_CORE_EN + r"|it)(?![A-Za-z])"
_PERSONS_EN = r"(?<![A-Za-z])(?:" + _PERSON_CORE_EN + r")(?![A-Za-z])"
_POSSESSIVE_EN = r"\s*['’]s?"
_NEG_BEFORE_EN = re.compile(r"(?<![A-Za-z])(?:not|never|no|cannot)(?![A-Za-z])|n['’]t(?![A-Za-z])", re.I)
GRAMMAR_EN = Grammar(
    clause_marks=",;:.!?\n—–",
    sentence_marks=".!?\n",
    actor_subject=re.compile(_ACTORS_EN + r"(?!['’]s)", re.I),
    person_subject=re.compile(_PERSONS_EN + r"(?!['’]s?(?![A-Za-z]))", re.I),
    actor_possessor=re.compile(_ACTORS_EN + _POSSESSIVE_EN + r"\s*$", re.I),
    person_possessor=re.compile(_PERSONS_EN + _POSSESSIVE_EN + r"\s*$", re.I),
    helps=re.compile(_en((r"help\w*", r"assist\w*", r"support\w*", r"enabl\w*")), re.I),
    replaces=re.compile(
        _en(
            (
                r"replac\w*",
                r"substitut\w*",
                r"instead\s+of",
                r"in\s+place\s+of",
                r"on\s+behalf\s+of",
                r"tak(?:e|es|ing)\s+over",
                r"does\s+it\s+for",
                r"does\s+not\s+have\s+to",
                r"no\s+(?:longer\s+)?need",
            )
        ),
        re.I,
    ),
    # English needs no causative: "let the AI decide" puts the product straight before the verb as its subject
    causes=re.compile(r"(?!)"),
    idle=re.compile(
        r"\s*(?:only\s+|just\s+|also\s+|merely\s+)?(?:shows?|displays?|lists?|reads?|presents?|quotes?|prints?|"
        r"does\s+not|doesn['’]t|do\s+not|never|is\s+not|isn['’]t|cannot|can['’]t|will\s+not|won['’]t|plays\s+no|"
        r"makes\s+no|has\s+no|gives\s+no)(?![A-Za-z])",
        re.I,
    ),
    shows=re.compile(
        r"\s*(?:only\s+|just\s+|merely\s+)?(?:shows?|displays?|lists?|reads?|presents?|quotes?|prints?)(?![A-Za-z])",
        re.I,
    ),
    replace_negated=lambda s, ss, se, r: bool(
        re.search("(?:" + _NEG_BEFORE_EN.pattern + r")(?:\s+\S+){0,3}\s*$", s[ss : r.start()], re.I)
    ),
    agent_after=re.compile(
        r"[^,;:.!?\n]*?(?<![A-Za-z])(?:by|thanks\s+to|with|using|of)\s+(?:the\s+|a\s+|an\s+|our\s+|their\s+|his\s+|"
        r"her\s+)?(?:(?P<actor>(?<![A-Za-z])(?:" + _ACTOR_CORE_EN + r")(?![A-Za-z]))|(?P<person>" + _PERSONS_EN + "))",
        re.I,
    ),
)
_VERDICT_EN = re.compile(r"(?<![A-Za-z_])diagnos(?:is|es)(?![A-Za-z_])", re.I)
_FIELD_AFTER_EN = re.compile(
    r"\s+(?:codes?|dates?|names?|fields?|columns?|records?|lists?|history|years?|age|categor(?:y|ies)|time)(?![A-Za-z])",
    re.I,
)
_FIELD_BEFORE_EN = re.compile(
    r"(?<![A-Za-z])(?:date|age|year|time|month)\s+(?:of|at|since|from)\s+(?:the\s+|first\s+)?$", re.I
)


def _record_masked_en(text: str) -> str:
    """:func:`_record_masked` with FORBIDDEN's English "diagnosis" and "diagnoses" (D-1256): a record field (diagnosis
    code, date of diagnosis) and a person's own diagnosis pass; the product's does not."""
    return _record_masked(
        text,
        _VERDICT_EN,
        _FIELD_AFTER_EN,
        lambda t, cs, m: bool(_FIELD_BEFORE_EN.search(t, cs, m.start())),
        GRAMMAR_EN,
    )


# the English denial: a negator before the word in its clause; "nor" continues a denial (neither ... nor) and denies
# alone only when no other negator stands before it; a negator straight after the verb's object slot (predicts
# nothing) denies too. "not only", "not just", "not unusual" deny nothing.
_NEG_EN = re.compile(
    r"(?<![A-Za-z])(?:not(?!\s+(?:only|just|merely|simply|unusual|uncommon|rare)(?![A-Za-z]))|never|no(?!\s+doubt)|"
    r"none|neither|without|cannot)(?![A-Za-z])|n['’]t(?![A-Za-z])|(?<![A-Za-z])(?:fail(?:s|ed)?|unable)\s+to(?![A-Za-z])",
    re.I,
)
_NOR_EN = re.compile(r"(?<![A-Za-z])nor(?![A-Za-z])", re.I)
_NEG_AFTER_EN = re.compile(r"\s+(?:nothing|no\s+one|nobody)(?![A-Za-z])", re.I)
_MISS_EN = re.compile(_en(CLAIM_MISS_EN), re.I)
_DENIABLE_EN = re.compile(
    _en(
        (
            *CLAIM_OUTRIGHT_EN,
            *CLAIM_FIND_EN,
            *CLAIM_RATE_EN,
            *CLAIM_POSSIBLE_EN,
            *CLAIM_WARN_EN,
            *CLAIM_REMIND_EN,
            *CLAIM_ACT_EN,
            *CLAIM_STATE_EN,
            *CLAIM_DECIDE_EN,
            *CLAIM_JUDGE_EN,
            r"diagnos(?:is|es)",
        )
    ),
    re.I,
)
_CLAUSE_END_EN = re.compile(
    r"[;:.!?\n—–]|"
    + _en(
        (
            r"but",
            r"although",
            r"though",
            r"while",
            r"whereas",
            r"because",
            r"however",
            r"yet",
            r"nevertheless",
            r"unless",
            r"instead",
            r"before",
            r"after",
            r"which",
            r"who",
        )
    )
    + r"|,(?!\s*(?:(?:or|and)\s+)?"
    + _DENIABLE_EN.pattern
    + ")"
    # "and" or "or" before another verb starts its own denial (does not predict a risk and gives no score); before a
    # claim word it continues a list (does not diagnose, treat or prevent)
    + r"|(?<![A-Za-z])(?:and|or)(?![A-Za-z])(?!\s*"
    + _DENIABLE_EN.pattern
    + ")"
    # ... and a finite verb is a new predicate (does not store names and detects heart disease)
    + r"|(?<![A-Za-z])(?:and|or)(?=\s*"
    + _DENIABLE_EN.pattern
    + r"(?<=s))",
    re.I,
)


def deny_masked_en(text: str) -> str:
    """``text`` with every denied English claim word blanked: the part of its clause before it carries an odd number
    of negators (TrialBox does not diagnose, treat or prevent disease; makes no prediction; neither diagnoses nor
    predicts), or "nothing" follows it (predicts nothing). Two cancel (never fails to spot); a negated miss counts
    for nothing. The disease and early words of a denied clause are blanked with it (does not tell the physician
    whether a patient has a disease). Read only for text the caller names en (:func:`deny_masked`)."""
    out = list(text)
    ends = [(e.start(), e.end()) for e in _CLAUSE_END_EN.finditer(text)]
    for m in _DENIABLE_EN.finditer(text):
        if _MISS_EN.fullmatch(m.group(0)):
            continue
        start = max((b for _, b in ends if b <= m.start()), default=0)
        stop = min((a for a, _ in ends if a >= m.end()), default=len(text))
        n = len(_NEG_EN.findall(text, start, m.start()))
        if n == 0 and _NOR_EN.search(text, start, m.start()):
            n = 1
        n += 1 if _NEG_AFTER_EN.match(text, m.end()) else 0
        if n % 2 == 1:
            out[m.start() : m.end()] = _MASK * (m.end() - m.start())
            for rx in (_DISEASE_EN, _EARLY_EN):
                for o in rx.finditer(text, m.end(), stop):
                    out[o.start() : o.end()] = _MASK * (o.end() - o.start())
    return "".join(out)


def _is_zh(lang: str | None) -> bool:
    return (lang or "").strip().lower().startswith("zh")


def _is_en(lang: str | None) -> bool:
    return (lang or "").strip().lower().startswith("en")


def _is_ja(lang: str | None) -> bool:
    return (lang or "").strip().lower().startswith("ja")


def deny_masked(text: str, lang: str | None = None) -> str:
    """``text`` with every denied claim word blanked: Japanese (:func:`deny_masked_ja`) always, zh-TW
    (:func:`deny_masked_zh`) when the caller names the text zh-TW, English (:func:`deny_masked_en`) when it names it
    en. FORBIDDEN's verdict words that name a record field or a person's own act are blanked too, for text named
    zh-TW, ja or en (D-1247, D-1256); text with no language keeps FORBIDDEN as before."""
    text = deny_masked_ja(text, d1228=not _is_ja(lang))
    if _is_zh(lang):
        return _record_masked_zh(deny_masked_zh(text))
    if _is_en(lang):
        return _record_masked_en(deny_masked_en(text))
    if _is_ja(lang):
        return _record_masked_ja(text)
    return text


# a space inside a Chinese word (診　斷, 早 期 發 現) hides it from the rule; text named zh-TW is read without it
_HAN_SPACE_ZH = re.compile(r"(?<=[\u3400-\u9fff])[ \u3000]+(?=[\u3400-\u9fff])")


def clean(text: str, lang: str | None = None) -> str:
    """D-1228's cleaning (:func:`clean_ja`) and, for text named zh-TW, the spaces between two Chinese characters
    removed."""
    text = clean_ja(text)
    return _HAN_SPACE_ZH.sub("", text) if _is_zh(lang) else text


@dataclass(frozen=True)
class ClaimTable:
    """One language's terms for the one claim rule (D-1228, D-1247, D-1256). The rule is :func:`check_claims`; a table
    only says which words, which objects and which subjects. Every class is read the same way for every language;
    what differs is the data here."""

    lang: str
    outright: tuple[str, ...]
    find: tuple[str, ...]
    rate: tuple[str, ...]
    judge: tuple[str, ...]
    disease: re.Pattern[str]
    early: re.Pattern[str]
    patient: re.Pattern[str]
    allowed: dict[str, tuple[str, ...]]
    actor_before: str
    actor_subject: re.Pattern[str]
    person_subject: re.Pattern[str]
    warn: tuple[str, ...] = ()
    allowed_more: dict[str, tuple[str, ...]] = field(default_factory=dict)  # read after ``allowed``
    # D-1247 gave zh-TW these classes; D-1256 gives them to ja and en: a warning only about a disease or an early case;
    # acting on a disease; telling a patient's state; deciding a treatment or a patient's taking part
    remind: tuple[str, ...] = ()
    act: tuple[str, ...] = ()
    state: tuple[str, ...] = ()
    decide: tuple[str, ...] = ()
    # rate words that are a claim only about a disease (可能性, possible, likely, suspected)
    possible: tuple[str, ...] = ()
    grammar: Grammar | None = None
    act_record_before: re.Pattern[str] | None = None  # searched up to the word: 接受…治療, received treatment
    act_record_after: re.Pattern[str] | None = None  # matched after the word: 治療紀錄, 治療歴, treatment arm
    act_actor_before: str = ""  # the product straight before an act (本產品的療效, TrialBoxの糖尿病改善)
    state_words: re.Pattern[str] | None = None
    state_both_sides: bool = False  # Japanese puts the object before the verb, English a passive's subject
    treatment: re.Pattern[str] | None = None
    candidate: re.Pattern[str] | None = None
    candidate_after: bool = True  # zh-TW reads the candidate after the word (找到…符合條件的受試者)
    # Japanese: the object of a reminder, a state or a decision stands before the verb, anywhere in its clause
    # (糖尿病…についてリマインド, どの患者にインスリンを開始すべきかを…提示)
    object_in_clause: bool = False
    window: int = CLAIM_WINDOW
    patterns: bool = False  # English: the words are patterns with their inflections, matched whole, in any case
    # a word whose past participle names a record (patients diagnosed with RA): not a finding unless the product does it
    find_record: re.Pattern[str] | None = None

    def rx(self, word: str) -> re.Pattern[str]:
        return _word_rx(word, self.patterns)


_WORD_RX: dict[tuple[str, bool], re.Pattern[str]] = {}


def _word_rx(word: str, patterns: bool) -> re.Pattern[str]:
    key = (word, patterns)
    if key not in _WORD_RX:
        _WORD_RX[key] = re.compile(_en((word,)), re.I) if patterns else re.compile(re.escape(word))
    return _WORD_RX[key]


_CANDIDATE_ZH = re.compile(
    r".{0,8}?(?:"
    + _zh_alt(("符合", "适合", "適合"))
    + r".{0,10}?"
    + _zh_alt(("條件", "資格", "標準", "收案"))
    + "|"
    + _zh_alt(("候選",))
    + ")"
)
_ACT_RECORD_ZH = re.compile(
    "(?:" + _zh_alt(("接受",)) + r"[^、，,；;。]{0,10}|" + _zh_alt(_ACT_RECORD_BEFORE_ZH) + r")\s*$"
)
_ACT_RECORD_AFTER_RX_ZH = re.compile(
    r"\s*(?:" + _zh_alt(_ACT_RECORD_AFTER_ZH) + "|" + _zh_alt(("的", "之")) + r"\s*" + _zh_alt(CLAIM_PATIENTS_ZH) + ")"
)
_STATE_ZH = re.compile(_zh_alt(_STATE_WORDS_ZH))
_CLAUSE_END_AT_ZH = re.compile(r"\s*(?:[" + _CLAUSE_MARKS_ZH + "]|$)")
_TREATMENT_RX_ZH = re.compile(_zh_alt(_TREATMENT_ZH))
_ZH_ACTOR_BEFORE = (
    _ACTORS_ZH + r"\s*(?:" + _zh_alt(("的", "之", "所", "產生的", "計算的", "給出的", "提供的")) + r")?\s*$"
)

# Japanese: the candidate words that make an early finding the product's purpose, and the allowed contexts the new
# classes need (a study's candidates who may meet its criteria: 参加条件に合う可能性のある患者)
_CANDIDATE_JA = re.compile("候補者|候補|基準|条件|適格|該当")
# The English names of the published instruments and measured items the catalogue holds (catalogue/items.csv
# name_en, catalogue/instruments.csv name) whose name carries a rate word: a record value named by its own name
# (D-351), as NAMED_INSTRUMENTS_ZH is for zh-TW. A test holds that each is in the catalogue and that every catalogue
# name passes.
NAMED_INSTRUMENTS_EN: tuple[str, ...] = (
    "International Prognostic Index",
    "FRAX 10-year major osteoporotic fracture probability",
    "PD-L1 tumour proportion score",
    "Birmingham Vasculitis Activity Score",
    "FRAX fracture risk",
)
# the same for name_ja: a record value named by its own name; read only for text named ja (D-1256)
NAMED_INSTRUMENTS_JA: tuple[str, ...] = ("主要骨粗鬆症性骨折10年確率",)
# the allowed contexts D-1256 adds for text named ja, beside D-1228's CLAIM_ALLOWED_JA (read for every text as before)
CLAIM_ALLOWED_MORE_JA: dict[str, tuple[str, ...]] = {
    # a study's candidates who may meet its criteria (参加条件に合う可能性のある患者): the product's own statement
    "可能性": (r"(?:合う|合致する|該当する|一致する|満たす|当てはまる)可能性",),
    "instrument": (*(re.escape(n) for n in NAMED_INSTRUMENTS_JA), r"[zZT]\s*スコア"),
    # the study's screening visit as a point in time (a protocol's スクリーニング前90日以内), not finding a disease
    "スクリーニング": (r"スクリーニング(?:の[^、。]{0,10}?)?(?:前|後|時|期間|来院|日|訪問|名簿)",),
}
CLAIM_ALLOWED_EN: dict[str, tuple[str, ...]] = {
    "instrument": tuple(re.escape(n) for n in NAMED_INSTRUMENTS_EN),
    "score": (
        r"(?:"
        + "|".join(re.escape(s) for s in sorted(NAMED_SCALES, key=len, reverse=True))
        + r")(?:\s*PS)?\s*(?:total\s+|global\s+)?(?:scores?|sub-?scores?)",
        r"scores?\s+definitions?",
        r"[zt]-scores?",
    ),
    # risk of bias; a study's own risks to the participant, as a consent form states them
    "risk": (
        r"risks?\s+of\s+bias",
        r"(?:study|trial|research|participation)(?:['’]s)?\s+(?:main\s+|possible\s+|potential\s+|known\s+)?risks?",
        r"risks?\s+(?:of|from|to|in)\s+(?:the\s+|this\s+|taking\s+part\s+in\s+(?:the\s+|this\s+)?)?"
        r"(?:study|trial|research|participation)",
        r"risks?\s+and\s+benefits",
        r"benefits\s+and\s+(?:the\s+)?risks?",
    ),
    # a study's enrolment forecast (feasibility) is a count, not a patient's outcome; a lung function's "% predicted"
    "predict": (
        r"(?:enrol(?:l)?ment|recruitment|randomi[sz]ations?|consents?|candidates?|accrual)\s+(?:count\s+)?"
        r"(?:forecasts?|predictions?|projections?)",
        r"(?:predicted|forecast)\s+(?:enrol(?:l)?ment|recruitment|randomi[sz]ations?|accrual|numbers?|counts?)",
        r"%\s*predicted",
    ),
    # a lab's detection limit; a study's screening visit as a point in time
    "detect": (r"(?:detection|quantification)\s+limits?", r"limits?\s+of\s+detection"),
    "screening": (
        r"(?:pre-?)?screening\s+(?:visits?|logs?|periods?|dates?|days?|numbers?|failures?|phase|weeks?|lists?)",
        r"(?:at|before|after|prior\s+to|since|from)\s+(?:the\s+)?(?:pre-?)?screening",
    ),
    "possible": (r"possible\s+candidates?",),
}
_CLAIM_CONTINUES_EN = r"(?!\s+(?:predictions?|scores?|scoring|models?|stratif\w*))"

CLAIM_TABLES: tuple[ClaimTable, ...] = (
    ClaimTable(
        lang="ja",
        outright=(*CLAIM_OUTRIGHT_JA, *CLAIM_OUTRIGHT_MORE_JA),
        find=(*CLAIM_FIND_JA, *CLAIM_FIND_MORE_JA),
        rate=CLAIM_RATE_JA,
        judge=CLAIM_JUDGE_JA,
        disease=_DISEASE_JA,
        early=re.compile("|".join(re.escape(w) for w in (*CLAIM_EARLY_JA, *CLAIM_EARLY_MORE_JA))),
        patient=_PATIENT,
        allowed=CLAIM_ALLOWED_JA,
        allowed_more=CLAIM_ALLOWED_MORE_JA,
        actor_before=_ACTOR_BEFORE,
        actor_subject=_ACTOR_SUBJECT,
        person_subject=_PERSON_SUBJECT,
        warn=CLAIM_WARN_JA,
        remind=CLAIM_REMIND_JA,
        act=CLAIM_ACT_JA,
        state=CLAIM_STATE_JA,
        decide=CLAIM_DECIDE_JA,
        possible=CLAIM_POSSIBLE_JA,
        grammar=GRAMMAR_JA,
        act_record_before=re.compile("(?:" + "|".join(re.escape(w) for w in _ACT_RECORD_BEFORE_JA) + r")\s*$"),
        act_record_after=re.compile(r"\s*(?:法の?)?(?:" + "|".join(re.escape(w) for w in _ACT_RECORD_AFTER_JA) + ")"),
        act_actor_before=_ACTORS_JA + r"\s*(?:の|による|により|で|を使うと|を使えば|のおかげで|なら)\s*$",
        state_words=re.compile("|".join(re.escape(w) for w in _STATE_WORDS_JA)),
        state_both_sides=True,
        treatment=re.compile("|".join(re.escape(w) for w in _TREATMENT_JA)),
        candidate=_CANDIDATE_JA,
        candidate_after=False,
        object_in_clause=True,
        window=16,
    ),
    ClaimTable(
        lang="zh-TW",
        outright=(*_zh_both(CLAIM_OUTRIGHT_ZH), *(_simplified(w) for w in FORBIDDEN_SIMPLIFIED_ZH)),
        find=_zh_both(CLAIM_FIND_ZH),
        rate=_zh_both(CLAIM_RATE_ZH),
        judge=_zh_both(CLAIM_JUDGE_ZH),
        disease=_DISEASE_ZH,
        early=re.compile(_zh_alt(CLAIM_EARLY_ZH)),
        patient=re.compile(_zh_alt(CLAIM_PATIENTS_ZH)),
        allowed=CLAIM_ALLOWED_ZH,  # read in both scripts through _zh_allowed()
        actor_before=_ZH_ACTOR_BEFORE,
        actor_subject=_ACTOR_SUBJECT_ZH,
        person_subject=_PERSON_SUBJECT_ZH,
        warn=_zh_both(CLAIM_WARN_ZH),
        remind=_zh_both(CLAIM_REMIND_ZH),
        act=_zh_both(CLAIM_ACT_ZH),
        state=_zh_both(CLAIM_STATE_ZH),
        decide=_zh_both(CLAIM_DECIDE_ZH),
        grammar=GRAMMAR_ZH,
        act_record_before=_ACT_RECORD_ZH,
        act_record_after=_ACT_RECORD_AFTER_RX_ZH,
        act_actor_before=_ZH_ACTOR_BEFORE,
        state_words=_STATE_ZH,
        treatment=_TREATMENT_RX_ZH,
        candidate=_CANDIDATE_ZH,
    ),
    ClaimTable(
        lang="en",
        outright=CLAIM_OUTRIGHT_EN,
        find=CLAIM_FIND_EN,
        rate=CLAIM_RATE_EN,
        judge=CLAIM_JUDGE_EN,
        disease=_DISEASE_EN,
        early=_EARLY_EN,
        patient=_PATIENT_EN,
        allowed=CLAIM_ALLOWED_EN,
        actor_before=_ACTORS_EN + r"(?:" + _POSSESSIVE_EN + r")?\s*$",
        actor_subject=GRAMMAR_EN.actor_subject,
        person_subject=GRAMMAR_EN.person_subject,
        warn=CLAIM_WARN_EN,
        remind=CLAIM_REMIND_EN,
        act=CLAIM_ACT_EN,
        state=CLAIM_STATE_EN,
        decide=CLAIM_DECIDE_EN,
        possible=CLAIM_POSSIBLE_EN,
        grammar=GRAMMAR_EN,
        act_record_before=_ACT_RECORD_BEFORE_EN,
        act_record_after=_ACT_RECORD_AFTER_EN,
        act_actor_before=_ACTORS_EN + _POSSESSIVE_EN + r"\s+(?:\S+\s+){0,2}$",
        state_words=_STATE_EN,
        state_both_sides=True,
        treatment=_TREATMENT_EN,
        candidate=_CANDIDATE_EN,
        candidate_after=False,
        window=64,
        patterns=True,
        find_record=re.compile(r"diagnosed", re.I),
    ),
)
CLAIM_TABLE_JA, CLAIM_TABLE_ZH, CLAIM_TABLE_EN = CLAIM_TABLES
# D-1228's Japanese table as it was: it reads every text not named ja (zh-TW, en, or no language) exactly as before
# D-1256, so a Chinese line (系統識別碼與病歷號) is never read by the Japanese disease class
CLAIM_TABLE_JA_D1228 = ClaimTable(
    lang="ja",
    outright=CLAIM_OUTRIGHT_JA,
    find=CLAIM_FIND_JA,
    rate=CLAIM_RATE_JA,
    judge=CLAIM_JUDGE_JA,
    disease=_DISEASE,
    early=_EARLY,
    patient=_PATIENT,
    allowed=CLAIM_ALLOWED_JA,
    actor_before=_ACTOR_BEFORE,
    actor_subject=_ACTOR_SUBJECT,
    person_subject=_PERSON_SUBJECT,
)


def _tables(lang: str | None) -> tuple[ClaimTable, ...]:
    """The tables that read text in ``lang``: the Japanese table always (as before D-1247), with D-1256's classes only
    for text the caller names ja; the zh-TW table only for text named zh-TW; the English table only for text named en
    (D-1256). Text with no language is read by D-1228's Japanese table, as before. The language is never guessed from
    the script."""
    if _is_ja(lang):
        return (CLAIM_TABLE_JA,)
    if _is_zh(lang):
        return (CLAIM_TABLE_JA_D1228, CLAIM_TABLE_ZH)
    if _is_en(lang):
        return (CLAIM_TABLE_JA_D1228, CLAIM_TABLE_EN)
    return (CLAIM_TABLE_JA_D1228,)


def check_claims(text: str, lang: str | None = None) -> list[Hit]:
    """Every device claim in ``text``: one rule (D-1228), one table per language (D-1247, D-1256). ``lang`` is the
    text's language as the caller knows it; without one, only the Japanese table reads it, as before. An empty list
    means no claim."""
    return _check_claims(clean(text, lang), lang)


# an English sentence ends at . ! ? before a space (6.0 mg/dL is one sentence), or at a line end
_SENTENCE_EN = re.compile(r"[^\n]+?(?:[.!?](?=\s|$)|$)", re.M)


def _check_claims(text: str, lang: str | None) -> list[Hit]:
    text = deny_masked(clean_ja(text), lang)
    hits: list[Hit] = []
    for table in _tables(lang):
        for sentence in (_SENTENCE_EN if table.patterns else _SENTENCE).findall(text):
            hits += _claims_in(sentence, table)
    return hits


def _allowed(table: ClaimTable) -> list[re.Pattern[str]]:
    if table.lang == "zh-TW":
        return [re.compile(rx) for patterns in _zh_allowed().values() for rx in patterns]
    if table.patterns:
        return [
            re.compile(_en((rx,)) + _CLAIM_CONTINUES_EN, re.I) for patterns in table.allowed.values() for rx in patterns
        ]
    return [re.compile(rx) for d in (table.allowed, table.allowed_more) for patterns in d.values() for rx in patterns]


def _claims_in(sentence: str, table: ClaimTable) -> list[Hit]:
    hits: list[Hit] = []
    masked = sentence
    for rx in _allowed(table):
        masked = rx.sub(_blank, masked)
    g = table.grammar

    def near(m: re.Match[str], rx: re.Pattern[str], s: str = masked) -> bool:
        # a class looks at the next character (病 of 病人 is no disease), so it is matched on the whole sentence and
        # must lie inside the window; a cut window would read 病人 as 病
        lo, hi = max(0, m.start() - table.window), m.end() + table.window
        return any(lo <= x.start() and x.end() <= hi for x in rx.finditer(s, lo, min(len(s), hi + 8)))

    def hit(m: re.Match[str], word: str, s: str = sentence) -> None:
        hits.append(
            Hit(
                word=m.group(0).lower() if table.patterns else word,
                context=s[max(0, m.start() - 30) : m.end() + 30].strip(),
            )
        )

    def subject(m: re.Match[str]) -> str | None:
        return _subject(g, masked, m.start(), m.end()) if g is not None else None

    def clause(m: re.Match[str]) -> tuple[int, int]:
        assert g is not None
        return _clause_start(g, masked, m.start()), _clause_end(g, masked, m.end())

    def candidate(m: re.Match[str]) -> bool:
        if table.candidate is None:
            return False
        if table.candidate_after:
            return table.candidate.match(masked, m.end()) is not None
        return near(m, table.candidate)

    for word in table.outright:
        for m in table.rx(word).finditer(masked):
            hit(m, word)
    for word in table.find:
        for m in table.rx(word).finditer(masked):
            if table.find_record is not None and table.find_record.fullmatch(m.group(0)) and subject(m) != "actor":
                continue  # patients diagnosed with RA: a record, unless the product diagnosed them
            # finding candidates who meet a study's criteria early is the product's purpose, not an early case
            early = near(m, table.early) and not candidate(m)
            if near(m, table.disease) or early:
                hit(m, word)
    for word in table.rate:
        for m in table.rx(word).finditer(masked):
            if near(m, table.patient) or near(m, table.disease) or re.search(table.actor_before, masked[: m.start()]):
                hit(m, word)
    for word in table.possible:
        for m in table.rx(word).finditer(masked):
            if near(m, table.disease):
                hit(m, word)
    for word in table.warn:
        for m in table.rx(word).finditer(masked):
            if near(m, table.patient) or near(m, table.disease) or near(m, table.early):
                hit(m, word)
    for word in table.remind:
        for m in table.rx(word).finditer(masked):
            # what it reminds of runs to the end of its clause (提醒醫師注意病人可能的心臟衰竭); in Japanese it stands
            # before the word, in its clause (糖尿病を発症しつつある患者についてリマインド)
            cs, ce = clause(m)
            lo = cs if table.object_in_clause else m.end()
            if table.disease.search(masked, lo, ce) or table.early.search(masked, lo, ce):
                hit(m, word)
    for word in table.act:
        for m in table.rx(word).finditer(masked):
            rec_before, rec_after = table.act_record_before, table.act_record_after
            if (rec_before is not None and rec_before.search(masked, 0, m.start())) or (
                rec_after is not None and rec_after.match(masked, m.end())
            ):
                continue  # a treatment the record holds (接受糖尿病治療, 治療歴, received treatment)
            on_disease = near(m, table.disease) or near(m, table.early)
            on_disease = on_disease or (word == "確診" and _CLAUSE_END_AT_ZH.match(masked, m.end()) is not None)
            if re.search(table.act_actor_before, masked[: m.start()]) or (on_disease and subject(m) == "actor"):
                hit(m, word)
    for word in table.state:
        for m in table.rx(word).finditer(masked):
            assert table.state_words is not None
            if table.object_in_clause:
                cs, ce = clause(m)
                about = table.state_words.search(masked, cs, ce) is not None
            elif table.state_both_sides:
                about = near(m, table.state_words)
            else:
                about = table.state_words.search(masked, m.end(), m.end() + table.window) is not None
            if about and subject(m) == "actor":
                hit(m, word)
    for word in table.decide:
        for m in table.rx(word).finditer(masked):
            assert table.treatment is not None
            if table.object_in_clause:
                cs, ce = clause(m)
                about = table.treatment.search(masked, cs, ce) is not None
            else:
                about = near(m, table.treatment)
            if about and subject(m) == "actor":
                hit(m, word)
    for word in table.judge:
        for m in table.rx(word).finditer(masked):
            if g is not None:
                if subject(m) == "actor":
                    hit(m, word)
                continue
            # D-1228's reading, kept for text not named ja: a person as the subject of the judgement's clause clears
            # an actor of an earlier clause (モデルが読み、人が判断します), never an actor of the same clause
            start = max(masked.rfind(c, 0, m.start()) for c in "、，,") + 1
            actors = [a.end() for a in table.actor_subject.finditer(masked, 0, m.start())]
            in_clause = [a for a in actors if a > start]
            persons = [p.end() for p in table.person_subject.finditer(masked, start, m.start())]
            if in_clause or (actors and not persons):
                hit(m, word)
    return hits


def check_claims_ja(text: str) -> list[Hit]:
    """The Japanese device claims in ``text``: :func:`check_claims` with the Japanese table only, the name D-1228's
    callers use."""
    return check_claims(text, "ja")


_TAG = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)


@dataclass(frozen=True)
class Hit:
    """One forbidden word found: the word and up to 30 characters either side, for the failure message."""

    word: str
    context: str


def _pattern(word: str) -> re.Pattern[str]:
    if word.isascii():
        return re.compile(r"(?<![A-Za-z_])" + re.escape(word) + r"(?![A-Za-z_])", re.I)
    return re.compile(re.escape(word))


def visible_text(page: str) -> str:
    """The words a reader sees on an HTML page: tags, attributes, scripts and styles removed, entities decoded."""
    return html.unescape(_TAG.sub(" ", page))


def check(
    text: str,
    words: Iterable[str] = FORBIDDEN,
    allowed: Iterable[str] = ALLOWED,
    *,
    claims: bool = True,
    lang: str | None = None,
) -> list[Hit]:
    """Every forbidden word in ``text`` after the allowed phrases are masked, and every device claim
    (:func:`check_claims`; ``claims=False`` leaves them out). ``lang`` is the text's language as the caller knows it
    (a catalogue's language key, a page's own); without one, the claims are read as Japanese only, as before D-1247.
    An empty list means the text is clean."""
    masked = text
    for phrase in allowed:
        masked = masked.replace(phrase, " ")
    masked = deny_masked(clean(masked, lang), lang)  # a denial says what the product does not do (D-1228, D-1247)
    hits: list[Hit] = []
    for word in words:
        for m in _pattern(word).finditer(masked):
            ctx = masked[max(0, m.start() - 30) : m.end() + 30].replace("\n", " ")
            hits.append(Hit(word=word, context=ctx.strip()))
    return hits + (_check_claims(masked, lang) if claims else [])


_BLOCK = re.compile(
    r"</?(?:p|div|li|ul|ol|dl|dt|dd|td|th|tr|table|thead|tbody|h[1-6]|br|hr|option|select|section|article|header"
    r"|footer|nav|main|aside|form|fieldset|legend|label|button|summary|details|blockquote|pre|figure|figcaption)\b[^>]*>",
    re.I,
)


def sentences_of_page(page: str) -> str:
    """What a reader sees of an HTML page, for the Japanese claim rule: a block element (a paragraph, a list item, a
    cell, an option ...) ends a line; an inline tag (<b>, <a>, <span>) joins its words with no space, so it cannot
    split a subject from its verb; the template's own line breaks inside a paragraph do not end a sentence."""
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
    page = _BLOCK.sub("\x00", page)
    page = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", page))
    return html.unescape(page).replace("\x00", "\n")


_HTML_LANG = re.compile(r"<html\b[^>]*\blang\s*=\s*[\"']?([A-Za-z-]+)", re.I)


def check_page(page: str, words: Iterable[str] = FORBIDDEN, lang: str | None = None) -> list[Hit]:
    """:func:`check` on what a reader sees of an HTML page (the claims on :func:`sentences_of_page`). The page's
    language is ``lang``, or else the one it declares (``<html lang="zh-TW">``); a fragment with neither is read as
    before D-1247."""
    if lang is None and (m := _HTML_LANG.search(page)):
        lang = m.group(1)
    return check(visible_text(page), words, claims=False, lang=lang) + check_claims(sentences_of_page(page), lang)


def lang_of(raw: str | None) -> str:
    """``ja``, ``ja-JP``, ``zh``, ``zh-Hant-TW`` ... -> one of :data:`LANGS`; anything else is ``en``."""
    low = (raw or "").strip().lower()
    if low.startswith("ja"):
        return "ja"
    if low.startswith("zh"):
        return "zh-TW"
    return "en"


def statement(lang: str | None) -> str:
    """The intended-use statement in ``lang`` (TB-IU-01 §1), for the footer of a report, a sheet or a mail."""
    return STATEMENT[lang_of(lang)]


_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿]")


def text_lang(text: str) -> str:
    """The language a message is written in, from its script: kana -> ja, five or more Han characters without kana ->
    zh-TW, else en. The mail gateway uses it to pick the statement's language, since a send request carries none."""
    sample = text[:4000]
    if _KANA.search(sample):
        return "ja"
    if len(_HAN.findall(sample)) >= 5:
        return "zh-TW"
    return "en"


def exempt(path: str) -> bool:
    """True for a file that may name the hazard plainly (:data:`EXEMPT_PATHS`); ``path`` is relative to trialbox/."""
    p = path.replace("\\", "/").removeprefix("./")
    return any(p == e or (e.endswith("/") and p.startswith(e)) for e in EXEMPT_PATHS)


def check_file(path: str, text: str, words: Iterable[str] = FORBIDDEN, lang: str | None = None) -> list[Hit]:
    """:func:`check` on a file's text, or nothing for an exempt path (by design: the risk file names the hazard)."""
    return [] if exempt(path) else check(text, words, lang=lang)
