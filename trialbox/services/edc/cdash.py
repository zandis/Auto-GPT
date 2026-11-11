"""CDASH tags for eCRF items (D-160).

Each item of a study's eCRF can carry a CDASH tag (``DOMAIN.VARIABLE``, and for findings the test code, as in
``VS.VSORRES`` with ``WEIGHT``). The tag is written into the ODM export (``ItemDef/@SDSVarName`` and an ``Alias``
with ``Context="CDASH"``), so a sponsor or another EDC can read what the item is without our field names.

:func:`suggest` proposes a tag and a record source from the field's name and label (English, Japanese and
Traditional Chinese words). It is only a suggestion: the coordinator checks every row of the map before drafts are
built, and the PI's study team owns the map (it is configuration, validated at OQ).

D-396 (T-619b, STD-063): the coverage adds AE (with the CTCAE grade ``AETOXGR``), IE and DS. :data:`BUILTIN` tags the
built-in forms' items, and :func:`ie_rows` and :func:`ds_rows` turn the screening log's steps into CDASH IE rows (the
criterion a screen failure did not meet) and DS rows (consent, screen failure, completion, withdrawal), the one CDISC
content TrialBox holds first-hand. EX, SDTM datasets, Define-XML and CDISC Controlled Terminology files are out of
scope; the DS and IE values below use the CDISC submission values of the NCI codelists named at each one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# CDASH v2 variables TrialBox can draft from a hospital record. A variable not listed here may still be typed by hand
# (the map accepts any ``DOMAIN.VARIABLE`` of the right shape); these are the ones the suggestion knows.
VARIABLES: dict[str, str] = {
    "DM.BRTHDAT": "Birth date",
    "DM.SEX": "Sex",
    "VS.VSORRES": "Vital sign result",
    "VS.VSDAT": "Vital signs date",
    "LB.LBORRES": "Lab result",
    "LB.LBDAT": "Lab collection date",
    "MH.MHTERM": "Medical history term",
    "MH.MHOCCUR": "Medical history occurrence",
    "MH.MHSTDAT": "Medical history start date",
    "CM.CMTRT": "Concomitant medication",
    "CM.CMOCCUR": "Concomitant medication occurrence",
    "CM.CMSTDAT": "Concomitant medication start date",
    "SV.VISDAT": "Visit date",
    "AE.AETERM": "Reported term for the adverse event",
    "AE.AESTDAT": "Adverse event start date",
    "AE.AEENDAT": "Adverse event end date",
    "AE.AESER": "Serious event",
    "AE.AESEV": "Severity",
    "AE.AETOXGR": "Standard toxicity grade (CTCAE)",
    "AE.AEOUT": "Outcome of the adverse event",
    "AE.AEREL": "Causality",
    "IE.IECAT": "Inclusion or exclusion category",
    "IE.IETESTCD": "Criterion short name",
    "IE.IETEST": "Criterion",
    "IE.IEORRES": "Criterion met (Y or N)",
    "IE.IEDAT": "Date of the eligibility assessment",
    "DS.DSCAT": "Category for disposition event",
    "DS.DSDECOD": "Standardized disposition term",
    "DS.DSTERM": "Reported term for the disposition event",
    "DS.DSSTDAT": "Disposition event start date",
}

#: the built-in forms' items with their CDASH tag (D-396). ``ae_ctcae_version`` has no CDASH variable of its own: in
#: SDTM the grading version is a trial summary parameter (``TS.TSPARMCD = TOXGRV``), so it is written as an alias.
BUILTIN: dict[str, str] = {
    "sl_date": "IE.IEDAT",
    "ic_date": "DS.DSSTDAT",
    "wd_date": "DS.DSSTDAT",
    "wd_reason": "DS.DSDECOD",
    "vs_date": "SV.VISDAT",
    "vs_weight": "VS.VSORRES",
    "ae_term": "AE.AETERM",
    "ae_onset": "AE.AESTDAT",
    "ae_end": "AE.AEENDAT",
    "ae_serious": "AE.AESER",
    "ae_severity": "AE.AESEV",
    "ae_ctcae_grade": "AE.AETOXGR",
    "ae_outcome": "AE.AEOUT",
    "ae_related": "AE.AEREL",
}
TOXGRV = "TS.TOXGRV"  # the alias of the CTCAE version item

# DS: DSCAT from the category codelist (C74558), DSDECOD from completion / reason for non-completion (C66727) or
# the protocol milestones (C114118)
DS_EVENT, DS_MILESTONE = "DISPOSITION EVENT", "PROTOCOL MILESTONE"
#: the built-in withdrawal form's reason codes (``wd_reason``) -> DSDECOD
WITHDRAWAL_DECOD: dict[str, str] = {"1": "WITHDRAWAL BY SUBJECT", "2": "PHYSICIAN DECISION", "3": "ADVERSE EVENT",
                                    "4": "LOST TO FOLLOW-UP", "5": "DEATH", "6": "OTHER"}  # fmt: skip
#: the items of the two CDASH groups the export writes, in order: (variable, ODM data type)
IE_ITEMS: tuple[tuple[str, str], ...] = (("IECAT", "text"), ("IETESTCD", "text"), ("IETEST", "text"),
                                         ("IEORRES", "text"), ("IEDAT", "date"))  # fmt: skip
DS_ITEMS: tuple[tuple[str, str], ...] = (("DSCAT", "text"), ("DSDECOD", "text"), ("DSTERM", "text"),
                                         ("DSSTDAT", "date"))  # fmt: skip
_TAG = re.compile(r"^[A-Z]{2}\.[A-Z][A-Z0-9]{1,7}$")
_TEST = re.compile(r"^[A-Z][A-Z0-9]{0,7}$")


def sds_name(var: str) -> str:
    """The SDTM variable of a CDASH name, or "" when the CDASH name is not one: CDASH dates and times (``BRTHDAT``,
    ``VSDAT``, ``VISDAT``, ``--TIM``) become ``--DTC`` in SDTM, so they carry only the CDASH alias (STD-062)."""
    return "" if re.search(r"(DAT|TIM)$", var) else var


def ie_category(criterion: str) -> str:
    """``INCLUSION`` or ``EXCLUSION`` from a criterion id as the rulesets name them (``GZQO-INC-02``,
    ``GZQO-EXC-06``, ``I3``, ``E1``), else "" (not known from the id)."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", criterion.upper()) if p]
    for p in reversed(parts):
        if re.fullmatch(r"(INCLUSION|INCL?|IN|I)\d*", p):
            return "INCLUSION"
        if re.fullmatch(r"(EXCLUSION|EXCL?|EX|E)\d*", p):
            return "EXCLUSION"
    return ""


def ie_testcd(criterion: str) -> str:
    """The CDASH short name (8 characters at most) of a criterion id: ``INCL02`` / ``EXCL06`` when the id says the
    category and ends in a number, else the id's letters and digits cut to 8."""
    cat = ie_category(criterion)
    num = re.search(r"(\d+)$", criterion)
    if cat and num:
        return f"{cat[:3]}L{int(num.group(1)):02d}"[:8]
    return (re.sub(r"[^A-Z0-9]", "", criterion.upper()) or "CRIT")[:8]


def ie_rows(steps: list[dict[str, Any]]) -> list[dict[str, str]]:
    """CDASH IE of one subject: one row for the criterion its screen failure did not meet (D-387 keeps it on the
    step). An inclusion criterion not met is ``IEORRES = N``, an exclusion criterion met is ``Y`` (CDASH IE collects
    only the criteria not met). A screen failure that names no criterion has no IE row (its DS row stands)."""
    last = steps[-1] if steps else {}
    crit = str(last.get("criterion") or "").strip()
    if last.get("new") != "screen_fail" or not crit:
        return []
    cat = ie_category(crit)
    version = str(last.get("criteria_version") or "").strip()
    return [
        {
            "IECAT": cat,
            "IETESTCD": ie_testcd(crit),
            "IETEST": f"{crit} (v{version})" if version else crit,
            "IEORRES": {"INCLUSION": "N", "EXCLUSION": "Y"}.get(cat, ""),
            "IEDAT": str(last.get("on_day") or ""),
        }
    ]


def ds_rows(steps: list[dict[str, Any]]) -> list[dict[str, str]]:
    """CDASH DS of one subject from its standing steps, in order: consent (a protocol milestone), and the end of the
    subject's part (screen failure, completion, withdrawal with its reason) as the disposition event."""
    out: list[dict[str, str]] = []
    for st in steps:
        new, day, reason = str(st.get("new") or ""), str(st.get("on_day") or ""), str(st.get("reason") or "")
        if new == "consented":
            out.append({"DSCAT": DS_MILESTONE, "DSDECOD": "INFORMED CONSENT OBTAINED",
                        "DSTERM": "INFORMED CONSENT OBTAINED", "DSSTDAT": day})  # fmt: skip
        elif new in ("screen_fail", "completed", "withdrawn"):
            decod = {"screen_fail": "SCREEN FAILURE", "completed": "COMPLETED"}.get(new)
            decod = decod or WITHDRAWAL_DECOD.get(reason, "OTHER")
            term = decod if new != "screen_fail" or not reason else f"SCREEN FAILURE: {reason.replace('_', ' ')}"
            out.append({"DSCAT": DS_EVENT, "DSDECOD": decod, "DSTERM": term.upper(), "DSSTDAT": day})
    return out


def valid_tag(tag: str) -> bool:
    return bool(_TAG.match(tag))


def valid_test(test: str) -> bool:
    return test == "" or bool(_TEST.match(test))


@dataclass(frozen=True)
class Hint:
    """What a field looks like it holds: the CDASH tag and test, and the record source to draft it from."""

    tag: str
    test: str = ""
    source: str = "none"  # patient | observation | condition | medication | note | none
    what: str = ""  # birth_date, sex, value, date, presence, term, start
    codes: tuple[str, ...] = ()
    system: str = ""
    unit: str = ""


LOINC = "http://loinc.org"
# (pattern over "name label", hint). Order matters: the first match wins. Words in en, ja and zh-TW.
_RULES: tuple[tuple[str, Hint], ...] = (
    (r"birth|\bdob\b|brthd|生年月日|出生日期|出生", Hint("DM.BRTHDAT", source="patient", what="birth_date")),
    (r"\bsex\b|gender|性別", Hint("DM.SEX", source="patient", what="sex")),
    (r"weight|体重|體重", Hint("VS.VSORRES", "WEIGHT", "observation", "value", ("29463-7",), LOINC, "kg")),
    (r"height|身長|身高", Hint("VS.VSORRES", "HEIGHT", "observation", "value", ("8302-2",), LOINC, "cm")),
    (
        r"systolic|\bsbp\b|収縮期|收縮壓",
        Hint("VS.VSORRES", "SYSBP", "observation", "value", ("8480-6",), LOINC, "mm[Hg]"),
    ),
    (
        r"diastolic|\bdbp\b|拡張期|舒張壓",
        Hint("VS.VSORRES", "DIABP", "observation", "value", ("8462-4",), LOINC, "mm[Hg]"),
    ),
    (r"hba1c|a1c|糖化", Hint("LB.LBORRES", "HBA1C", "observation", "value", ("4548-4",), LOINC, "%")),
    (r"creat|クレアチニン|肌酸酐", Hint("LB.LBORRES", "CREAT", "observation", "value", ("2160-0",), LOINC, "mg/dL")),
    (r"urate|uric|尿酸", Hint("LB.LBORRES", "URATE", "observation", "value", ("3084-1",), LOINC, "mg/dL")),
    (r"visit.?d|visdat|来院日|受診日|訪視日", Hint("SV.VISDAT")),
    (r"medic|drug|\bcm_|併用薬|薬剤|用藥|藥物", Hint("CM.CMOCCUR", source="medication", what="presence")),
    (r"history|diagnos|\bmh_|既往|病歴|診斷|病史", Hint("MH.MHOCCUR", source="condition", what="presence")),
    # D-396: AE items are never drafted from the record (source none); the tag tells the sponsor what the item is
    (r"ctcae|toxicity grade|\bae_?grade|aetoxgr|グレード|等級", Hint("AE.AETOXGR")),
    (r"\bae_?term\b|aeterm", Hint("AE.AETERM")),
)


def suggest(name: str, label: str) -> Hint | None:
    """A hint for a field, or None. Codes for a diagnosis or a medicine are never guessed: the coordinator types them
    (an empty code list is refused by the map's check, so nothing is drafted from a guess)."""
    text = f"{name} {label}".lower()
    for pattern, hint in _RULES:
        if re.search(pattern, text):
            return hint
    return None
