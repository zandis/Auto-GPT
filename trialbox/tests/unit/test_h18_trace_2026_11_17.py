"""Card H-18 (lane H, 2026-11-17): the patient behind each exclusion, read from a stored run (D-1134).

``tools.public_accuracy.trace`` names what the replay counts: each eligible pair the box excluded, on which line, at
which stage, and the model calls on that line; and each SCREEN job's note questions by the models' replies. The run
here is made up, in the records' real shape (launch P2b's ``built/gold`` and ``work/``): synthetic patients, notes,
protocols and pseudonyms, no patient data.
"""

from __future__ import annotations

import io
import json
import tarfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tools.public_accuracy import trace

pytestmark = pytest.mark.nodb

MRN0 = 79900000
REF = date(2026, 11, 17)
NOTE = "A 30-year-old man with a cough. The scan showed no lesion."


def _call(job: str, crit: str, out: str, alias: str = "j-workhorse", *, day: str = "2026-11-10",
          repair: bool = False) -> dict[str, Any]:  # fmt: skip
    v = {"criterion_text": crit, "note_question": f"{crit}?", "index_date": REF.isoformat(),
         "excerpts": [{"date": day, "note_type": "consult", "text": NOTE}]}  # fmt: skip
    prompt = [{"role": "system", "content": "made up"},
              {"role": "user", "content": "INPUT:\n```json\n" + json.dumps(v, indent=1) + "\n```"}]  # fmt: skip
    if repair:
        prompt += [{"role": "assistant", "content": "{}"}, {"role": "user", "content": "Return only corrected JSON."}]
    return {"attributes": {"tb.prompt": "judge@5", "tb.model_alias": alias, "tb.study_id": job},
            "call_id": f"c{len(out)}", "output": out, "prompt": prompt, "ts": "2026-11-17T08:00:00+00:00"}  # fmt: skip


def _reply(verdict: str, quote: str | None) -> str:
    return json.dumps({"verdict": verdict, "reason": "made up", "quote": quote, "quote_date": None, "confidence": 1.0})


def make_run(root: Path) -> Path:
    d = root / "set"
    (d / "built" / "gold").mkdir(parents=True)
    (d / "work").mkdir()
    g = d / "built" / "gold"
    g.joinpath("ids.json").write_text(json.dumps({"set": "made", "patients": {"p-1": str(MRN0 + 1),
                                      "p-2": str(MRN0 + 2), "p-3": str(MRN0 + 3)}}))  # fmt: skip
    pairs = [{"label": "eligible", "mrn": str(MRN0 + 1), "patient": "p-1", "ruleset": "RS-A", "trial": "T-A"},
             {"label": "eligible", "mrn": str(MRN0 + 2), "patient": "p-2", "ruleset": "RS-B", "trial": "T-B"},
             {"label": "not_refer", "mrn": str(MRN0 + 3), "patient": "p-3", "ruleset": "RS-A", "trial": "T-A"}]  # fmt: skip
    g.joinpath("pairs.jsonl").write_text("".join(json.dumps(p) + "\n" for p in pairs))
    crit = {"kind": "inclusion", "label": "included", "mrn": str(MRN0 + 2), "patient": "p-2", "ruleset": "RS-B",
            "text": "Cough", "trial": "T-B"}  # fmt: skip
    g.joinpath("criteria.jsonl").write_text(json.dumps(crit) + "\n")
    g.joinpath("written.json").write_text(json.dumps({"RS-A": ["Aged 40 years or older"]}))
    draft_a = [{"id": "A-INC-01", "kind": "inclusion", "class": "structured", "text": "Aged 40 years or older",
                "logic": {"age": {"min": 40.0}}, "flags": []}]  # fmt: skip
    draft_b = [{"id": "B-INC-01", "kind": "inclusion", "class": "mixed", "text": "Cough", "logic": {}, "flags": []},
               {"id": "B-INC-02", "kind": "inclusion", "class": "note", "text": "A lesion fit for surgery",
                "logic": {}, "flags": []}]  # fmt: skip
    fail_a = {"tier": "excluded", "verdicts": [{"id": "A-INC-01", "verdict": "fail", "basis": "coded", "quote": None}]}
    answers = {
        "RS-A": {"draft": draft_a, "patients": {"pid1": fail_a, "pid3": fail_a}},
        "RS-B": {"draft": draft_b, "patients": {"pid2": {"tier": "excluded", "verdicts": [
            {"id": "B-INC-01", "verdict": "pass", "basis": "pair", "quote": "cough"},
            {"id": "B-INC-02", "verdict": "fail", "basis": "notes", "quote": "The scan showed no lesion."}]}}},
    }  # fmt: skip
    w = d / "work"
    w.joinpath("answers.json").write_text(json.dumps(answers))
    w.joinpath("pidmap.json").write_text(json.dumps({str(MRN0 + i): f"pid{i}" for i in (1, 2, 3)}))
    w.joinpath("progress.json").write_text(json.dumps({"RS-A": {"screen_job": "JA"}, "RS-B": {"screen_job": "JB"}}))
    day2 = "2026-08-28"  # REF - (7 + 2*37 % 300) days: patient 2's placed visit
    traces = [_call("JB", "A lesion fit for surgery", _reply("fail", "The scan showed no lesion."), day=day2),
              _call("JB", "A lesion fit for surgery", _reply("fail", "no such words"), "v-verifier", day=day2),
              _call("JB", "Cough", _reply("unknown", None), day="2026-01-01"),
              _call("JB", "Cough", '{"verdict": "unknown", "reason": "\r\r\r', "v-verifier", day="2026-01-01"),
              _call("JB", "Cough", _reply("unknown", None), day="2026-01-01", repair=True)]  # fmt: skip
    w.joinpath("raw-traces.json").write_text(json.dumps({"since": "x", "calls": 5, "traces": traces}))
    return d


def test_each_eligible_pair_excluded_is_named_with_its_line_stage_and_calls(tmp_path: Path) -> None:
    rows = trace.exclusions(make_run(tmp_path))
    assert [(r["patient"], r["ruleset"]) for r in rows] == [("p-1", "RS-A"), ("p-2", "RS-B")]  # not the not_refer
    a, b = rows
    (la,) = a["failed_lines"]
    assert la["written_by_the_benchmark"] is True and la["a_gold_row_judges_it"] is False
    assert la["stage"].startswith("S1") and la["logic"] == {"age": {"min": 40.0}} and la["calls"] == []
    (lb,) = b["failed_lines"]  # the passing line is not listed
    assert lb["id"] == "B-INC-02" and lb["stage"].startswith("S3/S4") and not lb["written_by_the_benchmark"]
    assert [(c["model"], c["verdict"], c["quote_in_excerpts"]) for c in lb["calls"]] == [
        ("j-workhorse", "fail", True), ("v-verifier", "fail", False)]  # fmt: skip
    assert b["criterion_labels"] == ["inclusion included: Cough"]


def test_a_patient_or_protocol_lists_every_excluded_pair_whatever_its_label(tmp_path: Path) -> None:
    d = make_run(tmp_path)
    assert [r["patient"] for r in trace.exclusions(d, ruleset="RS-A")] == ["p-1", "p-3"]
    assert [r["label"] for r in trace.exclusions(d, patient="p-3")] == ["not_refer"]
    assert trace.exclusions(d, patient=str(MRN0 + 2))[0]["patient"] == "p-2"


def test_judged_groups_questions_says_repairs_and_no_reply_and_joins_the_visit_day(tmp_path: Path) -> None:
    j = trace.judged(make_run(tmp_path), ref=REF, mrn0=MRN0)
    assert j["questions"] == 2
    assert j["patterns"] == {"J:fail V:fail": 1, "J:unknown V:no reply (not JSON) J:unknown+repair": 1}
    rows = {r["criterion"]: r for r in j["jobs"]["JB"]}
    assert rows["A lesion fit for surgery"]["patients_on_that_visit_day"] == ["p-2"]
    assert rows["Cough"]["patients_on_that_visit_day"] == [] and j["questions_on_no_visit_day"] == 1
    assert trace.judged(make_run(tmp_path / "b"))["questions_on_no_visit_day"] is None  # no --ref: no join


def test_visit_days_follow_the_builders_formula() -> None:
    days = trace.visit_days({"patients": {"x": str(MRN0 + 1), "y": str(MRN0 + 301)}}, REF, MRN0)
    assert days == {"2026-10-04": ["x", "y"]}  # 7 + 37 days before; i and i + 300 share a day


def test_the_cli_reads_a_tarball_and_refuses_an_unsafe_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = make_run(tmp_path / "src")
    tgz = tmp_path / "made.tgz"
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(d / "built", arcname="built")
        tar.add(d / "work", arcname="work")
    out = tmp_path / "r.json"
    assert trace.main([str(tgz), "--json", str(out), "--scratch", str(tmp_path / "scr")]) == 0
    assert "p-1 (79900001) x T-A [RS-A], gold eligible" in capsys.readouterr().out
    assert json.loads(out.read_text())["sets"]["made"]["exclusions"][1]["patient"] == "p-2"
    bad = tmp_path / "bad.tgz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    assert trace.main([str(bad)]) == 2
