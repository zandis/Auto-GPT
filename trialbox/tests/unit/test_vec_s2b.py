"""S2b from the vector store behind the flag ``vec.s2b`` (T-203b, D-449). Pure units: no pgvector.

The lake side (:func:`vec.s2b.rank_chunks`, ``Lake.vec_s2b``) runs on an in-memory store with the same reads as
``VecStore`` (``chunks``, ``search``); the store's SQL is ``tests/integration/test_vec_store.py``'s and
``tests/integration/test_vec_s2b_pg.py``'s. The cascade side is run on the fake lake of the safety tests.
Synthetic notes only.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from matching.cascade.engine import CascadeConfig, run_cascade
from matching.cascade.s2b_semantic import SourceFallback, SourceRanking
from orchestrator.scenarios import screen_cascade
from tb_common import flags
from tb_common.ruleset import Ruleset
from vec import s2b
from vec.index import Note, index_notes, index_snapshot, note_chunks, snapshot_notes
from vec.s2b import LakeVecSource, rank_chunks, sentence_ranking, sentence_spans

from tests.unit.test_phi_note_mask import NOTES, SITE_MRN, _ndjson
from tests.unit.test_safety_properties import (
    CASCADE_RS,
    INDEX,
    INDEX_RS,
    LEXICON,
    _Embedder,
    _FakeLake,
    _lake,
    _note,
)
from tests.unit.test_vec import FakeStore


class SearchFake(FakeStore):
    """``VecStore``'s reads in memory: ``chunks`` and the exact search by patient (cosine, ties by note, chunk)."""

    def chunks(self, pid: str) -> list[dict[str, Any]]:
        rows = sorted((r for r in self.rows.values() if r.pid == pid), key=lambda r: (r.note_date or "", r.did,
                                                                                         r.chunk_no))  # fmt: skip
        return [{"pid": r.pid, "did": r.did, "chunk_no": r.chunk_no, "date": r.note_date, "type": r.note_type,
                 "start_char": r.start, "end_char": r.end, "text": r.text, "sha": r.sha,
                 "mask_version": r.mask_version} for r in rows]  # fmt: skip

    def search(
        self, vector: Sequence[float], model: str, k: int = 10, pids: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        out = []
        for c in self.chunks_of(pids):
            v = self.vectors.get((c["sha"], model))
            if v is None or len(v) != len(vector):
                continue
            num = sum(a * b for a, b in zip(v, vector, strict=True))
            den = (math.sqrt(sum(a * a for a in v)) or 1.0) * (math.sqrt(sum(b * b for b in vector)) or 1.0)
            out.append({**c, "score": num / den})
        out.sort(key=lambda h: (-h["score"], h["did"], h["chunk_no"]))
        return out[:k]

    def chunks_of(self, pids: Sequence[str] | None) -> list[dict[str, Any]]:
        every = {r.pid for r in self.rows.values()}
        return [c for p in sorted(every if pids is None else set(pids) & every) for c in self.chunks(p)]


NOTE_A = "Gout flare in the left toe. Colchicine started. Seen again next week."
NOTE_B = "Knee pain after a fall. X-ray normal."


def _store(notes: list[Note], embedder: Any = None) -> SearchFake:
    st = SearchFake()
    index_notes(st, notes, embedder or HashEmbedder(), mrn_regex=SITE_MRN)
    return st


def _two() -> list[Note]:
    return [Note("p1", "d1", NOTE_A, "2026-09-01", "progress"), Note("p1", "d2", NOTE_B, "2026-09-02", "ed")]


# ------------------------------------------------------------------------------------------------ the lake side
def test_fresh_notes_are_ranked_from_the_stored_vectors_with_every_chunk() -> None:
    notes = _two()
    st = _store(notes)
    got = rank_chunks(st, HashEmbedder(), "p1", notes, "knee pain fall", SITE_MRN)
    assert got["state"] == "vec" and got["model"] == HashEmbedder().model
    keys = {(h["did"], h["chunk_no"]) for h in got["hits"]}
    assert keys == {(n.did, c.chunk_no) for n in notes for c in note_chunks(n, SITE_MRN)}
    assert got["hits"][0]["did"] == "d2"  # the knee note ranks first for a knee question
    assert [h["score"] for h in got["hits"]] == sorted((h["score"] for h in got["hits"]), reverse=True)
    for h in got["hits"]:  # offsets into the note, no text in the answer
        assert set(h) == {"did", "chunk_no", "start", "end", "score"}


def test_a_note_changed_since_it_was_indexed_is_stale_and_one_never_indexed_is_missing() -> None:
    notes = _two()
    st = _store(notes)
    changed = [notes[0], Note("p1", "d2", NOTE_B + " Ice and rest.", "2026-09-02", "ed")]
    assert rank_chunks(st, HashEmbedder(), "p1", changed, "q", SITE_MRN) == s2b.fallback(s2b.STALE)
    extra = [*notes, Note("p1", "d9", "A note of the next night.", "2026-09-03", "progress")]
    assert rank_chunks(st, HashEmbedder(), "p1", extra, "q", SITE_MRN) == s2b.fallback(s2b.NOT_INDEXED)
    # the mask pattern is part of the chunks: a store indexed with another site pattern is not this lake's
    assert rank_chunks(_store([Note("p1", "d1", "Chart 12345678 reviewed.")]), HashEmbedder(), "p1",
                       [Note("p1", "d1", "Chart 12345678 reviewed.")], "q", None)["state"] == "fallback"  # fmt: skip


class _Other(HashEmbedder):
    model = "another-embedder-1"


def test_vectors_of_another_model_or_a_missing_vector_are_refused_never_mixed() -> None:
    notes = _two()
    st = _store(notes)
    assert rank_chunks(st, _Other(), "p1", notes, "q", SITE_MRN) == s2b.fallback(s2b.NO_VECTOR)
    st.vectors.pop(next(iter(st.vectors)))  # one chunk's vector gone: the ranking would skip it silently
    assert rank_chunks(st, HashEmbedder(), "p1", notes, "q", SITE_MRN) == s2b.fallback(s2b.NO_VECTOR)
    assert rank_chunks(None, HashEmbedder(), "p1", notes, "q", SITE_MRN) == s2b.fallback(s2b.UNAVAILABLE)


def test_sentences_take_the_score_of_the_best_chunk_over_them() -> None:
    @dataclass
    class N:
        did: str
        text: str
        sents: list[str]

    a = N("d1", "One. Two. Three.", ["One.", "Two.", "Three."])
    b = N("d2", "Four.", ["Four."])
    hits = [{"did": "d1", "start": 0, "end": 9, "score": 0.2}, {"did": "d1", "start": 5, "end": 16, "score": 0.7},
            {"did": "d2", "start": 0, "end": 5, "score": 0.5}]  # fmt: skip
    got = sentence_ranking(hits, [a, b], "m", k=3)
    assert isinstance(got, SourceRanking) and got.model == "m" and got.best == 0.7
    assert got.top == [(1, 0.7), (2, 0.7), (3, 0.5)]  # ties by position
    assert sentence_spans("a. b.", ["a.", "b."]) == [(0, 2), (3, 5)] and sentence_spans("a.", ["c."]) is None
    lost = sentence_ranking(hits[:1], [a], "m")
    assert isinstance(lost, SourceFallback) and "outside every stored chunk" in lost.reason
    assert isinstance(sentence_ranking([], [N("d1", "x", ["y"])], "m"), SourceFallback)


# ------------------------------------------------------------------------------------------------ the lake and the pin
def _lake_with(tmp_path: Path) -> Lake:
    lake = Lake(tmp_path / "lake", "Asia/Taipei", SITE_MRN)
    lake.rebuild("2026-01-02", HashEmbedder(), _ndjson(tmp_path / "nd"))
    return lake


def test_the_lake_reads_the_pinned_snapshot_and_a_newer_text_falls_back(tmp_path: Path) -> None:
    lake = _lake_with(tmp_path)
    st = SearchFake()
    stats = index_snapshot(st, lake, "2026-01-02", HashEmbedder(), exclude={"p2"}, mrn_regex=SITE_MRN)
    assert stats.notes == 1 and {r.pid for r in st.rows.values()} == {"p1"}  # the opted-out patient is not indexed
    did = next(r.did for r in st.rows.values())
    got = lake.vec_s2b("p1", [did], "gout", HashEmbedder(), st, "2026-01-02")
    assert got["state"] == "vec" and {h["did"] for h in got["hits"]} == {did}
    assert lake.vec_s2b("p2", ["d2"], "gout", HashEmbedder(), st, "2026-01-02")["state"] == "fallback"
    assert lake.vec_s2b("p1", [did, "nope"], "q", HashEmbedder(), st, "2026-01-02")["state"] == "fallback"
    assert lake.vec_s2b("p1", [did], "q", HashEmbedder(), None, "2026-01-02") == s2b.fallback(s2b.UNAVAILABLE)
    # the store indexed from a later night with another text is not the pinned snapshot's: fallback
    later = [Note(n.pid, n.did, n.text + " Seen again.") for n in snapshot_notes(lake, "2026-01-02")]
    index_notes(st, later, HashEmbedder(), mrn_regex=SITE_MRN)
    assert lake.vec_s2b("p1", [did], "q", HashEmbedder(), st, "2026-01-02") == s2b.fallback(s2b.STALE)
    local = LakeLocal(tmp_path / "lake", HashEmbedder(), "Asia/Taipei", vec_store=None, mrn_regex=SITE_MRN)
    assert local.vec_s2b("p1", [did], "q", "2026-01-02") == s2b.fallback(s2b.UNAVAILABLE)


def test_snapshot_notes_pages_by_note_id(tmp_path: Path) -> None:
    lake = _lake_with(tmp_path)
    got = list(snapshot_notes(lake, "2026-01-02", page=1))
    assert sorted(n.did for n in got) == sorted(NOTES) and [n.did for n in got] == sorted(n.did for n in got)


# ------------------------------------------------------------------------------------------------ the cascade side
@dataclass
class _Source:
    """A scripted S2b source: answers in turn (a ranking, a fallback or an exception)."""

    answers: list[Any]
    asked: list[str] = field(default_factory=list)

    def rank(self, pid: str, query: str, notes: Sequence[Any], k: int) -> SourceRanking | SourceFallback:
        self.asked.append(pid)
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        return a  # type: ignore[no-any-return]


def _run(lake: _FakeLake, source: Any = None, **cfg: Any) -> Any:
    conf = {"study_id": lake.rs.id, "run_date": INDEX, "index_mode": "single", "population": sorted(lake.s1),
            "semantics": "v1", "snapshot": None, "lexicon": LEXICON, "absence_semantics": False, **cfg}  # fmt: skip
    return run_cascade(lake, lake.rs, CascadeConfig(**conf), embedder=_Embedder(above=False), s2b_source=source)


TWO_SENTS = "Routine visit.\nNothing to report."


def test_flag_off_writes_what_it_wrote_before() -> None:
    res = _run(_lake(CASCADE_RS, ["Q-1"], [_note("Q-1", TWO_SENTS)]))
    t = res.traces["Q-1"]
    assert t.s2b_source is None and "s2b_source" not in t.to_dict()
    assert not {k for k in res.stage("S2b").detail if k.startswith("vec_")}


def test_a_stored_ranking_picks_the_excerpts_and_the_trace_names_its_model() -> None:
    src = _Source([SourceRanking(0.9, [(1, 0.9)], "e-embed-test")])
    res = _run(_lake(CASCADE_RS, ["Q-2"], [_note("Q-2", TWO_SENTS)]), src)
    t = res.traces["Q-2"]
    assert t.s2b_source == {"vec_pairs": 2, "fallback_pairs": 0, "vec_model": "e-embed-test", "fallback": [],
                            "on_the_fly_model": "stub-embedder"}  # fmt: skip
    d = res.stage("S2b").detail
    assert (d["vec_pairs"], d["vec_fallback_pairs"], d["vec_model"]) == (2, 0, "e-embed-test")
    assert t.exit_stage is None and t.to_dict()["s2b_source"]["vec_pairs"] == 2


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (SourceFallback(s2b.STALE), s2b.STALE),
        (RuntimeError("db down"), "vector store error: RuntimeError"),
        (SourceRanking(0.9, [(7, 0.9)], "m"), "the stored ranking does not index the window's sentences"),
        (SourceRanking(0.9, [], "m"), "the stored ranking does not index the window's sentences"),
    ],
)
def test_anything_the_store_cannot_answer_falls_back_and_is_recorded(answer: Any, reason: str) -> None:
    lake = _lake(CASCADE_RS, ["Q-3"], [_note("Q-3", TWO_SENTS)])
    off = _run(_lake(CASCADE_RS, ["Q-3"], [_note("Q-3", TWO_SENTS)]))
    res = _run(lake, _Source([answer]))
    t = res.traces["Q-3"]
    assert t.s2b_source is not None and t.s2b_source["fallback"] == [reason]
    assert (t.s2b_source["vec_pairs"], t.s2b_source["fallback_pairs"]) == (0, 2)
    assert res.stage("S2b").detail["vec_fallback_patients"] == 1
    # the on-the-fly path ran: the same outcomes as with the flag off
    assert {c: (o.status, o.stage, o.reason) for c, o in t.outcomes.items()} == {
        c: (o.status, o.stage, o.reason) for c, o in off.traces["Q-3"].outcomes.items()
    }


def test_a_second_model_inside_one_patients_run_is_refused() -> None:
    src = _Source([SourceRanking(0.9, [(0, 0.9)], "model-a"), SourceRanking(0.9, [(0, 0.9)], "model-b")])
    t = _run(_lake(CASCADE_RS, ["Q-4"], [_note("Q-4", TWO_SENTS)]), src).traces["Q-4"]
    assert t.s2b_source is not None and t.s2b_source["vec_model"] == "model-a"
    assert t.s2b_source["fallback"] == ["vectors of a second model (model-b) in one patient's run: refused"]


def test_with_absence_semantics_the_store_is_not_asked() -> None:
    src = _Source([SourceRanking(0.0, [(0, 0.0)], "m")])
    res = _run(_lake(CASCADE_RS, ["Q-5"], [_note("Q-5", TWO_SENTS)]), src, absence_semantics=True)
    t = res.traces["Q-5"]
    assert src.asked == [] and t.s2b_source is not None and t.s2b_source["vec_pairs"] == 0
    assert t.s2b_source["fallback"] == [
        "absence semantics on: the S2b threshold is fitted to on-the-fly vectors (D-429)"
    ]


def test_the_index_rescue_reads_the_stored_ranking_and_never_excludes() -> None:
    lake = _FakeLake(INDEX_RS, {"I-1": {"X-INC-01": False}}, notes=[_note("I-1", "Seen in clinic.", offset=-200)])
    res = _run(lake, _Source([SourceRanking(0.0, [(0, 0.0)], "m")]), semantics="affirmative",
               lexicon={"X-INC-01": ["gout"]})  # fmt: skip
    t = res.traces["I-1"]
    assert t.exit_stage is None and t.outcomes["X-INC-01"].status == "unknown"
    assert t.outcomes["X-INC-01"].reason == "index condition not coded and not found in the notes; review"
    up = _run(_FakeLake(INDEX_RS, {"I-1": {"X-INC-01": False}}, notes=[_note("I-1", "Seen in clinic.", offset=-200)]),
              _Source([SourceRanking(0.9, [(0, 0.9)], "m")]), semantics="affirmative", lexicon={"X-INC-01": ["gout"]})  # fmt: skip
    assert up.traces["I-1"].outcomes["X-INC-01"].reason == "index rescued"


def test_lake_source_remembers_an_unavailable_store_and_a_lake_without_the_read() -> None:
    @dataclass
    class L:
        calls: int = 0

        def vec_s2b(self, pid: str, dids: list[str], query: str, snapshot: str | None = None) -> dict[str, Any]:
            self.calls += 1
            return s2b.fallback(s2b.UNAVAILABLE)

    @dataclass
    class N:
        did: str = "d1"
        text: str = "A."
        sents: list[str] = field(default_factory=lambda: ["A."])

    lk = L()
    src = LakeVecSource(lk, "2026-01-02")
    assert src.rank("p", "q", [N()], 5) == src.rank("p", "q", [N()], 5) == SourceFallback(s2b.UNAVAILABLE)
    assert lk.calls == 1
    assert LakeVecSource(object(), None).rank("p", "q", [N()], 5) == SourceFallback(s2b.NO_LAKE_READ)

    @dataclass
    class Up:
        def vec_s2b(self, pid: str, dids: list[str], query: str, snapshot: str | None = None) -> dict[str, Any]:
            assert (dids, snapshot) == (["d1"], "2026-01-02")
            return {"state": "vec", "model": "m", "hits": [{"did": "d1", "start": 0, "end": 2, "score": 0.4}]}

    assert LakeVecSource(Up(), "2026-01-02").rank("p", "q", [N()], 5) == SourceRanking(0.4, [(0, 0.4)], "m")


def test_the_flag_is_declared_off_and_read_once_per_run(monkeypatch: pytest.MonkeyPatch) -> None:
    d = flags.declared("vec.s2b")
    assert (d.values, d.default, d.seed_env) == (("off", "on"), "off", None)
    monkeypatch.setattr(flags, "read", lambda name, url=None: None)
    assert screen_cascade.vec_s2b_on() is False
    monkeypatch.setattr(flags, "read", lambda name, url=None: "on" if name == "vec.s2b" else None)
    assert screen_cascade.vec_s2b_on() is True
    assert screen_cascade.s2b_source(object(), "2026-01-02", False) is None
    src = screen_cascade.s2b_source("lake", "2026-01-02", True)
    assert isinstance(src, LakeVecSource) and (src.lake, src.snapshot) == ("lake", "2026-01-02")


def test_the_job_file_exists_only_when_the_flag_was_on() -> None:
    from orchestrator.scenarios.screen import ScreenRun, s2b_source_doc

    rs = Ruleset.load(Path(__file__).resolve().parents[2] / "rulesets" / "GZQO")
    run = ScreenRun(rs, INDEX, "2026-01-02", [], {}, [], [], [], 30, None)
    assert s2b_source_doc(run) is None  # flag off: no file
    run.s2b_sources = {"p1": {"vec_pairs": 1, "fallback_pairs": 0, "vec_model": "m", "fallback": []}}
    doc = s2b_source_doc(run)
    assert doc is not None and doc["flag"] == "vec.s2b" and doc["patients"]["p1"]["vec_model"] == "m"
    assert (doc["ruleset"], doc["snapshot"]) == (rs.id, "2026-01-02")


def test_one_switch_every_path_or_none() -> None:
    """With the flag off no path reads the vector store; with it on every service path that runs S2b does: the
    only service caller of the cascade is ``screen_with_cascade`` (SCREEN and MICROBATCH go through it), and it is the
    only place that builds the store source."""
    root = Path(__file__).resolve().parents[2] / "services"
    callers, builders = set(), set()
    for f in sorted(root.rglob("*.py")):
        rel = f.relative_to(root).as_posix()
        text = f.read_text(encoding="utf-8")
        if "run_cascade(" in text and not rel.startswith("matching/cascade/") and rel != "vec/s2b.py":
            callers.add(rel)
        if "LakeVecSource(" in text and rel != "vec/s2b.py":
            builders.add(rel)
    assert callers == builders == {"orchestrator/scenarios/screen_cascade.py"}


def test_both_paths_publish_the_record_and_drop_who_opted_out_since(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from orchestrator.scenarios import screen
    from orchestrator.scenarios.screen import ScreenRun, publish_s2b_source

    published: list[tuple[str, bytes]] = []
    ctx = SimpleNamespace(publish=lambda name, body, label, to: published.append((name, body)))
    monkeypatch.setattr(screen, "opted_out_now", lambda ctx, pids, where: frozenset({"p2"}))
    rs = Ruleset.load(Path(__file__).resolve().parents[2] / "rulesets" / "GZQO")
    run = ScreenRun(rs, INDEX, "2026-01-02", [], {}, [], [], [], 30, None)
    publish_s2b_source(ctx, run)  # type: ignore[arg-type]
    assert published == []  # flag off: no file
    rec = {"vec_pairs": 0, "fallback_pairs": 1, "vec_model": None, "fallback": [s2b.STALE]}
    run.s2b_sources = {"p1": rec, "p2": rec}
    publish_s2b_source(ctx, run)  # type: ignore[arg-type]
    import json

    ((name, body),) = published
    assert name == f"s2b_source_{rs.id}_v{rs.version}.json" and set(json.loads(body)["patients"]) == {"p1"}
    import orchestrator.scenarios.microbatch as mb

    assert vars(mb)["publish_s2b_source"] is publish_s2b_source
