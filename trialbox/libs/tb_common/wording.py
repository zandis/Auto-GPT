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

``LATER`` holds the rest of the TB-IU-01 §2 list (診断, 判定, "diagnosis" and others). Card T-116 makes the walk
check them on every page in every role; until then :func:`check` takes them only when asked.
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
)

# The rest of TB-IU-01 §2, for card T-116 (every page, every role, reports and mail).
LATER: tuple[str, ...] = (
    "診断",
    "判定",
    "対象外",
    "見逃し",
    "診斷",
    "diagnosis",
    "abnormal",
    "risk score",
    "AI decides",
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


def check(text: str, words: Iterable[str] = FORBIDDEN, allowed: Iterable[str] = ALLOWED) -> list[Hit]:
    """Every forbidden word in ``text`` after the allowed phrases are masked. An empty list means the text is clean."""
    masked = text
    for phrase in allowed:
        masked = masked.replace(phrase, " ")
    hits: list[Hit] = []
    for word in words:
        for m in _pattern(word).finditer(masked):
            ctx = masked[max(0, m.start() - 30) : m.end() + 30].replace("\n", " ")
            hits.append(Hit(word=word, context=ctx.strip()))
    return hits


def check_page(page: str, words: Iterable[str] = FORBIDDEN) -> list[Hit]:
    """:func:`check` on what a reader sees of an HTML page."""
    return check(visible_text(page), words)
