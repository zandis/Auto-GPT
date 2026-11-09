"""CDASH tags for eCRF items (D-160).

Each item of a study's eCRF can carry a CDASH tag (``DOMAIN.VARIABLE``, and for findings the test code, as in
``VS.VSORRES`` with ``WEIGHT``). The tag is written into the ODM export (``ItemDef/@SDSVarName`` and an ``Alias``
with ``Context="CDASH"``), so a sponsor or another EDC can read what the item is without our field names.

:func:`suggest` proposes a tag and a record source from the field's name and label (English, Japanese and
Traditional Chinese words). It is only a suggestion: the coordinator checks every row of the map before drafts are
built, and the PI's study team owns the map (it is configuration, validated at OQ).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
}
_TAG = re.compile(r"^[A-Z]{2}\.[A-Z][A-Z0-9]{1,7}$")
_TEST = re.compile(r"^[A-Z][A-Z0-9]{0,7}$")


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
)


def suggest(name: str, label: str) -> Hint | None:
    """A hint for a field, or None. Codes for a diagnosis or a medicine are never guessed: the coordinator types them
    (an empty code list is refused by the map's check, so nothing is drafted from a guess)."""
    text = f"{name} {label}".lower()
    for pattern, hint in _RULES:
        if re.search(pattern, text):
            return hint
    return None
