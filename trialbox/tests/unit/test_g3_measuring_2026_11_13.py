"""The measuring fixes from the audit of run 20261112T165042Z-931a0f79 (hospital-ja at 1, 4, 16, 48 calls in flight);
each test failed before its fix. Synthetic numbers shaped as that run's results; no GPU, no cloud."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tools import chat_template_check as ctc
from tools import complete_run as cr
from tools import run_metrics as rm

HEAD = "e" * 40
T0 = datetime(2026, 11, 12, 17, 30, tzinfo=UTC).timestamp()


# ---------------------------------------------------------------- a: stage times, the main SCREEN's window
def test_stages_carry_their_start_and_end() -> None:
    @dataclass
    class Stage:
        name: str
        checks: list[tuple[str, bool, str]] = field(default_factory=list)
        seconds: float = 0.0

        @property
        def ok(self) -> bool:
            return True

    mod = SimpleNamespace(Stage=Stage)
    orig = cr.timed_stages(mod)
    st = mod.Stage("3 screening")
    st.seconds = 12.0
    mod.Stage = orig
    got = cr._stages([st])[0]
    assert got["started_at"] and got["ended_at"] and got["ended_at"] > got["started_at"]
    job = SimpleNamespace(received_at=datetime.fromtimestamp(T0, UTC), updated_at=datetime.fromtimestamp(T0 + 600, UTC))
    w = cr.screen_window(job)
    assert w is not None and w["from"] == T0 and w["to"] == T0 + 600
    assert cr.screen_window(SimpleNamespace(received_at=None, updated_at=None)) is None


def test_the_curve_is_over_the_main_screens_window(tmp_path: Path) -> None:
    """108 canary calls one at a time before the SCREEN and stage 15/17 calls after it no longer dilute the rate."""
    canary = [{"end": T0 - 300 + 2 * i, "latency_s": 2.0, "tokens_in": 10, "tokens_out": 1, "endpoint": "serving",
               "cached": False} for i in range(108)]  # fmt: skip
    screen = [{"end": T0 + 10 + i * 0.5, "latency_s": 2.0, "tokens_in": 800, "tokens_out": 100, "endpoint": "serving",
               "cached": False} for i in range(400)]  # fmt: skip
    later = [{"end": T0 + 900 + 3 * i, "latency_s": 3.0, "tokens_in": 10, "tokens_out": 1, "endpoint": "serving",
              "cached": False} for i in range(100)]  # fmt: skip
    inside = rm.window_calls(canary + screen + later, T0, T0 + 600)
    assert len(inside) == 400
    whole, main = rm.call_stats(canary + screen + later), rm.call_stats(inside)
    assert main["calls_per_second"] > 2 * whole["calls_per_second"]
    gpu = tmp_path / "gpu.csv"
    rows = ["timestamp,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"]
    for k, util in enumerate([0, 0, 90, 95, 80, 0, 0]):
        at = datetime.fromtimestamp(T0 - 200 + k * 150, UTC).strftime("%Y/%m/%d %H:%M:%S.000")
        rows.append(f"{at}, {util}, 62590, 97887, 40, 200.0")
    gpu.write_text("\n".join(rows) + "\n", encoding="utf-8")
    (tmp_path / "vllm.csv").write_text(
        "at,server,running,waiting,kv_cache_usage\n"
        f"{datetime.fromtimestamp(T0 + 60, UTC).isoformat()},judge,4,0,0.05\n"
        f"{datetime.fromtimestamp(T0 + 2000, UTC).isoformat()},judge,1,0,0.9\n",
        encoding="utf-8",
    )
    card = rm.window_card(tmp_path, T0, T0 + 600)
    assert card["gpu"]["util_max_pct"] == 95.0 and card["gpu"]["samples"] == 4
    assert card["kv_cache_usage_max"] == {"judge": 0.05}  # the 0.9 after the window is not the SCREEN's
    part = {"tag": "hospital-ja@c4", "part": "hospital", "lang": "ja", "llm_concurrency": 4, "stages": [],
            "seconds_total": 1, "throughput": whole, "throughput_screen": {**main, **card},
            "metrics": {"gpu": {"samples": 7, "util_mean_pct": 37.9}}}  # fmt: skip
    curve = rm.curve([part])
    assert [r["window"] for r in curve] == ["main SCREEN", "whole part"]
    assert curve[0]["calls"] == 400 and curve[0]["kv_cache_peak"] == {"judge": 0.05}
    a = argparse.Namespace(model="pair", direct=False, ocr="tesseract", patients=5000, langs=["ja"])
    md = cr.markdown(cr.report(a, [part], {"head": HEAD, "subject": "s", "dirty": False}, datetime.now(UTC)))
    assert "| hospital-ja@c4 | main SCREEN | 4 | 400 |" in md and "| hospital-ja@c4 | whole part |" in md
    assert "not a headroom measure" in md and "Not measured: the gateway's slot wait" in md


# ---------------------------------------------------------------- b: the main SCREEN's per-patient list, per setting
def test_the_main_screens_rows_are_kept_per_setting(tmp_path: Path) -> None:
    rows = [{"pid": "a" * 32, "tier": "high", "judge_verdict": "fail", "verifier_verdict": "fail", "note": "x"},
            {"pid": "b" * 32, "tier": "review"}]  # fmt: skip
    store = {"k": json.dumps({"rows": rows}).encode()}
    job = SimpleNamespace(job_id="J1", outputs=[SimpleNamespace(filename="candidate_list_GZQO_v1.json", minio_key="k")])
    out = tmp_path / "parts" / "hospital-ja@c4" / "screen-list.json"
    assert cr.save_screen_rows(SimpleNamespace(store=SimpleNamespace(get=store.__getitem__)), job, out) == 2
    got = json.loads(out.read_text(encoding="utf-8"))
    assert got["job"] == "J1" and got["rows"][0] == {"pid": "a" * 32, "tier": "high", "judge_verdict": "fail",
                                                    "verifier_verdict": "fail"}  # fmt: skip


# ---------------------------------------------------------------- e: the order of the curve's settings
def test_the_settings_order_is_seeded_and_recorded() -> None:
    lc = (1, 4, 16, 48)
    a, b = cr.shuffled(lc, 7), cr.shuffled(lc, 7)
    assert a == b and sorted(a) == list(lc)
    lines = cr.concurrency_lines({"llm_concurrency": list(a), "llm_concurrency_order": {"seed": 7, "given": list(lc)},
                                  "max_num_seqs": 16, "llm_speedup": [1, 1, 1, 1]})  # fmt: skip
    text = "\n".join(lines)
    assert "randomised with seed 7 (given: 1, 4, 16, 48" in text and "measures the gateway queue" in text


# ---------------------------------------------------------------- f: the report's text
def _row(tag: str, lang: str, ok: bool, at: str) -> dict[str, Any]:
    detail = "x" * 900
    return {"tag": tag, "part": "hospital", "lang": lang, "seconds_total": 600.0, "started_at": at,
            "finished_at": at.replace("T17", "T18"),
            "stages": [{"name": "12 site set-up", "ok": ok, "seconds": 1, "checks": [["c12", ok, detail]]}]}  # fmt: skip


def test_the_report_says_what_ran_when_and_where_each_failure_is(tmp_path: Path) -> None:
    rows = [_row("hospital-ja@c1", "ja", False, "2026-11-12T17:00:00+00:00"),
            _row("hospital-ja@c4", "ja", True, "2026-11-12T17:10:00+00:00")]  # fmt: skip
    a = argparse.Namespace(model="pair", direct=False, ocr="tesseract", patients=5000, langs=["ja", "zh-TW"])
    rep = cr.report(a, rows, {"head": HEAD, "subject": "s", "dirty": False}, datetime(2026, 11, 13, tzinfo=UTC))
    md = cr.markdown(rep)
    assert "Languages run: ja." in md and "zh-TW" not in md
    assert "Run started 2026-11-12T17:00:00+00:00, finished 2026-11-12T18:10:00+00:00 (the parts' own times)" in md
    assert "1 of 2 checks passed (1 failed)" in md and "20.0 min of part time (each part's wall time, summed" in md
    assert "* FAILED (hospital-ja@c1 / 12 site set-up): c12:" in md
    cr.save_report(rep, tmp_path)
    full = json.loads((tmp_path / cr.FAILED_DETAIL_FILE).read_text(encoding="utf-8"))
    assert full == [{"part": "hospital-ja@c1", "stage": "12 site set-up", "check": "c12", "detail": "x" * 900}]
    old = [{k: v for k, v in r.items() if k not in ("started_at", "finished_at")} for r in rows]
    md2 = cr.markdown(cr.report(a, old, {"head": HEAD, "subject": "s", "dirty": False}, datetime.now(UTC)))
    assert "Run start and end: not recorded in the parts" in md2


# ---------------------------------------------------------------- g: G-1's three verdicts
def test_g1_reports_three_verdicts_and_every_differing_prompt() -> None:
    folder = [[1, 2, 3, i] for i in range(20)]
    server = [[1, 2, 9, i] if i % 2 else [1, 2, 3, i] for i in range(20)]
    cmp = ctc.compare(server, folder, folder)
    assert len(cmp["server_different"]) == 10  # was cut at 5
    block = {"judge_started_with": None, "tokens": cmp,
             "verdicts": {"passed_vs_folder_text_sha256": False, "passed_vs_folder_token_ids": True,
                          "server_vs_folder_token_ids": False, "server_started_with_chat_template": False}}  # fmt: skip
    row = {"tag": "chat-template", "part": "chat-template", "lang": "", "seconds_total": 5, "chat_template": block,
           "stages": [{"name": "G-1", "ok": False, "seconds": 5, "checks": [["t", False, ""]]}]}  # fmt: skip
    a = argparse.Namespace(model="pair", direct=False, ocr="tesseract", patients=5000, langs=["ja"])
    md = cr.markdown(cr.report(a, [row], {"head": HEAD, "subject": "s", "dirty": False}, datetime.now(UTC)))
    assert "text (sha256): **DIFFERENT**" in md and "token ids (the folder's tokenizer): identical" in md
    assert "The server against the folder's tokenizer, token ids: **DIFFERENT**" in md
    assert "started with --chat-template: no" in md and "server against folder (10): #1 at token 2" in md


def test_the_driver_randomises_the_curve_unless_kept() -> None:
    root = Path(__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if k != "TB_ZONES"}
    base = [str(root / "deploy" / "gcp" / "complete-run.sh"), "--estimate", "--patients", "5000", "--only",
            "hospital-ja", "--llm-concurrency", "1,4,16,48"]  # fmt: skip
    seeded = subprocess.run([*base, "--order-seed", "7"], cwd=root, env=env, capture_output=True, text=True, check=True)
    assert "randomised with seed 7 (given: 1, 4, 16, 48" in seeded.stdout
    assert f"TB_SCREEN_LLM_CONCURRENCY): {', '.join(map(str, cr.shuffled((1, 4, 16, 48), 7)))};" in seeded.stdout
    drawn = subprocess.run(base, cwd=root, env=env, capture_output=True, text=True, check=True)
    assert "randomised with seed" in drawn.stdout  # no seed given: one is drawn and printed
    kept = subprocess.run([*base, "--keep-order"], cwd=root, env=env, capture_output=True, text=True, check=True)
    assert "order: as given" in kept.stdout and "TB_SCREEN_LLM_CONCURRENCY): 1, 4, 16, 48;" in kept.stdout
