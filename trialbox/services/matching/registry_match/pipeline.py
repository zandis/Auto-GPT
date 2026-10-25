"""End to end for one patient note: keywords -> retrieval -> criterion matching -> ranking.

Sources of candidate trials, both local:
* ``mirror``: the local ClinicalTrials.gov mirror (:class:`matching.registry_mirror.RegistryMirror`), filtered by
  status, country, age and sex, then ranked by the hybrid index. This replaces the port's live registry search: the
  keywords generated from the note (patient-derived, D3) only query the in-process index (FR-M5-9);
* ``index``: a prebuilt :class:`HybridIndex`, e.g. a frozen NCBI benchmark corpus (``eval/match_registry``).

The spec's production flow (``patient_to_trials.py``, durable steps, TrialBox judge) replaces this at MS4; this module
keeps the port's flow for the benchmark and for parity checks.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from matching.registry_match import core
from matching.registry_match.llm import LLMClient
from matching.registry_match.retrieval import HybridIndex
from matching.registry_mirror import RegistryMirror, to_corpus_entry

Progress = Callable[[str], None]


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
    mirror_sha256: str | None = None

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["ranked"] = [{**asdict(m), "score": m.score} for m in self.ranked]
        return d


def run_patient(
    note: str,
    *,
    client: LLMClient,
    mirror: RegistryMirror | None = None,
    index: HybridIndex | None = None,
    top_k: int = 10,
    countries: list[str] | None = None,
    prefer_country: str | None = None,
    recruiting_only: bool = True,
    age: float | None = None,
    sex: str | None = None,
    dense: bool = True,
    keywords: dict[str, Any] | None = None,
    progress: Progress | None = None,
) -> PatientRun:
    if (mirror is None) == (index is None):
        raise ValueError("give exactly one candidate source: mirror= or index=")
    say = progress or (lambda _m: None)
    t = time.perf_counter()
    secs: dict[str, float] = {}
    say("Generating search keywords")
    kw = keywords or core.generate_keywords(client, note)
    conds = kw["conditions"] or [note[:200]]
    secs["keywords"] = time.perf_counter() - t
    t = time.perf_counter()
    if mirror is not None:
        pool = mirror.trials(recruiting_only=recruiting_only, countries=countries, age=age, sex=sex)
        trials = {p["NCTID"]: p for p in pool}
        say(f"Ranking {len(pool)} mirror candidates")
        idx = HybridIndex.build([to_corpus_entry(p) for p in pool], dense=dense) if pool else None
        ranked_ids = [nct for nct, _ in idx.search(conds, n=len(pool))] if idx else []
        if prefer_country:  # reorder, never drop
            here = [n for n in ranked_ids if prefer_country in trials[n].get("countries", [])]
            first = set(here)
            ranked_ids = here + [n for n in ranked_ids if n not in first]
        source, n_candidates, sha = "mirror", len(pool), mirror.manifest().sha256
    else:
        assert index is not None
        say("Retrieving from the corpus index")
        ranked_ids = [nct for nct, _ in index.search(conds, n=2000)]
        trials = {n: {**index.docs[n]["metadata"], "NCTID": n} for n in ranked_ids[:top_k]}
        source, n_candidates, sha = "index", len(index.docs), None
    secs["retrieval"] = time.perf_counter() - t
    run = PatientRun(source, kw, n_candidates, ranked_ids, mirror_sha256=sha)
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
