"""Lane G, after run 20261114T061459Z-02858674 (public data, the real pair): the scenario parts' calls and cases.

1. B15: the run recorded 0 model calls for both public scenarios. The MedTxt-CR scenario's box writes the gateway's
   audit into its own work folder (``<work>/gw-audit``) and the TREC CT scenario calls the servers straight; the part
   read only ``gw-audit-scenario``, and removed the work folder first. The part now reads both before the folder
   goes, and its throughput counts them.
2. The scenario parts kept no per-case answer, so the run could show five of eight negated conditions and could not
   say which TREC criteria lost the twelve eligible pairs. The public scenarios now keep each case
   (``parts/scenario-<name>/answers.jsonl.gz``) and a summary in the part's result.

Each test failed before the change. No model, no cloud, no corpus: synthetic data in the corpora's shapes."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools import complete_run as cr
from tools import mlbench, pin_model, scenarios
from tools import run_metrics as rm
from tools.e2e_simple import Stage


def _audit_line(endpoint: str, latency_ms: int, event: str = "llm.gateway.call") -> str:
    now = datetime.now().astimezone().isoformat()
    return json.dumps({"ts": now, "event": event, "detail": {"endpoint": endpoint, "latency_ms": latency_ms,
                                                             "tokens_in": 100, "tokens_out": 20}})  # fmt: skip


def _cached_answer(folder: Path, model: str, n: int, seconds: float = 0.5) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    data = {"model": model, "choices": [{"message": {"content": "{}"}}], "_seconds": seconds,
            "usage": {"prompt_tokens": 300, "completion_tokens": 30}}  # fmt: skip
    (folder / f"{n:064x}.json").write_text(json.dumps(data), encoding="utf-8")


def _args(tmp_path: Path, scenario: str, **kw: Any) -> argparse.Namespace:
    return argparse.Namespace(part="scenario", scenario=scenario, lang="ja", model="stub", dir=tmp_path,
                              shots=tmp_path / "shots", run_id="r-test", resume=False, keep_work=False,
                              live_record=None, patients=5000, **kw)  # fmt: skip


# ---------------------------------------------------------------- 1. B15
def test_a_scenarios_own_calls_reach_the_parts_throughput(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def runner(_a: Any, work: Path) -> scenarios.Result:
        (work / "gw-audit").mkdir(parents=True)
        lines = [_audit_line("serving", 2000), _audit_line("verifier", 1000), _audit_line("serving", 0, "llm.x")]
        (work / "gw-audit" / "audit.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        _cached_answer(work / "responses", pin_model.JUDGE_SERVED, 1)
        res = scenarios.Result("fake")
        st = Stage("fake stage")
        st.check("ran", True, "")
        res.stages.append(st)
        res.block = {"input": "synthetic", "model_calls": 3}
        return res

    monkeypatch.setitem(scenarios.RUNNERS, "fake", runner)
    monkeypatch.setitem(scenarios.TITLES, "fake", "a synthetic scenario")
    monkeypatch.setattr("tools.pglocal.for_work", lambda _w: None)
    monkeypatch.setattr(cr, "shoot", lambda items, *_a, **_k: {i["name"]: {"ok": True, "status": 200} for i in items})
    a = _args(tmp_path, "fake")
    assert cr.run_part(a) == 0
    res = json.loads((tmp_path / "parts" / "scenario-fake.json").read_text(encoding="utf-8"))
    th = res["throughput"]
    assert th["calls"] == 3 and th["direct"] == 1
    assert th["endpoints"]["serving"]["calls"] == 2 and th["endpoints"]["verifier"]["calls"] == 1
    assert "gateway audit" in th["source"] and "straight to the model servers" in th["source"]
    assert "_calls" not in res and "_refused" not in res and not (tmp_path / "scenario-fake").exists()


def test_direct_calls_read_the_response_cache(tmp_path: Path) -> None:
    _cached_answer(tmp_path, pin_model.VERIFIER_SERVED, 1, 1.25)
    _cached_answer(tmp_path, "something-else", 2)
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    (tmp_path / "no-choices.json").write_text(json.dumps({"model": "x"}), encoding="utf-8")
    calls = rm.direct_calls(tmp_path, {pin_model.VERIFIER_SERVED: "verifier"})
    assert sorted(c["endpoint"] for c in calls) == ["direct", "verifier"]
    v = next(c for c in calls if c["endpoint"] == "verifier")
    assert v["latency_s"] == 1.25 and v["tokens_in"] == 300 and v["tokens_out"] == 30 and v["direct"] is True
    assert rm.call_stats(calls)["source"] == rm.DIRECT_SOURCE
    assert "direct" not in rm.call_stats([{**v, "direct": False}])  # a gateway-only part reads as before
    assert rm.direct_calls(tmp_path / "absent", {}) == []


# ---------------------------------------------------------------- 2. the cases of the TREC CT scenario
def _trec(monkeypatch: pytest.MonkeyPatch) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    pairs = [{"year": "2021", "patient": "synthetic-t1", "trial": "NCT00000001", "label": "2",
              "criteria": [("inclusion", "Synthetic adults"), ("exclusion", "Synthetic condition X")]},
             {"year": "2021", "patient": "synthetic-t2", "trial": "NCT00000002", "label": "1",
              "criteria": [("inclusion", "Synthetic age 18 or over"), ("exclusion", "Synthetic condition Y")]}]  # fmt: skip
    notes = {"synthetic-t1": ["A synthetic note."], "synthetic-t2": ["Another synthetic note."]}
    from tools import trec_ct_eval

    monkeypatch.setattr(trec_ct_eval, "dataset", lambda: (pairs, notes, {}, {}))
    return pairs, notes


def test_the_trec_scenario_keeps_each_criterion_and_names_the_losses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import trec_ct_eval
    from tools.trialgpt_compare import Client

    pairs, notes = _trec(monkeypatch)
    cache = tmp_path / "scenario-public-trec" / "responses"
    c = Client("http://stub/v1", "none", cache)
    answers = {"synthetic-t1|NCT00000001|0": "not included", "synthetic-t1|NCT00000001|1": "not excluded",
               "synthetic-t2|NCT00000002|0": "not excluded"}  # fmt: skip
    for p in trec_ct_eval.criterion_pairs(pairs):  # the last one has no answer: its call failed in the run
        if p.annotation_id in answers:
            body = c.body("stub", mlbench.messages(p, notes[p.patient_id]))
            data = {"model": "stub", "choices": [{"message": {"content": json.dumps({"label": answers[p.annotation_id],
                                                                                     "evidence": [0]})}}]}  # fmt: skip
            (cache / f"{c.key(body)}.json").write_text(json.dumps(data), encoding="utf-8")
    a = _args(tmp_path, "public-trec")
    got = cr.keep_cases(a, {"counts": {"criteria": 4}})
    assert got["kept"] is True and got["picks_match"] is True and got["file"].endswith("answers.jsonl.gz")
    assert got["eligible_lost"] == 1 and got["excluded_caught"] == 0
    assert got["lost"] == ["synthetic-t1|NCT00000001|0"] and got["lost_by_kind"] == {"inclusion": 1}
    assert got["unanswered_by_error"] == {"bad label: not excluded": 1, "no answer kept: the call failed": 1}
    head, cases = rm.read_cases(tmp_path / got["file"])
    assert head["criteria"] == 4 and head["roles"] == ["stub"] and len(cases) == 4
    first = next(x for x in cases if x["id"] == "synthetic-t1|NCT00000001|0")
    assert first["pair"] == "eligible" and first["a"] == {"stub": "not included"} and first["block"] is True
    # the part counted other criteria than the picks give: said, not hidden
    assert cr.keep_cases(a, {"counts": {"criteria": 5}})["picks_match"] is False


def test_cases_that_cannot_be_read_are_said_and_other_scenarios_keep_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import trec_ct_eval

    def gone() -> Any:
        raise FileNotFoundError("sample_trials.json")

    monkeypatch.setattr(trec_ct_eval, "dataset", gone)
    got = cr.keep_cases(_args(tmp_path, "public-trec"), {})
    assert got["kept"] is False and "sample_trials.json" in got["why"]
    assert cr.keep_cases(_args(tmp_path, "gateway"), {}) == {}


# ---------------------------------------------------------------- 3. the cases of the MedTxt-CR scenario
MARKUP = ('既往歴：<d certainty="negative">合成胃癌</d><r state="executed">手術</r>。'
          '<d certainty="negative">合成肺炎</d>なし。<d certainty="negative">合成骨折</d>。'
          '<d certainty="positive">合成高血圧</d>あり。')  # fmt: skip


def test_medtxt_negative_mentions_are_told_apart_by_their_context() -> None:
    kinds = cr.medtxt_negative_kinds(MARKUP)
    assert kinds == {"合成胃癌": {"treated"}, "合成肺炎": {"denied"}, "合成骨折": {"other"}}


def test_the_medtxt_scenario_keeps_every_condition_with_its_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orchestrator import app as orch_app

    from tools import medtxt_eval as mt

    tags = [("negative", "合成胃癌"), ("negative", "合成肺炎"), ("positive", "合成高血圧")]
    monkeypatch.setattr(scenarios, "medtxt_reports", lambda n: [("CR:SYN-1", "synthetic", tags)])
    monkeypatch.setattr(mt, "articles", lambda corpus, lang: {"CR:SYN-1": MARKUP})
    facts = [{"id": 1, "domain": "condition", "quote": "合成胃癌手術（４年前）", "code": "C16.9", "system": "icd10cm",
              "day": "", "status": "proposed"},
             {"id": 2, "domain": "condition", "quote": "合成高血圧あり", "status": "proposed"},
             {"id": 3, "domain": "condition", "quote": "合成肺炎なし", "status": "proposed"},
             {"id": 4, "domain": "observation", "quote": "合成値 8.2"}]  # fmt: skip
    svc = SimpleNamespace(pseudonym=lambda chart: f"p-{chart}",
                          store=SimpleNamespace(facts=lambda ws, pid: facts if (ws, pid) == ("medtxt", "p-50000001")
                                                else []))  # fmt: skip
    monkeypatch.setattr(orch_app, "_orch", object(), raising=False)
    monkeypatch.setattr("orchestrator.app.setup_of", lambda _orch: svc)
    got = cr.keep_cases(_args(tmp_path, "public-medtxt"), {"counts": {"conditions": 3}})
    assert got["kept"] is True and got["picks_match"] is True
    assert got["by_class"] == {"negative": 2, "positive": 1}
    assert got["on_negated_by_kind"] == {"treated": 1, "denied": 1}
    assert got["on_negated"] == ["CR:SYN-1: 合成胃癌手術（４年前） [treated]", "CR:SYN-1: 合成肺炎なし [denied]"]
    _, cases = rm.read_cases(tmp_path / got["file"])
    assert [c["fid"] for c in cases] == [1, 2, 3] and cases[0]["code"] == "C16.9" and cases[0]["neg"] == ["合成胃癌"]


# ---------------------------------------------------------------- 4. B17: the public scenarios' estimate
def test_the_public_scenarios_are_estimated_from_their_measured_parts() -> None:
    """Run 20261114T061459Z: MedTxt-CR took 2,806.7 s (estimate 1,371), TREC CT 2,709.7 s (estimate 1,143). Each
    asks one call at a time, so the estimate is the measured part, scaled with the reports or pairs."""
    e = cr.estimate(50000, ("ja",))
    rows = {r["scenario"]: r for r in e["rows"]}
    assert rows["public-medtxt"]["seconds"] == pytest.approx(2806.7, abs=1.0)
    assert rows["public-trec"]["seconds"] == pytest.approx(2709.7, abs=1.0)
