"""TrialBox's seven built-in forms (TB-PLAN-04 step 4, D-129), in ja, zh-TW and en.

``forms.csv`` is a REDCap data dictionary (API column names) with TrialBox's language columns, so the forms are read
by the same ``datacore.forms.read_dictionary`` as a site's own REDCap dictionary and export back to REDCap
unchanged. ``record_id`` (the screening number or pseudonym) is the record key, not an item. Adverse events are
free text with a severity chosen by a person: nothing is graded automatically.

D-396 (T-619b, STD-050, STD-051): an oncology study grades each AE by CTCAE, grade 1 to 5, and names the CTCAE version
it uses (5.0 or 6.0). The study picks the version when it adds the forms; the AE form then offers that one version and
every AE records it with its grade. In an oncology study the mild / moderate / severe choice stays on the form but is
no longer required (CDASH: ``AETOXGR`` or ``AESEV``). Other studies do not get the two CTCAE items. The AE term is kept
as written (CDASH ``AETERM``); MedDRA coding is the sponsor's or the data centre's, never TrialBox's.
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


#: the CTCAE versions a study may name (the AE form's ``ae_ctcae_version`` codes) -> what the pages show
CTCAE_VERSIONS: dict[str, str] = {"5": "CTCAE v5.0", "6": "CTCAE v6.0"}
CTCAE_FIELDS = ("ae_ctcae_grade", "ae_ctcae_version")


def ctcae_code(version: str) -> str:
    """``5``, ``5.0``, ``v5.0`` or ``CTCAE v5.0`` -> ``5``; "" for no version (not an oncology study). Anything else
    is refused (ValueError): a study names a version CTCAE has."""
    raw = (version or "").strip().lower()
    if not raw:
        return ""
    text = raw.removeprefix("ctcae").strip().removeprefix("v")
    code = text[:-2] if text.endswith(".0") else text
    if code not in CTCAE_VERSIONS:
        raise ValueError(f"the CTCAE version is one of {', '.join(CTCAE_VERSIONS.values())}")
    return code


def study_fields(ctcae: str = "") -> list[Field]:
    """The built-in fields of one study: with the CTCAE items narrowed to the study's version when it names one
    (an oncology study), without them otherwise."""
    code = ctcae_code(ctcae)
    out = []
    for f in fields():
        if f.name in CTCAE_FIELDS and not code:
            continue
        if f.name == "ae_ctcae_version":
            f.options = {code: f.options[code]}
            f.option_labels = {g: {code: o[code]} for g, o in f.option_labels.items()}
        if f.name == "ae_severity" and code:
            f.required = False
        out.append(f)
    return out


def builtin_questionnaires(study: str, ctcae: str = "") -> list[dict[str, Any]]:
    """The seven forms; ``ctcae`` names the study's CTCAE version (an oncology study, D-396), "" for none."""
    return questionnaires(study, study_fields(ctcae), record_field=RECORD_FIELD, titles=TITLES)


def ctcae_of(forms: list[dict[str, Any]]) -> str:
    """The CTCAE version a study's AE form records (``CTCAE v5.0``), or "" when it has no CTCAE grade."""
    for q in forms:
        for it in q.get("item", []):
            if it.get("linkId") == "ae_ctcae_version":
                codes = [str(o["valueCoding"]["code"]) for o in it.get("answerOption", []) if "valueCoding" in o]
                return ", ".join(CTCAE_VERSIONS.get(c, c) for c in codes)
    return ""
