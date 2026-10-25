"""The "Run end to end" adapter of the Test Bench.

The v4 entry point ``run_end_to_end(source_dir, trial_id, out_dir) -> E2EResult`` (cascade + feasibility pack + recall
certificate) is imported lazily. ``TB_TESTBENCH_E2E=<module>:<function>`` names it explicitly; otherwise the
candidates in :data:`CANDIDATES` are tried in order. Until one exists the adapter falls back to the v1 paths that
already work:

* synthetic site A: dataplat L0 → L5 (:func:`dataplat.pipeline.run_pipeline`), then FEAS on the published snapshot
  with ruleset GZQO (:func:`orchestrator.scenarios.feas_compute.compute`), the feasibility PDF and XLSX, and a second
  independent run for reproducibility;
* MIMIC-IV FHIR demo: :func:`tools.open_data_e2e.run` (the path behind ``make open-data-e2e``).

Either way the page gets a :class:`BenchE2E`: PASS/FAIL, stage counts, invariants and the files produced.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import os
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tools.testbench.datasets import BenchDataset
from tools.testbench.jobs import Log

ROOT = Path(__file__).resolve().parents[2]
ENV_VAR = "TB_TESTBENCH_E2E"
STRICT_VAR = "TB_TESTBENCH_E2E_STRICT"  # 1: a failing v4 entry point fails the run instead of falling back
CANDIDATES = (
    "tools.cascade_e2e:run_end_to_end",
    "tools.e2e:run_end_to_end",
    "tools.end_to_end:run_end_to_end",
    "tools.run_end_to_end:run_end_to_end",
    "tools.v4_e2e:run_end_to_end",
    "orchestrator.e2e:run_end_to_end",
    "orchestrator.end_to_end:run_end_to_end",
)
DEFAULT_TRIAL = {"synthea_site_a": "GZQO", "mimic_demo": "EMPULSE"}
SITE_KEY = b"trialbox-testbench-site-key-0123456789ab"  # fixed: reproducible pseudonyms on synthetic data
SYNTH_RUN_DATE = date(2026, 10, 5)
SYNTH_SNAPSHOT = "2026-10-04"
SMALL_CELL = 5


@dataclass
class Invariant:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class BenchE2E:
    engine: str
    dataset: str
    trial_id: str
    passed: bool
    out_dir: Path
    stages: list[tuple[str, str]] = field(default_factory=list)
    invariants: list[Invariant] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


# ------------------------------------------------------------------------------------------------ discovery
def find_entry(env: Mapping[str, str] | None = None) -> tuple[str, Callable[..., Any]] | None:
    """The v4 ``run_end_to_end`` callable and its dotted name, or ``None`` while it does not exist yet."""
    e = os.environ if env is None else env
    names = [e[ENV_VAR]] if e.get(ENV_VAR) else list(CANDIDATES)
    for name in names:
        mod_name, _, attr = name.partition(":")
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError as exc:
            if exc.name and (mod_name == exc.name or mod_name.startswith(exc.name + ".")):
                continue  # the module itself is missing: try the next candidate
            raise
        fn = getattr(mod, attr or "run_end_to_end", None)
        if callable(fn):
            return name, fn
    return None


def run(
    dataset: BenchDataset, trial_id: str, out_dir: Path, log: Log, env: Mapping[str, str] | None = None
) -> BenchE2E:
    if not dataset.available:
        raise FileNotFoundError(
            f"{dataset.title} is not present at {dataset.path}"
            + (
                " (run `make open-data-e2e` or `python tools/fetch_open_data.py` first)"
                if dataset.id == "mimic_demo"
                else ""
            )
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    trial_id = trial_id or DEFAULT_TRIAL.get(dataset.id, "")
    e = os.environ if env is None else env
    entry = find_entry(e)
    v4_error = ""
    if entry is not None:
        name, fn = entry
        log(f"v4 entry point found: {name}")
        (out_dir / "v4").mkdir(parents=True, exist_ok=True)
        try:
            result = fn(dataset.path, trial_id, out_dir / "v4")
            return from_e2e_result(result, name, dataset.id, trial_id, out_dir / "v4")
        except Exception as exc:
            if e.get(STRICT_VAR) == "1":
                raise
            v4_error = f"{name} raised {type(exc).__name__}: {exc}"
            log(v4_error)
            log(f"falling back to the v1 path (set {STRICT_VAR}=1 to fail instead)")
    else:
        log("run_end_to_end not found yet: falling back to the v1 path")
    if dataset.id == "synthea_site_a":
        res = synthetic_v1(dataset, trial_id, out_dir / "v1", log)
    elif dataset.id == "mimic_demo":
        res = open_data_v1(dataset, out_dir / "v1", log)
    else:
        raise ValueError(f"no end-to-end path for dataset {dataset.id!r}")
    if v4_error:
        res.engine += " — after the v4 entry point failed"
        res.note = f"v4: {v4_error[:600]}. {res.note}"
    return res


# ------------------------------------------------------------------------------------------------ v4 result
def _get(obj: Any, *names: str) -> Any:
    for n in names:
        if isinstance(obj, Mapping) and n in obj:
            return obj[n]
        if hasattr(obj, n):
            return getattr(obj, n)
    return None


def _plain(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, Mapping):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [_plain(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, str | int | float | bool) or obj is None:
        return obj
    return str(obj)


def _paths(value: Any, out_dir: Path) -> list[Path]:
    if value is None:
        return []
    items = value.values() if isinstance(value, Mapping) else value if isinstance(value, list | tuple) else [value]
    out: list[Path] = []
    for v in items:
        if isinstance(v, str | Path):
            p = Path(v)
            out.append(p if p.is_absolute() else out_dir / p)
    return out


def from_e2e_result(result: Any, engine: str, dataset: str, trial_id: str, out_dir: Path) -> BenchE2E:
    """Read an ``E2EResult`` without depending on its exact class: the usual field names are tried in turn."""
    passed = _get(result, "passed", "ok", "success")
    if passed is None:
        status = str(_get(result, "status", "outcome") or "")
        passed = status.upper() in ("PASS", "PASSED", "OK", "SUCCESS")
    stages_raw = _get(result, "stage_counts", "stages", "counts") or {}
    stages: list[tuple[str, str]] = []
    if isinstance(stages_raw, Mapping):
        stages = [(str(k), json.dumps(_plain(v), ensure_ascii=False)) for k, v in stages_raw.items()]
    elif isinstance(stages_raw, list | tuple):
        for s in stages_raw:
            name = _get(s, "name", "stage") or str(s)
            count = _get(s, "count", "n", "counts", "detail")
            stages.append((str(name), json.dumps(_plain(count), ensure_ascii=False)))
    inv_raw = _get(result, "invariants", "checks") or {}
    invariants: list[Invariant] = []
    if isinstance(inv_raw, Mapping):
        for k, v in inv_raw.items():
            ok = v if isinstance(v, bool) else not v  # bool, or a list of problems
            invariants.append(Invariant(str(k), bool(ok), "" if isinstance(v, bool) else json.dumps(_plain(v))))
    elif isinstance(inv_raw, list | tuple):
        for i in inv_raw:
            invariants.append(
                Invariant(str(_get(i, "name") or i), bool(_get(i, "ok", "passed")), str(_get(i, "detail") or ""))
            )
    for label, names in (
        ("final list", ("final_list_size",)),
        ("recall certificate", ("certificate_status",)),
        ("tiers", ("tiers",)),
        ("headline (released)", ("headline",)),
    ):
        value = _get(result, *names)
        if value not in (None, "", {}, []):
            stages.append((label, json.dumps(_plain(value), ensure_ascii=False)))
    problems = _get(result, "problems", "certificate_reasons") or []
    root = Path(str(_get(result, "out_dir", "output_dir") or out_dir))
    files = _paths(_get(result, "artefacts", "files", "outputs", "artifacts"), root)
    if not files and root.is_dir():
        files = sorted(p for p in root.rglob("*") if p.is_file())
    return BenchE2E(
        engine=engine,
        dataset=dataset,
        trial_id=trial_id,
        passed=bool(passed),
        out_dir=root,
        stages=stages,
        invariants=invariants,
        files=files,
        summary=_plain(result) if isinstance(_plain(result), dict) else {"result": _plain(result)},
        note="; ".join(str(p) for p in problems) if isinstance(problems, list | tuple) else str(problems),
    )


# ------------------------------------------------------------------------------------------------ v1 fallbacks
def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _released_ok(v: Any) -> bool:
    return not (isinstance(v, int) and 0 < v < SMALL_CELL)


def _one_synthetic_run(src: Path, work: Path, trial_id: str, log: Log) -> dict[str, Any]:
    from dataplat.common import fixed_clock
    from dataplat.pipeline import run_pipeline
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from orchestrator.scenarios.feas_compute import FeasParams, compute, raw_json
    from tb_common.ruleset import Ruleset

    clock = fixed_clock(datetime(2026, 10, 5, 2, 0, tzinfo=UTC))
    log(f"dataplat L0 → L5 on {src.name}")
    res = run_pipeline(src, work / "dataplat", site_key=SITE_KEY, clock=clock, snapshot=SYNTH_SNAPSHOT)
    log(f"publish gate: {res.outcome} {res.blocking_reasons or ''}")
    out: dict[str, Any] = {"pipeline": res}
    if not res.published:
        return out
    rs = Ruleset.load(ROOT / "rulesets" / trial_id)
    lake = LakeLocal(work / "dataplat" / "l4" / "lake", HashEmbedder(), "Asia/Taipei")
    log(f"FEAS {trial_id} on snapshot {SYNTH_SNAPSHOT}")
    result, raw = compute(
        lake, rs, FeasParams(run_date=SYNTH_RUN_DATE, snapshot=SYNTH_SNAPSHOT, capacity_per_month=9.0)
    )
    out.update(ruleset=rs, result=result, raw=raw, raw_json=json.loads(raw_json(raw)))
    return out


def synthetic_v1(dataset: BenchDataset, trial_id: str, out_dir: Path, log: Log) -> BenchE2E:
    from orchestrator.reports import feasibility_pdf, feasibility_xlsx
    from orchestrator.reports.common import ReportMeta
    from tb_contracts import dump

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", trial_id) or not (ROOT / "rulesets" / trial_id).is_dir():
        raise ValueError(f"no ruleset {trial_id!r} under rulesets/ for the v1 synthetic path")
    runs: list[dict[str, Any]] = []
    for i in (1, 2):
        work = out_dir / f"run{i}"
        src = work / "drop"
        shutil.copytree(dataset.path, src)
        log(f"run {i} of 2")
        runs.append(_one_synthetic_run(src, work, trial_id, log))
    first = runs[0]
    pr = first["pipeline"]
    inv: list[Invariant] = []
    blocking = list(pr.validation.blocking_reasons) if pr.validation else ["no validation report"]
    inv.append(Invariant("0 blocking DQ findings", not blocking and pr.published, f"gate {pr.outcome}; {blocking}"))
    inv.append(
        Invariant(
            "lineage complete",
            bool(pr.lineage and pr.lineage.complete),
            f"{len(pr.lineage.run_ids) if pr.lineage else 0} runs; missing {pr.lineage.missing if pr.lineage else '-'}",
        )
    )
    stages: list[tuple[str, str]] = []
    for level, tables in pr.counts.items():
        stages.append((f"dataplat {level}", f"{sum(tables.values())} rows in {len(tables)} tables"))
    if pr.validation:
        acc = sum(t.accepted for t in pr.validation.tables)
        q = sum(t.quarantined for t in pr.validation.tables)
        stages.insert(1, ("dataplat L1", f"{acc} accepted, {q} quarantined"))
    files: list[Path] = []
    summary: dict[str, Any] = {"gate": pr.gate.model_dump(mode="json")}
    if "raw" in first:
        raw = first["raw"]
        result = first["result"]
        applied = [f.criterion_id for f in result.funnel if f.applied]
        rem = [raw.remaining[c] for c in applied]
        inv.append(
            Invariant(
                "monotone funnel",
                all(r <= raw.start_n for r in rem) and rem == sorted(rem, reverse=True),
                f"start {raw.start_n} → {rem}",
            )
        )
        released = [result.start_n] + [v for f in result.funnel for v in (f.remaining, f.dropped, f.unknown)]
        released += [s.remaining for s in result.sensitivity] + [m.n for m in result.monthly_new]
        bad = [v for v in released if not _released_ok(v)]
        inv.append(Invariant("small cells suppressed (<5)", not bad, f"{len(released)} released counts; bad {bad[:5]}"))
        same = "raw_json" in runs[1] and _digest(first["raw_json"]) == _digest(runs[1]["raw_json"])
        same = same and dump(result) == dump(runs[1]["result"])
        inv.append(Invariant("reproducible second run", same, f"results sha256 {_digest(first['raw_json'])[:16]}"))
        stages.append((f"FEAS {trial_id} start", str(raw.start_n)))
        stages.append((f"FEAS {trial_id} eligible (exact)", str(rem[-1] if rem else raw.start_n)))
        stages.append(
            (
                f"FEAS {trial_id} eligible (released)",
                str(next((f.remaining for f in reversed(result.funnel) if f.applied), "-")),
            )
        )
        meta = ReportMeta(
            "DEMO-A",
            "Synthetic site A",
            trial_id,
            first["ruleset"].version,
            "trialbox-stub",
            SYNTH_SNAPSHOT,
            "testbench",
            SYNTH_RUN_DATE.isoformat(),
            locale="en",
        )
        log("rendering feasibility PDF and XLSX")
        pdf = out_dir / f"feasibility_{trial_id}.pdf"
        pdf.write_bytes(feasibility_pdf.render(result, first["ruleset"], meta, {}))
        xlsx = out_dir / f"feasibility_{trial_id}.xlsx"
        xlsx.write_bytes(feasibility_xlsx.render(result, first["ruleset"], meta))
        files += [pdf, xlsx]
        summary.update(feasibility=dump(result), raw=first["raw_json"])
    else:
        inv.append(Invariant("FEAS ran", False, "the publish gate held the snapshot"))
    report = out_dir / "report.json"
    report.write_text(json.dumps(summary, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    files.append(report)
    lineage = pr.workdir / "lineage" / "events.jsonl"
    if lineage.exists():
        files.append(lineage)
    return BenchE2E(
        engine="fallback: v1 synthetic path (dataplat + FEAS + reports)",
        dataset=dataset.id,
        trial_id=trial_id,
        passed=all(i.ok for i in inv),
        out_dir=out_dir,
        stages=stages,
        invariants=inv,
        files=files,
        summary={"gate_outcome": pr.outcome},
        note="No cascade S0–S5 and no recall certificate on this path: they arrive with run_end_to_end.",
    )


def open_data_v1(dataset: BenchDataset, out_dir: Path, log: Log) -> BenchE2E:
    from tools import open_data_e2e

    log("tools/open_data_e2e.py: MIMIC demo → adapter → lake → FEAS (EMPULSE, STARRT-AKI), two runs")
    report = open_data_e2e.run(dataset.path, repro=True)
    open_data_e2e.write_outputs(report, out_dir)
    inv = [Invariant(f"{rid} invariants", not probs, "; ".join(probs)) for rid, probs in report["invariants"].items()]
    inv.append(Invariant("reproducible second run", report["reproducible"] is not False, str(report["reproducible"])))
    stages = [("patients", str(report["patients"]))]
    stages += [(f"ingest {k}", str(v)) for k, v in report["ingest"]["counts"].items()]
    for rid, t in report["trials"].items():
        rem = list(t["raw"]["remaining"].values())
        stages.append((f"FEAS {rid} start → eligible (exact)", f"{t['raw']['start_n']} → {rem[-1] if rem else '-'}"))
    return BenchE2E(
        engine="fallback: tools/open_data_e2e.py (v1 open-data path)",
        dataset=dataset.id,
        trial_id=",".join(report["trials"]),
        passed=bool(report["passed"]),
        out_dir=out_dir,
        stages=stages,
        invariants=inv,
        files=[out_dir / "report.json", out_dir / "report.md"],
        summary={"results_sha256": report["results_sha256"]},
        note="No cascade S0–S5 and no recall certificate on this path: they arrive with run_end_to_end.",
    )


__all__ = ["CANDIDATES", "ENV_VAR", "BenchE2E", "Invariant", "find_entry", "from_e2e_result", "run"]
