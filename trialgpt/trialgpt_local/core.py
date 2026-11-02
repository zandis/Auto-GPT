"""TrialGPT-Matching and TrialGPT-Ranking on the local LLM (NCBI flow, prompts verbatim from :mod:`prompts`).

Deviations from the NCBI scripts, both switchable:
* labels are compared after ``lower().strip()`` (``strict_labels=False``): small local models write "Included" or
  "not enough information." where GPT-4 wrote the exact token, and NCBI's exact match would silently drop them;
* a criterion output that is not ``[reasoning, [ids], label]`` is kept as a parse error and excluded from the counts
  (NCBI's ranking script crashed on a non-dict output; its matching script stored the raw string).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, cast

from nltk.tokenize import sent_tokenize

from trialgpt_local import prompts
from trialgpt_local.llm import LLMClient

CONSENT = (
    "The patient will provide informed consent, and will comply with the trial protocol without any practical issues."
)
LABELS = {
    "inclusion": ("included", "not included", "not applicable", "not enough information"),
    "exclusion": ("excluded", "not excluded", "not applicable", "not enough information"),
}


_CJK_END = re.compile(r"(?<=[。！？])")


def split_sentences(note: str) -> list[str]:
    """NCBI's ``sent_tokenize``, then also split on CJK sentence ends (。！？), which NLTK does not know: a zh-TW
    progress note would otherwise be one "sentence" and evidence ids would point at nothing useful. English text has
    no such characters, so the NCBI cohorts are numbered exactly as in the paper."""
    out: list[str] = []
    for s in sent_tokenize(note):
        out += [p.strip() for p in _CJK_END.split(s) if p.strip()]
    return out


def number_patient(note: str) -> tuple[str, list[str]]:
    """NCBI: sentence-split the note, append the consent sentence, prefix each with its id."""
    sents = split_sentences(note)
    sents.append(CONSENT)
    return "\n".join(f"{i}. {s}" for i, s in enumerate(sents)), sents


def criteria_list(trial: dict[str, Any], inc_exc: str) -> list[str]:
    """The criteria exactly as NCBI numbers them in the prompt (``parse_criteria``)."""
    out = []
    for c in str(trial.get(f"{inc_exc}_criteria") or "").split("\n\n"):
        c = c.strip()
        if "inclusion criteria" in c.lower() or "exclusion criteria" in c.lower() or len(c) < 5:
            continue
        out.append(c)
    return out


@dataclass
class CriterionResult:
    kind: str  # inclusion | exclusion
    idx: str
    criterion: str
    reasoning: str
    evidence: list[int]
    label: str  # normalised; "parse error" when the output was unusable


@dataclass
class TrialMatch:
    nct_id: str
    raw: dict[str, Any]  # NCBI format: {"inclusion": {idx: [reasoning, ids, label]}, "exclusion": {...}}
    criteria: list[CriterionResult] = field(default_factory=list)
    aggregation: dict[str, Any] | None = None
    matching_score: float = 0.0
    aggregation_score: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        """NCBI ``rank_results.py``: matching score + aggregation score."""
        return self.matching_score + self.aggregation_score


# Typed views of the verbatim NCBI functions (NCBI annotates the two prompt builders "-> str" but they return
# (system, user); the scoring functions are unannotated).
def matching_prompt(trial: dict[str, Any], inc_exc: str, patient: str) -> tuple[str, str]:
    return cast(tuple[str, str], prompts.get_matching_prompt(trial, inc_exc, patient))


def aggregation_prompt(patient: str, pred: dict[str, Any], trial: dict[str, Any]) -> tuple[str, str]:
    return cast(tuple[str, str], prompts.convert_pred_to_prompt(patient, pred, trial))


def matching_score(matching: dict[str, Any]) -> float:
    return float(prompts.get_matching_score(matching))  # type: ignore[no-untyped-call]


def aggregation_score(assessment: dict[str, Any]) -> float:
    return float(prompts.get_agg_score(assessment))  # type: ignore[no-untyped-call]


def keyword_messages(note: str) -> list[dict[str, str]]:
    return cast(list[dict[str, str]], prompts.get_keyword_generation_messages(note))  # type: ignore[no-untyped-call]


def normalise(
    raw: Any, inc_exc: str, criteria: list[str], strict: bool
) -> tuple[dict[str, Any], list[CriterionResult]]:
    """Turn one model output into NCBI's dict and structured rows (criteria that the model skipped are not invented)."""
    if not isinstance(raw, dict):
        return {}, []
    clean: dict[str, Any] = {}
    rows = []
    for idx, pred in raw.items():
        ok = isinstance(pred, list) and len(pred) == 3
        label = str(pred[2]) if ok else ""
        if not strict:
            label = label.lower().strip().rstrip(".")
        if not ok or label not in LABELS[inc_exc]:
            label_out = "parse error"
        else:
            label_out = label
        reasoning = str(pred[0]) if ok else str(pred)[:500]
        evidence = [
            int(x) for x in (pred[1] if ok and isinstance(pred[1], list) else []) if str(x).lstrip("-").isdigit()
        ]
        i = str(idx).strip()
        text = criteria[int(i)] if i.isdigit() and int(i) < len(criteria) else ""
        rows.append(CriterionResult(inc_exc, i, text, reasoning, evidence, label_out))
        if label_out != "parse error":
            clean[i] = [reasoning, evidence, label_out]
    return clean, rows


def match_trial(
    client: LLMClient, trial: dict[str, Any], patient_numbered: str, *, strict_labels: bool = False
) -> TrialMatch:
    """TrialGPT-Matching: one prompt for inclusion, one for exclusion (NCBI ``trialgpt_matching``)."""
    out = TrialMatch(nct_id=str(trial.get("NCTID") or trial.get("nct_id") or ""), raw={})
    for inc_exc in ("inclusion", "exclusion"):
        system, user = matching_prompt(trial, inc_exc, patient_numbered)
        res = client.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}])
        clean, rows = normalise(res.data, inc_exc, criteria_list(trial, inc_exc), strict_labels)
        if res.data is None:
            out.errors.append(f"{inc_exc}: {res.error or 'output is not JSON'}")
        out.raw[inc_exc] = clean
        out.criteria += rows
    out.matching_score = matching_score(out.raw)
    return out


def aggregate(client: LLMClient, match: TrialMatch, trial: dict[str, Any], patient_numbered: str) -> TrialMatch:
    """TrialGPT-Ranking LLM aggregation: relevance R (0..100) and eligibility E (-R..R)."""
    system, user = aggregation_prompt(patient_numbered, match.raw, trial)
    res = client.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}])
    if isinstance(res.data, dict):
        match.aggregation = res.data
        match.aggregation_score = aggregation_score(res.data)
    else:
        match.errors.append(f"aggregation: {res.error or 'output is not JSON'}")
        match.aggregation_score = 0.0  # NCBI rank_results: missing aggregation counts 0
    return match


def rank(
    client: LLMClient, note: str, trials: list[dict[str, Any]], *, strict_labels: bool = False
) -> list[TrialMatch]:
    """Match + aggregate every trial for one patient; best first (NCBI ranking)."""
    numbered, _ = number_patient(note)
    results = []
    for t in trials:
        m = match_trial(client, t, numbered, strict_labels=strict_labels)
        results.append(aggregate(client, m, t, numbered))
    return sorted(results, key=lambda m: -m.score)


def generate_keywords(client: LLMClient, note: str) -> dict[str, Any]:
    """TrialGPT-Retrieval keyword generation: {"summary": str, "conditions": [str, ...]} (up to 32, by priority)."""
    res = client.chat_json(keyword_messages(note))
    data = res.data if isinstance(res.data, dict) else {}
    raw = data.get("conditions")
    conds: list[Any] = raw if isinstance(raw, list) else []
    return {"summary": str(data.get("summary") or ""), "conditions": [str(c) for c in conds if str(c).strip()][:32]}
