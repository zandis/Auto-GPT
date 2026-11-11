"""Why a criterion came out as it did, as a closed set of codes (TB-PLAN-03 step 3, D-118).

Every ``Evidence.reason`` on a candidate row is one of :class:`Reason`, never free text: the console, the PDFs and
the mails translate the code (catalogue key ``reason.<code>``), so no English internal token or model sentence reaches
a Japanese or Chinese clinical page, and no endpoint error text reaches a report (Fable review 2026-11-08, findings 6
and 10). The engines keep their own detailed strings internally (the cascade's stage log compares them);
:func:`code_of` maps them at the boundary.
"""

from __future__ import annotations

from enum import StrEnum


class Reason(StrEnum):
    CODED = "coded"  # decided by the coded records (a matching or failing value)
    NOTE = "note"  # decided by the notes: both models (or the one model) quoted the record
    DATA_GAP = "data_gap"  # no value / no record in the window
    UNKNOWN_KEPT = "unknown_kept"  # an exclusion with no value: not excluded, a person checks (FEAS D-18)
    NO_NOTES = "no_notes"  # no note in the window to read
    NOT_MENTIONED = "not_mentioned"  # the notes in the window were searched and never mention it
    CODE_OUTSIDE_LIST = "code_outside_list"  # coded inside the grouper's family, outside its list (D-113)
    UNKNOWN_CODE_SYSTEM = "unknown_code_system"  # a record coded in a system the mapping does not know (D-130)
    PROPOSED_FACT = "proposed_fact"  # a fact read from a chart that a person has not confirmed yet (D-135)
    SUSPECTED_DIAGNOSIS = "suspected_diagnosis"  # a diagnosis recorded as suspected (疑い, provisional; D-142)
    ABSTAINED = "abstained"  # the model said it cannot tell from the notes
    QUOTE_NOT_FOUND = "quote_not_found"  # the model's quote is not in the notes
    VERIFIER_QUOTE_MISSING = "verifier_quote_missing"  # the second model's quote is not in the notes
    DISAGREE = "disagree"  # the two models gave different answers
    LOW_CONFIDENCE = "low_confidence"  # the answer was below the minimum confidence
    MODEL_DOWN = "model_down"  # a model did not answer (outage, timeout, out of schema)
    REFUSED = "refused"  # the gateway refused the call (policy)
    HUMAN = "human"  # a person decides this criterion
    NOT_EVALUATED = "not_evaluated"  # not judged on this run (budget, not sampled, no judge)
    NOT_IN_SNAPSHOT = "not_in_snapshot"  # the patient is not in this snapshot of the records
    CHECK_DATES = "check_dates"  # deceased or not yet born at the screening date by the records (D-142)
    DERIVED_MISSING_INPUT = "derived_missing_input"  # a score lacks an input at the visit (D-149)
    DERIVED_UNIT = "derived_unit"  # a score's input has a unit the formula cannot use (D-149)
    # a lab row's unit cannot be used: not the lookup's at ingest (R-31, D-215), or not the criterion's and no tested
    # conversion (D-275): no value, unknown
    UNIT_MISMATCH = "unit_mismatch"
    UNKNOWN_VALUE = "unknown_value"  # a lab result that is not a readable number ("see note", 陰性; D-142, D-215)
    ORDER_DATES_MISSING = "order_dates_missing"  # a medicine order with no end date, or no date at all (D-275)
    RULES_CHANGED = "rules_changed"  # an approved answer the current safety rules do not confirm (D-275)
    # the model's quote is a sentence written as an instruction to a model (the guard's screen, T-606, D-359)
    PLANTED_INSTRUCTION = "planted_instruction"


CODES = frozenset(r.value for r in Reason)

# the minimum confidence for a decided note answer: below it the answer is not used (unknown, a person looks)
MIN_CONFIDENCE = 0.5

_RULES: tuple[tuple[tuple[str, ...], Reason], ...] = (
    (("not in the snapshot", "not_in_snapshot"), Reason.NOT_IN_SNAPSHOT),
    (("verifier's quote", "verifier quote"), Reason.VERIFIER_QUOTE_MISSING),
    (("disagree",), Reason.DISAGREE),
    (("unavailable", "did not answer", "swap", "wake check", "model_down"), Reason.MODEL_DOWN),
    (("gateway refused", "refused"), Reason.REFUSED),
    (("quote_not_found", "insufficient", "quote not found"), Reason.QUOTE_NOT_FOUND),
    (("zero hits", "absence"), Reason.NOT_MENTIONED),
    (("abstain", "s2b below", "not coded and not found"), Reason.ABSTAINED),
    (("low_confidence", "low confidence"), Reason.LOW_CONFIDENCE),
    (("human", "s5 reviewer"), Reason.HUMAN),
    (("no note", "no notes"), Reason.NO_NOTES),
    (("not evaluated", "not sampled", "unprocessed", "not judged", "no judge"), Reason.NOT_EVALUATED),
    (("unknown_kept", "unknown kept"), Reason.UNKNOWN_KEPT),
    (("unknown code system", "unknown_code_system"), Reason.UNKNOWN_CODE_SYSTEM),
    (("proposed_fact", "proposed fact"), Reason.PROPOSED_FACT),
    (("derived_unit",), Reason.DERIVED_UNIT),
    (("order_dates_missing",), Reason.ORDER_DATES_MISSING),
    (("rules_changed",), Reason.RULES_CHANGED),
    (("derived_missing_input",), Reason.DERIVED_MISSING_INPUT),
    (("unit_mismatch", "unit mismatch"), Reason.UNIT_MISMATCH),
    (("unknown_value", "unreadable value"), Reason.UNKNOWN_VALUE),
    (("no value", "no record", "not compiled", "index_absent", "data_gap", "index condition absent"), Reason.DATA_GAP),
    (("matching record", "failing value", "index rescued"), Reason.CODED),
)


# what each code says to a clinician, in the three page languages (the console, the reports and the mails use these)
LABELS: dict[str, dict[str, str]] = {
    "coded": {"en": "from the coded records", "ja": "コード化された記録から", "zh-TW": "依據結構化紀錄"},
    "note": {"en": "from the notes (quoted)", "ja": "記録の文章から（引用あり）", "zh-TW": "依據病歷文字（附引文）"},
    "data_gap": {"en": "no value in the period", "ja": "期間内に値なし", "zh-TW": "期間內無數值"},
    "unknown_kept": {
        "en": "no value recorded: not excluded, please check",
        "ja": "値の記録なし：除外せず、確認してください",
        "zh-TW": "無紀錄數值：未排除，請確認",
    },
    "no_notes": {"en": "no notes in the period", "ja": "期間内に記録の文章なし", "zh-TW": "期間內無病歷文字"},
    "not_mentioned": {"en": "not mentioned in the notes", "ja": "記録の文章に記載なし", "zh-TW": "病歷文字未提及"},
    "code_outside_list": {
        "en": "a code of this family that the list does not hold",
        "ja": "この分類の、一覧にないコード",
        "zh-TW": "屬於此類別但不在清單中的代碼",
    },
    "unknown_code_system": {
        "en": "a record coded in a system TrialBox cannot read: please check",
        "ja": "TrialBox が読めないコード体系の記録あり：確認してください",
        "zh-TW": "有以無法辨識的代碼系統記錄的資料：請確認",
    },
    "proposed_fact": {
        "en": "a fact read from a chart, not yet confirmed: please check",
        "ja": "カルテから読み取った未確認の情報あり：確認してください",
        "zh-TW": "有從病歷讀取、尚未確認的資料：請確認",
    },
    "suspected_diagnosis": {
        "en": "a diagnosis recorded as suspected, not confirmed: please check",
        "ja": "疑い病名として記録された診断あり（確定ではない）：確認してください",
        "zh-TW": "有記錄為疑似、尚未確診的診斷：請確認",
    },
    "abstained": {"en": "the notes do not say", "ja": "記録の文章からは判断できない", "zh-TW": "病歷文字無法判斷"},
    "quote_not_found": {
        "en": "the quoted text was not found in the notes",
        "ja": "引用が記録の文章に見つからない",
        "zh-TW": "引文不在病歷文字中",
    },
    "verifier_quote_missing": {
        "en": "the second check's quote was not found in the notes",
        "ja": "二次確認の引用が記録の文章に見つからない",
        "zh-TW": "第二次確認的引文不在病歷文字中",
    },
    "disagree": {
        "en": "the two checks differ: please look",
        "ja": "2回の確認が一致しない：確認してください",
        "zh-TW": "兩次確認結果不同：請查看",
    },
    "low_confidence": {
        "en": "not certain enough: please look",
        "ja": "確度が低い：確認してください",
        "zh-TW": "把握度不足：請查看",
    },
    "model_down": {"en": "not checked (system busy)", "ja": "未確認（システム混雑）", "zh-TW": "未確認（系統忙碌）"},
    "refused": {
        "en": "not checked (blocked by policy)",
        "ja": "未確認（規則により停止）",
        "zh-TW": "未確認（依規則停止）",
    },
    "human": {"en": "a person decides", "ja": "担当者が判断", "zh-TW": "由人員判斷"},
    "not_evaluated": {"en": "not checked on this run", "ja": "今回は未確認", "zh-TW": "本次未確認"},
    "not_in_snapshot": {
        "en": "not in this copy of the records",
        "ja": "今回の記録の写しに含まれない",
        "zh-TW": "不在本次紀錄副本中",
    },
    "check_dates": {
        "en": "the records give a death or birth date that rules out this date: please check the dates",
        "ja": "記録上の死亡日または生年月日ではこの日付に該当しない：日付を確認してください",
        "zh-TW": "紀錄中的死亡日期或出生日期與此日期不符：請確認日期",
    },
    "derived_missing_input": {
        "en": "the score cannot be computed: an input is missing at that visit",
        "ja": "スコアを計算できない：その受診日の入力値が不足",
        "zh-TW": "無法計算分數：該次就診缺少輸入值",
    },
    "derived_unit": {
        "en": "the score cannot be computed: an input has a unit that cannot be used, please check",
        "ja": "スコアを計算できない：入力値の単位が使用できないため確認してください",
        "zh-TW": "無法計算分數：輸入值的單位無法使用，請確認",
    },
    "unit_mismatch": {
        "en": "a result's unit does not fit the test or the criterion: not used, please check",
        "ja": "検査結果の単位がこの判定に使えない（検査または基準の単位と異なる）：使用せず、確認してください",
        "zh-TW": "檢驗結果的單位無法用於此判定（與檢驗或條件的單位不同）：未使用，請確認",
    },
    "unknown_value": {
        "en": "a result that is not a number: not used, please check",
        "ja": "数値として読めない結果あり：使用せず、確認してください",
        "zh-TW": "有無法讀成數值的結果：未使用，請確認",
    },
    "order_dates_missing": {
        "en": "a medicine order has no end date or no date: the duration is not known, please check",
        "ja": "処方に終了日または日付の記録なし：投与期間が不明のため確認してください",
        "zh-TW": "處方沒有結束日期或沒有日期：用藥期間不明，請確認",
    },
    "rules_changed": {
        "en": "the approved check and the current safety rules give different answers: please check",
        "ja": "承認済みの判定と現在の安全ルールの結果が異なる：確認してください",
        "zh-TW": "已核准的判定與目前的安全規則結果不同：請確認",
    },
}


def label(code: str | None, lang: str = "en") -> str:
    """The clinician's words for a code (English for an unknown language; the code itself only if unknown)."""
    if not code:
        return ""
    by = LABELS.get(str(code))
    if by is None:
        mapped = code_of(str(code))
        by = LABELS.get(mapped or "")
    if by is None:
        return ""
    return by.get(lang) or by.get(lang.split("-", maxsplit=1)[0]) or by["en"]


def code_of(text: str | None, verdict: str | None = None, quoted: bool = False) -> str | None:
    """The :class:`Reason` code for an engine's reason string. A code passes through; a decided answer whose string
    says nothing known is ``note`` when it carries a quote, else ``coded``; an open one is ``data_gap``."""
    t = (text or "").strip()
    if t in CODES:
        return t
    low = t.lower()
    for keys, code in _RULES:
        if any(k in low for k in keys):
            return code.value
    if verdict in ("pass", "fail"):
        return (Reason.NOTE if quoted else Reason.CODED).value if t or quoted else None
    if verdict in ("unknown",):
        return Reason.DATA_GAP.value if t else None
    if verdict == "pending_human":
        return Reason.HUMAN.value
    return None


__all__ = ["CODES", "LABELS", "MIN_CONFIDENCE", "Reason", "code_of", "label"]
