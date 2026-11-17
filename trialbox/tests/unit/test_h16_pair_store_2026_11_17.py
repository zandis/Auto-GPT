"""Card H-16 (lane H, 2026-11-17): the judged-pair store read from a stored run (D-1126).

``tools.public_accuracy.pair_store`` reads a run's SCREEN reports and model-call traces and prints the store's hit rate
in the run, what a second run of the same set on the same box would find again, and questions asked twice in one run.
The runs here are made up, in the records' real shape (launch P1b's ``work/screen/*.json``, ``progress.json`` and
``raw-traces.json``): synthetic criteria, notes and pseudonyms, no patient data.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest
from matching.cascade.judge import ASKING, Asking, question_digest
from orchestrator.jobs import GuardedLlm
from orchestrator.judged_store import JudgedPairs
from tb_common.llm import LlmResult

from tools.public_accuracy import pair_store

pytestmark = pytest.mark.nodb

BUILD = "b" * 64
JUDGE, VERIFIER = "j-workhorse", "v-verifier"
DAY = "2026-11-16"


def _vars(crit: str, note: str, day: str = DAY) -> dict[str, Any]:
    return {"criterion_text": crit, "note_question": f"Does the patient have {crit.lower()}?", "index_date": day,
            "excerpts": [{"date": "2026-08-06", "note_type": "consult", "text": note}]}  # fmt: skip


def _answer(verdict: str = "unknown") -> str:
    return json.dumps({"verdict": verdict, "reason": "made up", "quote": None, "quote_date": None, "confidence": 0.9})


def trace(job: str, ts: str, v: dict[str, Any], alias: str = JUDGE, out: str | None = None, *,
          repair_of: str | None = None, build: str = BUILD, asking: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    """One note-question trace as ``raw-traces.json`` holds it."""
    user = "INPUT:\n```json\n" + json.dumps(v, indent=1, sort_keys=True, ensure_ascii=False) + "\n```"
    prompt = [{"role": "system", "content": "You decide one eligibility criterion."}, {"role": "user", "content": user}]
    if repair_of is not None:
        prompt += [{"role": "assistant", "content": repair_of},
                   {"role": "user", "content": "Your previous output violated the JSON schema. Return only JSON."}]  # fmt: skip
    attrs: dict[str, Any] = {"tb.build_sha": build, "tb.cache": "miss", "tb.context_of_use": "s3_note_judgement",
             "tb.model_alias": alias, "tb.prompt": "judge@5", "tb.role": "judge", "tb.study_id": job}  # fmt: skip
    if asking is not None:
        attrs[pair_store.ASKING_ATTR] = asking
    return {"attributes": attrs, "call_id": f"c-{job}-{ts}", "output": out or _answer(), "prompt": prompt,
            "sc": False, "span": "chat", "ts": f"{DAY}T08:{ts}+00:00"}  # fmt: skip


def report(job: str, ruleset: str, read: int, live: int, s3: int, s4: int = 0) -> dict[str, Any]:
    return {"ruleset": ruleset, "provenance": {"job_id": job},
            "judging": {"mode": "agreement", "verifier_model": VERIFIER},
            "cascade": {"judged_store": {"on": True, "read": read, "live": live},
                        "metrics": {"pairs_judged": {"S3": s3, "S4": s4}, "cache_hits": 0}}}  # fmt: skip


def make_run(d: Path, name: str, reports: list[dict[str, Any]] | None, traces: list[dict[str, Any]] | None,
             progress: dict[str, Any] | None = None) -> Path:  # fmt: skip
    (d / "built" / "gold").mkdir(parents=True)
    (d / "built" / "gold" / "ids.json").write_text(json.dumps({"set": name}), encoding="utf-8")
    work = d / "work"
    work.mkdir()
    if reports is not None:
        (work / "screen").mkdir()
        for r in reports:
            (work / "screen" / f"{r['ruleset']}.json").write_text(json.dumps(r), encoding="utf-8")
    if traces is not None:
        (work / "raw-traces.json").write_text(json.dumps({"since": DAY, "calls": len(traces), "traces": traces}),
                                              encoding="utf-8")  # fmt: skip
    if progress is not None:
        (work / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
    return d


A1 = _vars("Prior stroke", "Stroke in 2019, on aspirin.")
A2 = _vars("Prior stroke", "No neurological history.")
A3 = _vars("Prior stroke", "Transient weakness, resolved.")
B1 = _vars("Asthma", "Wheeze since childhood.")


@pytest.fixture
def two_jobs(tmp_path: Path) -> dict[str, Any]:
    """Job A asks three judge questions (one with a schema repair) and one verifier question; job B asks two judge
    questions, its second the very question job A asked first."""
    traces = [
        trace("JOB-A", "00:01", A1),
        trace("JOB-A", "00:03", A2, out='{"verdict": "unknown", "quote_date": "bad"}'),
        trace("JOB-A", "00:04", A2, repair_of='{"quote_date": "bad"}'),
        trace("JOB-A", "00:05", A1, alias=VERIFIER),
        trace("JOB-A", "00:09", A3, out='{"verdict": "maybe", "confidence": 0.5}'),  # outside the schema: not kept
        trace("JOB-B", "01:00", B1),
        trace("JOB-B", "01:06", A1),
    ]
    reports = [report("JOB-A", "RS-A", 0, 4, 3), report("JOB-B", "RS-B", 0, 2, 2)]
    progress = {"RS-A": {"screen_job": "JOB-A", "screen": "done", "screen_metrics": {"wall_seconds": 30.0}},
                "RS-B": {"screen_job": "JOB-B", "screen": "done", "screen_metrics": {"wall_seconds": 12.0}}}  # fmt: skip
    d = make_run(tmp_path / "run", "syn", reports, traces, progress)
    return pair_store.read_set("syn", d)


def test_the_hit_rate_is_read_over_read_plus_live_from_the_reports(tmp_path: Path) -> None:
    d = make_run(tmp_path / "r", "syn", [report("JOB-A", "RS-A", 3, 9, 8), report("JOB-B", "RS-B", 1, 3, 4)], [])
    a = pair_store.read_set("syn", d)["recorded"]
    assert (a["reports"], a["with_store_block"], a["store_on"]) == (2, 2, 2)
    assert a["hit_rate"] == {"numerator": 4, "denominator": 16, "value": 0.25}
    assert a["pairs_judged"] == {"S3": 12, "S4": 0}


def test_traced_questions_count_repairs_apart_and_match_the_store_count(two_jobs: dict[str, Any]) -> None:
    t = two_jobs["traced"]
    assert (t["gateway_calls"], t["questions"], t["schema_repairs"]) == (7, 6, 1)
    assert t["by_alias"] == {JUDGE: 6, VERIFIER: 1}
    assert t["jobs_where_store_count_differs_from_traced_questions"] == []  # A: 4 live, 4 questions; B: 2 and 2


def test_a_reported_job_with_no_traced_question_is_a_count_that_differs(tmp_path: Path) -> None:
    reports = [report("JOB-A", "RS-A", 0, 1, 1), report("JOB-C", "RS-C", 0, 1, 1)]
    s = pair_store.read_set("syn", make_run(tmp_path / "r", "syn", reports, [trace("JOB-A", "00:01", A1)]))
    assert s["traced"]["jobs_where_store_count_differs_from_traced_questions"] == ["JOB-C"]


def test_a_second_run_finds_every_kept_answer_but_each_models_first_in_each_job(two_jobs: dict[str, Any]) -> None:
    b = two_jobs["second_run"]
    by = {r["protocol"]: r for r in b["by_job"].values()}
    # A: A1 judge (first of the judge: live), A2 judge (kept after its repair: read), A1 verifier (first of the
    # verifier: live), A3 judge (an answer outside the schema is never kept: live)
    assert (by["RS-A"]["saved"], by["RS-A"]["still_live"], by["RS-A"]["saved_gateway_calls"]) == (1, 3, 2)
    # B: B1 judge (first in the job: live), A1 judge (kept in job A, the judge has answered in B: read)
    assert (by["RS-B"]["saved"], by["RS-B"]["still_live"]) == (1, 1)
    assert b["share"] == {"numerator": 2, "denominator": 6, "value": 2 / 6}
    assert b["seconds_per_call_measured"] is None


def test_the_saving_in_time_and_money_is_an_estimate_from_the_jobs_own_span(two_jobs: dict[str, Any]) -> None:
    by = {r["protocol"]: r for r in two_jobs["second_run"]["by_job"].values()}
    assert by["RS-A"]["span_s"] == 8.0 and by["RS-A"]["s_per_question"] == 2.0  # 08:00:01 to 08:00:09, 4 asked
    assert by["RS-B"]["span_s"] == 6.0 and by["RS-B"]["s_per_question"] == 3.0
    e = two_jobs["second_run"]["estimate"]
    assert e["saved_s"] == 5.0  # one saved in each job
    assert e["usd"] == pytest.approx(5.0 / 3600 * 2.74)
    assert "an estimate from this run's rates" in pair_store._est(e)


def test_a_question_asked_again_in_a_later_job_is_a_finding_by_protocol(two_jobs: dict[str, Any]) -> None:
    dd = two_jobs["duplicates"]
    assert dd["repeats"] == 1 and dd["in_another_job"] == 1
    assert dd["store_should_have_answered"] == 1  # A1's judge answer was kept; the judge had answered live in B
    assert dd["by_protocol"] == {"RS-B": {"repeats": 1, "in_another_job": 1, "store_should_have_answered": 1}}


def test_a_repeat_before_the_models_first_live_answer_in_its_job_is_not_the_stores_to_answer(tmp_path: Path) -> None:
    traces = [trace("JOB-A", "00:01", A1), trace("JOB-B", "01:00", A1), trace("JOB-A", "00:02", A1, alias=VERIFIER)]
    s = pair_store.read_set("syn", make_run(tmp_path / "r", "syn", None, traces))
    assert s["duplicates"]["repeats"] == 1 and s["duplicates"]["store_should_have_answered"] == 0


def test_the_missing_parts_of_the_key_are_named_when_the_traces_hold_only_part_of_it(two_jobs: dict[str, Any]) -> None:
    k = two_jobs["key"]
    assert k["by"] == "the part of the store's key the traces hold"
    assert k["not_recorded_and_varying"] == ["the patient's pseudonym", "the criterion's canonical hash",
                                             "the cascade's role (S3 or S4)", "the criterion's window"]  # fmt: skip
    assert k["index_dates"] == [DAY]
    assert any("not computable from this run's records" in x for x in two_jobs["could_not"])


def test_another_index_date_is_another_question(tmp_path: Path) -> None:
    later = _vars("Prior stroke", "Stroke in 2019, on aspirin.", day="2026-11-17")
    traces = [trace("JOB-A", "00:01", B1), trace("JOB-A", "00:02", A1), trace("JOB-A", "00:03", later)]
    s = pair_store.read_set("syn", make_run(tmp_path / "r", "syn", None, traces))
    assert s["duplicates"]["repeats"] == 0 and s["key"]["index_dates"] == [DAY, "2026-11-17"]


class _Rows:
    """The store's table, in memory: what ``pair_put`` wrote."""

    def __init__(self) -> None:
        self.put: list[str] = []

    def pair_get(self, key: str) -> None:
        return None

    def pair_put(self, key: str, *a: Any) -> None:
        self.put.append(key)


class _Model:
    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        data = {"verdict": "unknown", "confidence": 0.9, "quote": None, "quote_date": None}
        return LlmResult(data, prompt_id, 5, "m", "local", "in", "out", 10, 5, 1, "", BUILD)


def test_with_the_cascades_question_traced_the_tool_computes_the_stores_own_key(tmp_path: Path) -> None:
    """The key SCREEN's guarded client writes for a question, and the one the tool computes from a trace carrying the
    cascade's question: the same (``JudgedPairs.key``, imported, not copied)."""
    rows = _Rows()
    store = JudgedPairs(rows, lambda: "2026-11-15", frozenset, lambda: "t")
    g = GuardedLlm(_Model(), lambda: False, None, "judge", pairs=store)
    win = ("2026-05-16", DAY)
    for v in (B1, A1):  # the first answer teaches the store the judge's build; the second is keyed and written
        q = question_digest(v["criterion_text"], v["note_question"], v["index_date"], v["excerpts"])
        tok = ASKING.set(Asking("pid-a", "sha256:crit", win, question=q))
        try:
            g.chat_json("judge", v)
        finally:
            ASKING.reset(tok)
    asked = {"pid": "pid-a", "criterion_hash": "sha256:crit", "window": list(win), "role": "judge", "audit": False,
             "prompt_id": "judge", "schema": None}  # fmt: skip
    calls, _, _ = pair_store.note_calls([trace("JOB-A", "00:01", A1, asking=asked)])
    assert rows.put and pair_store.store_key(calls[0]) == rows.put[-1]
    # two patients with the same note: one question to the traces, two pairs to the store
    traces = [trace("JOB-A", "00:01", A1, asking=asked), trace("JOB-A", "00:02", A1, asking={**asked, "pid": "pid-b"}),
              trace("JOB-A", "00:03", A1, asking=asked)]  # fmt: skip
    s = pair_store.read_set("syn", make_run(tmp_path / "r", "syn", None, traces))
    assert s["key"]["by"] == "the store's own key (JudgedPairs.key)" and s["key"]["not_recorded"] == []
    assert s["duplicates"]["repeats"] == 1  # only the third: pid-b's question is another pair


def test_a_run_with_no_store_records_says_what_it_could_not_tell(tmp_path: Path, capsys: Any) -> None:
    d = make_run(tmp_path / "r", "syn", None, None)
    assert pair_store.main([str(d)]) == 0
    out = capsys.readouterr().out
    assert "no SCREEN report" in out and "not derivable from this run's records" in out
    assert "hit rate read/(read+live) = 0/0 (no calls)" in out


def _tgz(src: Path, out: Path, extra: tarfile.TarInfo | None = None) -> Path:
    with tarfile.open(out, "w:gz") as tar:
        for sub in ("built", "work"):
            tar.add(src / sub, arcname=sub)
        if extra is not None:
            tar.addfile(extra, io.BytesIO(b"x" * extra.size) if extra.isreg() else None)
    return out


def test_a_stored_tarball_is_read_through_the_replays_safe_extractor(tmp_path: Path, capsys: Any) -> None:
    src = make_run(tmp_path / "src", "syn", [report("JOB-A", "RS-A", 0, 1, 1)], [trace("JOB-A", "00:01", A1)])
    good = _tgz(src, tmp_path / "good.tgz")
    out = tmp_path / "report.json"
    assert pair_store.main([str(good), "--json", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["schema_version"] == 1 and rep["all"]["recorded"]["hit_rate"]["denominator"] == 1
    bad = tarfile.TarInfo("../outside.txt")
    bad.size = 1
    assert pair_store.main([str(_tgz(src, tmp_path / "bad.tgz", bad))]) == 2
    assert "absolute or parent path" in capsys.readouterr().err
    link = tarfile.TarInfo("work/link")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    assert pair_store.main([str(_tgz(src, tmp_path / "link.tgz", link))]) == 2
    assert not (tmp_path / "outside.txt").exists()
