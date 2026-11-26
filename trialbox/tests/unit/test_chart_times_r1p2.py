"""R1-P2 (lane DB): the time per chart from what a screening run already records.

* each model call's own record (``llm.call``, written by ``tb_common.llm`` around a cascade question) names the
  patient, the role and the stage, with the call's time and tokens; the gateway's record of the same call, joined by
  ``call_id``, gives the server's time and the wait for a slot;
* the charts that reached the models give a median and a 95th percentile of their summed model time and tokens, and
  the share of the charts in scope that reached the models;
* the model servers' counters give the split of the model time into queue, prefill and decode; a counter a server
  does not report is named, never guessed;
* the stage log gives each stage's patients, and the cascade's timing file (when switched on) its wall time;
* the report holds no pseudonym, so it may leave the box with the walk's logs;
* ``watch`` samples the CPU from ``/proc/stat`` and stops on its own limit, writing ``watch.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from matching.cascade.judge import call_context
from tb_common.audit import AuditLog
from tb_common.llm import CALL_CONTEXT, LlmClient

from tools import chart_times as ct

JUDGE_VARS = {"criterion_text": "x", "note_question": "q", "index_date": "2026-01-01", "excerpts": []}


def _client(audit: AuditLog, tokens: tuple[int, int] = (120, 30)) -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"verdict": "unknown", "confidence": 0.5})
        usage = {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]}
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": usage})

    c = LlmClient("http://x/v1", "m", audit=audit)
    c.http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def _ask(c: LlmClient, role: str, pid: str) -> None:
    token = CALL_CONTEXT.set(call_context(role, pid, "h" * 64, ("2025-11-01", "2026-11-01"), "q"))
    try:
        c.chat_json("judge", JUDGE_VARS)
    finally:
        CALL_CONTEXT.reset(token)


def _calls_dir(tmp_path: Path) -> Path:
    """Three charts: P-A asked by the judge and the verifier, P-B by the judge, P-C twice by the judge; one call
    outside any cascade question (a canary), which is no chart's."""
    audit_dir = tmp_path / "audit"
    audit = AuditLog(audit_dir)
    c = _client(audit)
    _ask(c, "judge", "P-A")
    _ask(c, "second_opinion", "P-A")
    _ask(c, "judge", "P-B")
    _ask(c, "judge", "P-C")
    _ask(c, "judge", "P-C")
    c.chat_json("judge", JUDGE_VARS)  # no CALL_CONTEXT: not a chart's call
    return audit_dir


def test_each_cascade_call_is_read_with_its_patient_role_and_stage(tmp_path: Path) -> None:
    calls = ct.model_calls(_calls_dir(tmp_path))
    assert [c["pid"] for c in calls] == ["P-A", "P-A", "P-B", "P-C", "P-C"]  # the canary is no chart's
    assert {c["stage"] for c in calls} == {"S3", "S4"}
    assert all(c["tokens_in"] == 120 and c["tokens_out"] == 30 and c["ms"] >= 0 for c in calls)
    assert all(c["server_ms"] == 0 and c["slot_wait_ms"] == 0 for c in calls)  # a direct call: no gateway record


def test_the_gateway_record_of_a_call_is_joined_by_its_call_id(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    audit = AuditLog(audit_dir)
    audit.append(
        "llm.call",
        detail={
            "call_id": "c-1",
            "ms": 900,
            "tokens_in": 500,
            "tokens_out": 40,
            "asking": {"pid": "P-X", "role": "judge", "stage": "S3"},
        },
    )
    audit.append("llm.gateway.call", detail={"call_id": "c-1", "latency_ms": 700.0, "slot_wait_ms": 150.0})
    audit.append("llm.gateway.call", detail={"call_id": "c-other", "latency_ms": 1.0, "slot_wait_ms": 1.0})
    (call,) = ct.model_calls(audit_dir)
    assert (call["server_ms"], call["slot_wait_ms"], call["ms"]) == (700.0, 150.0, 900.0)


def test_per_chart_sums_a_charts_calls_and_gives_median_and_p95(tmp_path: Path) -> None:
    calls = ct.model_calls(_calls_dir(tmp_path))
    pc = ct.per_chart(calls)
    assert pc["charts"] == 3
    assert pc["calls"]["n"] == 3 and pc["calls"]["sum"] == 5 and pc["calls"]["max"] == 2
    assert pc["tokens_in"]["median"] == 240 and pc["tokens_in"]["max"] == 240 and pc["tokens_in"]["sum"] == 600
    assert pc["judge_ms"]["n"] == 3 and pc["second_opinion_ms"]["n"] == 3  # a chart with no such call counts 0
    assert set(pc["model_ms"]) == {"n", "median", "p95", "max", "sum"}


def _prom(path: Path, values: dict[str, float]) -> None:
    path.write_text("".join(f"{k} {v}\n" for k, v in values.items()), encoding="utf-8")


def test_the_server_counters_split_the_model_time_and_name_what_is_missing(tmp_path: Path) -> None:
    before = {
        "vllm:request_success_total": 10,
        "vllm:prompt_tokens_total": 1000,
        "vllm:generation_tokens_total": 100,
        "vllm:request_queue_time_seconds_sum": 1.0,
        "vllm:request_queue_time_seconds_count": 10,
        "vllm:request_prefill_time_seconds_sum": 2.0,
        "vllm:request_prefill_time_seconds_count": 10,
    }
    after = {
        "vllm:request_success_total": 30,
        "vllm:prompt_tokens_total": 5000,
        "vllm:generation_tokens_total": 500,
        "vllm:request_queue_time_seconds_sum": 5.0,
        "vllm:request_queue_time_seconds_count": 30,
        "vllm:request_prefill_time_seconds_sum": 6.0,
        "vllm:request_prefill_time_seconds_count": 30,
    }
    _prom(tmp_path / "vllm-judge-before.prom", before)
    _prom(tmp_path / "vllm-judge-after.prom", after)
    s = ct.server_split(tmp_path)["judge"]
    assert (s["requests"], s["prompt_tokens"], s["generation_tokens"]) == (20, 4000, 400)
    assert s["queue"] == {"seconds": 4.0, "mean_s": 0.2} and s["prefill"] == {"seconds": 4.0, "mean_s": 0.2}
    assert set(s["not_reported_by_server"]) == {"decode", "first_token", "end_to_end"}  # named, never guessed


def test_the_stage_log_gives_patients_and_the_timing_file_its_seconds(tmp_path: Path) -> None:
    job = tmp_path / "job"
    job.mkdir()
    rows = [
        {"stage": "S0", "patients_in": 2000, "patients_out": 1800, "pairs_in": 0},
        {"stage": "S1", "patients_in": 1800, "patients_out": 900, "pairs_in": 1800},
    ]
    (job / "cascade_log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    without = ct.stage_log(job)
    assert without["S1"] == {"patients_in": 1800, "patients_out": 900, "pairs_in": 1800} and "_run" not in without
    doc = {"stages": {"S0": {"seconds": 2.0}, "S1": {"seconds": 9.0}, "writes": {"seconds": 0.4}}, "wall_seconds": 60}
    (job / "cascade_timing.json").write_text(json.dumps(doc))
    timed = ct.stage_log(job)
    assert timed["S1"]["seconds"] == 9.0 and timed["S1"]["seconds_per_1000"] == 5.0
    assert timed["writes"] == {"seconds": 0.4} and timed["_run"] == {"seconds": 60.0, "rounds": 1}


def test_a_screening_runs_published_timing_file_carries_its_own_counts(tmp_path: Path) -> None:
    """The file a SCREEN publishes with the flag screen.timing on (two rounds on a time-shared card): read with
    ``--timing``, no stage log needed, the charts in scope from S0's patients."""
    published = tmp_path / "cascade_timing_GZQO_v1.0.0.json"
    stages = {
        "S0": {"seconds": 1.2, "patients_in": 600, "patients_out": 569, "pairs_in": 0},
        "S3": {"seconds": 180.0, "patients_in": 241, "patients_out": 241, "pairs_in": 3917},
    }
    published.write_text(json.dumps({"stages": stages, "wall_seconds": 240.0, "rounds": 2, "ruleset": "GZQO"}))
    rep = ct.report(_calls_dir(tmp_path), None, timing_file=published)
    assert rep["charts_in_scope"] == 600 and rep["stages"]["S3"]["seconds_per_1000"] == round(1000 * 180 / 241, 2)
    assert rep["stages"]["_run"] == {"seconds": 240.0, "rounds": 2}
    assert rep["throughput"]["seconds_per_chart"] == 0.4 and rep["throughput"]["source"] == "cascade_timing.json"


def test_the_report_holds_counts_and_times_and_no_pseudonym(tmp_path: Path) -> None:
    audit_dir = _calls_dir(tmp_path)
    job = tmp_path / "job"
    job.mkdir()
    (job / "cascade_log.jsonl").write_text(json.dumps({"stage": "S0", "patients_in": 6, "patients_out": 6}) + "\n")
    (job / "cascade_timing.json").write_text(json.dumps({"stages": {"S0": {"seconds": 0.5}}, "wall_seconds": 12.0}))
    folder = tmp_path / "watch"
    folder.mkdir()
    rep = ct.report(audit_dir, folder, job, ingest_seconds=131.0, ingest_patients=600)
    assert rep["charts_in_scope"] == 6 and rep["charts_reaching_model"] == 3 and rep["share_reaching_model"] == 0.5
    assert rep["model_calls"]["by_stage"] == {"S3": 4, "S4": 1}
    assert rep["throughput"] == {
        "wall_seconds": 12.0,
        "seconds_per_chart": 2.0,
        "charts_per_hour": 1800.0,
        "source": "cascade_timing.json",
    }
    assert rep["ingest"]["ms_per_chart"] == 218.3
    assert rep["card"]["samples"] == 0 and rep["cpu"]["samples"] == 0  # no watch run: said so
    text = json.dumps(rep)
    assert "P-A" not in text and "P-B" not in text and "P-C" not in text


def test_cpu_readings_give_the_busy_share_of_all_cores() -> None:
    a = ct.cpu_times("cpu  100 0 100 700 100 0 0 0\ncpu0 1\ncpu1 1\n")
    b = ct.cpu_times("cpu  200 0 200 800 100 0 0 0\ncpu0 1\ncpu1 1\n")
    assert a == (200, 1000, 2) and b == (400, 1300, 2)
    assert ct.cpu_share(a, b) == round(200 / 300, 4)
    assert ct.cpu_times("") is None and ct.cpu_share(None, b) is None


def test_watch_samples_the_cpu_and_stops_on_its_limit(tmp_path: Path) -> None:
    stat = tmp_path / "stat"
    stat.write_text("cpu  100 0 100 700 100 0 0 0\ncpu0 1\n", encoding="utf-8")
    folder = tmp_path / "w"
    out = ct.watch(folder, {}, "", every=0.05, max_seconds=0.3, stat=stat)
    assert (folder / "watch.json").exists() and out["seconds"] >= 0.25
    rows = (folder / "cpu.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == ",".join(ct.CPU_FIELDS) and len(rows) >= 3
    assert out["monitor"]["sampled"] in (True, False)  # a machine with no card and no server says so


def test_the_command_line_writes_the_report(tmp_path: Path, capsys: Any) -> None:
    audit_dir = _calls_dir(tmp_path)
    out = tmp_path / "rep.json"
    assert ct.main(["report", "--audit-dir", str(audit_dir), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["charts_reaching_model"] == 3
    assert "3 charts reached the models" in capsys.readouterr().out
