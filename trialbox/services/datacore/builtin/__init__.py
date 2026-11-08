"""TrialBox's seven built-in forms (TB-PLAN-04 step 4, D-129), in ja, zh-TW and en.

``forms.csv`` is a REDCap data dictionary (API column names) with TrialBox's language columns, so the forms are read
by the same ``datacore.forms.read_dictionary`` as a site's own REDCap dictionary and export back to REDCap
unchanged. ``record_id`` (the screening number or pseudonym) is the record key, not an item. Adverse events are
free text with a severity chosen by a person: nothing is graded automatically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from datacore.forms import Field, questionnaires, read_dictionary

ORIGIN = "builtin"
RECORD_FIELD = "record_id"
TITLES: dict[str, dict[str, str]] = {
    "tb_screening_log": {"en": "Screening log", "ja": "スクリーニング記録", "zh-TW": "篩選紀錄"},
    "tb_consent": {"en": "Consent", "ja": "同意", "zh-TW": "知情同意"},
    "tb_enrolment": {"en": "Enrolment", "ja": "登録", "zh-TW": "收案"},
    "tb_visit": {"en": "Visit", "ja": "来院", "zh-TW": "訪視"},
    "tb_adverse_event": {"en": "Adverse event", "ja": "有害事象", "zh-TW": "不良事件"},
    "tb_deviation": {"en": "Deviation", "ja": "逸脱", "zh-TW": "偏差"},
    "tb_withdrawal": {"en": "Withdrawal", "ja": "中止", "zh-TW": "退出"},
}


def fields() -> list[Field]:
    return read_dictionary((Path(__file__).parent / "forms.csv").read_text(encoding="utf-8"))


def builtin_questionnaires(study: str) -> list[dict[str, Any]]:
    return questionnaires(study, fields(), record_field=RECORD_FIELD, titles=TITLES)
