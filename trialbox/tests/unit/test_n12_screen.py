"""Blocker 3 of lane G's first real-model accuracy run (the split agreed on #639, 2026-11-15): ``qualify``'s N-12
evidence comes from SCREEN, the product path, not the benchmark prompt path (``tools.trec_ct_eval``).

N-12 is "TREC CT eligible pairs wrongly dropped, unadjusted, at most 5 %" (D-343). Lane G's product-path run
(``tools.public_accuracy``) screens the TREC sets with SCREEN through the gateway and scores them by ids after the run:
per language, ``eligible_lost`` (eligible pairs the box excluded, of the eligible pairs) and the pairs it never
answered. ``tools/n12_screen.py`` reads those score files and writes the evidence ``qualify``'s ``n12`` step reads:
``passed``, ``basis: "unadjusted"``, ``source: "screen"``, ``head``, the counts with exact intervals, and the files
it read. A run that left more than 10 % of the eligible pairs unanswered is no evidence (``complete: false``), so a box
that answered nothing cannot pass. Synthetic score files, no model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import n12_screen as n12


def _score(tmp: Path, name: str, set_name: str, lost: int, n: int, unanswered: int = 0, lang: str = "en") -> Path:
    doc = {
        "set": set_name,
        "pairs": {
            "rows": [
                {"lang": lang, "stratum": "", "gold": "eligible", "n": n, "excluded": lost,
                 "listed": n - lost - unanswered, "open": 0, "unanswered": unanswered},
            ],
            "summary": {lang: {"eligible_lost": {"k": lost, "n": n}}},
        },
    }  # fmt: skip
    p = tmp / name
    p.write_text(json.dumps(doc), "utf-8")
    return p


def test_the_evidence_is_what_qualify_reads_and_says_it_came_from_screen(tmp_path: Path) -> None:
    a = _score(tmp_path, "trec2021.json", "trec2021", 3, 100)
    b = _score(tmp_path, "trec2022.json", "trec2022", 2, 100)
    ev = n12.evidence([a, b], head="abc123")
    assert ev["source"] == "screen" and ev["basis"] == "unadjusted" and ev["head"] == "abc123"
    assert ev["lost"] == 5 and ev["eligible"] == 200 and ev["rate"] == pytest.approx(0.025)
    assert ev["passed"] is True and ev["ok"] is True and ev["complete"] is True
    assert ev["sets"] == ["trec2021", "trec2022"]
    assert [f["file"] for f in ev["inputs"]] == ["trec2021.json", "trec2022.json"]
    assert all(len(f["sha256"]) == 64 for f in ev["inputs"])
    lo, hi = ev["ci95"]
    assert lo < 0.025 < hi and ev["upper95"] > 0.025


def test_over_the_gate_fails(tmp_path: Path) -> None:
    ev = n12.evidence([_score(tmp_path, "t.json", "trec2021", 9, 100)], head="h")
    assert ev["passed"] is False and ev["rate"] == pytest.approx(0.09)


def test_a_run_that_answered_too_little_is_no_evidence(tmp_path: Path) -> None:
    """0 of 100 lost, but 60 never answered: it proves nothing."""
    ev = n12.evidence([_score(tmp_path, "t.json", "trec2021", 0, 100, unanswered=60)], head="h")
    assert ev["complete"] is False and ev["passed"] is False
    assert ev["unanswered"] == {"k": 60, "n": 100}


def test_only_the_trec_sets_and_english_count(tmp_path: Path) -> None:
    trec = _score(tmp_path, "t.json", "trec2023", 1, 50)
    sigir = _score(tmp_path, "s.json", "sigir", 40, 50)
    ev = n12.evidence([trec, sigir], head="h")
    assert ev["sets"] == ["trec2023"] and ev["eligible"] == 50
    with pytest.raises(n12.NoEvidence, match="TREC"):
        n12.evidence([sigir], head="h")


def test_qualify_accepts_the_written_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The file ``main`` writes passes ``qualify``'s ``n12`` check at the same HEAD."""
    from tools import qualify

    score = _score(tmp_path, "t.json", "trec2021", 2, 100)
    out = tmp_path / "n12.json"
    monkeypatch.setattr(n12, "git_head", lambda: "deadbeef")
    assert n12.main([str(score), "--out", str(out)]) == 0
    monkeypatch.setattr(qualify, "git_head", lambda: ("deadbeef", False))
    ctx: Any = type("Ctx", (), {"opts": type("O", (), {"stub": False, "evidence": {"n12": out}})()})()
    res = qualify.step_evidence("n12")(ctx)
    assert res.status == "passed", res


def test_main_says_so_and_exits_non_zero_when_it_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(n12, "git_head", lambda: "h")
    out = tmp_path / "n12.json"
    assert n12.main([str(_score(tmp_path, "t.json", "trec2021", 20, 100)), "--out", str(out)]) == 1
    assert json.loads(out.read_text("utf-8"))["passed"] is False
