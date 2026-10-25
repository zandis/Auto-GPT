"""Vendored TrialGPT port, harness: benchmark, pipeline over a corpus index and over the local mirror (S1-17)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from matching.registry_match import pipeline, retrieval
from matching.registry_match.llm import LLMClient
from matching.registry_mirror import RegistryMirror, split_criteria
from matching.registry_mirror.mirror import MirrorRecord

from eval.match_registry import benchmark, datasets
from tests.registry_match_mock import MockChat, make_mini_cohort, study

ROOT = Path(__file__).resolve().parents[2]
OPEN_DATA = ROOT / "tests" / "fixtures" / "open_data"


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    for k, sub in (("TB_MATCH_DATA_DIR", "data"), ("TB_MATCH_RESULTS_DIR", "results"), ("TB_MATCH_CACHE_DIR", "cache")):
        monkeypatch.setenv(k, str(tmp_path / sub))
    monkeypatch.setenv("TB_MATCH_MODEL", "mock-model")
    monkeypatch.delenv("TB_MATCH_LLM_MODE", raising=False)
    yield tmp_path


@pytest.fixture(autouse=True)
def fake_medcpt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic bag-of-words vectors instead of MedCPT (no model download in tests)."""

    def vec(text: str) -> np.ndarray:
        v = np.zeros(768, dtype=np.float32)
        for w in text.lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 768] += 1
        return v

    def articles(docs: list[dict[str, Any]], batch: int = 16) -> np.ndarray:
        return np.stack([vec(f"{d.get('title')} {d.get('text')}") for d in docs]) if docs else np.zeros((0, 768))

    monkeypatch.setattr(retrieval, "encode_articles", articles)
    monkeypatch.setattr(retrieval, "encode_queries", lambda texts: np.stack([vec(t) for t in texts]))


@pytest.fixture
def mini_cohort(isolated: Path) -> str:
    return make_mini_cohort(isolated / "data")


@pytest.mark.req("FR-M5-14")
def test_benchmark_rank_and_report(mini_cohort: str) -> None:
    chat = MockChat()
    d = benchmark.run_rank(mini_cohort, None, None, chat=chat)
    matching = json.loads(next(d.glob("matching_results_*.json")).read_text())
    assert set(matching) == {"sigir-1", "sigir-2"} and "NCT1" in matching["sigir-1"]["2"]  # NCBI layout
    run = json.loads((d / "run.json").read_text())
    assert run["tokenizer"] in ("nltk", "regex") and run["model"] == "mock-model"
    ev = benchmark.evaluate(mini_cohort, "mock-model")
    combined = ev["metrics"]["combined"]
    # sigir-1: NCT1 (label 2) has no failed criterion -> ranked above NCT2 (label 1, one NEGATIVE) -> AUROC 1
    assert combined["auroc"] == 1.0 and combined["ndcg@10"] is not None
    assert ev["diagnostics"]["criterion_parse_error_rate"] > 0  # the GARBLED criterion is counted, not hidden
    text = benchmark.report("mock-model")
    assert "Paper, GPT-4" in text and "0.7275" in text
    n = len(chat.calls)  # resumable: a second run makes no new model call
    benchmark.run_rank(mini_cohort, None, None, chat=chat)
    assert len(chat.calls) == n


def test_slice_keeps_every_label(mini_cohort: str) -> None:
    co = datasets.load(mini_cohort)
    sel = benchmark.select(co, 1, 2)
    ((pid, ts),) = sel.items()
    labels = {co.labels_for(pid)[t["NCTID"]] for t in ts}
    assert len(ts) == 2 and len(labels) == 2


@pytest.mark.req("FR-M5-14")
def test_retrieval_benchmark_with_a_keyword_set(mini_cohort: str) -> None:
    res = benchmark.run_retrieval(mini_cohort, "paper", None)
    assert res["patients"] == 2 and res["recall"]["100"] == 1.0


def test_pipeline_on_cohort_corpus(mini_cohort: str) -> None:
    index = retrieval.HybridIndex.build(datasets.corpus(mini_cohort), name=mini_cohort)
    note = "A man with gout and high serum urate."
    run = pipeline.run_patient(note, client=LLMClient(MockChat()), index=index, top_k=3)
    assert run.candidates == 4 and len(run.ranked) == 3 and run.source == "index"
    assert run.ranked == sorted(run.ranked, key=lambda m: -m.score)
    assert run.to_json()["ranked"][0]["score"] == run.ranked[0].score


def _mirror() -> RegistryMirror:
    crit = "Inclusion Criteria:\n\n* Gout\n* Serum urate above 6\n\nExclusion Criteria:\n\n* Pregnancy"
    return RegistryMirror(
        [
            MirrorRecord("NCT00000010", study("NCT00000010", "Gout flares", ["Gout"], crit, countries=["France"])),
            MirrorRecord("NCT00000011", study("NCT00000011", "Gout urate", ["Gout"], crit, countries=["Taiwan"])),
            MirrorRecord(
                "NCT00000012",
                study("NCT00000012", "Gout done", ["Gout"], crit, status="COMPLETED", countries=["Taiwan"]),
            ),
            MirrorRecord("NCT00000013", study("NCT00000013", "Paediatric gout", ["Gout"], crit, min_age="2 Years")),
            MirrorRecord("NCT00000014", study("NCT00000014", "Women only", ["Lupus"], crit, sex="FEMALE")),
        ]
    )


@pytest.mark.req("FR-M5-9", "FR-M5-7")
def test_pipeline_over_the_local_mirror_prefers_country() -> None:
    m = _mirror()
    run = pipeline.run_patient(
        "gout patient note here", client=LLMClient(MockChat()), mirror=m, top_k=2, prefer_country="Taiwan"
    )
    assert run.source == "mirror" and run.retrieved[0] == "NCT00000011" and run.mirror_sha256 == m.manifest().sha256
    assert "NCT00000012" not in run.retrieved  # completed: recruiting only by default
    tw = pipeline.run_patient("gout", client=LLMClient(MockChat()), mirror=m, countries=["Taiwan"], dense=False)
    assert tw.retrieved == ["NCT00000011"]
    with pytest.raises(ValueError, match="exactly one"):
        pipeline.run_patient("gout", client=LLMClient(MockChat()))


@pytest.mark.req("FR-M5-9")
def test_mirror_reads_cached_records_with_a_manifest(tmp_path: Path) -> None:
    m = RegistryMirror.from_dir(OPEN_DATA, "ctgov_*.json")
    man = m.manifest()
    assert man.records == 2 and man.sha256.startswith("sha256:") and man.fetched_at == "2026-10-17"
    assert set(m.get(["NCT02568722", "NCT04157751", "NCT99999999"])) == {"NCT02568722", "NCT04157751"}
    aki = m.get(["NCT02568722"])["NCT02568722"]
    assert "Serum potassium > 5.5 mmol/L" in aki["exclusion_criteria"].split("\n\n")
    assert m.trials(recruiting_only=True) == [] and len(m.trials()) == 2
    # a bare study and an API page load too, and the newest fetch of a study wins
    page = {"studies": [study("NCT00000020", "A", ["x"], "Inclusion Criteria:\n\n* adult")]}
    (tmp_path / "page.json").write_text(json.dumps(page))
    (tmp_path / "bare.json").write_text(json.dumps(study("NCT00000021", "B", ["y"], "* adult")))
    assert len(RegistryMirror.from_dir(tmp_path)) == 2
    old = MirrorRecord("NCT00000022", study("NCT00000022", "old", [], "* a"), fetched="2026-01-01")
    new = MirrorRecord("NCT00000022", study("NCT00000022", "new", [], "* a"), fetched="2026-02-01")
    assert RegistryMirror([new, old]).get(["NCT00000022"])["NCT00000022"]["brief_title"] == "new"
    mm = _mirror()
    assert [t["NCTID"] for t in mm.trials(age=10)] == ["NCT00000013"]
    assert "NCT00000014" not in {t["NCTID"] for t in mm.trials(sex="male")}


def test_split_criteria_free_form_headings() -> None:
    text = (
        "Patients are eligible to be included in the study only if all the following criteria apply:\n\n"
        "* Adults \\>18 years\n* Gout\n  diagnosed by a rheumatologist\n\n"
        "Patients are excluded from the study if any of the following criteria apply:\n\n* Pregnant\n* Dialysis"
    )
    inc, exc = split_criteria(text)
    assert inc.split("\n\n") == ["Adults >18 years", "Gout diagnosed by a rheumatologist"]
    assert exc.split("\n\n") == ["Pregnant", "Dialysis"]
    inc2, exc2 = split_criteria("Inclusion Criteria:\n\n1. Age 20-75\n2. RA\n\nKey Exclusion Criteria:\n\n- TB")
    assert inc2.split("\n\n") == ["Age 20-75", "RA"] and exc2 == "TB"
    groups = (
        "Group A\n\nInclusion Criteria:\n\n* chest pain\n\nExclusion Criteria:\n\n* pregnant\n"
        "* Inclusion in another trial within 30 days\n\nGroup B\n\nInclusion Criteria:\n\n* obstructive CAD\n\n"
        "Exclusion Criteria:\n\n* dialysis"
    )
    inc3, exc3 = split_criteria(groups)
    assert "obstructive CAD" in inc3.split("\n\n") and "obstructive CAD" not in exc3
    assert exc3.split("\n\n") == ["pregnant", "Inclusion in another trial within 30 days", "Group B", "dialysis"]
