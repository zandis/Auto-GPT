"""Chia as bench gold (HOLISTIC-3 lane N, owner decision D7 (i)): the scorer reads Chia's entities, relations and
OR groups per line and scores what the deterministic layer decides today, the negation scope, against them.

The text and annotation below are written for this test in Chia's brat form; no corpus text is committed.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from tools import chia_score

TXT = "No history of asthma or diabetes\nPrior chemotherapy\n"
ANN = "\n".join(
    [
        "T1\tNegation 0 2\tNo",
        "T2\tCondition 14 20\tasthma",
        "T3\tCondition 24 32\tdiabetes",
        "*\tOR T2 T3",
        "T4\tScope 14 32\tasthma or diabetes",
        "R1\tHas_negation Arg1:T4 Arg2:T1\t",
        "T5\tDrug 39 51\tchemotherapy",
    ]
)


def test_a_negated_scope_negates_every_concept_inside_it_and_an_or_group_makes_the_line_composite() -> None:
    lines = chia_score.parse(TXT, ANN)
    assert [ln["text"] for ln in lines] == ["No history of asthma or diabetes", "Prior chemotherapy"]
    first, second = lines
    assert {e["text"]: e["negated"] for e in first["concepts"]} == {"asthma": True, "diabetes": True}
    assert first["composite"] is True
    assert [(e["type"], e["negated"]) for e in second["concepts"]] == [("Drug", False)]
    assert second["composite"] is False


def test_the_negation_scope_is_scored_against_the_gold_per_concept() -> None:
    txt = "No asthma\nPrior chemotherapy\nPregnant\n"
    ann = "\n".join(
        [
            "T1\tNegation 0 2\tNo",
            "T2\tCondition 3 9\tasthma",
            "R1\tHas_negation Arg1:T2 Arg2:T1\t",
            "T3\tDrug 16 28\tchemotherapy",
            "T4\tCondition 29 37\tgravid",  # a surface the line does not carry: the rule never reads it
        ]
    )
    res = chia_score.score(chia_score.parse(txt, ann))
    neg = res["negation_scope"]
    assert (neg["tp"], neg["fp"], neg["fn"], neg["tn"], neg["not_found"]) == (1, 0, 0, 1, 1)
    assert (neg["precision"], neg["recall"], neg["f1"]) == (1.0, 1.0, 1.0)
    assert res["lines"] == 3 and res["composite_lines"] == 0
    assert res["entities"] == {"Condition": 2, "Negation": 1, "Drug": 1}


def _zip_of_two_pairs() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for stem in ("a", "b"):
            z.writestr(f"{stem}.txt", "x")
            z.writestr(f"{stem}.ann", "")
    return buf.getvalue()


def test_an_interrupted_extraction_leaves_no_cache_the_next_run_trusts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "scope"
    monkeypatch.setattr(chia_score, "CACHE", cache)
    reply = SimpleNamespace(content=_zip_of_two_pairs(), raise_for_status=lambda: None)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: reply)
    real = Path.write_bytes
    calls: list[Path] = []

    def dying(self: Path, data: bytes) -> int:
        calls.append(self)
        if len(calls) == 3:
            raise OSError("interrupted")
        return real(self, data)

    with monkeypatch.context() as m:
        m.setattr(Path, "write_bytes", dying)
        with pytest.raises(OSError):
            chia_score.fetch()
    assert not cache.exists()
    assert sorted(p.name for p in chia_score.fetch().iterdir()) == ["a.ann", "a.txt", "b.ann", "b.txt"]


def test_an_interrupted_write_leaves_the_previous_scores_json_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "scope"
    folder.mkdir()
    results = tmp_path / "results"
    results.mkdir()
    (results / "scores.json").write_text("previous\n")
    monkeypatch.setattr(chia_score, "RESULTS", results)
    monkeypatch.setattr(chia_score, "fetch", lambda: folder)
    real = Path.write_text

    def dying(self: Path, data: str, *a: Any, **k: Any) -> int:
        real(self, data[: len(data) // 2], *a, **k)
        raise OSError("interrupted")

    monkeypatch.setattr(Path, "write_text", dying)
    with pytest.raises(OSError):
        chia_score.main()
    assert (results / "scores.json").read_text() == "previous\n"
