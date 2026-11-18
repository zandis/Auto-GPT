"""The size ladder (H-23, D-1137): the synthetic hospital at several sizes, each night measured with the product's own
tools, and one small results file with the time and peak memory of each stage and where a stage first slows.

It adds no generator and no instrument. For each size it drives:

1. ``tools.scale_gate`` (lane B2's gate, T-687): the synthetic hospital (``tools.synth``), the night's ingest under
   the ``adapter`` cap, the lake's rebuild and the site publish under the ``lake`` cap, the cascade of one study
   (GZQO) under the ``orchestrator`` cap judged through the real gateway by the stand-in, and the backup. The stand-in
   answers at once (0 s per call: the stub), so the gate's model-share line (D-973) is empty by design;
2. the orchestrator's own FEAS and SCREEN jobs (``orchestrator.core.Orchestrator.run``) for each study in turn, in one
   process under the ``orchestrator`` cap, reading the lake service (``lake.app``, under the ``lake`` cap) over HTTP
   with the box's service token, judged by the stub model (``llm_stub``). The studies are the shipped rulesets,
   approved as the test box approves them (``tests.inproc_box``); a ladder of more studies than are shipped runs them
   again in the same order, and the results say which runs were repeats. SCREEN is asked for the whole hospital
   (``scope=hospital``, D-146), the largest scope a site can choose.

Each process's peak is the resident memory of its process tree (``tb_testkit.scale``; ``cgroup`` mode when the host
can make one, else ``measure``). The stub's own time in a SCREEN job is the sum of the stub's request log (``ms``),
the stage's own record. Nothing here changes a product file. The raw runs stay in ``--work`` and are removed after
each size; only the summary (``--results``) is kept.

    TB_ENV=DEV TB_TZ=<the site's zone> PYTHONPATH=libs:services:. python -m tools.size_ladder \\
        --plan 5000:20:2 20000:20:2 50000:5:1 --work /tmp/ladder --results build/size_ladder.json

``--plan`` takes ``PATIENTS:STUDIES:REPEATS``. ``tests/unit/test_size_ladder.py`` checks the arithmetic and the
report's shape on made-up runs (no data, no processes).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import shutil
import statistics
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services", "."):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

#: the shipped rulesets, in the order a ladder runs them (a longer ladder runs them again in this order)
STUDIES = ("GZQO", "RA-BIO", "AD-MAB", "GOUT-COH", "NEUR-COH", "ONC-OSI", "RA-COH", "RA-JAK")
#: a stage "first slows" at the first size whose time per unit is more than this many times the lowest time per unit
#: of every smaller size (D-1137)
SLOW_FACTOR = 1.5
#: a stage's time below this many seconds is not judged for slowing: start-up costs dominate it
SLOW_FLOOR_S = 5.0
#: the results file's shape; a change of keys moves it
SCHEMA = "size-ladder/1"
TRACE_SCHEMA = "size-ladder-trace/1"
SITE_KEY = b"trialbox-scale-gate-site-key-0123456789"  # the scale gate's own synthetic site key

# the jobs, as the orchestrator runs them: one process, each study's FEAS then its SCREEN, a JSON line per job
CHILD_JOBS = r"""
import json, os, re, resource, sys, time
from pathlib import Path
import tb_contracts as c
import dataclasses
from tb_common.config import Config
from lake.client import LakeHttp
from tests.inproc_box import make_box

work, lake_dir, lake_url, key = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4].encode()
log, studies = Path(sys.argv[5]), sys.argv[6:]  # the stub writes its request lines to the log
sec = work / "sec"
sec.mkdir(parents=True, exist_ok=True)
(sec / "site_hmac.key").write_bytes(key)
box = make_box(work, lake_dir, sec)
# the box with no embed service (the scale gate's hash embedder), and the lake service over HTTP, as a box runs it
box.orch.cfg = Config(env=dataclasses.replace(box.orch.cfg.env, embed_url=""), settings=box.orch.cfg.settings)
box.orch.services.lake = LakeHttp(lake_url)
ms = re.compile(rb'"logger": "llm-stub", "msg": "request".*?"ms": ([0-9.]+)')

def stub_ms(start):
    with log.open("rb") as fh:
        fh.seek(start)
        data = fh.read()
    return sum(float(m) for m in ms.findall(data)), start + len(data)

pos = log.stat().st_size if log.exists() else 0
for i, rs in enumerate(studies):
    for kind in ("FEAS", "SCREEN"):
        t0 = time.perf_counter()
        opts = {"scope": "hospital"} if kind == "SCREEN" else {}
        job = box.orch.create(c.JobCreate(type=kind, ruleset=rs, requested_by="pi@hospa.test", options=opts))
        job = box.orch.run(job.job_id)
        took = time.perf_counter() - t0
        sys.stderr.flush()
        spent, pos = stub_ms(pos)
        m = job.metrics
        print(json.dumps({"i": i, "study": rs, "kind": kind, "state": job.state,
                          "error": str(job.error)[:300] if job.error else "", "seconds": round(took, 2),
                          "scoped": m.patients_scoped if m else 0, "model_calls": m.llm_calls if m else 0,
                          "stub_s": round(spent / 1000, 2),
                          "rss_peak": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}), flush=True)
"""


# H-23b: the gate's cascade (``scale_gate.CHILD_SCREEN``, unchanged) with each top-level stage of ``run_cascade`` timed
# and its memory read: the process's resident peak within the stage (``VmHWM``, reset at the stage's start) and, with
# ``TB_LADDER_TRACE_FRAMES`` above 0, Python's own tracer (``tracemalloc``): the stage's traced peak and the largest
# allocation sites still held at its end. A JSON line per stage goes to ``TB_LADDER_TRACE_OUT``. It patches the class
# in this process only; the product file is not changed.
TRACE_PREFIX = r"""
import json as _json, os as _os, time as _time, tracemalloc as _tm
from pathlib import Path as _Path
from matching.cascade import engine as _eng
_frames = int(_os.environ.get("TB_LADDER_TRACE_FRAMES", "0"))
_top = int(_os.environ.get("TB_LADDER_TRACE_TOP", "15"))
_out = _Path(_os.environ["TB_LADDER_TRACE_OUT"])
_t0, _depth = _time.perf_counter(), [0]
if _frames:
    _tm.start(_frames)

def _status(key):
    with open("/proc/self/status") as fh:
        for ln in fh:
            if ln.startswith(key):
                return int(ln.split()[1]) * 1024
    return 0

def _short(path):
    return path.split("/trialbox/", 1)[-1]

def _wrap(name):
    fn = getattr(_eng._Run, name)
    def inner(self, *a, **k):
        _depth[0] += 1
        outer = _depth[0] == 1
        if outer:
            try:
                with open("/proc/self/clear_refs", "w") as fh:
                    fh.write("5")  # VmHWM from here
            except OSError:
                pass
            if _frames:
                _tm.reset_peak()
        t = _time.perf_counter()
        try:
            return fn(self, *a, **k)
        finally:
            _depth[0] -= 1
            if outer:
                rec = {"stage": name, "start_s": round(t - _t0, 1), "seconds": round(_time.perf_counter() - t, 1),
                       "rss_end": _status("VmRSS:"), "rss_peak": _status("VmHWM:")}
                if _frames:
                    cur, peak = _tm.get_traced_memory()
                    snap = _tm.take_snapshot().filter_traces([_tm.Filter(False, _tm.__file__)])
                    rec.update(traced_end=cur, traced_peak=peak, top=[
                        {"bytes": st.size, "count": st.count,
                         "where": [f"{_short(f.filename)}:{f.lineno}" for f in st.traceback]}
                        for st in snap.statistics("traceback")[:_top]])
                    del snap
                with _out.open("a") as fh:
                    fh.write(_json.dumps(rec) + "\n")
    setattr(_eng._Run, name, inner)

for _n in ("s0", "s1", "note_stage", "sample", "s3", "s4", "tiers", "s5"):
    _wrap(_n)
"""
#: the stages ``TRACE_PREFIX`` reads, in ``run_cascade``'s order
TRACED_STAGES = ("s0", "s1", "note_stage", "sample", "s3", "s4", "tiers", "s5")


# ------------------------------------------------------------------------------------------------ the arithmetic
@dataclass(frozen=True)
class Rung:
    patients: int
    studies: int
    repeats: int


def parse_plan(items: Iterable[str]) -> list[Rung]:
    """``PATIENTS:STUDIES:REPEATS`` each; a missing part is 1. Refuses a size or count that is not a whole number above
    0, naming the item."""
    out: list[Rung] = []
    for raw in items:
        parts = ([*raw.split(":"), "1", "1"])[:3]
        try:
            n, k, r = (int(p.replace(",", "").replace("_", "")) for p in parts)
        except ValueError:
            raise ValueError(f"--plan {raw!r}: give PATIENTS:STUDIES:REPEATS as whole numbers") from None
        if min(n, k, r) < 1:
            raise ValueError(f"--plan {raw!r}: every number must be at least 1")
        out.append(Rung(n, k, r))
    return out


def study_list(k: int) -> list[str]:
    """The first ``k`` studies, the shipped rulesets cycled in :data:`STUDIES` order."""
    return [STUDIES[i % len(STUDIES)] for i in range(k)]


def spread(values: Sequence[float]) -> dict[str, float]:
    """The middle and the spread of a stage's repeats: the median, the lowest, the highest and (highest - lowest) as a
    percentage of the median (0 for one run)."""
    if not values:
        return {"median": 0.0, "min": 0.0, "max": 0.0, "spread_pct": 0.0, "n": 0}
    med = statistics.median(values)
    lo, hi = min(values), max(values)
    return {
        "median": round(med, 2),
        "min": round(lo, 2),
        "max": round(hi, 2),
        "spread_pct": round(100 * (hi - lo) / med, 1) if med > 0 else 0.0,
        "n": len(values),
    }


def per_unit_ms(seconds: float, units: float) -> float:
    """Milliseconds per unit (per patient, per patient and study), 0 without units."""
    return round(1000 * seconds / units, 3) if units > 0 else 0.0


def first_slow(
    points: Mapping[int, tuple[float, float]], factor: float = SLOW_FACTOR, floor_s: float = SLOW_FLOOR_S
) -> dict[str, Any] | None:
    """The first size at which a stage slows: ``points`` maps patients to (seconds, ms per unit). A size slows when its
    ms per unit is more than ``factor`` times the lowest ms per unit of every smaller size and its time is at least
    ``floor_s``. None when no size does (or fewer than two sizes)."""
    sizes = sorted(points)
    for j, n in enumerate(sizes[1:], start=1):
        seconds, rate = points[n]
        best = min(points[m][1] for m in sizes[:j])
        if seconds >= floor_s and best > 0 and rate > factor * best:
            return {"patients": n, "ms_per_unit": rate, "lowest_smaller": best, "ratio": round(rate / best, 2)}
    return None


def stage_rows(run: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One measured size and repeat as stage rows: stage, service, seconds, peak bytes, cap bytes, units, unit, the
    ms per unit, and the stage's own counts."""
    n = int(run["patients"])
    rows: list[dict[str, Any]] = []
    moved = lifted_services(run)
    gate = run.get("gate") or {}
    procs = {p["name"]: p for p in gate.get("runs", [])}
    nums = gate.get("numbers") or {}

    def add(stage: str, proc: str, seconds: float | None, units: float, unit: str, **extra: Any) -> None:
        p = procs.get(proc, {})
        sec = float(p.get("seconds", 0.0) if seconds is None else seconds)
        rows.append(
            {
                "stage": stage,
                "service": p.get("service", extra.pop("service", "-")),
                "seconds": round(sec, 2),
                "peak": int(p.get("peak", extra.pop("peak", 0)) or 0),
                "cap": int(p.get("cap", extra.pop("cap", 0)) or 0),
                "units": units,
                "unit": unit,
                "ms_per_unit": per_unit_ms(sec, units),
                "ok": p.get("rc", 0) == 0 and not p.get("oom", False),
                **extra,
            }
        )

    if procs:
        add("generate", "generate", None, n, "patient")
        ing = nums.get("ingest") or {}
        add("ingest", "ingest (nightly)", None, n, "patient", records=int(ing.get("records", 0)))
        pub = nums.get("publish") or {}
        add("rebuild+publish", "lake (rebuild, queries)", float(pub.get("seconds", 0.0)), n, "patient")
        sc = nums.get("screen") or {}
        add("cascade (gate, GZQO)", "screen (cascade)", None, n, "patient", model_calls=int(sc.get("judge_calls", 0)))
    jobs = run.get("jobs") or {}
    for kind in ("FEAS", "SCREEN"):
        every = [j for j in jobs.get("lines", []) if j["kind"] == kind]
        for k in marks(len(every)):
            rows.append(_job_row(kind, every[:k], n, jobs))
    cut = cut_job(jobs)
    if cut is not None:
        rows.append(cut | {"units": n, "ms_per_unit": per_unit_ms(cut["seconds"], n)})
    for row in rows:
        row["lifted"] = row["service"] in moved
    return rows


#: the compose memory setting of each service the ladder caps (``deploy/docker-compose.yml``)
CAP_SERVICE = {"TB_MEM_ADAPTER": "adapter", "TB_MEM_LAKE": "lake", "TB_MEM_ORCH": "orchestrator"}


def lifted_services(run: Mapping[str, Any]) -> set[str]:
    """H-23b: the services whose cap a run was given from the environment (``cap_env``), not the shipped default."""
    return {CAP_SERVICE[k] for k in (run.get("cap_env") or {}) if k in CAP_SERVICE}


def cut_job(jobs: Mapping[str, Any]) -> dict[str, Any] | None:
    """The job the orchestrator process was in when it ended without finishing (killed at its cap, or an error): the
    one after the last job line (each study's FEAS, then its SCREEN), its time the process's time after the last line,
    its peak the process's peak. None when the process finished."""
    if not jobs or (not jobs.get("orchestrator_oom") and not jobs.get("orchestrator_rc")):
        return None
    lines = jobs.get("lines", [])
    if lines and lines[-1]["kind"] == "FEAS":
        kind, study, i = "SCREEN", lines[-1]["study"], lines[-1]["i"]
    else:
        i = (lines[-1]["i"] + 1) if lines else 0
        kind, study = "FEAS", study_list(i + 1)[i]
    done = sum(1 for j in lines if j["kind"] == kind)
    why = "killed at the cap" if jobs.get("orchestrator_oom") else f"exit {jobs.get('orchestrator_rc')}"
    return {
        "stage": f"{kind} x{done + 1}",
        "service": "orchestrator",
        "seconds": round(max(0.0, float(jobs.get("orchestrator_s", 0.0)) - sum(j["seconds"] for j in lines)), 2),
        "peak": int(jobs.get("orchestrator_peak", 0)),
        "cap": int(jobs.get("orchestrator_cap", 0)),
        "unit": "patient-study",
        "ok": False,
        "studies": done + 1,
        "cut": f"{study}: {why}",
        "lake_peak": int(jobs.get("lake_peak", 0)),
    }


def marks(k: int) -> list[int]:
    """The study counts a run of ``k`` studies is reported at: 1, 5 and ``k`` (each at most ``k``)."""
    return sorted({m for m in (1, 5, k) if 0 < m <= k})


def _job_row(kind: str, done: list[dict[str, Any]], n: int, jobs: Mapping[str, Any]) -> dict[str, Any]:
    """The first ``len(done)`` studies' jobs of one kind, one after another in one orchestrator process: their summed
    time, and the process's own peak after the last of them."""
    sec = sum(j["seconds"] for j in done)
    k = len(done)
    return {
        "stage": f"{kind} x{k}",
        "service": "orchestrator",
        "seconds": round(sec, 2),
        "peak": max(int(j.get("rss_peak", 0)) for j in done),
        "cap": int(jobs.get("orchestrator_cap", 0)),
        "units": n * k,
        "unit": "patient-study",
        "ms_per_unit": per_unit_ms(sec, n * k),
        "ok": all(j["state"] == "done" for j in done),
        "studies": k,
        "model_calls": sum(int(j.get("model_calls", 0)) for j in done),
        "stub_s": round(sum(float(j.get("stub_s", 0.0)) for j in done), 2),
        "scoped": max(int(j.get("scoped", 0)) for j in done),
        "lake_peak": int(jobs.get("lake_peak", 0)),  # the lake service over every job of the run, not per mark
    }


def summarise(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The ladder's table (stage x size, with the repeats' spread) and where each stage first slows."""
    by: dict[tuple[str, int, bool], list[dict[str, Any]]] = {}
    for run in runs:
        for row in stage_rows(run):
            by.setdefault((row["stage"], int(run["patients"]), row["lifted"]), []).append(row)
    table: list[dict[str, Any]] = []
    for (stage, n, lifted), rows in sorted(by.items(), key=lambda kv: (kv[0][1], _stage_order(kv[0][0]), kv[0][2])):
        secs = [r["seconds"] for r in rows]
        sp = spread(secs)
        first = rows[0]
        table.append(
            {
                "stage": stage,
                "patients": n,
                "service": first["service"],
                "seconds": sp,
                "peak": max(r["peak"] for r in rows),
                "cap": first["cap"],
                "units": first["units"],
                "unit": first["unit"],
                "ms_per_unit": per_unit_ms(sp["median"], first["units"]),
                "ok": all(r["ok"] for r in rows),
                "lifted": lifted,
                **{
                    k: first[k]
                    for k in ("records", "model_calls", "stub_s", "studies", "scoped", "lake_peak", "cut")
                    if k in first
                },
            }
        )
    slows = {}
    for stage in sorted({t["stage"] for t in table}, key=_stage_order):
        # a stage killed at its cap did not finish: its time is not a rate, and its row says FAILED instead. H-23b: at
        # each size the shipped cap's row when it finished, else a lifted cap's; the sizes judged on a lifted cap are
        # named
        pts: dict[int, tuple[float, float]] = {}
        on_lifted: set[int] = set()
        for t in sorted((t for t in table if t["stage"] == stage and t["ok"]), key=lambda t: not t["lifted"]):
            pts[t["patients"]] = (t["seconds"]["median"], t["ms_per_unit"])  # the shipped row, last, wins
            if t["lifted"]:
                on_lifted.add(t["patients"])
            else:
                on_lifted.discard(t["patients"])
        slow = first_slow(pts)
        if slow is not None and on_lifted:
            slow["lifted_sizes"] = sorted(on_lifted)
        slows[stage] = slow
    return {"table": table, "first_slow": slows, "slow_factor": SLOW_FACTOR, "slow_floor_s": SLOW_FLOOR_S}


def _stage_order(stage: str) -> tuple[int, int, str]:
    """The night's order, and a job's study marks by number (x1, x5, x20)."""
    order = ("generate", "ingest", "rebuild+publish", "cascade", "FEAS", "SCREEN")
    k = int(stage.rsplit(" x", 1)[1]) if " x" in stage and stage.rsplit(" x", 1)[1].isdigit() else 0
    for i, prefix in enumerate(order):
        if stage.startswith(prefix):
            return i, k, stage
    return len(order), k, stage


def gib(n: float) -> str:
    return f"{n / 2**30:.2f}"


def markdown_table(summary: Mapping[str, Any]) -> str:
    """The ladder table as the measurement page shows it."""
    head = (
        "| Patients | Stage | Service (cap GiB) | Seconds (median; min-max; n) | Peak GiB | Per unit (ms) | Counts |\n"
        "| ---: | --- | --- | --- | ---: | ---: | --- |\n"
    )
    lines = []
    for t in summary["table"]:
        s = t["seconds"]
        span = (
            f"{s['median']:,.1f}; {s['min']:,.1f}-{s['max']:,.1f}; {s['n']}" if s["n"] > 1 else f"{s['median']:,.1f}; 1"
        )
        counts = ", ".join(
            f"{k.replace('_', ' ')} {t[k]:,}" if isinstance(t[k], int) else f"{k.replace('_', ' ')} {t[k]}"
            for k in ("records", "model_calls", "stub_s", "scoped", "cut")
            if k in t
        )
        lifted = ", lifted" if t.get("lifted") else ""
        cap = f"{t['service']} ({gib(t['cap'])}{lifted})" if t["cap"] else t["service"]
        bad = "" if t["ok"] else " **FAILED**"
        lines.append(
            f"| {t['patients']:,} | {t['stage']}{bad} | {cap} | {span} | {gib(t['peak'])} | "
            f"{t['ms_per_unit']:,.3f} per {t['unit']} | {counts or '-'} |"
        )
    return head + "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------ the runs
def machine() -> dict[str, Any]:
    """This host's shape: processors, memory and the free disk of the work folder's file system."""
    mem = 0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem = int(line.split()[1]) * 1024
    except OSError:
        pass
    cpu = ""
    with contextlib.suppress(OSError):
        cpu = next(
            (
                ln.split(":", 1)[1].strip()
                for ln in Path("/proc/cpuinfo").read_text().splitlines()
                if ln.startswith("model name")
            ),
            "",
        )
    return {"cpus": os.cpu_count() or 0, "cpu": cpu, "mem_bytes": mem, "machine": platform.machine(),
            "python": platform.python_version()}  # fmt: skip


def _env(**extra: str) -> dict[str, str]:
    env = {**os.environ, "PYTHONPATH": "libs:services:.", "TB_ENV": os.environ.get("TB_ENV", "DEV")}
    env.update(extra)
    return env


def run_jobs(work: Path, lake_dir: Path, studies: Sequence[str], enforce: str = "") -> dict[str, Any]:
    """The FEAS and SCREEN jobs of ``studies`` in one orchestrator process under its cap, over the lake service under
    its cap. Returns the job lines, both peaks and caps, and each process's result."""
    import secrets as _secrets

    from tb_testkit.scale import Enforcer, compose_caps, free_port, wait_http

    from tools import scale_gate as sg

    caps = compose_caps()
    enf = Enforcer.detect(enforce)
    logs = work / "logs"
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    token = _secrets.token_hex(16)
    lake_env = _env(TB_LAKE_DIR=str(lake_dir), TB_LAKE_EMBEDDER="hash", TB_LAKE_BUILD="process",
                    TB_SERVICE_TOKEN=token, TB_SCALE_CAP_BYTES=str(caps["lake"]))  # fmt: skip
    out: dict[str, Any] = {"orchestrator_cap": caps["orchestrator"], "lake_cap": caps["lake"], "mode": enf.mode}
    stub_log = logs / "jobs.log"
    with enf.start("lake (jobs)", "lake", caps["lake"], [sys.executable, "-c", sg.CHILD_LAKE, str(port)], lake_env,
                   ROOT, logs / "lake-jobs.log") as (proc, lake_run):  # fmt: skip
        if not wait_http(f"{url}/healthz", 120, lambda: proc.poll() is None):
            raise RuntimeError(f"the lake service did not start: {lake_run.tail[-400:]}")
        jr = enf.run(
            "jobs (FEAS, SCREEN)",
            "orchestrator",
            caps["orchestrator"],
            [
                sys.executable,
                "-c",
                CHILD_JOBS,
                str(work / "box"),
                str(lake_dir),
                url,
                SITE_KEY.decode(),
                str(stub_log),
                *studies,
            ],
            _env(TB_SERVICE_TOKEN=token),
            ROOT,
            stub_log,
        )
    out["lines"] = [json.loads(ln) for ln in _json_lines(stub_log) if '"kind"' in ln and '"study"' in ln]
    out["orchestrator_peak"], out["orchestrator_s"] = jr.peak, round(jr.seconds, 1)
    out["orchestrator_rc"], out["orchestrator_oom"] = jr.rc, jr.oom
    out["lake_peak"], out["lake_s"], out["lake_oom"] = lake_run.peak, round(lake_run.seconds, 1), lake_run.oom
    if jr.rc:
        out["tail"] = jr.tail[-600:]
    return out


def trace_cascade(kept: Path, frames: int = 0, enforce: str = "") -> dict[str, Any]:
    """H-23b: the gate's cascade of one study again, over the lake a kept size left (``measure(..., keep=True)``), with
    :data:`TRACE_PREFIX`: each stage's time and memory, and with ``frames`` above 0 Python's tracer (which slows the
    run several times and adds its own memory: its times are not the ladder's). Under the ``orchestrator`` cap, read
    from the environment as compose reads it (``TB_MEM_ORCH``), over the lake service under its cap and the stub."""
    import secrets as _secrets

    from tb_testkit.scale import Enforcer, SlowModel, compose_caps, free_port, wait_http

    from tools import scale_gate as sg

    lake_dir = kept / "work" / "lake"
    if not (lake_dir / "CURRENT").exists():
        raise ValueError(f"{kept}: no built lake (run the size with --keep first)")
    caps = compose_caps()
    enf = Enforcer.detect(enforce)
    work = kept / "trace"
    shutil.rmtree(work, ignore_errors=True)
    logs = work / "logs"
    logs.mkdir(parents=True)
    stages = work / "stages.jsonl"
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    token = _secrets.token_hex(16)
    lake_env = _env(TB_LAKE_DIR=str(lake_dir), TB_LAKE_EMBEDDER="hash", TB_LAKE_BUILD="process",
                    TB_SERVICE_TOKEN=token, TB_SCALE_CAP_BYTES=str(caps["lake"]))  # fmt: skip
    model = SlowModel(work / "stub")
    model.start()
    try:
        with enf.start("lake (trace)", "lake", caps["lake"], [sys.executable, "-c", sg.CHILD_LAKE, str(port)],
                       lake_env, ROOT, logs / "lake.log") as (proc, lake_run):  # fmt: skip
            if not wait_http(f"{url}/healthz", 120, lambda: proc.poll() is None):
                raise RuntimeError(f"the lake service did not start: {lake_run.tail[-400:]}")
            sc = enf.run(
                "cascade (traced)",
                "orchestrator",
                caps["orchestrator"],
                [sys.executable, "-c", TRACE_PREFIX + sg.CHILD_SCREEN, url, model.url, sg.TRIAL, sg.SNAPSHOT,
                 sg.REF_DATE.isoformat(), str(work / "screen"), "auto"],  # fmt: skip
                _env(TB_SERVICE_TOKEN=token, TB_LADDER_TRACE_FRAMES=str(frames), TB_LADDER_TRACE_OUT=str(stages)),
                ROOT,
                logs / "cascade.log",
            )
    finally:
        model.stop()
    got: list[dict[str, Any]] = []
    with contextlib.suppress(OSError):
        got = [json.loads(ln) for ln in stages.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return {
        "patients_dir": kept.name,
        "frames": frames,
        "cap": caps["orchestrator"],
        "mode": enf.mode,
        "seconds": round(sc.seconds, 1),
        "peak": sc.peak,
        "rc": sc.rc,
        "oom": sc.oom,
        "lake_peak": lake_run.peak,
        "stages": got,
        **({"tail": sc.tail[-600:]} if sc.rc else {}),
    }


def stage_memory_table(trace: Mapping[str, Any]) -> str:
    """A traced cascade's stages as the measurement page shows them: seconds, the resident peak within the stage and
    at its end, and (traced) the tracer's peak within the stage and what is held at its end."""
    traced = int(trace.get("frames", 0)) > 0
    head = "| Stage | Seconds | Resident peak GiB | Resident at end GiB |"
    rule = "| --- | ---: | ---: | ---: |"
    if traced:
        head += " Traced peak GiB | Traced at end GiB |"
        rule += " ---: | ---: |"
    lines = [head, rule]
    for st in trace.get("stages", []):
        row = f"| {st['stage']} | {st['seconds']:,.1f} | {gib(st['rss_peak'])} | {gib(st['rss_end'])} |"
        if traced:
            row += f" {gib(st.get('traced_peak', 0))} | {gib(st.get('traced_end', 0))} |"
        lines.append(row)
    return "\n".join(lines) + "\n"


def _json_lines(log: Path) -> list[str]:
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [ln for ln in text.splitlines() if ln.startswith('{"i":')]


def measure(rung: Rung, repeat: int, work: Path, enforce: str = "", keep: bool = False) -> dict[str, Any]:
    """One size, one repeat: the scale gate, then the jobs. The work folder is removed afterwards (unless ``keep``)."""
    from tools import scale_gate as sg

    out = work / f"n{rung.patients}-r{repeat}"
    shutil.rmtree(out, ignore_errors=True)
    t0 = time.monotonic()
    rec: dict[str, Any] = {"patients": rung.patients, "studies": rung.studies, "repeat": repeat, **conditions()}
    try:
        p = sg.Params(patients=rung.patients, out=out, enforce=enforce, stall_s=sg.STALL_S)
        try:
            rep = sg.run(p)
            rec["gate"] = rep.to_json()
        except BaseException as exc:
            rec["gate_error"] = f"{type(exc).__name__}: {exc}"[:600]
            got = out / "scale_gate.json"
            rec["gate"] = json.loads(got.read_text()) if got.exists() else {}
            if isinstance(exc, KeyboardInterrupt):
                raise
        lake = out / "work" / "lake"
        if (lake / "CURRENT").exists():
            try:
                rec["jobs"] = run_jobs(out / "jobs", lake, study_list(rung.studies), enforce)
            except Exception as exc:
                rec["jobs_error"] = f"{type(exc).__name__}: {exc}"[:600]
        else:
            rec["jobs_error"] = "the gate left no built lake"
        rec["disk_bytes"] = _du(out)
    finally:
        rec["seconds"] = round(time.monotonic() - t0, 1)
        if not keep:
            shutil.rmtree(out, ignore_errors=True)
    return rec


#: the compose memory settings a run may be given from the environment (``deploy/.env`` moves them on a box)
CAP_VARS = ("TB_MEM_ADAPTER", "TB_MEM_LAKE", "TB_MEM_ORCH")


def conditions(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """H-23b: what a run was measured under, kept in its record: the caps in force (bytes, by service), the compose
    settings given from the environment that moved them (empty: the shipped defaults), and whether the night's ingest
    ran the HL7 validator (the JVM, when ``TB_HL7_VALIDATOR_JAR`` and the packages are there) or the structural check
    alone. A run with a lifted cap is reported as such, never as the shipped shape."""
    from tb_testkit.scale import compose_caps

    env = os.environ if environ is None else environ
    caps = compose_caps(environ=env)
    jar = Path(env.get("TB_HL7_VALIDATOR_JAR", "/opt/hl7/validator_cli.jar"))
    home = Path(env.get("TB_FHIR_PACKAGE_HOME", "/opt/hl7/home"))
    hl7 = jar.exists() and (home / ".fhir" / "packages").exists() and shutil.which(env.get("TB_JAVA", "java"))
    return {
        "caps": {k: caps[k] for k in ("adapter", "lake", "orchestrator") if k in caps},
        "cap_env": {k: env[k] for k in CAP_VARS if env.get(k)},
        "validator": "hl7" if hl7 else "structural",
    }


def _du(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(dirpath, f)).st_size
    return total


def compact(rec: Mapping[str, Any]) -> dict[str, Any]:
    """A measured run without its logs' tails and per-tick lists: what the results file keeps."""
    gate = dict(rec.get("gate") or {})
    nums = dict(gate.get("numbers") or {})
    if "publish" in nums:
        nums["publish"] = {k: v for k, v in nums["publish"].items() if k != "ticks"}
    keep_gate = {k: gate[k] for k in ("ok", "mode", "unfinished", "notes", "runs") if k in gate}
    keep_gate["numbers"] = nums
    keep_gate["checks"] = {r["check"]: r["state"] for r in gate.get("rows", [])}
    out = {k: v for k, v in rec.items() if k not in ("gate", "jobs")}
    out["gate"] = keep_gate
    if "jobs" in rec:
        out["jobs"] = {k: v for k, v in rec["jobs"].items() if k != "tail"}
    return out


def write_results(path: Path, runs: list[dict[str, Any]], started: str) -> dict[str, Any]:
    doc = {
        "schema": SCHEMA,
        "decision": "D-1137",
        "started": started,
        "written": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": machine(),
        "studies": list(STUDIES),
        "runs": runs,
        "summary": summarise(runs),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", nargs="+", default=[], help="PATIENTS:STUDIES:REPEATS, smallest first")
    ap.add_argument("--work", type=Path, required=True, help="where the raw runs go (removed after each size)")
    ap.add_argument("--results", type=Path, required=True, help="the summary JSON file")
    ap.add_argument("--enforce", default="", choices=("", "cgroup", "measure"))
    ap.add_argument("--keep", action="store_true", help="keep each size's raw run in --work")
    ap.add_argument("--resume", action="store_true", help="keep the runs already in --results and skip them")
    ap.add_argument("--trace-cascade", type=Path, metavar="KEPT",
                    help="H-23b: no ladder; the gate's cascade again over a size kept in --work (n<patients>-r<repeat>)"
                    ", each stage timed with its memory; the record goes to --results")  # fmt: skip
    ap.add_argument("--trace-frames", type=int, default=0, help="with --trace-cascade: the tracer's frames (0: off)")
    a = ap.parse_args(argv)
    if not os.environ.get("TB_TZ"):
        ap.error("TB_TZ is not set: the product has no default site zone (D-315); give the zone the box would have")
    if a.trace_cascade is not None:
        kept = a.trace_cascade if a.trace_cascade.is_absolute() else a.work / a.trace_cascade
        tr = {**conditions(), **trace_cascade(kept, a.trace_frames, a.enforce)}
        a.results.parent.mkdir(parents=True, exist_ok=True)
        a.results.write_text(json.dumps({"schema": TRACE_SCHEMA, "decision": "D-1137", "machine": machine(),
                                         "trace": tr}, indent=1) + "\n", encoding="utf-8")  # fmt: skip
        sys.stdout.write(stage_memory_table(tr))
        return 0 if not tr["rc"] else 1
    if not a.plan:
        ap.error("give --plan (the ladder) or --trace-cascade (one kept size's cascade)")
    plan = parse_plan(a.plan)
    runs: list[dict[str, Any]] = []
    started = datetime.now(UTC).isoformat(timespec="seconds")
    if a.resume and a.results.exists():
        old = json.loads(a.results.read_text())
        runs, started = old.get("runs", []), old.get("started", started)
    done = {(r["patients"], r["repeat"]) for r in runs}
    for rung in plan:
        for r in range(1, rung.repeats + 1):
            if (rung.patients, r) in done:
                continue
            print(f"[size_ladder] {rung.patients:,} patients, {rung.studies} studies, repeat {r}", flush=True)
            rec = measure(rung, r, a.work, a.enforce, a.keep)
            runs.append(compact(rec))
            doc = write_results(a.results, runs, started)
            print(f"[size_ladder] done in {rec['seconds']:,.0f} s", flush=True)
    sys.stdout.write(markdown_table(doc["summary"]) if runs else "nothing measured\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
