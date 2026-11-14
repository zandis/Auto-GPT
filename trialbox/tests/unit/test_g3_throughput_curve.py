"""The driver's features for the deep review's GPU tests G-1 and G-3 (2026-11-12).

G-3, throughput against the calls in flight: ``--llm-concurrency N[,N...]`` reaches every part as
``TB_SCREEN_LLM_CONCURRENCY``; a list runs the hospital part once per value as ``hospital-<lang>@c<N>``; the estimate
takes each setting from the measured parts (``complete_run.HOSPITAL_MEASURED``) and names the runs;
every model part records the servers' ``/metrics``, the card and its calls per second. G-1, the chat template: the
part ``chat-template``. No GPU, no cloud: the driver's ``--dry-run``, pure functions and local stand-ins."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools import chat_template_check as ctc
from tools import complete_run as cr
from tools import run_metrics as rm
from tools import vllm_standin as vs

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"
HEAD = "b" * 40
KEY = "rehearsal-key-0123456789"
G3 = ("--patients", "5000", "--only", "hospital-ja,chat-template", "--llm-concurrency", "1,4,16,48")


# ---------------------------------------------------------------- the setting and the plan
def test_the_concurrency_list_is_parsed_and_checked() -> None:
    assert cr.parse_concurrency("1,4,16,48") == (1, 4, 16, 48) and cr.parse_concurrency("16") == (16,)
    assert cr.parse_concurrency("1 4 4 16") == (1, 4, 16) and cr.parse_concurrency("") == ()
    for bad in ("0", "65", "four", "1,-2", "1.5"):
        with pytest.raises(ValueError):
            cr.parse_concurrency(bad)


def test_the_default_is_the_serving_records_max_num_seqs(tmp_path: Path) -> None:
    assert cr.record_max_seqs() == 16  # deploy/measured/serving_config.rtxpro6000.json
    live = tmp_path / "live.json"
    live.write_text(json.dumps({"servers": [{"role": "verifier", "max_num_seqs": 4},
                                            {"role": "judge", "max_num_seqs": 8}]}), encoding="utf-8")  # fmt: skip
    assert cr.record_max_seqs(live) == 8
    assert cr.record_max_seqs(tmp_path / "none.json") == 16  # no live record: the vendor's


def _ns(**kw: Any) -> argparse.Namespace:
    base: dict[str, Any] = {"langs": ["ja"], "scenarios": ["gateway"], "skip": [], "only": [], "llm_concurrency": ""}
    return argparse.Namespace(**{**base, **kw})


def test_a_list_runs_the_hospital_part_once_per_value_on_one_prepared_hospital() -> None:
    a = _ns(only=["hospital-ja", "chat-template", "prepare"], llm_concurrency="1,4,16,48")
    tags = [cr._tag(*p) for p in cr.plan(a)]
    assert tags == ["prepare", "chat-template", "hospital-ja@c1", "hospital-ja@c4", "hospital-ja@c16",
                    "hospital-ja@c48"]  # fmt: skip
    # the VM's --only holds the expanded tags; one of them selects only itself
    assert [cr._tag(*p) for p in cr.plan(_ns(only=["hospital-ja@c4"], llm_concurrency="1 4 16 48"))] == [
        "hospital-ja@c4"]  # fmt: skip
    one = _ns(only=["hospital-ja"], llm_concurrency="16")
    assert [cr._tag(*p) for p in cr.plan(one)] == ["hospital-ja"]  # one value: no repeat, the plain tag
    assert "chat-template" not in [cr._tag(*p) for p in cr.plan(_ns())]  # G-1 only when --only names it


def test_g3s_full_curve_runs_ja_then_zh_tw_at_1_4_8_16_32_48(tmp_path: Path) -> None:
    """Plan G-3: 1, 4, 8, 16, 32, 48 in flight, ja then zh-TW: nothing refuses 8 or 32 or the zh-TW repeats."""
    lc = "1,4,8,16,32,48"
    out = _dry(
        tmp_path, "--patients", "5000", "--only", "hospital-ja,hospital-zh-TW", "--llm-concurrency", lc, "--keep-order"
    )
    meta = next(ln for ln in out.splitlines() if "add-metadata" in ln and "tb-run-id=" in ln)
    assert "tb-llm-concurrency=1 4 8 16 32 48," in meta
    want = [f"hospital-{lang}@c{n}" for lang in ("ja", "zh-TW") for n in (1, 4, 8, 16, 32, 48)]
    assert sorted(meta.split("tb-only=")[1].split(",")[0].split()) == sorted(["prepare", *want])
    a = _ns(langs=["ja", "zh-TW"], only=["prepare", *want], llm_concurrency=lc, scenarios=[])
    assert [cr._tag(*p) for p in cr.plan(a)] == ["prepare", *want]  # the VM's order: ja's curve, then zh-TW's


def test_each_part_process_gets_its_concurrency(tmp_path: Path) -> None:
    a = _ns(llm_concurrency="1,4", dir=tmp_path, patients=500, model="stub", ocr="fake", run_id="R", direct=False,
            live_record=None, resume=False, keep_work=False)  # fmt: skip
    cmd = cr._cmd(a, "hospital", "ja", "c4", tmp_path)
    assert cmd[cmd.index("--variant") + 1] == "c4" and cmd[cmd.index("--llm-concurrency") + 1] == "4"
    assert "--scenario" not in cmd
    one = _ns(llm_concurrency="16", dir=tmp_path, patients=500, model="stub", ocr="fake", run_id="R", direct=False,
              live_record=None, resume=False, keep_work=False)  # fmt: skip
    for part, lang, sc in (("hospital", "ja", ""), ("public", "ja", ""), ("scenario", "ja", "gateway")):
        cmd = cr._cmd(one, part, lang, sc, tmp_path)
        assert cmd[cmd.index("--llm-concurrency") + 1] == "16", part
    assert "--llm-concurrency" not in cr._cmd(_ns(dir=tmp_path, patients=500, model="stub", ocr="fake", run_id="R",
                                                  direct=False, live_record=None, resume=False, keep_work=False),
                                              "hospital", "ja", "", tmp_path)  # fmt: skip


# ---------------------------------------------------------------- the estimate
def _row(e: dict[str, Any], tag: str) -> dict[str, Any]:
    return next(r for r in e["rows"] if r["tags"] == [tag])


def test_the_screening_time_is_the_measured_parts_at_each_setting() -> None:
    """M3 (OD-10, measured), re-based 2026-11-13: the gain at N calls in flight is the main SCREEN's curve of run
    20261113T044219Z-2b9eec74 (5,000 patients, ja and zh-TW: 0.385, 1.435, 4.391 calls/s ja at 1, 4, 16); a setting
    a run measured is that run's figure (G1's 0.78 calls/s and the old 2026-11-12 curve are gone)."""
    assert [cr.llm_speedup(n) for n in (1, 4, 16, 48)] == [1.0, 3.709, 11.647, 11.647]
    assert 3.709 < cr.llm_speedup(8) < 11.647  # between points: interpolated
    assert cr.llm_speedup(64) == cr.llm_speedup(16)  # above the last point: held, never extrapolated
    assert cr.SINGLE_CALL_CPS == 0.403  # the whole part's calls/s at one in flight (both languages, 5,000)
    e = cr.estimate(5000, llm_concurrency=(1, 4, 16, 48))
    assert e["llm_concurrency"] == [1, 4, 16, 48] and e["llm_speedup"] == [1.0, 3.709, 11.647, 11.647]
    ja = {n: cr.hospital_split(5000, n, "ja") for n in (1, 4, 16)}
    non_llm = (1685.5 - 606 / 0.402 + 734.1 - 597 / 1.046 + 501.5 - 603 / 1.779) / 3  # the mean over the settings
    for n, rate in ((1, 0.385), (4, 1.435), (16, 4.391)):  # the main SCREEN's calls (mean) at the measured rate
        assert ja[n]["non_llm"] == pytest.approx(non_llm) and ja[n]["main"] == pytest.approx(
            (244 + 244 + 246) / 3 / rate
        )
        assert _row(e, f"hospital-ja@c{n}")["seconds"] == pytest.approx(ja[n]["seconds"])
    assert _row(e, "hospital-ja@c48")["seconds"] == _row(e, "hospital-ja@c16")["seconds"]
    assert _row(e, "hospital-zh-TW@c4")["seconds"] == pytest.approx(cr.hospital_seconds(5000, 4, lang="zh-TW"))
    assert _row(cr.estimate(50000), "hospital-ja")["seconds"] == pytest.approx(cr.hospital_seconds(50000, 1, lang="ja"))


def test_the_factor_is_a_declared_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common.config import DECLARED

    assert DECLARED["TB_ESTIMATE_LLM_SPEEDUP"].default == "" and DECLARED["TB_ESTIMATE_LLM_SPEEDUP"].kind == "float"
    one = cr.hospital_seconds(50000, 1)
    monkeypatch.setenv("TB_ESTIMATE_LLM_SPEEDUP", "1")  # the strict bound: one call in flight's time at every N
    assert cr.hospital_seconds(50000, 48) == pytest.approx(one) and cr.hospital_seconds(50000, 16) == pytest.approx(one)
    monkeypatch.setenv("TB_ESTIMATE_LLM_SPEEDUP", "8")
    assert cr.llm_speedup(4) == 4.0 and cr.llm_speedup(48) == 8.0 and cr.llm_speedup(1) == 1.0
    text = cr.print_estimate(cr.estimate(5000, llm_concurrency=(1, 4)))
    assert "times min(N, 8) (TB_ESTIMATE_LLM_SPEEDUP, the owner's override" in text
    for bad in ("0.5", "fast", "nan"):
        monkeypatch.setenv("TB_ESTIMATE_LLM_SPEEDUP", bad)
        with pytest.raises(ValueError):
            cr.llm_speedup(4)


def test_the_bounded_g3_estimate_names_every_repeat_and_its_measured_gain() -> None:
    e = cr.restrict(cr.estimate(5000, llm_concurrency=(1, 4, 16, 48)), ["hospital-ja", "chat-template"])
    tags = [t for r in e["rows"] for t in r["tags"]]
    assert tags == ["chat-template", "hospital-ja@c1", "hospital-ja@c4", "hospital-ja@c16", "hospital-ja@c48"]
    work = sum(cr.hospital_seconds(5000, n, lang="ja") for n in (1, 4, 16, 48)) + ctc.SECONDS
    assert e["hours"] == pytest.approx((1800 + work) / 3600, abs=0.01) and e["cap_hours"] == 2
    assert e["provisioning"] == "STANDARD"  # a hospital part: on demand (D-468)
    text = cr.print_estimate(e)
    assert "model calls in flight (TB_SCREEN_LLM_CONCURRENCY): 1, 4, 16, 48" in text
    assert "the gain of the curve measured in run 20261113T044219Z-2b9eec74" in text and "4: 3.709x" in text
    assert "UPPER BOUND" not in text and "48 in flight is above the servers' max_num_seqs (16)" in text
    shard = cr.shard_plan(e, 1)["shards"][0]
    assert shard["tags"][:2] == ["prepare", "chat-template"] and len(shard["tags"]) == 6
    alone = cr.print_estimate(cr.restrict(cr.estimate(5000, llm_concurrency=(1,)), ["hospital-ja"]))
    assert "model time at N in flight" not in alone  # N = 1 is the measurement
    with pytest.raises(ValueError):
        cr.restrict(cr.estimate(5000, llm_concurrency=(1, 4)), ["hospital-ja@c16"])


def _part(d: Path, tag: str, run_id: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{tag}.json").write_text(json.dumps({"stages": [{"name": "s", "ok": True, "seconds": 1,
                                                           "checks": [["c", True, ""]]}],
                                               "run": {"id": run_id, "head": HEAD}}), encoding="utf-8")  # fmt: skip


def test_a_restarted_shard_keeps_the_repeats_done_and_caps_what_is_left(tmp_path: Path) -> None:
    doc = cr.restrict(cr.estimate(5000, llm_concurrency=(1, 4, 16)), ["hospital-ja"])
    doc["plan"] = cr.shard_plan(doc, 1)
    for tag in ("prepare", "hospital-ja@c1", "hospital-ja@c4"):
        _part(tmp_path / "parts", tag, "R-s1")
    now = cr.shard_now(doc, 1, [tmp_path / "parts"], "R", HEAD)
    assert now["left"] == ["hospital-ja@c16"] and now["provisioning"] == "STANDARD"
    assert now["hours"] == pytest.approx(0.5 + cr.hospital_seconds(5000, 16, lang="ja") / 3600, abs=0.01)


# ---------------------------------------------------------------- the driver (--dry-run: nothing starts)
def _dry(tmp_path: Path, *args: str, **env_kw: str) -> str:
    env = dict(os.environ, TB_COMPLETE_DIR=str(tmp_path / "out"), PY=str(ROOT / ".venv" / "bin" / "python"), **env_kw)
    for k in ("TB_ZONES", "TB_ESTIMATE_LLM_SPEEDUP"):
        env.pop(k, None)
    r = subprocess.run([str(GCP / "complete-run.sh"), "--dry-run", *args], cwd=ROOT, env=env, capture_output=True,
                       text=True, check=False, timeout=300)  # fmt: skip
    assert r.returncode == 0, r.stderr[-800:]
    return r.stdout


def test_the_g3_launch_plan_cap_and_metadata(tmp_path: Path) -> None:
    out = _dry(tmp_path, *G3, "--keep-order", TB_RUN_ID="R")  # the order given (else seeded at random)
    assert "model calls in flight (TB_SCREEN_LLM_CONCURRENCY): 1, 4, 16, 48" in out
    assert "the gain of the curve measured in run" in out and "above the servers' max_num_seqs (16)" in out
    meta = next(ln for ln in out.splitlines() if "add-metadata" in ln and "tb-run-id=" in ln)
    assert "tb-llm-concurrency=1 4 16 48," in meta and "tb-patients=5000," in meta
    only = meta.split("tb-only=")[1].split(",")[0].split()
    assert sorted(only) == sorted(["prepare", "chat-template", "hospital-ja@c1", "hospital-ja@c4", "hospital-ja@c16",
                                   "hospital-ja@c48"])  # fmt: skip
    sched = next(ln for ln in out.splitlines() if "set-scheduling" in ln and "max-run-duration=" in ln)
    assert "--max-run-duration=2h" in sched and "--provisioning-model=STANDARD" in sched
    plan = json.loads((tmp_path / "out" / "plan.json").read_text(encoding="utf-8"))
    assert plan["llm_concurrency"] == [1, 4, 16, 48] and plan["plan"]["shards"][0]["hours"] == pytest.approx(1.53)
    report = next(ln for ln in out.splitlines() if "--report-only" in ln)
    assert "--llm-concurrency 1 4 16 48" in report and "hospital-ja@c48" in report


def test_not_given_the_driver_prints_and_passes_the_records_max_num_seqs(tmp_path: Path) -> None:
    out = _dry(tmp_path, "--patients", "5000", "--only", "hospital-ja,scenario-gateway")
    assert "(TB_SCREEN_LLM_CONCURRENCY): 16 (not given: the serving record's max_num_seqs, 16)" in out
    assert "tb-llm-concurrency=16," in out and "hospital-ja@" not in out


def test_the_default_cap_covers_what_was_measured_and_no_gain_beyond_it(tmp_path: Path) -> None:
    """Not given, the estimate takes 16 in flight. Its cap (x 1.3) holds the run at the parts as measured at 16; at a
    setting no run measured at that size it also holds the run should the calls in flight gain nothing (G1 bug A4: a
    cap below the part). Re-based 2026-11-13: 16 is measured at 50,000, so its floor is the measured part."""
    for only in (["hospital-ja"], ["hospital-ja", "hospital-zh-TW"], []):
        for patients in (5000, 50000):
            fast = cr.restrict(cr.estimate(patients, llm_concurrency=(cr.record_max_seqs(),)), only)
            assert fast["cap_hours"] >= 1.3 * fast["hours"], (only, patients)
            slow = cr.restrict(cr.estimate(patients, llm_concurrency=(1,)), only)
            odd = cr.restrict(cr.estimate(patients, llm_concurrency=(8,)), only)  # 8: measured at no size
            assert fast["hours"] < odd["hours"] < slow["hours"] <= odd["cap_hours"], (only, patients)
    out = _dry(tmp_path, "--patients", "50000")
    # 7.08 h x 1.3 = 9.2 h: 10 h (9 h at 6.25 h until the public scenarios were estimated from their measured parts,
    # lane G B17; 15 h on G1's figure)
    assert "--max-run-duration=10h" in out


def test_one_value_reaches_the_vm_and_the_vm_script_passes_it_on(tmp_path: Path) -> None:
    out = _dry(tmp_path, "--patients", "5000", "--only", "hospital-ja", "--llm-concurrency", "4")
    assert "tb-llm-concurrency=4," in out and "(TB_SCREEN_LLM_CONCURRENCY): 4" in out
    vm = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")
    assert "LLMC=$(md tb-llm-concurrency || true)" in vm and '${LLMC:+--llm-concurrency "$LLMC"}' in vm
    bad = subprocess.run([str(GCP / "complete-run.sh"), "--estimate", "--llm-concurrency", "0"], cwd=ROOT,
                         env=dict(os.environ, PY=str(ROOT / ".venv" / "bin" / "python")), capture_output=True,
                         text=True, check=False, timeout=120)  # fmt: skip
    assert bad.returncode != 0 and "whole numbers from 1 to 64" in bad.stderr


def test_a_part_sets_the_setting_for_its_screen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``part selftest --llm-concurrency 4``: the part's process has TB_SCREEN_LLM_CONCURRENCY=4 and records it."""
    monkeypatch.setenv("TB_SELFTEST_SECONDS", "0")
    monkeypatch.delenv("TB_SCREEN_LLM_CONCURRENCY", raising=False)
    monkeypatch.setattr(cr, "shoot", lambda items, *a, **k: {it["name"]: {"ok": True} for it in items})
    rc = cr.main(["part", "selftest", "--scenario", "busy", "--dir", str(tmp_path), "--shots", str(tmp_path / "s"),
                  "--run-id", "R", "--llm-concurrency", "4"])  # fmt: skip
    res = json.loads((tmp_path / "parts" / "selftest-busy.json").read_text(encoding="utf-8"))
    assert rc == 0 and os.environ["TB_SCREEN_LLM_CONCURRENCY"] == "4" and res["llm_concurrency"] == 4
    monkeypatch.delenv("TB_SCREEN_LLM_CONCURRENCY")


# ---------------------------------------------------------------- the metrics (pure functions)
PROM = """# HELP vllm:prompt_tokens_total Number of prefill tokens processed.
# TYPE vllm:prompt_tokens_total counter
vllm:prompt_tokens_total{model_name="m",engine="0"} %(pt)s
vllm:generation_tokens_total{model_name="m"} %(gt)s
vllm:request_success_total{finished_reason="stop",model_name="m"} %(n)s
vllm:request_success_total{finished_reason="length",model_name="m"} 1.0
vllm:time_to_first_token_seconds_bucket{le="0.1",model_name="m"} 3.0
vllm:time_to_first_token_seconds_sum{model_name="m"} %(ttft)s
vllm:time_to_first_token_seconds_count{model_name="m"} %(n)s
vllm:request_queue_time_seconds_sum{model_name="m"} %(q)s
vllm:request_queue_time_seconds_count{model_name="m"} %(n)s
vllm:num_requests_waiting{model_name="m"} 3.0
vllm:num_requests_running{model_name="m"} 16.0
vllm:kv_cache_usage_perc{model_name="m"} 0.42
vllm:prompt_tokens_created{model_name="m"} 1.7e9
garbage line
"""


def test_the_servers_metrics_are_parsed_and_differenced() -> None:
    before = PROM % {"pt": "1000.0", "gt": "200.0", "n": "10.0", "ttft": "1.0", "q": "0.5"}
    after = PROM % {"pt": "9000.0", "gt": "1200.0", "n": "50.0", "ttft": "9.0", "q": "20.5"}
    got = rm.parse_prometheus(after)
    assert got["vllm:prompt_tokens_total"] == 9000.0 and got["vllm:request_success_total"] == 51.0  # labels summed
    assert not any(k.endswith(("_bucket", "_created")) for k in got)
    assert rm.pick(got, rm.GAUGES) == {"running": 16.0, "waiting": 3.0, "kv_cache_usage": 0.42}
    d = rm.metrics_delta(before, after)
    assert d["scraped"] and d["prompt_tokens"] == 8000.0 and d["generation_tokens"] == 1000.0 and d["requests"] == 40.0
    assert d["ttft_mean_s"] == 0.2 and d["queue_mean_s"] == 0.5
    assert rm.metrics_delta("", "") == {"scraped": False}  # a server that gave nothing says so
    assert rm.metrics_url("http://127.0.0.1:8080/judge/v1") == "http://127.0.0.1:8080/judge/metrics"
    old = rm.pick(rm.parse_prometheus("vllm:gpu_cache_usage_perc 0.3\n"), rm.GAUGES)  # the gauge's older name
    assert old == {"kv_cache_usage": 0.3}


def test_the_cards_samples_are_summed_up() -> None:
    rows = [rm.gpu_row("2026/11/12 01:00:00.000, 80, 62000, 97887, 60, 400.5"),
            rm.gpu_row("2026/11/12 01:00:10.000, 100, 62574, 97887, 64, 450.0"),
            rm.gpu_row("2026/11/12 01:00:20.000, [N/A], 62100, 97887, 61, [N/A]")]  # fmt: skip
    assert rm.gpu_row("NVIDIA RTX PRO 6000 | Driver Version: 580") is None
    s = rm.gpu_summary([r for r in rows if r])
    assert s == {"samples": 3, "every_s": 10.0, "util_mean_pct": 90.0, "util_max_pct": 100.0,
                 "memory_peak_mib": 62574.0, "memory_total_mib": 97887.0, "temperature_max_c": 64.0,
                 "power_max_w": 450.0}  # fmt: skip
    g = rm.gauge_summary([{"server": "judge", "running": "16", "waiting": "32", "kv_cache_usage": "0.5"},
                          {"server": "judge", "running": "12", "waiting": "", "kv_cache_usage": "0.7"}])  # fmt: skip
    assert g == {"judge": {"running_max": 16.0, "waiting_max": 32.0, "kv_cache_usage_max": 0.7}}


def _call(end: float, latency: float, ep: str = "serving", t_in: int = 900, t_out: int = 100) -> dict[str, Any]:
    return {"end": end, "latency_s": latency, "tokens_in": t_in, "tokens_out": t_out, "endpoint": ep}


def test_calls_and_tokens_per_second_are_over_the_time_a_call_was_in_flight() -> None:
    assert rm.percentile([], 0.5) == 0.0 and rm.percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert rm.percentile([float(x) for x in range(1, 101)], 0.95) == pytest.approx(95.05)
    # one at a time, 1 s each, with a 100 s pause between two stages: 4 calls in 4 busy seconds
    seq = [_call(1, 1), _call(2, 1), _call(103, 1), _call(104, 1)]
    assert rm.busy_seconds(seq) == 4.0
    s = rm.call_stats(seq)
    assert s["calls"] == 4 and s["calls_per_second"] == 1.0 and s["tokens_per_second"] == 1000.0
    assert s["p50_s"] == 1.0 and s["p95_s"] == 1.0 and s["mean_in_flight"] == 1.0
    # four in flight, each 2 s: the same two seconds, 2 calls/s
    par = [_call(2, 2), _call(2, 2), _call(2, 2, "verifier"), _call(2, 2, "verifier")]
    s = rm.call_stats(par)
    assert s["busy_seconds"] == 2.0 and s["calls_per_second"] == 2.0 and s["mean_in_flight"] == 4.0
    assert s["endpoints"]["verifier"]["calls"] == 2 and s["endpoints"]["serving"]["calls_per_second"] == 1.0
    assert rm.call_stats([])["calls"] == 0 and rm.call_stats([])["calls_per_second"] == 0.0
    hit = {**_call(2, 0, t_in=0, t_out=0), "cached": True}  # answered from the gateway's cache: no server time
    s = rm.call_stats([*par, hit])
    assert s["calls"] == 4 and s["cached"] == 1 and s["calls_per_second"] == 2.0 and s["p50_s"] == 2.0


def test_the_gateway_audit_gives_the_calls_of_this_part_only(tmp_path: Path) -> None:
    t0 = datetime(2026, 11, 12, 1, 0, 0, tzinfo=UTC)

    def line(at: datetime, event: str = "llm.gateway.call", ms: int = 1500) -> str:
        return json.dumps({"ts": at.isoformat(timespec="milliseconds"), "event": event,
                           "detail": {"latency_ms": ms, "tokens_in": 800, "tokens_out": 50, "cache": "miss",
                                      "endpoint": "serving"}})  # fmt: skip

    (tmp_path / "audit-2026-11-12.jsonl").write_text("\n".join([
        line(t0 - timedelta(minutes=5)),  # an earlier repeat of the part: the audit folder is shared
        line(t0 + timedelta(seconds=2)), line(t0 + timedelta(seconds=4), ms=2000),
        line(t0 + timedelta(seconds=5), event="llm.gateway.refuse"), "{torn",
    ]) + "\n", encoding="utf-8")  # fmt: skip
    calls = rm.audit_calls(tmp_path, t0)
    assert [c["latency_s"] for c in calls] == [1.5, 2.0] and calls[0]["tokens_in"] == 800 and not calls[0]["cached"]
    assert len(rm.audit_calls(tmp_path)) == 3 and rm.audit_calls(tmp_path / "none") == []
    assert rm.call_stats(calls)["calls_per_second"] == pytest.approx(2 / 3.5, abs=0.001)


def test_the_candidate_list_has_a_hash_that_does_not_depend_on_the_order() -> None:
    pv = SimpleNamespace
    a = {"p2": pv(tier="review"), "p1": pv(tier="high"), "p3": pv(tier="excluded")}
    b = {"p1": pv(tier="high"), "p3": pv(tier="excluded"), "p2": pv(tier="review")}
    ca, cb = rm.candidate_list(a), rm.candidate_list(b)
    assert ca["count"] == 2 and ca["list"] == [["p1", "high"], ["p2", "review"]] and ca["sha256"] == cb["sha256"]
    assert ca["tiers"] == {"high": 1, "review": 1}
    moved = rm.candidate_list({**a, "p2": pv(tier="high")})  # the same people, another tier: another list
    assert moved["sha256"] != ca["sha256"] and rm.candidate_list({})["count"] == 0
    rows: list[dict[str, Any]]
    rows = [{"part": "hospital", "lang": "ja", "candidates": ca}, {"part": "hospital", "lang": "ja", "candidates": cb},
            {"part": "hospital", "lang": "zh-TW", "candidates": ca}, {"part": "public", "lang": "ja"}]  # fmt: skip
    assert rm.lists_identical(rows) == {"ja": True}  # one result of a language compares nothing
    assert rm.lists_identical([*rows, {"part": "hospital", "lang": "ja", "candidates": moved}]) == {"ja": False}


# ---------------------------------------------------------------- the stand-in and the monitor around a part
@pytest.fixture()
def standin() -> Any:
    s, _, _ = vs.build(["--model=/models/judge", "--served-model-name=local/judge", "--api-key", KEY], {})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), vs.make_handler(s))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield s, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_the_stand_in_answers_metrics_and_tokenize_as_vllm_does(standin: Any) -> None:
    s, base = standin
    text = rm.fetch(f"{base}/metrics")  # no key, as vLLM's
    got = rm.pick(rm.parse_prometheus(text), {**rm.COUNTERS, **rm.GAUGES})
    assert set(got) == set(rm.COUNTERS) | set(rm.GAUGES) and got["requests"] == 0.0
    assert 'model_name="local/judge"' in text and s.stats()["counts"] == {}  # a scrape is not a model call
    msgs = ctc.prompts()
    ids = ctc.server_ids(f"{base}/v1", "local/judge", msgs)
    assert len(ids) == ctc.N_PROMPTS and all(i for i in ids) and ids[0] != ids[1]
    assert ids == ctc.server_ids(f"{base}/v1", "local/judge", msgs)  # the same text, the same ids
    assert vs.tokenize({"prompt": "ab"}) == {"count": 2, "max_model_len": 32768, "tokens": [97, 98]}
    assert "vllm:prompt_tokens_total" in vs.metrics_text("m", 2, 30, 4) and " 30.0" in vs.metrics_text("m", 2, 30, 4)


def test_the_monitor_writes_the_parts_files(standin: Any, tmp_path: Path) -> None:
    _, base = standin
    smi = tmp_path / "nvidia-smi"
    smi.write_text("#!/bin/sh\necho '2026/11/12 01:00:00.000, 87, 62574, 97887, 61, 412.50'\n", encoding="utf-8")
    smi.chmod(0o755)
    folder = tmp_path / "parts" / "hospital-ja@c4"
    mon = rm.Monitor(folder, {"judge": f"{base}/v1", "verifier": ""}, KEY, every=0.05, gpu_cmd=[str(smi)]).start()
    threading.Event().wait(0.2)
    m = mon.stop()
    assert sorted(p.name for p in folder.iterdir()) == ["gpu.csv", "vllm-judge-after.prom", "vllm-judge-before.prom",
                                                        "vllm.csv"]  # fmt: skip
    assert (folder / "gpu.csv").read_text(encoding="utf-8").splitlines()[0] == ",".join(rm.GPU_FIELDS)
    assert m["sampled"] and m["folder"] == "parts/hospital-ja@c4" and m["servers"]["judge"]["scraped"]
    assert m["gpu"]["samples"] >= 2 and m["gpu"]["util_mean_pct"] == 87.0 and m["gpu"]["memory_peak_mib"] == 62574.0
    assert m["gauges"]["judge"]["waiting_max"] == 0.0
    idle = rm.Monitor(tmp_path / "parts" / "x", {}, gpu_cmd=["no-such-nvidia-smi"]).start().stop()
    assert idle["sampled"] is False and not (tmp_path / "parts" / "x").exists()  # the stub on a laptop: nothing


# ---------------------------------------------------------------- the report
def _result(tag: str, n: int, sha: str, rate: float) -> dict[str, Any]:
    return {"part": "hospital", "lang": "ja", "tag": tag, "seconds_total": 10, "llm_concurrency": n,
            "stages": [{"name": "s", "ok": True, "seconds": 1, "checks": [["c", True, ""]]}],
            "throughput": {"calls": 670, "calls_per_second": rate, "tokens_per_second": 900.0, "p50_s": 1.2,
                           "p95_s": 3.4, "breaker_opens": {"serving": 0, "verifier": 0}},
            "metrics": {"gpu": {"samples": 9, "util_mean_pct": 91.0, "memory_peak_mib": 62574.0},
                        "servers": {"judge": {"queue_mean_s": 0.4, "ttft_mean_s": 0.2}}},
            "candidates": {"count": 62, "sha256": sha, "list": []}}  # fmt: skip


def test_the_report_has_the_curve_and_says_whether_the_lists_agree() -> None:
    a = argparse.Namespace(model="pair", direct=False, ocr="tesseract", patients=5000, langs=["ja"])
    rows = [_result("hospital-ja@c1", 1, "a" * 64, 0.78), _result("hospital-ja@c4", 4, "a" * 64, 2.9)]
    rep = cr.report(a, rows, {"head": HEAD, "subject": "s", "dirty": False}, datetime.now(UTC))
    assert rep["llm_concurrency"] == [1, 4] and rep["candidates_identical"] == {"ja": True}
    assert [(r["tag"], r["calls_per_second"], r["breaker_opens"]) for r in rep["throughput"]] == [
        ("hospital-ja@c1", 0.78, 0), ("hospital-ja@c4", 2.9, 0)]  # fmt: skip
    md = cr.markdown(rep)
    assert "Model calls in flight: 1, 4." in md and "## Throughput (model calls through the gateway)" in md
    assert (
        "| hospital-ja@c4 | whole part | 4 | 670 | 2.9 | 900.0 | 1.2 | 3.4 | judge 0.4 | 91.0 | - | - | 62574.0 | 0 | 62 |"
        in md
    )
    assert "Candidate lists of hospital-ja at every setting: **identical**." in md
    rows[1]["candidates"]["sha256"] = "b" * 64
    rep = cr.report(a, rows, {"head": HEAD, "subject": "s", "dirty": False}, datetime.now(UTC))
    assert "**DIFFERENT**" in cr.markdown(rep)


# ---------------------------------------------------------------- G-1: the chat template
def test_the_twenty_prompts_are_synthetic_and_cover_the_templates_roles() -> None:
    msgs = ctc.prompts()
    assert len(msgs) == ctc.N_PROMPTS == 20 and len({json.dumps(m, ensure_ascii=False) for m in msgs}) == 20
    assert any(m[0]["role"] == "system" for m in msgs) and any(len(m) > 2 for m in msgs)
    assert any("痛風" in m[-1]["content"] or "痛風" in m[0]["content"] for m in msgs)


def test_token_identity_names_the_first_difference() -> None:
    folder = [[1, 2, 3], [4, 5, 6]]
    same = ctc.compare([[1, 2, 3], [4, 5, 6]], folder, [[1, 2, 3], [4, 5, 6]])
    assert same["server_equals_folder"] and same["passed_equals_folder"] and same["tokens"] == 6
    diff = ctc.compare([[1, 2, 3], None], folder, [[1, 9, 3], [4, 5, 6, 7]])
    assert not diff["server_equals_folder"] and diff["server_different"] == [
        {"prompt": 1, "first_difference_at": 0, "lengths": [0, 3]}]  # fmt: skip
    assert [d["first_difference_at"] for d in diff["passed_different"]] == [1, 3]
    assert "passed_equals_folder" not in ctc.compare(folder, folder, None)
    assert not ctc.compare([[1, 2, 3]], folder, None)["server_equals_folder"]  # a prompt without an answer


def test_the_part_passes_only_when_hashes_and_ids_are_identical(standin: Any, tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """The part end to end with a stand-in tokenizer side (the image's ``transformers`` is not here): the same
    template and the same ids pass; another passed template fails the hash and the passed-template ids."""
    _, base = standin
    tpl = tmp_path / "models" / "chat-templates" / "gemma-4-26b-a4b-it" / "chat_template.jinja"
    tpl.parent.mkdir(parents=True)
    tpl.write_text("{% for m in messages %}{{ m.content }}{% endfor %}", encoding="utf-8")
    fake = tmp_path / "hf_side.py"  # stands in for `python -m tools.chat_template_check hf` in the server's image
    fake.write_text(
        "import hashlib, json, sys\n"
        "from tools import vllm_standin as vs\n"
        "a = dict(zip(sys.argv[4::2], sys.argv[5::2]))\n"
        "msgs = json.load(open(a['--prompts']))\n"
        "ids = [vs.tokenize({'messages': m})['tokens'] for m in msgs]\n"
        "text = open(a['--template']).read()\n"
        "own = text if 'endfor' in text else 'the folder template'\n"
        "sha = lambda t: hashlib.sha256(t.encode()).hexdigest()\n"
        "passed = ids if own == text else [i + [0] for i in ids]\n"
        "json.dump({'folder_template_sha256': sha(own), 'passed_template_sha256': sha(text), 'ids': ids,\n"
        "           'ids_passed': passed, 'folder_template_chars': len(own)}, open(a['--out'], 'w'))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TB_BENCH_EMBED_CMD", f"{sys.executable} {fake}")
    monkeypatch.setenv("TB_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    a = argparse.Namespace(dir=tmp_path / "run", live_record=None, judge_url=f"{base}/v1")
    monkeypatch.setattr(cr, "JUDGE", "local/judge")
    res = ctc.run(a)
    checks = {c[0]: c[1] for st in res["stages"] for c in st["checks"]}
    assert len(checks) == 5 and all(checks.values()), checks
    block = res["chat_template"]
    assert block["identical"] and block["folder_template_sha256"] == block["passed_text_sha256"]
    assert block["passed"]["from"] == "the registry row's file under the models root"
    assert block["tokens"]["prompts"] == 20
    tpl.write_text("another template", encoding="utf-8")
    res = ctc.run(a)
    checks = {c[0]: c[1] for st in res["stages"] for c in st["checks"]}
    assert [k for k, ok in checks.items() if not ok] == [
        "the two templates are identical (sha256 of the text)",
        "20 prompts: the passed template gives the same token ids as the folder's",
    ]
    assert res["chat_template"]["identical"] is False


def test_without_the_tokenizer_the_part_is_a_failed_row_not_a_crash(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    monkeypatch.delenv("TB_BENCH_EMBED_CMD", raising=False)
    monkeypatch.setattr(ctc, "passed_template", lambda *a, **k: {"path": None, "why": "not here"})
    res = ctc.run(argparse.Namespace(dir=tmp_path, live_record=None, judge_url=""))
    assert [c[1] for st in res["stages"] for c in st["checks"]] == [False] * 5
    assert res["chat_template"]["identical"] is False
