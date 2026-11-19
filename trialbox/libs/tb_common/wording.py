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

# Japanese device claims (JP-4, card 10C-5, D-1228; the reasoning is docs/plan/intended-use-jp.md). Under the MHLW
# guideline a program is a device by what it says it does: finding, detecting or predicting disease, or giving a patient
# a risk, a score or a prognosis (case database No.74, No.243, as review 11 reads them). Finding trial CANDIDATES by
# a study's written criteria is the product's purpose and no such claim. So the rule refuses the claim, not the word,
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
# * 判断: a claim when the product, the system, the AI or a model is its nearest subject (AIが…判断; not
#   モデルが読み、人が判断します: CLAIM_PERSONS_JA). A judgement in the product's own words always has a person as
#   subject (医師が判断します); what a model does is 読み取り (D-1228).
#
# First the text is NFKC-normalised (half-width ﾘｽｸ, full-width ＡＩ), the term's allowed contexts are masked (named
# clinical scales, a lab's detection limit, バイアスのリスク, a study's enrolment forecast), and so is a real denial: a
# list of claim words with a negative verb that ends the clause (本製品は診断、予測、スコアリングを行いません). A
# double negative (発見しない日はない) is not a denial. A sentence ends at 。！？, a line end, or two spaces (on a page,
# where one element ends and the next begins). 診断 and 判定 stay refused outright in FORBIDDEN, and 疑い患者 joins
# them; a denial of them is masked too. Protocol and chart text the product quotes is not checked here (D-351).

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
CLAIM_PATIENTS_JA: tuple[str, ...] = ("患者", "被験者", "受診者", "候補者", "対象者", "症例", "個人")
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

_DENIABLE = sorted(
    {*CLAIM_OUTRIGHT_JA, *CLAIM_FIND_JA, *CLAIM_RATE_JA, *CLAIM_JUDGE_JA, "診断支援", "診断", "判定", "疑い患者"},
    key=len,
    reverse=True,
)
_ITEM = "(?:" + "|".join(re.escape(w) for w in _DENIABLE) + ")"
_NEG = (
    r"(?:いません|いたしません|わない|わず|しません|しない|せず|できません|できない|ではありません|ではない"
    r"|さない|さず|しておりません|しておらず)"
)
_END = r"(?=[。、．，！？!?\s」）)]|$|が[、,]|ので|ため)"
# a real denial: claim words (a list of them, or one as the object of the next) and a negative verb ending the clause
_DENIAL = re.compile(
    _ITEM + r"(?:(?:[、・,]|および|及び|と|や|を|は|も|の|など|等)*" + _ITEM + r")*(?:など|等)?(?:を|は|も)?(?:一切)?"
    r"(?:行|おこな)?" + _NEG + _END
)
_SUBJECT = r"\s*(?:が|は|により|による|によって|で|を用いて|を使って|を使い)"
_ACTORS = "(?<![A-Za-z])(?:" + "|".join(re.escape(a) for a in CLAIM_ACTORS_JA) + ")"
_ACTOR_SUBJECT = re.compile(_ACTORS + _SUBJECT)
_PERSON_SUBJECT = re.compile("(?:" + "|".join(re.escape(p) for p in CLAIM_PERSONS_JA) + ")" + _SUBJECT)
_ACTOR_BEFORE = _ACTORS + r"\s*(?:による|の|が|で)?\s*$"
_SENTENCE = re.compile(r"(?:[^。！？!?\n ]| (?! ))+[。！？!?]?")
_MASK = "　"


def _alt(words: Iterable[str]) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(w) for w in words))


_DISEASE = _alt(CLAIM_DISEASE_JA)
_EARLY = _alt(CLAIM_EARLY_JA)
_PATIENT = _alt(CLAIM_PATIENTS_JA)


def _blank(m: re.Match[str]) -> str:
    return _MASK * len(m.group(0))


def deny_masked_ja(text: str) -> str:
    """``text`` with every real denial of a claim word blanked: 本製品は診断、予測、スコアリングを行いません says what
    the product does not do. A double negative (発見しない日はない) is not a denial and stays."""
    return _DENIAL.sub(_blank, text)


def check_claims_ja(text: str) -> list[Hit]:
    """Every Japanese device claim in ``text`` (the rule above). An empty list means no claim."""
    text = deny_masked_ja(unicodedata.normalize("NFKC", text))
    hits: list[Hit] = []
    for sentence in _SENTENCE.findall(text):
        masked = sentence
        for patterns in CLAIM_ALLOWED_JA.values():
            for rx in patterns:
                masked = re.sub(rx, _blank, masked)

        def near(m: re.Match[str], rx: re.Pattern[str], s: str = masked) -> bool:
            return rx.search(s[max(0, m.start() - CLAIM_WINDOW) : m.end() + CLAIM_WINDOW]) is not None

        def hit(m: re.Match[str], word: str, s: str = sentence) -> None:
            hits.append(Hit(word=word, context=s[max(0, m.start() - 30) : m.end() + 30].strip()))

        for word in CLAIM_OUTRIGHT_JA:
            for m in re.finditer(re.escape(word), masked):
                hit(m, word)
        for word in CLAIM_FIND_JA:
            for m in re.finditer(re.escape(word), masked):
                if near(m, _DISEASE) or near(m, _EARLY):
                    hit(m, word)
        for word in CLAIM_RATE_JA:
            for m in re.finditer(re.escape(word), masked):
                if near(m, _PATIENT) or near(m, _DISEASE) or re.search(_ACTOR_BEFORE, masked[: m.start()]):
                    hit(m, word)
        for word in CLAIM_JUDGE_JA:
            for m in re.finditer(re.escape(word), masked):
                actors = [a.end() for a in _ACTOR_SUBJECT.finditer(masked, 0, m.start())]
                persons = [p.end() for p in _PERSON_SUBJECT.finditer(masked, 0, m.start())]
                if actors and (not persons or max(actors) > max(persons)):  # the nearest subject is the product
                    hit(m, word)
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
    if claims:  # a real denial of a claim word says what the product does not do (D-1228)
        masked = deny_masked_ja(unicodedata.normalize("NFKC", masked))
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
