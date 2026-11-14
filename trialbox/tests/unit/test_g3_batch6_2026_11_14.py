"""Lane G batch 6 (2026-11-14): the run extras of plan v7 G-3 and the deep review.

1. Each hospital part keeps, per setting and repeat, every listed synthetic patient's answer to each criterion with
   its confidence, the list's sha256 and the counts of the patients not listed (``parts/<tag>/answers.jsonl.gz``).
2. The report compares the lists of a language across its settings and repeats from those answers (how many patients
   differ, which criteria flipped) and G-3's "the candidate list is identical at every setting" is a check.
3. ``--restart-between`` restarts both model servers before every hospital part after the first; the part and the
   report say whether they were restarted, and the estimate counts the restarts.
4. The estimate of G-3's whole curve (1, 4, 8, 16, 32, 48 in flight, ja and zh-TW, 50,000 patients) prints each
   setting's hours and US$; hospital VMs on demand (D-468) unless TB_PROVISIONING says otherwise.
5. Each model part records the failed context reads (``GET /v1/models``), the serving record (structured-output
   backend, image digests) and the servers' ``num_requests_running`` right after each gateway time-out.
6. An English hospital part is refused, clearly and before anything starts, while the synthetic hospital has no
   English site (profile ``ci-en``, lane B2 NEW-B-42), and planned with no further change once it has.

Each test failed before the change. No cloud, no model: pure functions, the parts' helpers on synthetic data, the
driver's ``--dry-run``, the results reader on a synthetic folder."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools import complete_run as cr
from tools import run_metrics as rm

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"
FIXTURES = ROOT / "tests" / "rehearsal" / "results-fixtures"
HEAD = "d" * 40


def _crit(cid: str, verdict: str, conf: float | None = None, basis: str | None = "pair", **ev: Any) -> dict[str, Any]:
    e: dict[str, Any] = {"resource_refs": ["DocumentReference/x"], "quote": "synthetic quote", **ev}
    if conf is not None:
        e["confidence"] = conf
    return {"id": cid, "verdict": verdict, "basis": basis, "evidence": e}


def _rows(flip: bool = False, extra: bool = False) -> list[dict[str, Any]]:
    rows = [
        {"pid": "a" * 32, "tier": "high", "criteria": [_crit("INC-01", "pass", 0.9, reason="note"),
                                                       _crit("EXC-02", "fail" if flip else "pass", 0.7)]},
        {"pid": "b" * 32, "tier": "review", "criteria": [_crit("INC-01", "unknown", basis=None, reason="data_gap")]},
    ]  # fmt: skip
    if extra:
        rows.append({"pid": "c" * 32, "tier": "review", "criteria": [_crit("INC-01", "pass", 0.6)]})
    return rows


def _box_job(rows: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> tuple[Any, Any]:
    store = {"cl": json.dumps({"rows": rows}).encode(), "ex": json.dumps({"rows": excluded}).encode()}
    job = SimpleNamespace(job_id="J1", outputs=[SimpleNamespace(filename="candidate_list_GZQO_v1.json", minio_key="cl"),
                                                SimpleNamespace(filename="excluded_GZQO_v1.json", minio_key="ex")])  # fmt: skip
    return SimpleNamespace(store=SimpleNamespace(get=store.__getitem__)), job


EXCLUDED = [{"pid": "x" * 32, "criteria": [{"id": "EXC-01"}]}, {"pid": "y" * 32, "criteria": [{"id": "EXC-01"},
                                                                                              {"id": "EXC-02"}]}]  # fmt: skip


def _save(root: Path, tag: str, rows: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> dict[str, Any]:
    box, job = _box_job(rows, excluded)
    main = rm.candidate_list_of_rows(rows)
    main["answers"] = cr.save_answers(box, job, root / "parts" / tag / rm.ANSWERS_FILE, main, tag)
    return main


# ---------------------------------------------------------------- 1. each patient's answers, kept per part
def test_the_part_keeps_each_listed_patients_answers_and_the_counts_of_the_others(tmp_path: Path) -> None:
    main = _save(tmp_path, "hospital-ja@c16#r1", _rows(), EXCLUDED)
    rec = main["answers"]
    assert rec["file"] == "parts/hospital-ja@c16#r1/answers.jsonl.gz" and rec["listed"] == 2
    assert rec["list_sha256"] == main["sha256"] and rec["excluded"] == 2
    assert rec["excluded_by_criterion"] == {"EXC-01": 2, "EXC-02": 1}
    raw = (tmp_path / rec["file"]).read_bytes()
    assert rec["bytes"] == len(raw) and len(rec["sha256"]) == 64
    head, pats = rm.read_answers(tmp_path / rec["file"])
    assert head["schema"] == rm.ANSWERS_SCHEMA and head["list_sha256"] == main["sha256"] and head["job"] == "J1"
    a = pats["a" * 32]
    assert a["tier"] == "high" and a["c"] == [{"id": "EXC-02", "v": "pass", "b": "pair", "conf": 0.7},
                                              {"id": "INC-01", "v": "pass", "b": "pair", "conf": 0.9, "r": "note"}]  # fmt: skip
    assert pats["b" * 32]["c"] == [{"id": "INC-01", "v": "unknown", "r": "data_gap"}]
    text = gzip.decompress(raw).decode("utf-8")
    assert "synthetic quote" not in text and "DocumentReference" not in text  # nothing of the note
    assert "x" * 32 not in text  # the patients not listed: counts only
    # the same answers give the same bytes (no time in the gzip header): two runs' files compare by sha256
    again = _save(tmp_path / "again", "hospital-ja@c16#r1", _rows(), EXCLUDED)["answers"]
    assert again["sha256"] == rec["sha256"]


def test_an_answer_keeps_codes_and_each_models_verdict_never_words() -> None:
    v = _crit("INC-03", "pending_human", 0.5, reason="the model said: probably yes", basis="person",
              opinions=[{"role": "verifier", "verdict": "fail", "quote": "q"}, {"role": "judge", "verdict": "pass"}])  # fmt: skip
    v["final"] = False
    assert rm.answer_of(v) == {"id": "INC-03", "v": "pending_human", "b": "person", "f": False, "conf": 0.5,
                               "o": {"judge": "pass", "verifier": "fail"}}  # fmt: skip
    assert rm.answers_of_rows([{"pid": "z", "tier": "excluded", "criteria": [v]}]) == []  # listed patients only


# ---------------------------------------------------------------- 2. the lists across settings and repeats
def _part(root: Path, tag: str, rows: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> dict[str, Any]:
    main = _save(root, tag, rows, excluded)
    n = int(tag.split("@c", 1)[1].split("#", 1)[0])
    return {"tag": tag, "part": "hospital", "lang": "ja", "llm_concurrency": n, "candidates": main,
            "screen": {"listed": main["count"]}, "throughput": {"calls": 10, "calls_per_second": 1.0},
            "stages": [{"name": "s", "ok": True, "seconds": 1, "checks": [["c", True, ""]]}], "seconds_total": 1}  # fmt: skip


def test_the_report_names_how_many_patients_differ_and_which_criteria_flipped(tmp_path: Path) -> None:
    rows = [_part(tmp_path, "hospital-ja@c16#r1", _rows(), EXCLUDED),
            _part(tmp_path, "hospital-ja@c16#r2", _rows(flip=True, extra=True), EXCLUDED[:1]),
            _part(tmp_path, "hospital-ja@c4", _rows(), EXCLUDED)]  # fmt: skip
    cmp = rm.lists_compare(rows, tmp_path)["ja"]
    assert cmp["identical"] is False and cmp["answers"] == "kept"
    assert cmp["patients_differ"] == 2  # c...: listed at one repeat only; a...: listed alike, EXC-02 flipped
    assert cmp["criteria_flipped"] == {"EXC-02": 1}
    assert cmp["differ"] == [{"pid": "c" * 32, "flipped": [], "tiers": {"hospital-ja@c16#r1": "-",
                                                                        "hospital-ja@c16#r2": "review",
                                                                        "hospital-ja@c4": "-"}}]  # fmt: skip
    assert cmp["flipped_listed_alike"] == {"a" * 32: ["EXC-02"]}
    assert cmp["excluded_by_criterion"] == {"EXC-01": {"hospital-ja@c16#r1": 2, "hospital-ja@c16#r2": 1,
                                                       "hospital-ja@c4": 2},
                                            "EXC-02": {"hospital-ja@c16#r1": 1, "hospital-ja@c16#r2": 0,
                                                       "hospital-ja@c4": 1}}  # fmt: skip
    assert cmp["excluded"] == {"hospital-ja@c16#r1": 2, "hospital-ja@c16#r2": 1, "hospital-ja@c4": 2}
    a = argparse.Namespace(model="pair", direct=False, ocr="tesseract", patients=5000, langs=["ja"], dir=tmp_path)
    rep = cr.report(a, rows, {"head": HEAD, "subject": "s", "dirty": False}, datetime.now(UTC))
    g3 = next(r for r in rep["parts"] if r["tag"] == cr.G3_LISTS)
    (name, ok, detail) = g3["stages"][0]["checks"][0]
    assert not ok and name.startswith("hospital-ja: the candidate list is identical at every setting and repeat")
    assert "2 patient(s) differ; criteria flipped: EXC-02 (1)" in detail
    assert rep["verdict"] == "FAILED" and rep["failed"] == 1
    md = cr.markdown(rep)
    assert "criteria flipped (patients): `EXC-02` 1; 1 patient(s) listed alike with another answer" in md
    assert "| `" + "c" * 32 + "` | - | review | - | - |" in md
    # the same list at every setting and repeat: the check passes, and the answers are identical too
    same = [_part(tmp_path / "s", f"hospital-ja@c{n}", _rows(), EXCLUDED) for n in (1, 16)]
    a.dir = tmp_path / "s"
    rep2 = cr.report(a, same, {"head": HEAD, "subject": "s", "dirty": False}, datetime.now(UTC))
    assert next(r for r in rep2["parts"] if r["tag"] == cr.G3_LISTS)["stages"][0]["checks"][0][1] is True
    assert rep2["candidates_compare"]["ja"]["answers_identical"] is True and rep2["verdict"] == "PASSED"


def test_answers_that_were_not_kept_are_said_and_the_check_still_judges_the_list(tmp_path: Path) -> None:
    rows = [_part(tmp_path, f"hospital-ja@c{n}", _rows(), EXCLUDED) for n in (1, 16)]
    (tmp_path / rows[1]["candidates"]["answers"]["file"]).unlink()
    cmp = rm.lists_compare(rows, tmp_path)["ja"]
    assert cmp["identical"] is True and cmp["answers"] == "not kept or not readable: hospital-ja@c16"
    assert "criteria_flipped" not in cmp
    assert rm.lists_compare([dict(r) for r in rows])["ja"]["patients_differ"] == 0  # no root: the list only


# ---------------------------------------------------------------- 3. --restart-between
def test_the_restart_runs_before_every_hospital_part_after_the_first(tmp_path: Path, monkeypatch: Any) -> None:
    seen: list[tuple[str, dict[str, Any] | None]] = []

    def fake(a: Any, cmd: list[str], env: dict[str, str]) -> int:
        tag = cr._tag(cmd[4], cmd[cmd.index("--lang") + 1] if "--lang" in cmd else "",
                      cmd[cmd.index("--variant") + 1] if "--variant" in cmd else "")  # fmt: skip
        seen.append((tag, json.loads(env[cr.RESTART_ENV]) if cr.RESTART_ENV in env else None))
        return 0

    monkeypatch.setattr(cr, "_run_part_process", fake)
    log = tmp_path / "restarts.log"
    rc = cr.main(["--dir", str(tmp_path / "run"), "--patients", "500", "--only", "hospital-ja", "--llm-concurrency",
                  "1,16", "--repeats", "2", "--restart-between", "--restart-cmd",
                  f"echo restarted >> {log}; echo TB-RESTART ok"])  # fmt: skip
    assert rc == 1  # no part reported (the fake runs nothing)
    hosp = [x for x in seen if x[0].startswith("hospital-")]
    assert len(hosp) == 4 and hosp[0][1] == {"asked": True, "restarted": False,
                                             "why": "the first hospital part of this run: the servers as booted"}  # fmt: skip
    assert all(r is not None and r["restarted"] and r["ok"] and r["exit"] == 0 and "TB-RESTART ok" in r["said"]
               for _, r in hosp[1:])  # fmt: skip
    assert log.read_text(encoding="utf-8").count("restarted") == 3
    with pytest.raises(SystemExit):  # a run needs the command
        cr.main(["--dir", str(tmp_path / "x"), "--only", "hospital-ja", "--restart-between"])


def test_the_part_records_the_restart_and_a_failed_one_is_a_failed_check() -> None:
    res: dict[str, Any] = {"stages": [{"name": "s", "ok": True, "seconds": 1, "checks": [["c", True, ""]]}]}
    cr.with_restart(res, json.dumps({"asked": True, "restarted": True, "ok": False, "exit": 1, "seconds": 3.5,
                                     "said": "TB-RESTART-FAILED: judge not healthy in 1200 s"}))  # fmt: skip
    assert res["restart"]["gateway_orchestrator"].startswith("fresh")
    assert res["stages"][0]["name"] == "model servers restarted before this part (--restart-between)"
    assert res["stages"][0]["checks"][0][1] is False and "judge not healthy" in res["stages"][0]["checks"][0][2]
    assert not cr._passed(res)
    plain: dict[str, Any] = {"stages": []}
    cr.with_restart(plain, "")
    assert plain["restart"]["restarted"] is False and plain["restart"]["why"] == "--restart-between not given"
    assert plain["stages"] == []
    first: dict[str, Any] = {"stages": []}
    cr.with_restart(first, json.dumps(cr.restart_before(argparse.Namespace(), "hospital-ja@c1", HEAD, True)))
    assert first["restart"]["restarted"] is False and first["stages"] == []


def test_the_report_says_whether_the_servers_were_restarted() -> None:
    def hosp(tag: str, restart: dict[str, Any]) -> dict[str, Any]:
        return {"tag": tag, "part": "hospital", "lang": "ja", "llm_concurrency": 16, "restart": restart,
                "throughput": {"calls": 600, "calls_per_second": 1.0},
                "throughput_screen": {"calls": 244, "calls_per_second": 4.4},
                "stages": [{"name": "s", "ok": True, "seconds": 1, "checks": [["c", True, ""]]}], "seconds_total": 1}  # fmt: skip

    rows = [hosp("hospital-ja@c16#r1", {"asked": True, "restarted": False}),
            hosp("hospital-ja@c16#r2", {"asked": True, "restarted": True, "ok": True, "seconds": 201.5})]  # fmt: skip
    rep = {"throughput": rm.curve(rows), "parts": rows, "restarts": cr.restart_summary(rows)}
    text = "\n".join(cr._throughput_section(rep))
    assert ("The model servers were restarted (--restart-between) before 1 part(s) (hospital-ja@c16#r2), each "
            "restart 201.5 to 201.5 s; all healthy again.") in text  # fmt: skip
    plain = [hosp("hospital-ja@c16#r1", {}), hosp("hospital-ja@c16#r2", {})]
    text2 = "\n".join(cr._throughput_section({"throughput": rm.curve(plain), "parts": plain}))
    assert "The model servers were not restarted between settings or repeats (--restart-between not given)" in text2


def test_the_estimate_counts_one_restart_per_hospital_part_after_the_first(capsys: Any) -> None:
    base = cr.restrict(cr.estimate(50000, llm_concurrency=(16,), repeats=2, order_seed=3), ["hospital-ja"])
    e = cr.restrict(cr.estimate(50000, llm_concurrency=(16,), repeats=2, order_seed=3, restart_between=True),
                    ["hospital-ja"])  # fmt: skip
    hosp = [r for r in e["rows"] if r.get("restart_seconds") is not None]
    assert [r["restart_seconds"] for r in hosp] == [0.0, cr.RESTART_SECONDS] and cr.RESTART_SECONDS == 199.0
    assert e["hours"] == pytest.approx(base["hours"] + 199 / 3600, abs=0.011) and e["restart_between"] is True
    # a bounded run whose first planned hospital part is not the estimate's first: that one needs no restart
    z = cr.restrict(cr.estimate(50000, llm_concurrency=(16,), repeats=2, restart_between=True), ["hospital-zh-TW"])
    assert [r["restart_seconds"] for r in z["rows"] if r.get("restart_seconds") is not None] == [0.0, 199.0]
    assert cr.main(["--estimate", "--patients", "50000", "--only", "hospital-ja", "--repeats", "2",
                    "--restart-between", "--order-seed", "3"]) == 0  # fmt: skip
    out = capsys.readouterr().out
    assert "--restart-between: both model servers restarted before every hospital part after the first (1 " in out
    assert "not restarted" not in out


def test_the_driver_puts_the_restart_on_the_vm(tmp_path: Path) -> None:
    env = dict(os.environ, TB_COMPLETE_DIR=str(tmp_path / "out"), PY=str(ROOT / ".venv" / "bin" / "python"),
               TB_RUN_ID="R")  # fmt: skip
    for k in ("TB_ZONES", "TB_ESTIMATE_LLM_SPEEDUP", "TB_PROVISIONING"):
        env.pop(k, None)
    r = subprocess.run([str(GCP / "complete-run.sh"), "--dry-run", "--patients", "5000", "--only", "hospital-ja",
                        "--repeats", "2", "--restart-between", "--order-seed", "7"], cwd=ROOT, env=env,
                       capture_output=True, text=True, check=False, timeout=300)  # fmt: skip
    assert r.returncode == 0, r.stderr[-800:]
    meta = next(ln for ln in r.stdout.splitlines() if "add-metadata" in ln and "tb-run-id=" in ln)
    assert "tb-order-seed=7,tb-restart-between=1," in meta
    assert json.loads((tmp_path / "out" / "plan.json").read_text(encoding="utf-8"))["restart_between"] is True
    vm = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")
    assert "RESTART_ARGS=(--restart-between --restart-cmd /usr/local/sbin/tb-restart-servers)" in vm
    assert '"${RESTART_ARGS[@]}"' in vm and "cat >/usr/local/sbin/tb-restart-servers <<EOS" in vm
    shim = (ROOT / "tests" / "rehearsal" / "shims" / "docker").read_text(encoding="utf-8")
    assert "  stop)" in shim and "  start)" in shim  # the rehearsal's docker restarts the stand-ins


# ---------------------------------------------------------------- 4. G-3's whole curve at 50,000
def test_the_whole_g3_curve_is_estimated_per_setting(capsys: Any, monkeypatch: Any) -> None:
    monkeypatch.delenv("TB_PROVISIONING", raising=False)
    monkeypatch.delenv("TB_ESTIMATE_LLM_SPEEDUP", raising=False)
    argv = ["--estimate", "--patients", "50000", "--only", "hospital-ja,hospital-zh-TW", "--llm-concurrency",
            "1,4,8,16,32,48", "--order-seed", "5"]  # fmt: skip
    argv[4:5] = ["hospital-ja", "hospital-zh-TW"]
    assert cr.main(argv) == 0
    out = capsys.readouterr().out
    lines = [ln.strip() for ln in out.splitlines() if " in flight: 2 part(s) (ja, zh-TW)," in ln]
    assert [int(ln.split()[0]) for ln in lines] == [1, 4, 8, 16, 32, 48]
    assert "(above max_num_seqs: measures the gateway queue)" in lines[-1] and "above" not in lines[3]
    assert "one VM: on demand (a hospital part, D-468)" in out
    monkeypatch.setenv("TB_PROVISIONING", "SPOT")
    assert cr.main(argv) == 0
    assert "one VM: spot" in capsys.readouterr().out


# ---------------------------------------------------------------- 5. context reads, the serving record, time-outs
def test_the_serving_record_is_in_the_parts_metrics(tmp_path: Path) -> None:
    rec = {"captured_at": "2026-11-14T00:00:00Z", "servers": [
        {"role": "judge", "image": "vllm/vllm-openai:v0.32.0", "image_digests": ["vllm/vllm-openai@sha256:ab"],
         "structured_outputs_backend": "auto", "vllm_version": "0.32.0", "max_num_seqs": 16, "model": "m/x"},
        {"role": "verifier", "image": "vllm/vllm-openai:v0.32.0", "image_digests": [], "max_num_seqs": 16}]}  # fmt: skip
    f = tmp_path / "rec.json"
    f.write_text(json.dumps(rec), encoding="utf-8")
    b = rm.serving_block(f)
    assert b["servers"]["judge"] == {"image": "vllm/vllm-openai:v0.32.0", "image_digests": ["vllm/vllm-openai@sha256:ab"],
                                     "structured_outputs_backend": "auto", "vllm_version": "0.32.0",
                                     "max_num_seqs": 16}  # fmt: skip
    assert b["servers"]["verifier"]["structured_outputs_backend"] == "not recorded"
    assert b["backend_named"] is False and b["digests"] is False and "m/x" not in json.dumps(b)
    assert rm.serving_block(None) == {"recorded": False, "why": "no serving record of this run (--live-record)"}


def test_failed_context_reads_are_counted() -> None:
    from tb_llm.client import GatewayClient

    class Http:
        def __init__(self) -> None:
            self.ok = False

        def get(self, url: str, headers: Any = None) -> Any:
            if not self.ok:
                raise __import__("httpx").ConnectError("down")
            return SimpleNamespace(status_code=200, json=lambda: {"data": [{"id": "j", "context_length": 32768}]})

    http = Http()
    c = GatewayClient("http://gw/v1", "orchestrator", http=http)  # type: ignore[arg-type]
    cc = cr.ContextChecks()
    cc.install()
    try:
        assert c.contexts() == {} and c.contexts() == {}
        http.ok = True
        assert c.contexts() == {"j": 32768} and c.contexts() == {"j": 32768}  # the second from the client's cache
    finally:
        got = cc.uninstall()
    assert (got["asked"], got["failed"], got["from_cache"]) == (3, 2, 1) and len(got["failed_at"]) == 2
    assert GatewayClient.contexts is not None and c.contexts() == {"j": 32768}  # put back


class _Metrics(BaseHTTPRequestHandler):
    running = 3.0

    def log_message(self, *a: Any) -> None:
        return

    def do_GET(self) -> None:
        body = f"vllm:num_requests_running {self.running}\nvllm:num_requests_waiting 1\n".encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)


def test_the_servers_are_read_right_after_a_gateway_timeout(tmp_path: Path) -> None:
    srv = HTTPServer(("127.0.0.1", 0), _Metrics)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    audit = tmp_path / "gw-audit-hospital"
    audit.mkdir()
    old = {"ts": "2026-11-14T00:00:00+00:00", "event": "llm.gateway.refuse",
           "detail": {"reason": "upstream_failed", "message": "serving: ReadTimeout"}}  # fmt: skip
    (audit / "a.jsonl").write_text(json.dumps(old) + "\n", encoding="utf-8")  # an earlier part's: not counted
    url = f"http://127.0.0.1:{srv.server_port}/judge/v1"
    try:
        w = rm.TimeoutWatch(audit, tmp_path / "parts" / "hospital-ja", {"judge": url}, every=60).start()
        new = [{**old, "ts": "2026-11-14T00:01:00+00:00", "detail": {"reason": "upstream_failed", "endpoint": "serving",
                                                                    "message": "serving: ReadTimeout"}},
               {**old, "detail": {"reason": "upstream_failed", "message": "serving: HTTP 400"}},
               {**old, "event": "llm.gateway.call", "detail": {"latency_ms": 5}}]  # fmt: skip
        with (audit / "a.jsonl").open("a", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(x) + "\n" for x in new))
        got = w.stop()
    finally:
        srv.shutdown()
    assert got["timeouts"] == 1 and got["file"] == "parts/hospital-ja/after-timeout.csv"
    assert got["servers"]["judge"] == {"samples": 1, "running_max": 3.0, "running_mean": 3.0, "still_running": 1}
    csv_text = (tmp_path / got["file"]).read_text(encoding="utf-8")
    assert "2026-11-14T00:01:00+00:00,upstream_failed,serving,judge,3.0,1.0" in csv_text
    # an interactive call's read time-out is "<endpoint>: busy"; a call that got no slot is the gateway's own message
    assert rm.is_timeout({"event": "llm.gateway.refuse", "detail": {"message": "verifier: busy"}}) is True
    no_slot = {"reason": "model_busy", "message": "the model is busy (a screening run is using the GPU); try again"}
    assert rm.is_timeout({"event": "llm.gateway.refuse", "detail": no_slot}) is False
    assert rm.is_timeout({"event": "llm.gateway.call", "detail": {"message": "x: ReadTimeout"}}) is False
    assert 0 < rm.TIMEOUT_WATCH_S < 3.2


def test_the_report_shows_the_serving_record_context_reads_and_timeouts() -> None:
    m = {"serving": {"servers": {"judge": {"structured_outputs_backend": "xgrammar", "image": "i",
                                           "image_digests": ["i@sha256:1"]}}},
         "context_checks": {"asked": 4, "failed": 1},
         "after_timeout": {"timeouts": 2, "servers": {"judge": {"samples": 2, "running_max": 5.0,
                                                                "still_running": 2}}}}  # fmt: skip
    row = {"tag": "hospital-ja", "part": "hospital", "metrics": m, "throughput": {"calls": 1, "calls_per_second": 1}}
    text = "\n".join(cr._throughput_section({"throughput": rm.curve([row]), "parts": [row]}))
    assert (
        "* `hospital-ja`: serving judge: backend xgrammar, image i (i@sha256:1). Context reads (/v1/models): 4 "
        "asked, **1 failed**. Gateway time-outs: 2 (judge running max 5.0, still running in 2 of 2)."
    ) in text


# ---------------------------------------------------------------- 6. English
def test_an_english_hospital_part_is_refused_while_there_is_no_english_site(
    capsys: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from tools import synth_hospital

    monkeypatch.delitem(synth_hospital.PROFILES, "ci-en", raising=False)
    with pytest.raises(SystemExit) as exc:
        cr.main(["--estimate", "--patients", "50000", "--only", "hospital-en"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "hospital-en: the synthetic hospital has no English site on this commit (profile ci-en" in err
    assert "NEW-B-42" in err
    with pytest.raises(SystemExit):  # a run is refused the same way, before any part
        cr.main(["--dir", str(tmp_path), "--only", "hospital-en"])
    with pytest.raises(SystemExit):
        cr.main(["--estimate", "--langs", "ja", "en"])
    assert cr.main(["--estimate", "--patients", "5000", "--only", "hospital-ja"]) == 0  # ja and zh-TW unchanged
    env = dict(os.environ, TB_COMPLETE_DIR=str(tmp_path / "out"), PY=str(ROOT / ".venv" / "bin" / "python"))
    r = subprocess.run([str(GCP / "complete-run.sh"), "--estimate", "--only", "hospital-en"], cwd=ROOT, env=env,
                       capture_output=True, text=True, check=False, timeout=120)  # fmt: skip
    assert r.returncode == 2 and "no English site" in r.stderr


def test_an_english_hospital_part_runs_with_no_further_change_once_the_site_exists(
    capsys: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    from tools import synth_hospital

    monkeypatch.setitem(synth_hospital.PROFILES, "ci-en", {"sites": "en-a:EN:2500,en-b:EN:2500", "tolerance": 0.05})
    assert cr.hospital_lang_problem("en") == "" and cr.hospital_patients("en", 50000) == 5000
    assert cr.synth_dir(tmp_path, "en", 50000) == tmp_path / "synth-ci-en-5000"
    assert cr.synth_dir(tmp_path, "ja", 50000) == tmp_path / "synth-50000"
    assert cr.main(["--estimate", "--patients", "50000", "--only", "hospital-en", "--json"]) == 0
    e = json.loads(capsys.readouterr().out)
    hosp = [r for r in e["rows"] if r["tags"] and r["tags"][0].startswith("hospital-")]
    assert [(r["tags"], r["patients"]) for r in hosp] == [(["hospital-en"], 5000)]
    assert e["plan"]["shards"][0]["tags"] == ["prepare", "hospital-en"]
    a = argparse.Namespace(langs=["ja", "zh-TW", "en"], scenarios=["gateway"], skip=[], only=["prepare", "hospital-en"],
                           llm_concurrency="", dir=tmp_path, patients=50000, model="stub", ocr="fake", run_id="R",
                           direct=False, live_record=None, resume=False, keep_work=False, lc=(16,))  # fmt: skip
    assert [cr._tag(*p) for p in cr.plan(a)] == ["prepare", "hospital-en"]
    cmd = cr._cmd(a, "prepare", "", "", tmp_path)
    assert cmd[cmd.index("--hospital-langs") + 1 :] == ["en"]
    assert cr.langs_named(["hospital-en@c16#r2", "public-ja", "scenario-gateway"]) == ["en", "ja"]


# ---------------------------------------------------------------- the results reader
def _reader() -> Any:
    spec = importlib.util.spec_from_file_location("results_report_b6", GCP / "results_report.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["results_report_b6"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_results_reader_keeps_the_comparison_not_the_answers(tmp_path: Path) -> None:
    rr = _reader()
    folder = tmp_path / "run"
    shutil.copytree(FIXTURES / "complete", folder)
    parts = folder / "parts"
    for f in parts.glob("hospital-ja@c*.json"):
        doc = json.loads(f.read_text(encoding="utf-8"))
        doc["restart"] = {"asked": True, "restarted": f.stem != "hospital-ja@c1", "ok": True}
        doc.setdefault("candidates", {})["answers"] = {"file": f"parts/{f.stem}/answers.jsonl.gz", "bytes": 10,
                                                       "sha256": "e" * 64, "listed": 2, "excluded": 3}  # fmt: skip
        f.write_text(json.dumps(doc), encoding="utf-8")
    (folder / "report").mkdir(exist_ok=True)
    (folder / "report" / "report.json").write_text(json.dumps({"candidates_compare": {"ja": {
        "identical": True, "answers": "kept", "patients_differ": 1, "criteria_flipped": {"EXC-02": 1},
        "flipped_listed_alike": {"a" * 32: ["EXC-02"]}, "differ": []}}}), encoding="utf-8")  # fmt: skip
    out = tmp_path / "out"
    assert rr.main([str(folder), "--out", str(out), "--window-patients", "50000", "--studies", "5",
                    "--night-hours", "8"]) == 0  # fmt: skip
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "- Kept answers: 1 patient(s) differ; criteria flipped (patients): `EXC-02` 1." in readme
    assert "The model servers were restarted (--restart-between) before 4, 16, 48" in readme
    cap = json.loads((out / "capacity_inputs.json").read_text(encoding="utf-8"))
    g3 = cap["g3"]["ja"]
    assert g3["answers_compare"]["criteria_flipped"] == {"EXC-02": 1} and g3["restarted"] == [4, 16, 48]
    assert next(s for s in g3["settings"] if s["in_flight"] == 16)["answers"]["sha256"] == "e" * 64
    text = "".join(p.read_text(encoding="utf-8") for p in out.iterdir())
    assert "a" * 32 not in text  # no patient id leaves the run's folder through the reader
    assert not list(out.rglob("*.gz"))


# ---------------------------------------------------------------- the rehearsal's check of run-a
def _check_module() -> Any:
    spec = importlib.util.spec_from_file_location("rehearsal_check_b6", ROOT / "tests" / "rehearsal" / "check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rehearsal_check_b6"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_rehearsal_checks_the_answers_the_restart_and_the_records(tmp_path: Path, capsys: Any) -> None:
    ck = _check_module()
    tags = ["hospital-ja@c16#r2", "hospital-ja@c16#r1"]
    rows = []
    for i, tag in enumerate(tags):
        p = _part(tmp_path, tag, _rows(), EXCLUDED)
        p["started_at"] = f"2026-11-14T0{i}:00:00+00:00"
        p["restart"] = {"asked": True, "restarted": i == 1, **({"ok": True} if i == 1 else {})}
        p["metrics"] = {"serving": {"backend_named": True, "digests": True},
                        "context_checks": {"asked": 1, "failed": 0}, "after_timeout": {"timeouts": 0}}  # fmt: skip
        rows.append(p)
    a = argparse.Namespace(model="pair", direct=False, ocr="tesseract", patients=500, langs=["ja"], dir=tmp_path)
    rep = cr.report(a, rows, {"head": HEAD, "subject": "s", "dirty": False}, datetime.now(UTC))
    res = {f"parts/{t}/answers.jsonl.gz": (tmp_path / "parts" / t / rm.ANSWERS_FILE).read_bytes() for t in tags}
    vm = "--restart-between: done in 21.0 s (TB-RESTART ok: judge and verifier restarted ...)"
    r = ck.Result("run-a")
    ck.check_batch6(r, rep, res, vm, 2)
    assert r.bad == 0 and r.n >= 16, capsys.readouterr().out
    # the same evidence without the restart, or without a part's answers: the check says so
    r2 = ck.Result("run-a")
    ck.check_batch6(r2, rep, {k: v for k, v in res.items() if "#r1" not in k}, "", 2)
    out = capsys.readouterr().out
    assert r2.bad >= 2 and "FAIL  results.tgz has parts/hospital-ja@c16#r1/answers.jsonl.gz" in out
    assert "FAIL  vm.log: tb-restart-servers said TB-RESTART ok" in out
