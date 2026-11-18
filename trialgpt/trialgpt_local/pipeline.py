"""End to end for one patient note: keywords -> retrieval -> criterion matching -> ranking.

Sources of candidate trials:
* ``live``: ClinicalTrials.gov (recruiting), the same registry trialgpt.app searches — used by the interface and the
  head-to-head;
* a cohort name (``sigir``, ``trec_2021``, ``trec_2022``): the frozen NCBI corpus of that cohort (benchmark).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from trialgpt_local import core, ctgov, datasets
from trialgpt_local.llm import LLMClient
from trialgpt_local.retrieval import HybridIndex

Progress = Callable[[str], None]
_INDEXES: dict[str, HybridIndex] = {}


@dataclass
class PatientRun:
    source: str
    keywords: dict[str, Any]
    candidates: int
    retrieved: list[str]  # NCT ids after hybrid retrieval, best first
    ranked: list[core.TrialMatch] = field(default_factory=list)
    trials: dict[str, dict[str, Any]] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)
    sentences: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["ranked"] = [{**asdict(m), "score": m.score} for m in self.ranked]
        return d


def cohort_index(cohort: str) -> HybridIndex:
    if cohort not in _INDEXES:
        _INDEXES[cohort] = HybridIndex.build(datasets.corpus(cohort), name=cohort)
    return _INDEXES[cohort]


def run_patient(
    note: str,
    *,
    client: LLMClient,
    source: str = "live",
    top_k: int = 10,
    country: str | None = None,
    prefer_country: str | None = None,
    keywords: dict[str, Any] | None = None,
    progress: Progress | None = None,
) -> PatientRun:
    say = progress or (lambda _m: None)
    t = time.perf_counter()
    secs: dict[str, float] = {}
    say("Generating search keywords")
    kw = keywords or core.generate_keywords(client, note)
    conds = kw["conditions"] or [note[:200]]
    secs["keywords"] = time.perf_counter() - t
    t = time.perf_counter()
    if source == "live":
        say(f"Searching ClinicalTrials.gov for {len(conds[:8])} conditions")
        pool = ctgov.search(conds, country=country)
        trials = {p["NCTID"]: p for p in pool}
        say(f"Ranking {len(pool)} candidates (BM25 + MedCPT)")
        index = HybridIndex.build([ctgov.to_corpus_entry(p) for p in pool]) if pool else None
        ranked_ids = [nct for nct, _ in index.search(conds, n=len(pool))] if index else []
        if prefer_country:  # like trialgpt.app's "prioritize trials in selected country": reorder, never drop
            here = [n for n in ranked_ids if prefer_country in trials[n].get("countries", [])]
            first = set(here)
            ranked_ids = here + [n for n in ranked_ids if n not in first]
    else:
        say(f"Retrieving from the {source} corpus")
        index = cohort_index(source)
        ranked_ids = [nct for nct, _ in index.search(conds, n=2000)]
        trials = {n: datasets.trial_from_corpus(index.docs[n]) for n in ranked_ids[:top_k]}
        pool = list(index.docs.values())
    secs["retrieval"] = time.perf_counter() - t
    run = PatientRun(source, kw, len(pool), ranked_ids)
    numbered, run.sentences = core.number_patient(note)
    t = time.perf_counter()
    for i, nct in enumerate(ranked_ids[:top_k], start=1):
        say(f"Matching trial {i}/{min(top_k, len(ranked_ids))}: {nct}")
        m = core.match_trial(client, trials[nct], numbered)
        run.ranked.append(core.aggregate(client, m, trials[nct], numbered))
        run.trials[nct] = trials[nct]
    run.ranked.sort(key=lambda m: -m.score)
    secs["matching"] = time.perf_counter() - t
    run.seconds = {k: round(v, 2) for k, v in secs.items()}
    say("Done")
    return run
