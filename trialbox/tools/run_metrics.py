"""What one part of the complete run measures besides its checks (deep review 2026-11-12, tests G-3 and G-06).

* **The model servers' own counters.** ``GET /metrics`` of both vLLM servers before and after the part (the raw
  text is kept beside the part's result) and their difference: prompt and generation tokens, time to first token,
  queue time, requests.
* **The card.** ``nvidia-smi`` every :data:`SAMPLE_S` seconds while the part runs, as ``gpu.csv`` in the part's
  result folder (``parts/<tag>/``); the servers' gauges (running, waiting, KV cache) at the same moments as
  ``vllm.csv``.
* **The calls.** Calls per second, tokens per second and the p50 / p95 call time from the gateway's audit
  (``llm.gateway.call``: its time stamp is the call's end, ``latency_ms`` its length).
* **The candidate list** of a SCREEN (who is listed, in which tier) with its sha256, so two runs at different
  ``TB_SCREEN_LLM_CONCURRENCY`` can be compared: the list must not depend on the calls in flight.

Standard library only. Nothing here raises into the part: a server that does not answer ``/metrics`` or a machine
without ``nvidia-smi`` gives an empty measurement that says so, never a failed part. No patient text is read or
written: counters, times and pseudonymous ids of synthetic patients only.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

SAMPLE_S = 10.0  # the review's interval (G-3: "every 10 s")
GPU_FIELDS = ("timestamp", "utilization.gpu", "memory.used", "memory.total", "temperature.gpu", "power.draw")
GPU_QUERY = ["nvidia-smi", f"--query-gpu={','.join(GPU_FIELDS)}", "--format=csv,noheader,nounits"]
VLLM_FIELDS = ("at", "server", "running", "waiting", "kv_cache_usage")
# vLLM's Prometheus names (v0.32; the KV cache gauge was gpu_cache_usage_perc before): report name -> metric names
COUNTERS: dict[str, tuple[str, ...]] = {
    "prompt_tokens": ("vllm:prompt_tokens_total",),
    "generation_tokens": ("vllm:generation_tokens_total",),
    "requests": ("vllm:request_success_total",),
    "ttft_seconds_sum": ("vllm:time_to_first_token_seconds_sum",),
    "ttft_count": ("vllm:time_to_first_token_seconds_count",),
    "queue_seconds_sum": ("vllm:request_queue_time_seconds_sum",),
    "queue_count": ("vllm:request_queue_time_seconds_count",),
    "e2e_seconds_sum": ("vllm:e2e_request_latency_seconds_sum",),
    "e2e_count": ("vllm:e2e_request_latency_seconds_count",),
}
GAUGES: dict[str, tuple[str, ...]] = {
    "running": ("vllm:num_requests_running",),
    "waiting": ("vllm:num_requests_waiting",),
    "kv_cache_usage": ("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc"),
}
_SAMPLE = re.compile(r"^([A-Za-z_:][A-Za-z0-9_:]*)(?:\{[^}]*\})?\s+(\S+)")


# ---------------------------------------------------------------- the servers' /metrics
def parse_prometheus(text: str) -> dict[str, float]:
    """Metric name -> the sum of its samples over every label set (one model per server, so the labels add nothing).
    Histogram buckets and ``_created`` stamps are left out; a line that is not a sample is skipped."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        m = _SAMPLE.match(line)
        if not m or m.group(1).endswith(("_bucket", "_created")):
            continue
        try:
            v = float(m.group(2))
        except ValueError:
            continue
        if math.isfinite(v):
            out[m.group(1)] = out.get(m.group(1), 0.0) + v
    return out


def pick(samples: dict[str, float], names: dict[str, tuple[str, ...]]) -> dict[str, float]:
    """The report's names out of a parsed ``/metrics`` (the first metric name that is there); absent ones left out."""
    out: dict[str, float] = {}
    for key, metrics in names.items():
        for m in metrics:
            if m in samples:
                out[key] = samples[m]
                break
    return out


def metrics_delta(before: str, after: str) -> dict[str, Any]:
    """What one server did between two ``/metrics`` texts: the counters' difference, and from it the mean time to
    first token and the mean queue time per request. ``scraped`` False: the server gave no metrics (both empty)."""
    b, a = pick(parse_prometheus(before), COUNTERS), pick(parse_prometheus(after), COUNTERS)
    d = {k: round(a[k] - b.get(k, 0.0), 3) for k in a}
    out: dict[str, Any] = {"scraped": bool(a), **d}
    for mean, total, n in (("ttft_mean_s", "ttft_seconds_sum", "ttft_count"),
                           ("queue_mean_s", "queue_seconds_sum", "queue_count"),
                           ("e2e_mean_s", "e2e_seconds_sum", "e2e_count")):  # fmt: skip
        if d.get(n):
            out[mean] = round(d[total] / d[n], 4)
    return out


def metrics_url(v1_url: str) -> str:
    """``http://host/judge/v1`` -> ``http://host/judge/metrics`` (vLLM serves it beside ``/v1``, not under it)."""
    return server_root(v1_url) + "/metrics"


def server_root(v1_url: str) -> str:
    base = v1_url.rstrip("/")
    return base[: -len("/v1")] if base.endswith("/v1") else base


def fetch(url: str, key: str = "", timeout: float = 10.0) -> str:
    """The text at ``url`` ("" when it does not answer): the VM's own model servers only, no proxy."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"} if key else {})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as r:
            return str(r.read().decode("utf-8", "replace"))
    except (OSError, ValueError):
        return ""


# ---------------------------------------------------------------- the card
def gpu_row(line: str) -> list[str] | None:
    """One ``nvidia-smi`` CSV line as the fields of :data:`GPU_FIELDS` (None when it is not such a line)."""
    cells = [c.strip() for c in line.split(",")]
    return cells if len(cells) == len(GPU_FIELDS) else None


def _num(x: str) -> float | None:
    try:
        v = float(x)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def gpu_summary(rows: Iterable[list[str]]) -> dict[str, Any]:
    """Mean and peak utilisation, peak memory, temperature and power over the samples of ``gpu.csv``."""
    cols: dict[str, list[float]] = {f: [] for f in GPU_FIELDS[1:]}
    n = 0
    for r in rows:
        n += 1
        for f, cell in zip(GPU_FIELDS[1:], r[1:], strict=False):
            v = _num(cell)
            if v is not None:
                cols[f].append(v)
    out: dict[str, Any] = {"samples": n, "every_s": SAMPLE_S}
    if cols["utilization.gpu"]:
        u = cols["utilization.gpu"]
        out.update({"util_mean_pct": round(sum(u) / len(u), 1), "util_max_pct": max(u)})
    for key, f in (("memory_peak_mib", "memory.used"), ("memory_total_mib", "memory.total"),
                   ("temperature_max_c", "temperature.gpu"), ("power_max_w", "power.draw")):  # fmt: skip
        if cols[f]:
            out[key] = max(cols[f])
    return out


def gauge_summary(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, float]]:
    """Per server, the peak of each gauge over the samples of ``vllm.csv`` (queue length, KV cache share)."""
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        s = out.setdefault(r.get("server", "?"), {})
        for g in GAUGES:
            v = _num(r.get(g, ""))
            if v is not None:
                s[f"{g}_max"] = max(s.get(f"{g}_max", 0.0), v)
    return out


class Monitor:
    """The measurement around one part: ``start()`` before it, ``stop()`` after it; the files go to ``folder``
    (``parts/<tag>/``): ``vllm-<server>-before.prom`` and ``-after.prom``, ``gpu.csv``, ``vllm.csv``. ``servers``:
    name -> the server's ``/v1`` URL (empty on the stub: only the card is sampled, when there is one)."""

    def __init__(self, folder: Path, servers: dict[str, str] | None = None, key: str = "",
                 every: float = SAMPLE_S, gpu_cmd: list[str] | None = None) -> None:  # fmt: skip
        self.folder, self.key, self.every = folder, key, every
        self.servers = {n: metrics_url(u) for n, u in (servers or {}).items() if u}
        self.gpu_cmd = GPU_QUERY if gpu_cmd is None else gpu_cmd
        self.has_gpu = bool(self.gpu_cmd) and shutil.which(self.gpu_cmd[0]) is not None
        self.before: dict[str, str] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.t0 = 0.0

    @property
    def active(self) -> bool:
        return bool(self.servers) or self.has_gpu

    def _scrape(self, when: str) -> dict[str, str]:
        out = {}
        for name, url in self.servers.items():
            out[name] = fetch(url, self.key)
            (self.folder / f"vllm-{name}-{when}.prom").write_text(out[name], encoding="utf-8")
        return out

    def sample(self) -> None:
        """One sample: a ``gpu.csv`` line per card, a ``vllm.csv`` line per server."""
        at = datetime.now().astimezone().isoformat(timespec="seconds")
        if self.has_gpu:
            try:
                r = subprocess.run(self.gpu_cmd, capture_output=True, text=True, timeout=8, check=False)
                rows = [g for ln in r.stdout.splitlines() if (g := gpu_row(ln))]
            except (OSError, subprocess.TimeoutExpired):
                rows = []
            with (self.folder / "gpu.csv").open("a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(rows)
        if self.servers:
            with (self.folder / "vllm.csv").open("a", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                for name, url in self.servers.items():
                    now = pick(parse_prometheus(fetch(url, self.key, timeout=5.0)), GAUGES)
                    w.writerow([at, name, *(now.get(k, "") for k in VLLM_FIELDS[2:])])

    def _loop(self) -> None:
        while not self._stop.wait(self.every):
            self.sample()

    def start(self) -> Monitor:
        if not self.active:
            return self
        self.folder.mkdir(parents=True, exist_ok=True)
        self.t0 = time.time()
        if self.has_gpu:
            (self.folder / "gpu.csv").write_text(",".join(GPU_FIELDS) + "\n", encoding="utf-8")
        if self.servers:
            (self.folder / "vllm.csv").write_text(",".join(VLLM_FIELDS) + "\n", encoding="utf-8")
        self.before = self._scrape("before")
        self.sample()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> dict[str, Any]:
        """End the sampling and return the part's ``metrics`` block (what is in the files, summed up)."""
        if not self.active:
            return {"sampled": False, "why": "no model server URL and no nvidia-smi on this machine"}
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.every + 10)
        self.sample()
        after = self._scrape("after")
        servers = {n: metrics_delta(self.before.get(n, ""), text) for n, text in after.items()}
        out: dict[str, Any] = {"sampled": True, "seconds": round(time.time() - self.t0, 1),
                               "folder": f"parts/{self.folder.name}", "servers": servers}  # fmt: skip
        if self.has_gpu:
            with (self.folder / "gpu.csv").open(newline="", encoding="utf-8") as fh:
                out["gpu"] = gpu_summary(list(csv.reader(fh))[1:])
        else:
            out["gpu"] = {"samples": 0, "why": "no nvidia-smi on this machine"}
        if self.servers:
            with (self.folder / "vllm.csv").open(newline="", encoding="utf-8") as fh:
                out["gauges"] = gauge_summary(csv.DictReader(fh))
        return out


# ---------------------------------------------------------------- the calls (the gateway's audit)
def audit_calls(audit_dir: Path, since: datetime | None = None) -> list[dict[str, Any]]:
    """The gateway's model calls in ``audit_dir`` that ended at or after ``since`` (a part's start: the audit of a
    part is shared by its repeats): ``{"end": epoch seconds, "latency_s", "tokens_in", "tokens_out", "endpoint",
    "cached"}``. ``cached``: answered from the gateway's cache, no server asked."""
    out: list[dict[str, Any]] = []
    for f in sorted(audit_dir.glob("*.jsonl")) if audit_dir.is_dir() else []:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if '"llm.gateway.call"' not in line:
                continue
            try:
                rec = json.loads(line)
                end = datetime.fromisoformat(rec["ts"])
            except (ValueError, KeyError, TypeError):
                continue
            d = rec.get("detail") or {}
            if rec.get("event") != "llm.gateway.call" or (since is not None and end < since):
                continue
            out.append({"end": end.timestamp(), "latency_s": float(d.get("latency_ms") or 0) / 1000.0,
                        "tokens_in": int(d.get("tokens_in") or 0), "tokens_out": int(d.get("tokens_out") or 0),
                        "endpoint": str(d.get("endpoint") or "?"), "cached": d.get("cache") == "hit"})  # fmt: skip
    return out


def percentile(values: list[float], q: float) -> float:
    """The ``q`` quantile (0..1) of ``values`` by linear interpolation; 0.0 for none."""
    if not values:
        return 0.0
    v = sorted(values)
    pos = (len(v) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def busy_seconds(calls: list[dict[str, Any]]) -> float:
    """The seconds in which at least one call was in flight: the union of every call's ``[end - latency, end]``.
    Calls per second over this time is the throughput while the models were asked, whatever else the part did
    between its stages (ingest, reports, screenshots)."""
    spans = sorted((c["end"] - c["latency_s"], c["end"]) for c in calls)
    total, cur_a, cur_b = 0.0, None, 0.0
    for a, b in spans:
        if cur_a is None or a > cur_b:
            total += (cur_b - cur_a) if cur_a is not None else 0.0
            cur_a, cur_b = a, b
        else:
            cur_b = max(cur_b, b)
    return total + ((cur_b - cur_a) if cur_a is not None else 0.0)


def _stats(calls: list[dict[str, Any]]) -> dict[str, Any]:
    busy = busy_seconds(calls)
    lat = [c["latency_s"] for c in calls]
    t_in, t_out = sum(c["tokens_in"] for c in calls), sum(c["tokens_out"] for c in calls)
    per = (lambda x: round(x / busy, 3)) if busy > 0 else (lambda x: 0.0)
    return {"calls": len(calls), "busy_seconds": round(busy, 1), "calls_per_second": per(len(calls)),
            "tokens_in": t_in, "tokens_out": t_out, "tokens_in_per_second": per(t_in),
            "tokens_out_per_second": per(t_out), "tokens_per_second": per(t_in + t_out),
            "p50_s": round(percentile(lat, 0.50), 3), "p95_s": round(percentile(lat, 0.95), 3),
            "mean_in_flight": round(sum(lat) / busy, 2) if busy > 0 else 0.0}  # fmt: skip


def call_stats(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Calls per second, tokens per second and p50 / p95 call time over every call a server answered, and per
    endpoint (the judge is ``serving``, the verifier ``verifier``). ``mean_in_flight``: the calls' summed time over
    the busy time. ``cached``: the calls the gateway answered from its cache (no server time: counted apart)."""
    sent = [c for c in calls if not c.get("cached")]
    out = {"source": "gateway audit (llm.gateway.call)", **_stats(sent), "cached": len(calls) - len(sent)}
    out["endpoints"] = {ep: _stats([c for c in sent if c["endpoint"] == ep])
                        for ep in sorted({c["endpoint"] for c in sent})}  # fmt: skip
    return out


# ---------------------------------------------------------------- the candidate list
def candidate_list(results: dict[str, Any]) -> dict[str, Any]:
    """Who a SCREEN listed (every tier but ``excluded``), sorted, with the sha256 of the list: equal lists at two
    concurrency settings have equal hashes. ``results``: pid -> the cascade's verdicts (``tier``)."""
    rows = sorted((str(pid), str(getattr(pv, "tier", ""))) for pid, pv in results.items()
                  if getattr(pv, "tier", "excluded") != "excluded")  # fmt: skip
    digest = hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()
    return {"count": len(rows), "sha256": digest, "tiers": dict(sorted(Counter(t for _, t in rows).items())),
            "list": [list(r) for r in rows]}  # fmt: skip


def curve(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The report's throughput table: one line per part result that measured calls or a card."""
    out = []
    for r in rows:
        t, m, c = r.get("throughput") or {}, r.get("metrics") or {}, r.get("candidates") or {}
        if not (t.get("calls") or (m.get("gpu") or {}).get("samples") or c):
            continue
        gpu = m.get("gpu") or {}
        srv = m.get("servers") or {}
        out.append({
            "tag": r.get("tag"), "llm_concurrency": r.get("llm_concurrency"), "calls": t.get("calls", 0),
            "calls_per_second": t.get("calls_per_second"), "tokens_per_second": t.get("tokens_per_second"),
            "p50_s": t.get("p50_s"), "p95_s": t.get("p95_s"), "gpu_util_mean_pct": gpu.get("util_mean_pct"),
            "gpu_memory_peak_mib": gpu.get("memory_peak_mib"),
            "queue_mean_s": {n: s.get("queue_mean_s") for n, s in srv.items() if s.get("queue_mean_s") is not None},
            "ttft_mean_s": {n: s.get("ttft_mean_s") for n, s in srv.items() if s.get("ttft_mean_s") is not None},
            "breaker_opens": sum((t.get("breaker_opens") or {}).values()) if "breaker_opens" in t else None,
            "candidates": c.get("count"), "candidates_sha256": c.get("sha256"),
        })  # fmt: skip
    return out


def lists_identical(rows: list[dict[str, Any]]) -> dict[str, bool]:
    """Per hospital language with more than one result that has a candidate list: are the lists the same?"""
    by: dict[str, set[str]] = {}
    n: Counter[str] = Counter()
    for r in rows:
        sha = (r.get("candidates") or {}).get("sha256")
        if r.get("part") == "hospital" and sha:
            by.setdefault(str(r.get("lang")), set()).add(sha)
            n[str(r.get("lang"))] += 1
    return {lang: len(s) == 1 for lang, s in sorted(by.items()) if n[lang] > 1}
