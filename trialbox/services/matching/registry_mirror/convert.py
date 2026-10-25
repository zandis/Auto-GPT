"""ClinicalTrials.gov API v2 study record -> the trial dict the NCBI prompts expect (from the port's ``ctgov.py``,
without its live search).

The registry writes eligibility as Markdown with free-form headings ("Inclusion Criteria:", "Patients are excluded if
...:", "Key Exclusion Criteria"). NCBI's ``parse_criteria`` splits criteria on blank lines and drops lines that contain
"inclusion criteria"/"exclusion criteria", so :func:`split_criteria` returns one criterion per blank-line block.
"""

from __future__ import annotations

import re
from typing import Any

_EXCL = re.compile(
    r"^\W*(key\s+)?(exclusion criteria|exclusion|exclusions|non-?inclusion criteria)\b"
    r"|\b(are|is|will be)\s+(excluded|ineligible|not eligible)\b.*:\s*$",
    re.I,
)
_INCL = re.compile(
    r"^\W*(key\s+)?(inclusion criteria|inclusion|eligibility criteria)\b|\b(eligible|included)\b.*\b(if|when)\b.*:\s*$",
    re.I,
)
_BULLET = re.compile(r"^\s*(?:[*\-•+]|\d{1,3}[.)])\s+")
_INCL_HEADING = re.compile(r"^\W*(key\s+)?(inclusion|eligibility) criteria\W*$", re.I)


def _unescape(s: str) -> str:
    return re.sub(r"\\([<>*_\[\]()#~=+-])", r"\1", s)


def _blocks(lines: list[str]) -> str:
    """Bulleted lines -> one criterion per blank-line block; continuation lines are joined to their bullet."""
    items: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if _BULLET.match(line) and not raw.startswith(("    ", "\t")):
            items.append(_BULLET.sub("", line).strip())
        elif items and raw.startswith(("  ", "\t")):
            items[-1] += " " + _BULLET.sub("", line).strip()
        else:
            items.append(line.strip())
    return "\n\n".join(i for i in items if i)


def split_criteria(text: str) -> tuple[str, str]:
    """Registry eligibility text -> (inclusion, exclusion), each a blank-line separated list of criteria. Multi-arm
    trials repeat "Inclusion Criteria:" / "Exclusion Criteria:" per group; each heading switches the list."""
    lines = _unescape(text or "").splitlines()
    inc: list[str] = []
    exc: list[str] = []
    cur = inc
    for line in lines:
        stripped = line.strip()
        if _EXCL.search(stripped) and len(stripped) < 160:
            cur = exc
            continue
        if _INCL.search(stripped) and len(stripped) < 160:
            if cur is inc:
                continue
            if _INCL_HEADING.match(stripped) or stripped.endswith(":"):  # next arm group: back to inclusion
                cur = inc
                continue
        cur.append(line)
    return _blocks(inc), _blocks(exc)


def to_trial(study: dict[str, Any]) -> dict[str, Any]:
    p = study.get("protocolSection", {})
    ident = p.get("identificationModule", {})
    elig = p.get("eligibilityModule", {})
    inc, exc = split_criteria(elig.get("eligibilityCriteria", ""))
    interventions = [i.get("name", "") for i in p.get("armsInterventionsModule", {}).get("interventions", [])]
    conditions = p.get("conditionsModule", {}).get("conditions", [])
    demo = []
    if elig.get("minimumAge") or elig.get("maximumAge"):
        demo.append(f"Age {elig.get('minimumAge', 'N/A')} to {elig.get('maximumAge', 'N/A')}")
    if elig.get("sex") and elig.get("sex") != "ALL":
        demo.append(f"Sex: {elig['sex'].lower()}")
    if demo:  # structured registry fields the free text often omits
        inc = "\n\n".join(x for x in (inc, "; ".join(demo)) if x)
    return {
        "NCTID": ident.get("nctId", ""),
        "brief_title": ident.get("briefTitle", ""),
        "official_title": ident.get("officialTitle", ""),
        "phase": ", ".join(p.get("designModule", {}).get("phases", []) or []),
        "diseases_list": conditions,
        "drugs_list": [i for i in interventions if i],
        "brief_summary": p.get("descriptionModule", {}).get("briefSummary", ""),
        "inclusion_criteria": inc,
        "exclusion_criteria": exc,
        "status": p.get("statusModule", {}).get("overallStatus", ""),
        "countries": sorted(
            {loc.get("country", "") for loc in p.get("contactsLocationsModule", {}).get("locations", [])}
        ),
    }


def to_corpus_entry(trial: dict[str, Any]) -> dict[str, Any]:
    """Trial dict -> the corpus line the hybrid index takes (NCBI corpus.jsonl shape)."""
    text = "\n".join(x for x in (trial["brief_summary"], trial["inclusion_criteria"], trial["exclusion_criteria"]) if x)
    return {"_id": trial["NCTID"], "title": trial["brief_title"], "text": text, "metadata": trial}
