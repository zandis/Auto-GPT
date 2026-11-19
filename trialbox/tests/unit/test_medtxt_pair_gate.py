"""Card 10G-22 (D-1325): the MedTxt Japanese pair score is a standing gate on recorded answers.

The candidate pair named in ``eval/medtxt/gate.json`` must pass review 17 §7.3 rules 1 and 2 against the control,
on the recorded answers in the tree (no model, no network); a planted worse build, written from today's recorded
answers with a few answers changed, fails it.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from tools import medtxt_gate as g
from tools.mlbench import BLOCKS

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks` on every tier; no database

CTRL = json.loads(g.GATE.read_text(encoding="utf-8"))["control"]


def _rows(model: str) -> list[dict[str, Any]]:
    with gzip.open(g.raw_file(model), "rt", encoding="utf-8") as fh:
        return [json.loads(x) for x in fh]


def _write(raw: Path, model: str, rows: list[dict[str, Any]]) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    with gzip.open(g.raw_file(model, raw), "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _planted(tmp_path: Path, change: Any) -> Path:
    """A copy of today's recorded pair as a build named ``planted/<model>``, with ``change(rows_j, rows_v)`` applied."""
    raw = tmp_path / "raw"
    rj, rv = _rows(CTRL["judge"]), _rows(CTRL["verifier"])
    change(rj, rv)
    _write(raw, "planted/judge", rj)
    _write(raw, "planted/verifier", rv)
    return raw


def _ids(certainty: str, blocked: bool) -> list[str]:
    key = g.load_key()
    rj = {r["annotation_id"]: r for r in _rows(CTRL["judge"])}
    rv = {r["annotation_id"]: r for r in _rows(CTRL["verifier"])}
    out = []
    for aid, c in sorted(key.items()):
        both = all((x.get(aid) or {}).get("label") in BLOCKS for x in (rj, rv))
        if c == certainty and both is blocked and not rj[aid].get("error") and not rv[aid].get("error"):
            out.append(aid)
    return out


def test_todays_candidate_passes_the_gate() -> None:
    v = g.gate()
    assert v["passed"], v["fails"]


def test_the_control_reproduces_the_recorded_scores() -> None:
    """The committed key and the recorded answers give the pair figures of eval/medtxt/results/scores.json."""
    rec = json.loads((g.MEDTXT / "results" / "scores.json").read_text(encoding="utf-8"))
    pair = rec["both_must_block"][f"{CTRL['judge']}+{CTRL['verifier']}|ja"]
    s = g.score_pair(CTRL["judge"], CTRL["verifier"], g.load_key())
    for c in ("positive", "negative", "suspicious", "absent"):
        assert (s["rates"][c]["blocked"], s["rates"][c]["n"]) == (pair[c]["blocked"], pair[c]["n"]), c
    assert s["unanswered"] == pair["unanswered"] and s["missing"] == 0
    assert (pair["positive"]["blocked"], pair["negative"]["blocked"]) == (455, 38)  # 69.0 % and 10.9 % (review 17)


def _block_negated(tmp_path: Path, n: int) -> Path:
    """Today's pair with ``n`` more stated-absent findings blocked by both (unanswered unchanged)."""
    flip = set(_ids("negative", blocked=False)[:n])

    def change(rj: list[dict[str, Any]], rv: list[dict[str, Any]]) -> None:
        for r in (*rj, *rv):
            if r["annotation_id"] in flip:
                r["label"] = "excluded"

    return _planted(tmp_path, change)


def test_a_planted_build_that_blocks_more_stated_absent_findings_fails(tmp_path: Path) -> None:
    v = g.gate("planted/judge", "planted/verifier", _block_negated(tmp_path, 5))  # 43 of 349: 12.3 %, > 10.9 % + 1
    assert not v["passed"]
    assert any(f.startswith("rule 1: stated-absent blocked 0.123 (43/349) > the control's 0.109") for f in v["fails"])
    assert any(f.startswith("rule 1: stated-absent blocked 95 % upper bound 0.162") for f in v["fails"]), v["fails"]


def test_one_more_stated_absent_block_passes_and_three_fail_on_the_upper_bound(tmp_path: Path) -> None:
    one = g.gate("planted/judge", "planted/verifier", _block_negated(tmp_path / "1", 1))  # 39: 11.2 %, UB 14.9 %
    assert one["passed"], one["fails"]
    three = g.gate("planted/judge", "planted/verifier", _block_negated(tmp_path / "3", 3))  # 41: 11.7 %, UB 15.5 %
    assert three["fails"] == ["rule 1: stated-absent blocked 95 % upper bound 0.155 not under 0.15"]


def test_a_planted_build_that_catches_fewer_present_findings_fails(tmp_path: Path) -> None:
    drop = set(_ids("positive", blocked=True)[:1])  # one present finding fewer: 455 -> 454 of 659

    def change(rj: list[dict[str, Any]], rv: list[dict[str, Any]]) -> None:
        for r in rj:
            if r["annotation_id"] in drop:
                r["label"] = "not excluded"

    v = g.gate("planted/judge", "planted/verifier", _planted(tmp_path, change))
    assert not v["passed"]
    assert any(f.startswith("rule 2: present blocked 0.689") for f in v["fails"]), v["fails"]


def test_a_planted_build_that_answers_fewer_items_fails(tmp_path: Path) -> None:
    """An unanswered item is never a block: a build that errors more must not pass rule 1 by saying nothing."""
    gone = set(_ids("negative", blocked=True)[:10])

    def change(rj: list[dict[str, Any]], rv: list[dict[str, Any]]) -> None:
        rj[:] = [r for r in rj if r["annotation_id"] not in gone]

    v = g.gate("planted/judge", "planted/verifier", _planted(tmp_path, change))
    assert not v["passed"]
    assert any(f.startswith("not the same items: 10 answers") for f in v["fails"]), v["fails"]
    assert any(f.startswith("unanswered 159 > the control's 149") for f in v["fails"]), v["fails"]


def test_the_gate_command_exits_1_on_a_planted_worse_build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw = _block_negated(tmp_path, 5)
    assert g.main(["check", "--judge", "planted/judge", "--verifier", "planted/verifier", "--raw", str(raw)]) == 1
    assert "medtxt gate: FAILED: rule 1" in capsys.readouterr().out
    assert g.main(["check"]) == 0
    assert capsys.readouterr().out.endswith("medtxt gate: passed\n")


def test_the_key_holds_ids_and_certainty_only() -> None:
    """The committed key carries no report text (the corpus stays in .cache, never committed)."""
    k = json.loads(g.KEY.read_text(encoding="utf-8"))
    assert k["licence"] == "CC BY 4.0" and len(k["items"]) == 1677
    assert set(k["items"].values()) == {"positive", "negative", "suspicious", "absent"}
    assert all(aid.split(":")[0] in ("CR", "RR") and "|" in aid for aid in k["items"])
    assert set(k) == {"what", "source", "licence", "corpus_sha256", "items"}


def test_a_missing_recorded_build_is_named(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no recorded answers for nobody/none"):
        g.gate("nobody/none", CTRL["verifier"], tmp_path)
