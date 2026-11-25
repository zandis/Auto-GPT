"""INT-S-F: the step-9 checker (``tools/step9_compare.py``) on small synthetic run files.

A run file is ``{"judged_store": {"on", "read", "live"}, "rows": [CandidateRow...]}``: the SCREEN summary's
``judged_store`` and every patient's row (excluded ones too), with the product's own field names. Rules, for the same
patients on the same build across runs:

* (i) no patient leaves the list (tier ``high`` or ``review``); a verdict may move between pass and unknown and a
  patient between the two tiers;
* (ii) no coded (``basis: coded``) verdict differs at all;
* (iii) the share of model pairs (a call behind them) whose verdict differs between two runs is reported with the
  pairs named, and is at most 3 %;
* the quoted evidence (note reference, quote date) is compared and "same verdict, different evidence" is counted, not
  failed;
* the store state of each run is printed; runs whose state differs or is not recorded are refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools import step9_compare


def _row(pid: str, tier: str, criteria: list[dict[str, Any]]) -> dict[str, Any]:
    return {"pid": pid, "tier": tier, "criteria": criteria, "actions": []}


def _model(cid: str, verdict: str, *, ref: str = "DocumentReference/n1", date: str = "2026-10-01") -> dict[str, Any]:
    ev = {"resource_refs": [ref], "quote": "synthetic quote", "quote_date": date}
    return {"id": cid, "verdict": verdict, "basis": "pair", "prov": [f"call-{cid}-{verdict}"], "evidence": ev}


def _coded(cid: str, verdict: str) -> dict[str, Any]:
    return {
        "id": cid,
        "verdict": verdict,
        "basis": "coded",
        "prov": [],
        "evidence": {"resource_refs": ["Condition/c1"]},
    }


STORE_ON = {"on": True, "read": 0, "live": 5}


def _write(tmp_path: Path, name: str, rows: list[dict[str, Any]], store: Any = STORE_ON) -> Path:
    doc: dict[str, Any] = {"rows": rows}
    if store is not None:
        doc["judged_store"] = store
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _population(n: int, verdicts: dict[int, str] | None = None) -> list[dict[str, Any]]:
    """n patients, each one coded and one model pair; ``verdicts`` overrides the model verdict of patient i."""
    out = []
    for i in range(n):
        v = (verdicts or {}).get(i, "pass")
        out.append(_row(f"p{i:03d}", "high" if v == "pass" else "review", [_coded("c0", "pass"), _model("c1", v)]))
    return out


def _check(tmp_path: Path, runs: list[list[dict[str, Any]]], capsys: Any, **kw: Any) -> tuple[int, dict[str, Any]]:
    files = [str(_write(tmp_path, f"r{i}.json", rows, **kw)) for i, rows in enumerate(runs)]
    out = tmp_path / "report.json"
    rc = step9_compare.main([*files, "--out", str(out)])
    capsys.readouterr()
    return rc, json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}


def test_identical_runs_pass(tmp_path: Path, capsys: Any) -> None:
    rc, rep = _check(tmp_path, [_population(20), _population(20)], capsys)
    assert rc == 0 and rep["pass"] is True
    assert rep["pairs"][0]["model_differing"] == [] and rep["pairs"][0]["model_share"] == 0.0


def test_a_flip_between_pass_and_unknown_that_moves_tiers_stays_on_the_list(tmp_path: Path, capsys: Any) -> None:
    rc, rep = _check(tmp_path, [_population(100), _population(100, {7: "unknown"})], capsys)
    assert rc == 0, rep  # 1 of 100 differs: under the bound
    p = rep["pairs"][0]
    assert p["model_differing"] == ["p007/c1"] and p["tier_moves"] == ["p007"] and p["left_list"] == []


def test_a_patient_who_leaves_the_list_fails_and_is_named(tmp_path: Path, capsys: Any) -> None:
    second = _population(20)
    second[3] = _row("p003", "excluded", [_coded("c0", "pass"), _model("c1", "fail")])
    rc, rep = _check(tmp_path, [_population(20), second], capsys)
    assert rc == 1 and rep["rules"]["i_list"] is False
    assert rep["pairs"][0]["left_list"] == ["p003"]


def test_a_patient_missing_from_a_run_has_left_the_list(tmp_path: Path, capsys: Any) -> None:
    rc, rep = _check(tmp_path, [_population(20), _population(20)[:-1]], capsys)
    assert rc == 1 and rep["pairs"][0]["left_list"] == ["p019"]


def test_a_coded_verdict_that_differs_fails_whatever_the_share(tmp_path: Path, capsys: Any) -> None:
    second = _population(1000)
    second[0]["criteria"][0] = _coded("c0", "fail")
    rc, rep = _check(tmp_path, [_population(1000), second], capsys)
    assert rc == 1 and rep["rules"]["ii_coded"] is False and rep["rules"]["iii_share"] is True
    assert rep["pairs"][0]["coded_differing"] == ["p000/c0"]


def test_the_bound_is_at_most_three_percent_exactly_three_passes(tmp_path: Path, capsys: Any) -> None:
    flips = {i: "unknown" for i in (1, 2, 3)}
    rc, rep = _check(tmp_path, [_population(100), _population(100, flips)], capsys)
    p = rep["pairs"][0]
    assert p["model_total"] == 100 and len(p["model_differing"]) == 3 and p["model_share"] == 0.03
    assert rc == 0 and rep["rules"]["iii_share"] is True


def test_one_over_three_percent_fails(tmp_path: Path, capsys: Any) -> None:
    flips = {i: "unknown" for i in (1, 2, 3, 4)}
    rc, rep = _check(tmp_path, [_population(100), _population(100, flips)], capsys)
    assert rc == 1 and rep["rules"]["iii_share"] is False
    assert rep["pairs"][0]["model_differing"] == ["p001/c1", "p002/c1", "p003/c1", "p004/c1"]


def test_with_three_runs_the_bound_holds_for_every_pair_of_runs(tmp_path: Path, capsys: Any) -> None:
    a = _population(100)
    b = _population(100, {i: "unknown" for i in (1, 2)})
    c = _population(100, {i: "unknown" for i in (3, 4)})  # a-b 2 %, a-c 2 %, b-c 4 %
    rc, rep = _check(tmp_path, [a, b, c], capsys)
    assert rc == 1 and len(rep["pairs"]) == 3
    assert [len(p["model_differing"]) for p in rep["pairs"]] == [2, 2, 4]


def test_same_verdict_different_evidence_is_counted_not_failed(tmp_path: Path, capsys: Any) -> None:
    second = _population(10)
    second[2]["criteria"][1] = _model("c1", "pass", ref="DocumentReference/n9")
    second[5]["criteria"][1] = _model("c1", "pass", date="2026-09-30")
    rc, rep = _check(tmp_path, [_population(10), second], capsys)
    p = rep["pairs"][0]
    assert rc == 0 and p["same_verdict_different_evidence"] == ["p002/c1", "p005/c1"]
    assert p["model_differing"] == []


def test_the_store_state_of_each_run_is_reported(tmp_path: Path, capsys: Any) -> None:
    files = [str(_write(tmp_path, f"r{i}.json", _population(5), {"on": False, "read": 0, "live": 5})) for i in (0, 1)]
    assert step9_compare.main(files) == 0
    out = capsys.readouterr().out
    assert out.count("judged-pair store: off") == 2


def test_runs_with_different_store_states_are_refused(tmp_path: Path, capsys: Any) -> None:
    a = _write(tmp_path, "a.json", _population(5), {"on": True, "read": 0, "live": 5})
    b = _write(tmp_path, "b.json", _population(5), {"on": False, "read": 0, "live": 5})
    assert step9_compare.main([str(a), str(b)]) == 2
    assert "store state differs" in capsys.readouterr().err


def test_a_run_that_does_not_record_the_store_state_is_refused_and_says_what_is_missing(
    tmp_path: Path, capsys: Any
) -> None:
    a = _write(tmp_path, "a.json", _population(5))
    b = _write(tmp_path, "b.json", _population(5), None)
    assert step9_compare.main([str(a), str(b)]) == 2
    err = capsys.readouterr().err
    assert "b.json" in err and "judged_store" in err and "not recorded" in err


def test_a_store_block_without_a_boolean_on_is_refused(tmp_path: Path, capsys: Any) -> None:
    a = _write(tmp_path, "a.json", _population(5))
    b = _write(tmp_path, "b.json", _population(5), {"read": 0, "live": 5})
    assert step9_compare.main([str(a), str(b)]) == 2
    assert "judged_store.on" in capsys.readouterr().err


def test_fewer_than_two_runs_is_refused(tmp_path: Path, capsys: Any) -> None:
    assert step9_compare.main([str(_write(tmp_path, "a.json", _population(5)))]) == 2
    assert "at least two" in capsys.readouterr().err
