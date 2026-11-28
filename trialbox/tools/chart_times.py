"""The time per chart (card R1-P2, the owner's ruling of 2026-11-23): what one screening run spends on each patient's
chart, split by stage, as a median and a 95th percentile, with the cards' and the CPU's use while it ran.

Two commands, run on the box that screens (the walk's B200; any box with ``nvidia-smi`` and the model servers):

    python -m tools.chart_times watch --folder F [--server judge=URL --server verifier=URL] [--key-file K]
    python -m tools.chart_times report --audit-dir A --folder F [--timing T | --job-dir J] [--since ISO]
                                       [--until ISO] [--ingest-seconds S --ingest-patients N] [--out report.json]

``watch`` samples until it is stopped (``SIGINT`` or ``SIGTERM``, or the file ``F/stop`` appearing): the cards
(``gpu.csv``) and the servers' gauges (``vllm.csv``) through :class:`tools.run_metrics.Monitor`, the servers'
``/metrics`` before and after, and the CPU from ``/proc/stat`` (``cpu.csv``) at the same interval. It writes
``F/watch.json`` when it stops. The servers' key is read from ``--key-file`` (a root-only file), never from the command
line, and never written anywhere.

``report`` reads what the run already records and joins it per chart:

* **each model call** (``llm.call``, written by ``tb_common.llm``): the patient, the role (judge or verifier), the
  cascade stage (S3 or S4), the call's time on the caller's side (``ms``) and its tokens (``asking`` of H-16);
* **the gateway's record of the same call** (``llm.gateway.call``, by ``call_id``): the time at the server
  (``latency_ms``) and the time waiting for a server slot (``slot_wait_ms``);
* **the servers' own counters** (``F/vllm-<server>-before.prom`` and ``-after.prom``): requests, tokens, and the summed
  time in the server's queue, in prefill and in decode, so the split of the model time is the server's, not a guess;
* **each stage's wall time and patients**: the file a SCREEN or MICROBATCH run publishes while the flag
  ``screen.timing`` is on (``--timing``, ``cascade_timing_<study>_v<n>.json``: counts and seconds only, the judge and
  verifier passes summed when one card is time-shared), or a cascade output folder (``--job-dir``:
  ``cascade_log.jsonl`` and ``cascade_timing.json``);
* **ingest**: ``--ingest-seconds`` and ``--ingest-patients`` from the ingest job's record (the walk's log line).

What a chart's numbers mean. A chart's **model time** is the sum of its own calls' times: the time the models spent
on that chart, which calls running side by side overlap. The **throughput** is the run's wall time over its charts:
what a chart costs the run. Both are reported; neither is the other. A bulk stage (the coded rules, retrieval,
writes) runs over all charts at once, so its time is given per stage and per 1,000 charts, not per chart.

Standard library only. No patient text is read: ids, counts and times. The report holds no pseudonym: only counts,
times and percentiles, so it can leave the box with the walk's logs.
"""

from __future__ import annotations

import argparse
import csv
import json
import signal
import sys
import time
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.run_metrics import SAMPLE_S, Monitor, gpu_summary, parse_prometheus, percentile

STOP_FILE = "stop"
CPU_FIELDS = ("at", "busy_share", "cores")
#: the servers' counters that split the model time (vLLM's names; a server without one gives none, said so)
SPLIT: dict[str, tuple[str, str]] = {
    "queue": ("vllm:request_queue_time_seconds_sum", "vllm:request_queue_time_seconds_count"),
    "prefill": ("vllm:request_prefill_time_seconds_sum", "vllm:request_prefill_time_seconds_count"),
    "decode": ("vllm:request_decode_time_seconds_sum", "vllm:request_decode_time_seconds_count"),
    "first_token": ("vllm:time_to_first_token_seconds_sum", "vllm:time_to_first_token_seconds_count"),
    "end_to_end": ("vllm:e2e_request_latency_seconds_sum", "vllm:e2e_request_latency_seconds_count"),
}
TOKENS = {
    "prompt_tokens": "vllm:prompt_tokens_total",
    "generation_tokens": "vllm:generation_tokens_total",
    "requests": "vllm:request_success_total",
}


# ---------------------------------------------------------------- the CPU
def cpu_times(text: str) -> tuple[int, int, int] | None:
    """``/proc/stat``'s first line as (busy, total) jiffies and the number of cores; None when it is not there."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("cpu "):
        return None
    v = [int(x) for x in lines[0].split()[1:]]
    idle = v[3] + (v[4] if len(v) > 4 else 0)  # idle + iowait
    cores = sum(1 for ln in lines if ln.startswith("cpu") and ln[3:4].isdigit())
    return sum(v) - idle, sum(v), cores


def cpu_share(before: tuple[int, int, int] | None, after: tuple[int, int, int] | None) -> float | None:
    """The share of all cores busy between two readings (0..1), or None."""
    if before is None or after is None or after[1] <= before[1]:
        return None
    return round((after[0] - before[0]) / (after[1] - before[1]), 4)


def read_proc_stat(path: Path = Path("/proc/stat")) -> tuple[int, int, int] | None:
    try:
        return cpu_times(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def cpu_summary(rows: Iterable[dict[str, str]]) -> dict[str, Any]:
    shares = [float(r["busy_share"]) for r in rows if r.get("busy_share") not in (None, "")]
    if not shares:
        return {"samples": 0, "why": "no /proc/stat on this machine"}
    return {
        "samples": len(shares),
        "busy_mean_pct": round(100 * sum(shares) / len(shares), 1),
        "busy_max_pct": round(100 * max(shares), 1),
    }


# ---------------------------------------------------------------- watch
def watch(
    folder: Path,
    servers: dict[str, str],
    key: str,
    every: float = SAMPLE_S,
    max_seconds: float | None = None,
    stat: Path = Path("/proc/stat"),
) -> dict[str, Any]:
    """Sample until stopped (a signal, ``folder/stop``, or ``max_seconds``); write and return ``watch.json``."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / STOP_FILE).unlink(missing_ok=True)
    stopping = {"now": False}

    def _stop(*_: Any) -> None:
        stopping["now"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _stop)
    mon = Monitor(folder, servers, key, every=every).start()
    t0 = time.time()
    with (folder / "cpu.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CPU_FIELDS)
        prev = read_proc_stat(stat)
        while not stopping["now"] and not (folder / STOP_FILE).exists():
            left = None if max_seconds is None else max_seconds - (time.time() - t0)
            if left is not None and left <= 0:
                break
            time.sleep(every if left is None else min(every, left))
            now = read_proc_stat(stat)
            share = cpu_share(prev, now)
            w.writerow(
                [
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                    "" if share is None else share,
                    now[2] if now else "",
                ]
            )
            fh.flush()
            prev = now
    out = {
        "from": datetime.fromtimestamp(t0).astimezone().isoformat(timespec="seconds"),
        "to": datetime.now().astimezone().isoformat(timespec="seconds"),
        "seconds": round(time.time() - t0, 1),
        "monitor": mon.stop(),
    }
    (folder / "watch.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------- the records
def _records(audit_dir: Path, events: tuple[str, ...]) -> Iterable[dict[str, Any]]:
    for f in sorted(audit_dir.glob("**/*.jsonl")) if audit_dir.is_dir() else []:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if not any(f'"{e}"' in line for e in events):
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("event") in events:
                yield rec


def _in_window(rec: dict[str, Any], since: datetime | None, until: datetime | None) -> bool:
    try:
        at = datetime.fromisoformat(str(rec["ts"]))
    except (KeyError, ValueError):
        return False
    return (since is None or at >= since) and (until is None or at <= until)


def model_calls(audit_dir: Path, since: datetime | None = None, until: datetime | None = None) -> list[dict[str, Any]]:
    """Every cascade model call in the window: patient, role, stage, caller's ms, tokens, and the gateway's server
    and slot times by ``call_id`` (0 when the call went past no gateway)."""
    gateway: dict[str, dict[str, Any]] = {}
    calls: list[dict[str, Any]] = []
    for rec in _records(audit_dir, ("llm.call", "llm.gateway.call")):
        if not _in_window(rec, since, until):
            continue
        d = rec.get("detail") or {}
        if rec["event"] == "llm.gateway.call":
            if d.get("call_id"):
                gateway[str(d["call_id"])] = d
            continue
        asking = d.get("asking") or {}
        if not asking.get("pid"):
            continue  # not a cascade call (a canary, a compile): not a chart's
        calls.append(
            {
                "pid": str(asking["pid"]),
                "role": str(asking.get("role") or "?"),
                "stage": str(asking.get("stage") or "?"),
                "ms": float(d.get("ms") or 0),
                "tokens_in": int(d.get("tokens_in") or 0),
                "tokens_out": int(d.get("tokens_out") or 0),
                "call_id": str(d.get("call_id") or ""),
                "attempts": int(d.get("attempts") or 1),
            }
        )
    for c in calls:
        g = gateway.get(c["call_id"], {})
        c["server_ms"] = float(g.get("latency_ms") or 0)
        c["slot_wait_ms"] = float(g.get("slot_wait_ms") or 0)
        c["gateway_cache"] = g.get("cache") == "hit"
    return calls


def _dist(values: list[float], digits: int = 1) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "median": round(percentile(values, 0.5), digits),
        "p95": round(percentile(values, 0.95), digits),
        "max": round(max(values), digits),
        "sum": round(sum(values), digits),
    }


def per_chart(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """The charts that reached the models: per chart, summed over its calls, as distributions (no pseudonyms)."""
    charts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for c in calls:
        ch = charts[c["pid"]]
        ch["calls"] += 1
        ch["model_ms"] += c["ms"]
        ch[f"{c['role']}_ms"] += c["ms"]
        ch["server_ms"] += c["server_ms"]
        ch["slot_wait_ms"] += c["slot_wait_ms"]
        ch["tokens_in"] += c["tokens_in"]
        ch["tokens_out"] += c["tokens_out"]
        ch["retries"] += max(0, c["attempts"] - 1)
    keys = sorted({k for ch in charts.values() for k in ch})
    return {
        "charts": len(charts),
        **{
            k: _dist([ch.get(k, 0.0) for ch in charts.values()], 0 if "tokens" in k or k in ("calls", "retries") else 1)
            for k in keys
        },
    }


# ---------------------------------------------------------------- the servers' split
def server_split(folder: Path) -> dict[str, Any]:
    """Per server, from its ``/metrics`` before and after: requests, tokens, and the mean and summed seconds in the
    queue, prefill, decode (and first token, end to end). A counter the server does not have is left out, named."""
    out: dict[str, Any] = {}
    for before in sorted(folder.glob("vllm-*-before.prom")):
        name = before.name[len("vllm-") : -len("-before.prom")]
        after = folder / f"vllm-{name}-after.prom"
        if not after.exists():
            continue
        b = parse_prometheus(before.read_text(encoding="utf-8"))
        a = parse_prometheus(after.read_text(encoding="utf-8"))
        s: dict[str, Any] = {k: round(a.get(m, 0.0) - b.get(m, 0.0)) for k, m in TOKENS.items() if m in a}
        missing = []
        for part, (total, count) in SPLIT.items():
            if total not in a or count not in a:
                missing.append(part)
                continue
            n = a[count] - b.get(count, 0.0)
            secs = a[total] - b.get(total, 0.0)
            s[part] = {"seconds": round(secs, 2), "mean_s": round(secs / n, 4) if n else None}
        if missing:
            s["not_reported_by_server"] = missing
        out[name] = s
    return out


# ---------------------------------------------------------------- the stages
def stage_log(job_dir: Path | None, timing_file: Path | None = None) -> dict[str, dict[str, Any]]:
    """The patients that entered each stage (``J/cascade_log.jsonl``) and, when the run's timing was on, each stage's
    wall seconds with the seconds per 1,000 of its patients: from ``J/cascade_timing.json`` (the cascade's own
    outputs) or ``timing_file`` (the file a SCREEN or MICROBATCH run publishes, ``cascade_timing_<study>_v<n>.json``;
    the flag ``screen.timing``), whose stage rows carry the counts themselves."""
    out: dict[str, dict[str, Any]] = {}
    log = job_dir / "cascade_log.jsonl" if job_dir is not None else None
    if log is not None and log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                s = json.loads(line)
                out[str(s["stage"])] = {
                    "patients_in": int(s.get("patients_in") or 0),
                    "patients_out": int(s.get("patients_out") or 0),
                    "pairs_in": int(s.get("pairs_in") or 0),
                }
    timing = timing_file or (job_dir / "cascade_timing.json" if job_dir is not None else None)
    if timing is None or not timing.exists():
        return out
    t = json.loads(timing.read_text(encoding="utf-8"))
    for stage, cell in (t.get("stages") or {}).items():
        row = out.setdefault(str(stage), {})
        given = cell if isinstance(cell, dict) else {"seconds": cell}
        for k in ("patients_in", "patients_out", "pairs_in"):
            if k in given and k not in row:
                row[k] = int(given[k])
        secs = float(given.get("seconds") or 0.0)
        row["seconds"] = round(secs, 2)
        if row.get("patients_in"):
            row["seconds_per_1000"] = round(1000 * secs / row["patients_in"], 2)
    if t.get("wall_seconds") is not None:
        out["_run"] = {"seconds": round(float(t["wall_seconds"]), 2), "rounds": int(t.get("rounds") or 1)}
    return out


# ---------------------------------------------------------------- report
def report(
    audit_dir: Path,
    folder: Path | None,
    job_dir: Path | None = None,
    timing_file: Path | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    ingest_seconds: float | None = None,
    ingest_patients: int | None = None,
) -> dict[str, Any]:
    """The run's time per chart, by stage; see the module text for what each number means."""
    calls = model_calls(audit_dir, since, until)
    stages = stage_log(job_dir, timing_file)
    in_scope = stages.get("S0", {}).get("patients_in") or None
    charts = per_chart(calls)
    out: dict[str, Any] = {
        "window": {"since": since.isoformat() if since else None, "until": until.isoformat() if until else None},
        "charts_in_scope": in_scope,
        "charts_reaching_model": charts["charts"],
        "share_reaching_model": round(charts["charts"] / in_scope, 4) if in_scope else None,
        "model_calls": {
            "calls": len(calls),
            "by_stage": _count(c["stage"] for c in calls),
            "by_role": _count(c["role"] for c in calls),
            "answered_by_gateway_cache": sum(1 for c in calls if c["gateway_cache"]),
            "call_ms": _dist([c["ms"] for c in calls]),
            "server_ms": _dist([c["server_ms"] for c in calls]),
            "slot_wait_ms": _dist([c["slot_wait_ms"] for c in calls]),
        },
        "per_chart_reaching_model": charts,
        "stages": stages,
    }
    if folder is not None:
        out["servers"] = server_split(folder)
        out["card"] = _csv_summary(folder / "gpu.csv", gpu=True)
        out["cpu"] = _csv_summary(folder / "cpu.csv", gpu=False)
        w = folder / "watch.json"
        if w.exists():
            out["watch_seconds"] = json.loads(w.read_text(encoding="utf-8")).get("seconds")
    wall = (stages.get("_run") or {}).get("seconds") or out.get("watch_seconds")
    if wall and in_scope:
        out["throughput"] = {
            "wall_seconds": wall,
            "seconds_per_chart": round(wall / in_scope, 3),
            "charts_per_hour": round(3600 * in_scope / wall, 1),
            "source": "cascade_timing.json" if stages.get("_run") else "watch.json",
        }
    if ingest_seconds is not None and ingest_patients:
        out["ingest"] = {
            "seconds": ingest_seconds,
            "patients": ingest_patients,
            "ms_per_chart": round(1000 * ingest_seconds / ingest_patients, 1),
        }
    return out


def _count(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for v in values:
        out[v] += 1
    return dict(sorted(out.items()))


def _csv_summary(path: Path, gpu: bool) -> dict[str, Any]:
    if not path.exists():
        return {"samples": 0, "why": f"no {path.name} (watch was not run, or the machine has none)"}
    with path.open(newline="", encoding="utf-8") as fh:
        if gpu:
            return gpu_summary([r for r in csv.reader(fh) if r and r[0] != "timestamp"])
        return cpu_summary(csv.DictReader(fh))


# ---------------------------------------------------------------- command line
def _servers(pairs: list[str]) -> dict[str, str]:
    out = {}
    for p in pairs:
        name, _, url = p.partition("=")
        if not name or not url:
            raise SystemExit(f"--server takes name=URL, got {p!r}")
        out[name] = url
    return out


def _when(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise SystemExit(f"not an ISO time: {text!r}") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.chart_times", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch", help="sample the cards, the CPU and the model servers until stopped")
    w.add_argument("--folder", type=Path, required=True)
    w.add_argument("--server", action="append", default=[], help="name=URL of a server's /v1 (repeatable)")
    w.add_argument("--key-file", type=Path, help="a file holding the servers' key (read, never printed)")
    w.add_argument("--every", type=float, default=SAMPLE_S)
    w.add_argument("--max-seconds", type=float)
    r = sub.add_parser("report", help="join a run's records into the time per chart")
    r.add_argument("--audit-dir", type=Path, required=True)
    r.add_argument("--folder", type=Path, help="the watch folder")
    r.add_argument("--job-dir", type=Path, help="a cascade output folder (cascade_log.jsonl, cascade_timing.json)")
    r.add_argument("--timing", type=Path, help="the file a screening run published with screen.timing on")
    r.add_argument("--since")
    r.add_argument("--until")
    r.add_argument("--ingest-seconds", type=float)
    r.add_argument("--ingest-patients", type=int)
    r.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "watch":
        key = a.key_file.read_text(encoding="utf-8").strip() if a.key_file else ""
        out = watch(a.folder, _servers(a.server), key, a.every, a.max_seconds)
        print(f"chart_times watch: {out['seconds']} s sampled, {a.folder / 'watch.json'}")
        return 0
    rep = report(
        a.audit_dir, a.folder, a.job_dir, a.timing, _when(a.since), _when(a.until), a.ingest_seconds, a.ingest_patients
    )
    text = json.dumps(rep, indent=1, sort_keys=True) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"chart_times report: {rep['charts_reaching_model']} charts reached the models; {a.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
