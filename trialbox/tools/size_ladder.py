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
studies = sys.argv[5:]
sec = work / "sec"
sec.mkdir(parents=True, exist_ok=True)
(sec / "site_hmac.key").write_bytes(key)
box = make_box(work, lake_dir, sec)
# the box with no embed service (the scale gate's hash embedder), and the lake service over HTTP, as a box runs it
box.orch.cfg = Config(env=dataclasses.replace(box.orch.cfg.env, embed_url=""), settings=box.orch.cfg.settings)
box.orch.services.lake = LakeHttp(lake_url)
log = Path(os.environ["TB_LADDER_STUB_LOG"])
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
    return rows


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
    by: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for run in runs:
        for row in stage_rows(run):
            by.setdefault((row["stage"], int(run["patients"])), []).append(row)
    table = []
    for (stage, n), rows in sorted(by.items(), key=lambda kv: (kv[0][1], _stage_order(kv[0][0]))):
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
                **{
                    k: first[k]
                    for k in ("records", "model_calls", "stub_s", "studies", "scoped", "lake_peak")
                    if k in first
                },
            }
        )
    slows = {}
    for stage in sorted({t["stage"] for t in table}, key=_stage_order):
        pts = {t["patients"]: (t["seconds"]["median"], t["ms_per_unit"]) for t in table if t["stage"] == stage}
        slows[stage] = first_slow(pts)
    return {"table": table, "first_slow": slows, "slow_factor": SLOW_FACTOR, "slow_floor_s": SLOW_FLOOR_S}


def _stage_order(stage: str) -> tuple[int, str]:
    order = ("generate", "ingest", "rebuild+publish", "cascade", "FEAS", "SCREEN")
    for i, prefix in enumerate(order):
        if stage.startswith(prefix):
            return i, stage
    return len(order), stage


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
            for k in ("records", "model_calls", "stub_s", "scoped")
            if k in t
        )
        cap = f"{t['service']} ({gib(t['cap'])})" if t["cap"] else t["service"]
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
            [sys.executable, "-c", CHILD_JOBS, str(work / "box"), str(lake_dir), url, SITE_KEY.decode(), *studies],
            _env(TB_SERVICE_TOKEN=token, TB_LADDER_STUB_LOG=str(stub_log)),
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
    rec: dict[str, Any] = {"patients": rung.patients, "studies": rung.studies, "repeat": repeat}
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
    ap.add_argument("--plan", nargs="+", required=True, help="PATIENTS:STUDIES:REPEATS, smallest first")
    ap.add_argument("--work", type=Path, required=True, help="where the raw runs go (removed after each size)")
    ap.add_argument("--results", type=Path, required=True, help="the summary JSON file")
    ap.add_argument("--enforce", default="", choices=("", "cgroup", "measure"))
    ap.add_argument("--keep", action="store_true", help="keep each size's raw run in --work")
    ap.add_argument("--resume", action="store_true", help="keep the runs already in --results and skip them")
    a = ap.parse_args(argv)
    if not os.environ.get("TB_TZ"):
        ap.error("TB_TZ is not set: the product has no default site zone (D-315); give the zone the box would have")
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
