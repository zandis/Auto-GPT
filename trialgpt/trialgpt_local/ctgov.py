"""Live mode: candidate trials from ClinicalTrials.gov API v2 (the registry trialgpt.app also searches), converted to
the trial dict the NCBI prompts expect.

The registry writes eligibility as Markdown with free-form headings ("Inclusion Criteria:", "Patients are excluded if
...:", "Key Exclusion Criteria"). NCBI's ``parse_criteria`` splits criteria on blank lines and drops lines that contain
"inclusion criteria"/"exclusion criteria", so :func:`split_criteria` returns one criterion per blank-line block.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from trialgpt_local.config import settings

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
FIELDS = (
    "NCTId,BriefTitle,OfficialTitle,Condition,Keyword,InterventionName,BriefSummary,EligibilityCriteria,Phase,"
    "OverallStatus,EnrollmentCount,MinimumAge,MaximumAge,Sex,LocationCountry"
)


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
    """Registry eligibility text -> (inclusion, exclusion), each a blank-line separated list of criteria."""
    lines = _unescape(text or "").splitlines()
    inc: list[str] = []
    exc: list[str] = []
    cur = inc
    for line in lines:
        stripped = line.strip()
        if _EXCL.search(stripped) and len(stripped) < 160:
            cur = exc
            continue
        if _INCL.search(stripped) and len(stripped) < 160 and cur is inc:
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


MIN_COND_HITS = 10


def search(
    conditions: list[str],
    *,
    per_condition: int = 50,
    max_conditions: int = 8,
    recruiting_only: bool = True,
    country: str | None = None,
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Candidate pool: the registry's own search for each of the top keywords (by priority), de-duplicated.

    ``query.cond`` matches a phrase against the conditions field strictly ("progressive dysphagia" finds 3 studies,
    "dysphagia" 50+), so a keyword with fewer than ``MIN_COND_HITS`` hits is also run as a full-text ``query.term``
    search; the hybrid ranking that follows orders the pool."""
    client = http or httpx.Client(timeout=60)
    seen: dict[str, dict[str, Any]] = {}
    for cond in conditions[:max_conditions]:
        for field in ("query.cond", "query.term"):
            params: dict[str, Any] = {field: cond, "pageSize": per_condition, "format": "json"}
            if recruiting_only:
                params["filter.overallStatus"] = "RECRUITING|NOT_YET_RECRUITING"
            if country:
                params["query.locn"] = country
            r = client.get(f"{settings().ctgov_base}/studies", params=params)
            r.raise_for_status()
            studies = r.json().get("studies", [])
            for s in studies:
                t = to_trial(s)
                if t["NCTID"] and t["NCTID"] not in seen and (t["inclusion_criteria"] or t["exclusion_criteria"]):
                    seen[t["NCTID"]] = t
            if len(studies) >= MIN_COND_HITS:
                break
    return list(seen.values())


def get(nct_ids: list[str], http: httpx.Client | None = None) -> dict[str, dict[str, Any]]:
    """Fetch specific trials (e.g. the ones trialgpt.app returned) for cross-evaluation."""
    client = http or httpx.Client(timeout=60)
    out = {}
    for i in range(0, len(nct_ids), 50):
        chunk = nct_ids[i : i + 50]
        r = client.get(
            f"{settings().ctgov_base}/studies", params={"filter.ids": ",".join(chunk), "pageSize": 50, "format": "json"}
        )
        r.raise_for_status()
        for s in r.json().get("studies", []):
            t = to_trial(s)
            out[t["NCTID"]] = t
    return out
