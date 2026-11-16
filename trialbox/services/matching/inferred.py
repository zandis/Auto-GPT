"""F6 of the integrator's root-cause review of the P1b run (#639, 2026-11-16), D-985: a note exclusion decided by
INFERRING a diagnosis. On jmed both models agreed, four times, that a patient "has a history of hypertension" from
"降圧薬は服用しています" (takes an antihypertensive) or "has a history of diabetes" from metformin with an HbA1c, and
the judge's own reason said there was no stated history; sigir's NCT01784523 counted ACR criteria into SLE.
``both_agree`` does not protect against a shared inference.

An exclusion's "present" stands only on a quote that states the condition: one that names neither the criterion's
condition nor any diagnosis word (a drug, a dose, a lab value, findings counted into a diagnosis) is an inference, and
goes to review. The quote is the verified span (CAS-16), never the model's reason, which claimed a diagnosis on
every one of these.
"""

from __future__ import annotations

import re

_DIAGNOSIS = re.compile(
    r"症|病|疾患|既往|併存|診断|合併|診斷|病史|ICD|history of|diagnos|\bknown\b|comorbid|syndrome|disease|disorder",
    re.IGNORECASE,
)
_GENERIC = re.compile(r"既往|患者|がある|のある|の|歴|病史|有|曾|者|ある|いる|患|史")
_CJK_RUN = re.compile(r"[㐀-䶿一-鿿぀-ヿ]+")
_STOP = {"patient", "patients", "history", "with", "have", "has", "had", "known", "current", "prior", "previous",
         "does", "the", "any", "who", "that", "this", "subject", "subjects", "diagnosis", "diagnosed"}  # fmt: skip


def names_condition(quote: str, criterion: str) -> bool:
    """The quote names the criterion's condition: three of its Han / kana characters in a row (its generic words
    removed: 既往, 患者, がある ...), or the first five letters of one of its English words ("diabetes" finds
    "diabetic")."""
    q = quote or ""
    for run in _CJK_RUN.findall(_GENERIC.sub(" ", criterion or "")):
        if len(run) >= 3 and any(run[i : i + 3] in q for i in range(len(run) - 2)):
            return True
    words = {w.lower() for w in re.findall(r"[A-Za-z]{5,}", criterion or "")} - _STOP
    low = q.lower()
    return any(w[:5] in low for w in words)


def inferred(quote: str, criterion: str) -> bool:
    """The quote states no diagnosis: it names neither the criterion's condition nor any diagnosis word (a treatment,
    a dose, a value, findings the model counted into a diagnosis). A "present" on it is an inference."""
    q = quote or ""
    return not _DIAGNOSIS.search(q) and not names_condition(q, criterion)
