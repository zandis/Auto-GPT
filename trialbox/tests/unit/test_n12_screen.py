"""Blocker 3 of lane G's first real-model accuracy run (the split agreed on #639, 2026-11-15): ``qualify``'s N-12
evidence comes from SCREEN, the product path, not the benchmark prompt path (``tools.trec_ct_eval``).

N-12 is "TREC CT eligible pairs wrongly dropped, unadjusted, at most 5 %" (D-343). Lane G's product-path run
(``tools.public_accuracy``) screens the TREC sets with SCREEN through the gateway and scores them by ids after the
run: one ``score.json`` per set run, its pair rows per language, stratum (``trec2021``, ``trec2022``) and gold label.
``tools/n12_screen.py`` reads those files and writes the evidence ``qualify``'s ``n12`` step reads. It is no evidence
(``NoEvidence``) unless every file comes from a real run at this checkout's HEAD (the file's ``run`` block: ``head``,
the served models, ``stub: false``), names the TREC 2021/22 set once, holds counts that add up, and reaches
:data:`MIN_ELIGIBLE` eligible pairs; and it fails when more than 10 % went unanswered (review of D-791: a stand-in
run, a file read twice or three pairs passed). Synthetic score files, no model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import n12_screen as n12

HEAD = "deadbeef"


def _row(stratum: str, n: int, lost: int, unanswered: int = 0, open_: int = 0, lang: str = "en") -> dict[str, Any]:
    return {"lang": lang, "stratum": stratum, "gold": "eligible", "n": n, "excluded": lost,
            "listed": n - lost - unanswered - open_, "open": open_, "unanswered": unanswered}  # fmt: skip


def _score(
    tmp: Path, rows: list[dict[str, Any]], set_name: str = "trec", run: Any = "real", name: str = "s.json"
) -> Path:
    doc: dict[str, Any] = {"set": set_name, "pairs": {"rows": rows}}
    if run == "real":
        doc["run"] = {"head": HEAD, "models": {"judge": "j-build-1", "verifier": "v-build-1"}, "stub": False}
    elif run is not None:
        doc["run"] = run
    p = tmp / name
    p.write_text(json.dumps(doc), "utf-8")
    return p


BIG = [_row("trec2021", 300, 9), _row("trec2022", 300, 6)]


def test_the_evidence_is_what_qualify_reads_and_says_it_came_from_screen(tmp_path: Path) -> None:
    ev = n12.evidence([_score(tmp_path, BIG)], head=HEAD)
    assert ev["source"] == "screen" and ev["basis"] == "unadjusted" and ev["head"] == HEAD
    assert ev["lost"] == 15 and ev["eligible"] == 600 and ev["rate"] == pytest.approx(0.025)
    assert ev["passed"] is True and ev["ok"] is True and ev["complete"] is True
    assert ev["models"] == {"judge": "j-build-1", "verifier": "v-build-1"} and ev["sets"] == ["trec"]
    assert [f["file"] for f in ev["inputs"]] == ["s.json"] and len(ev["inputs"][0]["sha256"]) == 64
    lo, hi = ev["ci95"]
    assert lo < 0.025 < hi and ev["upper95"] > 0.025 and ev["open"] == {"k": 0, "n": 600}


def test_over_the_gate_fails(tmp_path: Path) -> None:
    ev = n12.evidence([_score(tmp_path, [_row("trec2021", 600, 54)])], head=HEAD)
    assert ev["passed"] is False and ev["rate"] == pytest.approx(0.09)


def test_a_run_that_answered_too_little_fails(tmp_path: Path) -> None:
    ev = n12.evidence([_score(tmp_path, [_row("trec2021", 600, 0, unanswered=300)])], head=HEAD)
    assert ev["complete"] is False and ev["passed"] is False and ev["unanswered"] == {"k": 300, "n": 600}


@pytest.mark.parametrize(
    "run,why",
    [
        (None, "run"),  # a score file from before the run block
        ({"head": HEAD, "models": {"judge": "trialbox-stub-1"}, "stub": True}, "stand-in"),
        ({"head": "0ld", "models": {"judge": "j"}, "stub": False}, "HEAD"),
        ({"head": HEAD, "models": {}, "stub": False}, "models"),
    ],
)
def test_only_a_real_run_at_this_head_is_evidence(tmp_path: Path, run: Any, why: str) -> None:
    """Review: a stand-in run (every pair "open") passed with 0 lost, and the head was stamped at scoring time."""
    with pytest.raises(n12.NoEvidence, match=why):
        n12.evidence([_score(tmp_path, BIG, run=run)], head=HEAD)


def test_a_set_read_twice_is_refused(tmp_path: Path) -> None:
    a = _score(tmp_path, BIG, name="a.json")
    with pytest.raises(n12.NoEvidence, match="twice"):
        n12.evidence([a, a], head=HEAD)
    b = _score(tmp_path, BIG, name="b.json")
    with pytest.raises(n12.NoEvidence, match="twice"):
        n12.evidence([a, b], head=HEAD)


def test_too_few_pairs_is_no_evidence(tmp_path: Path) -> None:
    with pytest.raises(n12.NoEvidence, match="at least"):
        n12.evidence([_score(tmp_path, [_row("trec2021", 3, 0)])], head=HEAD)


@pytest.mark.parametrize("set_name", ["trec2023", "trecSYNTH", "sigir"])
def test_only_the_trec_2021_and_2022_set_counts(tmp_path: Path, set_name: str) -> None:
    """D-343's figure is TREC CT 2021/22; another set needs its own decision."""
    with pytest.raises(n12.NoEvidence, match="TREC"):
        n12.evidence([_score(tmp_path, BIG, set_name=set_name)], head=HEAD)


@pytest.mark.parametrize(
    "bad",
    [
        {"excluded": -1},
        {"unanswered": -500},
        {"n": True},
        {"excluded": 2.9},
        {"listed": 5},  # the cells no longer add up to n
        {"unanswered": None},
    ],
)
def test_counts_that_do_not_add_up_are_refused(tmp_path: Path, bad: dict[str, Any]) -> None:
    row = _row("trec2021", 600, 10) | bad
    with pytest.raises(n12.NoEvidence):
        n12.evidence([_score(tmp_path, [row])], head=HEAD)


def test_a_malformed_file_is_refused_with_a_sentence(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text("[1, 2]", "utf-8")
    with pytest.raises(n12.NoEvidence, match="x.json"):
        n12.evidence([p], head=HEAD)


def test_the_head_is_this_checkouts() -> None:
    """Review: ``git rev-parse`` ran in the caller's folder."""
    import subprocess

    git = ["git", "rev-parse", "HEAD"]
    want = subprocess.run(git, cwd=n12.ROOT, capture_output=True, text=True, check=True).stdout.strip()
    assert n12.git_head() == want


def test_qualify_accepts_the_written_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools import qualify

    out = tmp_path / "n12.json"
    monkeypatch.setattr(n12, "git_head", lambda: HEAD)
    assert n12.main([str(_score(tmp_path, BIG)), "--out", str(out)]) == 0
    monkeypatch.setattr(qualify, "git_head", lambda: (HEAD, False))
    ctx: Any = type("Ctx", (), {"opts": type("O", (), {"stub": False, "evidence": {"n12": out}})()})()
    assert qualify.step_evidence("n12")(ctx).status == "passed"


def test_main_exits_non_zero_when_it_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(n12, "git_head", lambda: HEAD)
    out = tmp_path / "n12.json"
    assert n12.main([str(_score(tmp_path, [_row("trec2021", 600, 60)])), "--out", str(out)]) == 1
    assert json.loads(out.read_text("utf-8"))["passed"] is False
