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

import pytest

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


META: dict[str, Any] = {"commit": "abc123", "snapshot": "2026-10-01", "flags": {"derived.stored_read": False},
                        "consent_state": "reg-1", "list_withheld": False}  # fmt: skip


def _write(tmp_path: Path, name: str, rows: list[dict[str, Any]], store: Any = STORE_ON, **meta: Any) -> Path:
    doc: dict[str, Any] = {"rows": rows, **{k: v for k, v in {**META, **meta}.items() if v is not None}}
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


# ---- the second round: no vacuous pass


def test_a_run_that_read_stored_answers_is_refused(tmp_path: Path, capsys: Any) -> None:
    a = _write(tmp_path, "a.json", _population(5), {"on": True, "read": 3, "live": 2})
    b = _write(tmp_path, "b.json", _population(5), {"on": True, "read": 3, "live": 2})
    assert step9_compare.main([str(a), str(b)]) == 2
    err = capsys.readouterr().err
    assert "a.json" in err and "read 3" in err and "replays stored answers" in err


def test_a_run_with_the_store_on_and_no_read_count_is_refused(tmp_path: Path, capsys: Any) -> None:
    a = _write(tmp_path, "a.json", _population(5), {"on": True, "live": 2})
    b = _write(tmp_path, "b.json", _population(5))
    assert step9_compare.main([str(a), str(b)]) == 2
    assert "judged_store.read" in capsys.readouterr().err


def test_runs_must_state_the_same_commit_snapshot_flag_and_consent(tmp_path: Path, capsys: Any) -> None:
    for key, other in (("commit", "def456"), ("snapshot", "2026-10-02"), ("consent_state", "reg-2"),
                       ("flags", {"derived.stored_read": True})):  # fmt: skip
        a = _write(tmp_path, "a.json", _population(5))
        b = _write(tmp_path, "b.json", _population(5), **{key: other})
        assert step9_compare.main([str(a), str(b)]) == 2
        assert ("derived.stored_read" if key == "flags" else key) in capsys.readouterr().err


def test_a_run_file_lacking_one_of_them_says_which(tmp_path: Path, capsys: Any) -> None:
    a = _write(tmp_path, "a.json", _population(5))
    b = _write(tmp_path, "b.json", _population(5), consent_state=None)
    assert step9_compare.main([str(a), str(b)]) == 2
    err = capsys.readouterr().err
    assert "b.json" in err and "consent_state" in err and "not recorded" in err


def test_a_run_whose_list_was_withheld_counts_every_patient_as_leaving_the_list(tmp_path: Path, capsys: Any) -> None:
    a = _write(tmp_path, "a.json", _population(4))
    b = _write(tmp_path, "b.json", _population(4), list_withheld=True)
    out = tmp_path / "r.json"
    assert step9_compare.main([str(a), str(b), "--out", str(out)]) == 1
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["rules"]["i_list"] is False and rep["pairs"][0]["left_list"] == ["p000", "p001", "p002", "p003"]
    capsys.readouterr()


def test_a_run_that_does_not_say_whether_its_list_was_withheld_is_refused(tmp_path: Path, capsys: Any) -> None:
    a = _write(tmp_path, "a.json", _population(4))
    b = _write(tmp_path, "b.json", _population(4), list_withheld=None)
    assert step9_compare.main([str(a), str(b)]) == 2
    assert "list_withheld" in capsys.readouterr().err


def _two_criteria(n: int, flips: dict[tuple[int, str], str]) -> list[dict[str, Any]]:
    out = []
    for i in range(n):
        crit = [_coded("c0", "pass"), *(_model(c, flips.get((i, c), "pass")) for c in ("c1", "c2"))]
        out.append(_row(f"p{i:03d}", "high", crit))
    return out


def test_the_share_per_criterion_is_reported_and_a_criterion_over_half_is_named(tmp_path: Path, capsys: Any) -> None:
    flips = {(1, "c1"): "unknown", (2, "c1"): "unknown", (3, "c2"): "unknown"}
    rc, rep = _check(tmp_path, [_two_criteria(100, {}), _two_criteria(100, flips)], capsys)
    p = rep["pairs"][0]
    assert p["per_criterion"]["c1"] == {"total": 100, "differing": 2, "share": 0.02}
    assert p["per_criterion"]["c2"]["differing"] == 1 and p["criterion_over_half"] == "c1"
    assert rc == 0  # 3 of 200 is 1.5 %: the per-criterion line is reported, not a gate


def test_no_criterion_is_named_when_none_carries_more_than_half(tmp_path: Path, capsys: Any) -> None:
    flips = {(1, "c1"): "unknown", (2, "c2"): "unknown"}
    _, rep = _check(tmp_path, [_two_criteria(100, {}), _two_criteria(100, flips)], capsys)
    assert rep["pairs"][0]["criterion_over_half"] is None


def test_section_four_names_tier_changes_and_says_the_harm_measure_is_missing_without_labels(
    tmp_path: Path, capsys: Any
) -> None:
    files = [str(_write(tmp_path, f"r{i}.json", _population(100, {3: "unknown"} if i else None))) for i in (0, 1)]
    assert step9_compare.main(files) == 0
    out = capsys.readouterr().out
    assert "p003: r0.json high, r1.json review" in out and "harm measure is not available" in out


def test_section_four_with_a_note_truth_counts_false_demotions_misses_and_unknown_apart(
    tmp_path: Path, capsys: Any
) -> None:
    exc, inc = "GZQO-EXC-11", "GZQO-INC-05"  # an exclusion (truth yes speaks against) and an inclusion (truth no does)
    cases = {"a": (exc, "no", "fail"), "b": (exc, "yes", "pass"), "c": (exc, "yes", "fail"),
             "d": (exc, "unknown", "fail"), "e": (inc, "no", "unknown"), "f": (inc, "yes", "fail"),
             "g": (inc, "yes", "pass")}  # fmt: skip
    rows = [_row(f"p{k}", "review", [_coded("c0", "pass"), _model(c, v)]) for k, (c, _, v) in cases.items()]
    truth = tmp_path / "truth.json"
    truth.write_text(json.dumps({f"p{k}": {c: t} for k, (c, t, _) in cases.items()}), encoding="utf-8")
    files = [str(_write(tmp_path, f"r{i}.json", rows)) for i in (0, 1)]
    out = tmp_path / "r.json"
    assert step9_compare.main([*files, "--note-truth", str(truth), "--out", str(out)]) == 0
    h = json.loads(out.read_text(encoding="utf-8"))["section4"]["harm"]["r0.json"]
    assert h[exc]["false_demotion"] == ["pa/GZQO-EXC-11"] and h[exc]["missed"] == ["pb/GZQO-EXC-11"]
    assert h[exc]["speaks_against"] == 2 and h[exc]["does_not_speak_against"] == 1 and h[exc]["truth_unknown"] == 1
    assert h[inc]["false_demotion"] == ["pf/GZQO-INC-05"] and h[inc]["missed"] == ["pe/GZQO-INC-05"]
    assert "false demotion: pa/GZQO-EXC-11" in capsys.readouterr().out


# ---- OCR 1502-1, 1502-2, 1502-3


def test_a_run_with_no_patient_is_refused(tmp_path: Path, capsys: Any) -> None:
    """OCR 1502-1: two runs that hold no patient compare nothing; they must not pass step 9."""
    files = [str(_write(tmp_path, f"r{i}.json", [])) for i in (0, 1)]
    assert step9_compare.main(files) == 2
    assert "rows empty" in capsys.readouterr().err


def test_a_run_with_no_model_pair_or_no_coded_pair_is_refused_and_says_which(tmp_path: Path, capsys: Any) -> None:
    only_model = [_row("p0", "high", [_model("c1", "pass")])]
    only_coded = [_row("p0", "high", [_coded("c0", "pass")])]
    for rows, missing in ((only_model, "no coded pair"), (only_coded, "no model pair")):
        files = [str(_write(tmp_path, f"r{i}.json", rows)) for i in (0, 1)]
        assert step9_compare.main(files) == 2
        assert missing in capsys.readouterr().err


def test_a_pair_decided_without_a_model_or_a_coded_record_is_counted_and_reported(tmp_path: Path, capsys: Any) -> None:
    def run(v: str) -> list[dict[str, Any]]:
        rows = _population(100)
        rows[0]["criteria"].append({"id": "s2", "verdict": v, "basis": None, "prov": []})
        return rows

    rc, rep = _check(tmp_path, [run("pass"), run("fail")], capsys)
    assert rep["pairs"][0]["other_differing"] == ["p000/s2"] and rep["pairs"][0]["other_total"] == 1
    assert rc == 0  # reported, not gated


def test_a_malformed_row_is_refused_with_the_row_named(tmp_path: Path, capsys: Any) -> None:
    bad_rows: list[Any] = [{"tier": "high", "criteria": []}, "not an object"]
    for bad in bad_rows:
        rows: list[Any] = [*_population(3), bad]
        files = [str(_write(tmp_path, f"r{i}.json", rows)) for i in (0, 1)]
        assert step9_compare.main(files) == 2
        assert "row 3" in capsys.readouterr().err
    rows = _population(3)
    rows[1]["criteria"].append({"verdict": "pass"})
    files = [str(_write(tmp_path, f"r{i}.json", rows)) for i in (0, 1)]
    assert step9_compare.main(files) == 2
    assert "row 1" in capsys.readouterr().err


def test_a_duplicate_patient_or_criterion_is_refused_never_last_wins(tmp_path: Path, capsys: Any) -> None:
    rows = _population(3)
    rows.append(_row("p001", "excluded", [_coded("c0", "pass"), _model("c1", "pass")]))
    files = [str(_write(tmp_path, f"r{i}.json", rows)) for i in (0, 1)]
    assert step9_compare.main(files) == 2
    assert "p001" in capsys.readouterr().err
    rows = _population(3)
    rows[0]["criteria"].append(_model("c1", "fail"))
    files = [str(_write(tmp_path, f"r{i}.json", rows)) for i in (0, 1)]
    assert step9_compare.main(files) == 2
    assert "p000/c1" in capsys.readouterr().err


def test_a_missing_or_unknown_tier_or_verdict_is_refused_and_named(tmp_path: Path, capsys: Any) -> None:
    """Review of #1547 R2: a run whose rows lack their tier or verdict has no screening outcome to compare; read as
    the string "None" it compared equal and passed."""
    for bad in ({"tier": None}, {"tier": "listed"}):
        pop = _population(20)
        pop[4] = {**pop[4], **bad}
        rc, _ = _check(tmp_path, [pop, pop], capsys)
        assert rc == 2, bad
        with pytest.raises(step9_compare.Refused, match=r"row 4 \(patient p004\): tier"):
            step9_compare.load(_write(tmp_path, "t.json", pop))
    for verdict in (None, "maybe"):
        pop = _population(20)
        pop[2]["criteria"][1] = {**pop[2]["criteria"][1], "verdict": verdict}
        if verdict is None:
            del pop[2]["criteria"][1]["verdict"]
        assert _check(tmp_path, [pop, pop], capsys)[0] == 2, verdict
        with pytest.raises(step9_compare.Refused, match="pair p002/c1: verdict"):
            step9_compare.load(_write(tmp_path, "v.json", pop))
