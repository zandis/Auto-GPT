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
from collections.abc import Iterable
from dataclasses import dataclass

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

# Japanese device claims (JP-4, card 10C-5; reasoning in docs/plan/intended-use-jp.md). Under the MHLW guideline a
# program becomes a device by what it says it does for a patient: finding (発見), predicting (予測), scoring (スコア) a
# patient, or listing "suspected" or "undiagnosed" ones (case database No.74 and No.243). Most of these are ordinary
# words the product needs (バイアスのリスク, ECOG スコア, 検出限界, 登録の予測), so the rule refuses the claim, not the
# word: a term in CLAIMS_JA is a hit only in a claiming context, i.e. in the same sentence as
#   * an actor doing it: the product, the system, the AI or a model as subject (CLAIM_ACTORS_JA + が, は, による ...)
#     anywhere before the term, or
#   * a patient: a word of CLAIM_PATIENTS_JA within CLAIM_WINDOW characters of the term (患者のリスク, 患者を発見).
# Before that, the term's allowed contexts are masked (each a regular expression), and so is a negation straight
# after the term (予測しません, 発見は行いません): a sentence that says what the product does not do is not a claim.
# 疑い患者 is refused outright (in FORBIDDEN); 診断 (so 診断する, 診断支援) and 判定 were already refused
# outright in FORBIDDEN and stay so. Protocol and chart text the product quotes is not checked here (D-351).


@dataclass(frozen=True)
class ClaimTerm:
    """A Japanese word that is a device claim only in a claiming context. ``actor_only``: only an actor as subject
    makes it a claim (判断: 治験責任医師が患者の参加の可否を判断します is the product's own rule, not a claim)."""

    term: str
    allowed: tuple[str, ...] = ()
    actor_only: bool = False


CLAIMS_JA: tuple[ClaimTerm, ...] = (
    ClaimTerm("発見"),
    ClaimTerm("見つけ出"),
    # a study's enrolment forecast (feasibility) is a count, not a patient's outcome
    ClaimTerm(
        "予測",
        allowed=(r"(登録|組み入れ|無作為化|同意取得)(数の|の)?予測", r"予測(期間|される(登録|無作為化|同意取得))"),
    ),
    ClaimTerm("予後"),
    ClaimTerm("リスク", allowed=(r"バイアスのリスク", r"リスク・?オブ・?バイアス")),
    ClaimTerm("危険度"),
    ClaimTerm("未診断"),
    ClaimTerm(
        "スコア",
        # a named clinical scale (ECOG, DAS28, eGFR, NIHSS ...) entered by a person or computed by its published
        # formula for a criterion; and the character "_"
        allowed=(r"[A-Za-z][A-Za-z0-9-]*\s*(の)?スコア", r"アンダースコア", r"スコア定義"),
    ),
    ClaimTerm("検出", allowed=(r"検出(限界|下限|感度|日時)", r"未検出", r"検出され(ず|ない|なかった|ません)")),
    ClaimTerm("判断", actor_only=True),
)

CLAIM_ACTORS_JA: tuple[str, ...] = (
    "TrialBox",
    "本ソフトウェア",
    "本システム",
    "システム",
    "本製品",
    "本ツール",
    "AI",
    "ＡＩ",
    "人工知能",
    "モデル",
    "アルゴリズム",
)
CLAIM_PATIENTS_JA: tuple[str, ...] = ("患者", "被験者", "候補者", "対象者", "受診者", "症例")
CLAIM_WINDOW = 10

_SUBJECT = r"(?:が|は|により|による|によって|で|を用いて|を使って|を使い)"
_ACTOR = re.compile(r"(?<![A-Za-z])(?:" + "|".join(re.escape(a) for a in CLAIM_ACTORS_JA) + r")\s*" + _SUBJECT)
_PATIENT = re.compile("|".join(re.escape(p) for p in CLAIM_PATIENTS_JA))
_NEGATION = (
    r"(?:(?:は|を|も)?(?:行(?:いません|わず|わない|っていません)|しません|せず|しない|できません|できない|できなかった|さない|さず)"
    r"|ではありません|ではない|はしません)"
)
# a sentence ends at 。！？, a line end, or two spaces (on a page, where one element ends and the next begins)
_SENTENCE = re.compile(r"(?:[^。！？!?\n ]| (?! ))+[。！？!?]?")


def check_claims_ja(text: str, terms: Iterable[ClaimTerm] = CLAIMS_JA) -> list[Hit]:
    """Every Japanese device claim in ``text``: a term of :data:`CLAIMS_JA` in a claiming context. An empty list
    means no claim."""
    terms = tuple(terms)
    alt = "|".join(re.escape(t.term) for t in terms)
    # a negated term, with the terms that are its object (リスクを予測しません): what the product does not do
    negated = re.compile(r"(?:(?:" + alt + r")(?:を|は|も|の))*(?:" + alt + r")" + _NEGATION)
    hits: list[Hit] = []
    for sentence in _SENTENCE.findall(text):
        unnegated = negated.sub(lambda m: "　" * len(m.group(0)), sentence)
        for t in terms:
            if t.term not in unnegated:
                continue
            masked = unnegated
            for rx in t.allowed:
                masked = re.sub(rx, lambda m: "　" * len(m.group(0)), masked)
            for m in re.finditer(re.escape(t.term), masked):
                actor = any(a.end() <= m.start() for a in _ACTOR.finditer(masked))
                near = masked[max(0, m.start() - CLAIM_WINDOW) : m.end() + CLAIM_WINDOW]
                patient = not t.actor_only and _PATIENT.search(near) is not None
                if actor or patient:
                    ctx = sentence[max(0, m.start() - 30) : m.end() + 30]
                    hits.append(Hit(word=t.term, context=ctx.strip()))
    return hits


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
    text: str, words: Iterable[str] = FORBIDDEN, allowed: Iterable[str] = ALLOWED, *, claims: bool = True
) -> list[Hit]:
    """Every forbidden word in ``text`` after the allowed phrases are masked, and every Japanese device claim
    (:func:`check_claims_ja`; ``claims=False`` leaves them out). An empty list means the text is clean."""
    masked = text
    for phrase in allowed:
        masked = masked.replace(phrase, " ")
    hits: list[Hit] = []
    for word in words:
        for m in _pattern(word).finditer(masked):
            ctx = masked[max(0, m.start() - 30) : m.end() + 30].replace("\n", " ")
            hits.append(Hit(word=word, context=ctx.strip()))
    return hits + (check_claims_ja(masked) if claims else [])


def check_page(page: str, words: Iterable[str] = FORBIDDEN) -> list[Hit]:
    """:func:`check` on what a reader sees of an HTML page."""
    return check(visible_text(page), words)


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


def check_file(path: str, text: str, words: Iterable[str] = FORBIDDEN) -> list[Hit]:
    """:func:`check` on a file's text, or nothing for an exempt path (by design: the risk file names the hazard)."""
    return [] if exempt(path) else check(text, words)
