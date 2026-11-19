"""Where an approval's seconds go, step by step, on a local stub run (card H-41). Offline: the repository's stub model
in process, no GPU, no network, no FHIR server, no lake.

    python -m tools.public_accuracy.approve_profile [--protocol PDF_OR_TXT] [--runs N] [--fake-translator]
                                                    [--json OUT] [--top K]

It compiles one made-up protocol (default: the synthetic GZQO fixture) as ``tools.build_rulesets`` does, with the stub
model and the repository's terminology tables, with an installed-tables folder of its own (empty, or with one made-up
site list of ``--site-list-rows`` rows, loaded by ``terminology.installed.install_site_list``), then approves it
``--runs`` times from the review workbook as sent (the launch driver mails it back unchanged). Each approval runs on
a fresh copy of the compiled repository, so each one is a first approval.

Every step of ``Compiler.approve`` is wrapped with a timer: the draft read, ``refresh_installed``, the per-criterion
``ai.confirmed`` records, ``build_artifacts`` (CQL generation and the CQL-to-ELM translation), the equivalence report
read and enforce, ``stamp_differs``, ``site_list_blocks``, the files, the repository write, tag and promotion, and the
audit records. The rest of ``approve`` is ``other``. ``--top`` adds the functions with the most cumulative time
(``cProfile``) over all approvals.

What a local run cannot say: how long the FHIR server takes to load the libraries and value sets (no server here: a
recording stand-in counts the resources and bytes an approval sends, and sends nothing), the box's disk and audit
journal, and approvals waiting on each other (one at a time here).

The equivalence gate runs at compile with a made-up gate that passes every compiled criterion (no lake here); an
approval with nothing rejected or edited reads the compile's report and does not run the gate again.

Card H-45: ``Compiler.approve`` and the orchestrator's APPROVE job now record their own step seconds
(``metrics.step_seconds`` of the job, ``step_seconds`` of the compiler's answer; names in ``tb_common.steptime``). The
stub run prints the compiler's recorded steps beside the wrapped ones. ``--steps`` reads them back from stored
records instead of running anything:

    python -m tools.public_accuracy.approve_profile --steps PATH [PATH ...] [--json OUT]

``PATH`` is a launch set (a ``.tgz`` or a folder with ``built/`` and ``work/``: its ``work/box-calls.log``), a
``box-calls.log`` itself, or a job record saved as JSON. It prints, over the APPROVE jobs found, each step's median,
mean and largest seconds and its share of the jobs' summed time, and checks that each job's steps add up to its
``wall_seconds``.

Exit 0 when the approvals ran, 1 when one was not approved, 2 on an input it will not read (``--steps``: 2 also when
no APPROVE job with step seconds is found).
"""

from __future__ import annotations

import argparse
import cProfile
import functools
import json
import logging
import pstats
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = ROOT / "tests" / "fixtures" / "protocols" / "GZQO_protocol_v3.pdf"
RULESET = "ZZPROF"
SCHEMA_VERSION = 1

#: (owner, attribute) -> step name. ``owner`` is "Compiler", "repo" or a module path.
STEPS: tuple[tuple[str, str, str], ...] = (
    ("Compiler", "_draft", "draft read"),
    ("criteria_compiler.service", "refresh_installed", "refresh_installed"),
    ("criteria_compiler.service.provenance", "confirmed", "ai.confirmed records"),
    ("Compiler", "build_artifacts", "build_artifacts (CQL, ELM)"),
    ("Compiler", "enforce", "equivalence enforce"),
    ("Compiler", "_equivalence", "equivalence gate"),
    ("Compiler", "_flag", "flag"),
    ("criteria_compiler.service", "stamp_differs", "stamp_differs"),
    ("criteria_compiler.service", "site_list_blocks", "site_list_blocks"),
    ("Compiler", "_files", "files"),
    ("Compiler", "_package", "package (review round)"),
    ("repo", "read", "repo read"),
    ("repo", "write_dir", "repo write"),
    ("repo", "tag", "repo tag"),
    ("repo", "promote", "repo promote"),
    ("Compiler", "_audit", "audit records"),
)


class PassGate:
    """A made-up equivalence gate: every compiled criterion passes (no lake here)."""

    def __call__(self, criteria: list[Any], sql: str, library: str, index_date: date, seed: str) -> Any:
        import tb_contracts as c
        from criteria_compiler.semantics import compiled

        ids = [x.id for x in compiled(criteria)]
        return c.EquivalenceReport(overall_pct=100.0, per_criterion={i: 100.0 for i in ids}, failing=[],
                                   sample_size=200, engine="profile-pass")  # fmt: skip


class RecordingFhir:
    """Stands in for the FHIR server: records what an approval would load (resources, bytes), sends nothing."""

    def __init__(self) -> None:
        self.loads = 0
        self.resources: list[tuple[str, int]] = []

    def load(self, libraries: list[dict[str, Any]], valuesets: Any) -> None:
        self.loads += 1
        for r in [*list(valuesets), *libraries]:
            name = f"{r.get('resourceType')}/{r.get('name') or r.get('id')}"
            self.resources.append((name, len(json.dumps(r, separators=(",", ":")).encode("utf-8"))))


def _timed(fn: Any, name: str, acc: dict[str, float], depth: list[int]) -> Any:
    @functools.wraps(fn)
    def run(*a: Any, **kw: Any) -> Any:
        if depth[0]:  # a step inside a step counts once, in the outer one
            return fn(*a, **kw)
        depth[0] += 1
        t0 = time.perf_counter()
        try:
            return fn(*a, **kw)
        finally:
            acc[name] += time.perf_counter() - t0
            depth[0] -= 1

    return run


def _wrap(comp: Any, acc: dict[str, float], depth: list[int]) -> list[tuple[Any, str, Any]]:
    """Wrap each step of the compiler and its modules (the repository's are wrapped per approval); returns what to
    put back."""
    import importlib

    from criteria_compiler import service

    undo: list[tuple[Any, str, Any]] = []
    for owner, attr, name in STEPS:
        if owner == "Compiler":
            target: Any = type(comp)
        elif owner == "repo":
            continue
        elif owner.endswith(".provenance"):
            target = getattr(service, "provenance")  # noqa: B009 - the module the service calls it through
        else:
            target = importlib.import_module(owner)
        if not hasattr(target, attr):
            continue
        orig = target.__dict__[attr] if attr in getattr(target, "__dict__", {}) else getattr(target, attr)
        undo.append((target, attr, orig))
        wrapped = _timed(getattr(target, attr), name, acc, depth)
        setattr(target, attr, staticmethod(wrapped) if isinstance(orig, staticmethod) else wrapped)
    return undo


def made_up_site_list(directory: Path, rows: int) -> None:
    """A made-up site list of ``rows`` lines (department codes D00001...), loaded as the box's IT would load one."""
    from criteria_compiler.terminology import installed as inst

    src = directory.parent / "made-up-site-list.csv"
    lines = ["local_code,local_name,code,system"] + [f"L{i:06d},made-up unit {i},D{i:05d},department"
                                                     for i in range(rows)]  # fmt: skip
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    inst.install_site_list(src, directory, "profile")


def _deps(work: Path, seed: Path, *, fake_translator: bool, site_list_rows: int = 0) -> Any:
    from criteria_compiler.compile_cql.translator import Translation, Translator
    from criteria_compiler.repo import RulesetRepo
    from criteria_compiler.service import CompilerDeps
    from criteria_compiler.terminology.mapper import Terminology
    from fastapi.testclient import TestClient
    from llm_stub.app import app as stub
    from tb_common.audit import AuditLog
    from tb_common.llm import LlmClient
    from tb_common.objstore import FsStore

    class FakeTranslator:
        def translate(self, sources: dict[str, str], check: set[str] | None = None) -> Translation:
            return Translation({name: '{"library":{}}' for name in sources})

    installed = work / "installed"  # never the box's /data/terminology
    installed.mkdir()
    if site_list_rows:
        made_up_site_list(installed, site_list_rows)
    audit = AuditLog(work / "audit")
    llm = LlmClient("http://stub/v1", "trialbox-stub", audit=audit)
    llm.http = TestClient(stub)
    return CompilerDeps(
        store=FsStore(work / "obj"), repo=RulesetRepo(work / "repo", seed), llm=llm,
        term=Terminology(installed=installed), settings_thresholds={"equivalence_min_pct": 98.0},
        translator=FakeTranslator() if fake_translator else Translator(),  # type: ignore[arg-type]
        audit=audit, equivalence=PassGate(), mrn_regex=r"^\d{8}$",
        fhir=RecordingFhir(),  # type: ignore[arg-type]
    )  # fmt: skip


def profile(
    protocol: Path, runs: int, *, fake_translator: bool = False, top: int = 0, site_list_rows: int = 0
) -> dict[str, Any]:
    import tb_contracts as c
    from criteria_compiler.repo import RulesetRepo
    from criteria_compiler.review import parse_review_xlsx
    from criteria_compiler.service import Compiler
    from doc_parser.parser import parse
    from tb_common.config import adopt_site_tz
    from tb_common.steptime import COMPILER_STEPS

    adopt_site_tz()
    logging.getLogger("llm-stub").setLevel(logging.WARNING)
    with tempfile.TemporaryDirectory(prefix="tb-approve-profile-") as t:
        work = Path(t)
        seed = work / "seed"
        seed.mkdir()
        t0 = time.perf_counter()
        deps = _deps(work, seed, fake_translator=fake_translator, site_list_rows=site_list_rows)
        setup_s = time.perf_counter() - t0
        comp = Compiler(deps)
        data = protocol.read_bytes()
        deps.store.put("attachments/P/parsed.json", c.dump_json(parse(data, protocol.name)).encode())
        t0 = time.perf_counter()
        res = comp.compile(c.CompileRequest(job_id="01JPROF0000000000000000000", ruleset=RULESET,
                                            parsed_doc_key="attachments/P/parsed.json", requested_by="crc1@hospa.test",
                                            options={"index_date": "2026-10-05"}))  # fmt: skip
        compile_s = time.perf_counter() - t0
        assert res.review_xlsx_key is not None
        deps.fhir.resources.clear()
        deps.fhir.loads = 0
        decisions, _ = parse_review_xlsx(deps.store.get(res.review_xlsx_key))
        shutil.copytree(work / "repo", work / "compiled")
        acc: dict[str, float] = defaultdict(float)
        recorded: dict[str, float] = defaultdict(float)
        depth = [0]
        undo = _wrap(comp, acc, depth)
        prof = cProfile.Profile()
        walls: list[float] = []
        statuses: list[str] = []
        try:
            for i in range(runs):
                shutil.rmtree(work / "repo")
                shutil.copytree(work / "compiled", work / "repo")
                comp.d.repo = RulesetRepo(work / "repo", seed)  # a new repo object: its steps are wrapped again
                for owner, attr, name in STEPS:
                    if owner == "repo" and hasattr(comp.d.repo, attr):
                        setattr(comp.d.repo, attr, _timed(getattr(comp.d.repo, attr), name, acc, depth))
                req = c.ApproveRequest(ruleset=RULESET, version=res.version, by="crc1@hospa.test", decisions=decisions,
                                       job_id=f"01JPROFA{i:018d}")  # fmt: skip
                t0 = time.perf_counter()
                prof.enable()
                got = comp.approve(req)
                prof.disable()
                walls.append(time.perf_counter() - t0)
                statuses.append(got.status)
                for k, v in (got.step_seconds or {}).items():
                    recorded[k] += v
        finally:
            for target, attr, orig in reversed(undo):
                setattr(target, attr, orig)
    total = sum(walls)
    steps = {k: round(v / runs, 4) for k, v in sorted(acc.items(), key=lambda kv: -kv[1])}
    steps["other"] = round(max(0.0, total - sum(acc.values())) / runs, 4)
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "tool": "python -m tools.public_accuracy.approve_profile",
        "protocol": protocol.name, "criteria": len(res.criteria), "runs": runs, "statuses": statuses,
        "translator": "fake" if fake_translator else "real (CQL-to-ELM, JVM)",
        "fhir": "recorded, not sent (no server here)",
        "fhir_load": {"loads_per_approval": deps.fhir.loads / runs,
                      "resources_per_approval": len(deps.fhir.resources) // runs,
                      "bytes_per_approval": sum(b for _n, b in deps.fhir.resources) // runs,
                      "largest": sorted({n: b for n, b in deps.fhir.resources}.items(), key=lambda kv: -kv[1])[:5]},
        "site_list_rows": site_list_rows,
        "setup_s": round(setup_s, 3), "compile_s": round(compile_s, 3),
        "approve_s": {"mean": round(total / runs, 4), "each": [round(w, 4) for w in walls]}, "steps_mean_s": steps,
        "recorded_steps_mean_s": {k: round(recorded[k] / runs, 4) for k in COMPILER_STEPS if k in recorded},
    }  # fmt: skip
    if top:
        st = pstats.Stats(prof)
        rows = sorted(st.stats.items(), key=lambda kv: -kv[1][3])  # type: ignore[attr-defined]
        out["top_cumulative"] = [
            {"function": f"{Path(f).name}:{ln}:{fn}", "calls": v[1], "cum_s_per_approval": round(v[3] / runs, 4)}
            for (f, ln, fn), v in rows[:top]
        ]
    return out


def render(r: dict[str, Any]) -> str:
    out = [f"approve profile: {r['protocol']} ({r['criteria']} criteria), {r['runs']} approval(s), translator "
           f"{r['translator']}, fhir {r['fhir']}, made-up site list {r['site_list_rows']} rows; "
           f"statuses {sorted(set(r['statuses']))}",
           f"  setup {r['setup_s']} s, compile {r['compile_s']} s, "
           f"approve mean {r['approve_s']['mean']} s"]  # fmt: skip
    f = r["fhir_load"]
    out.append(
        f"  fhir load per approval: {f['loads_per_approval']} load(s), {f['resources_per_approval']} resources, "
        f"{f['bytes_per_approval']} bytes; largest {f['largest']}"
    )
    for k, v in r["steps_mean_s"].items():
        out.append(f"  {v:9.4f} s  {k}")
    if r.get("recorded_steps_mean_s"):
        out.append("  recorded by Compiler.approve itself (step_seconds, H-45):")
        for k, v in r["recorded_steps_mean_s"].items():
            out.append(f"  {v:9.4f} s  {k}")
    for row in r.get("top_cumulative", []):
        out.append(f"  top {row['cum_s_per_approval']:9.4f} s  {row['calls']:6d} calls  {row['function']}")
    return "\n".join(out) + "\n"


def _records(text: str) -> list[dict[str, Any]]:
    """The JSON objects of a job record file (one object or a list) or of a log (one object per line)."""
    try:
        whole = json.loads(text)
    except ValueError:
        whole = None
    if isinstance(whole, dict):
        return [whole]
    if isinstance(whole, list):
        return [x for x in whole if isinstance(x, dict)]
    out = []
    for line in text.splitlines():
        if line.startswith("{"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict):
                out.append(d)
    return out


def approve_jobs(paths: list[Path]) -> list[dict[str, Any]]:
    """[{job, state, wall, steps}] of each APPROVE job with step seconds, the last record of each job."""
    from tb_common.steptime import numbers_only

    from tools.public_accuracy.replay import collect

    files: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="tb-approve-steps-") as t:
        sets = [p for p in paths if p.is_dir() or p.name.endswith((".tgz", ".tar.gz", ".tar"))]
        for folder in collect(sets, Path(t)).values() if sets else []:
            files.append(folder / "work" / "box-calls.log")
        files += [p for p in paths if p not in sets]
        found: dict[str, dict[str, Any]] = {}
        for f in files:
            if not f.is_file():
                continue
            for d in _records(f.read_text(encoding="utf-8", errors="replace")):
                m = d.get("metrics")
                if d.get("type") != "APPROVE" or not isinstance(m, dict) or not isinstance(m.get("step_seconds"), dict):
                    continue
                jid = str(d.get("job") or d.get("job_id") or f"#{len(found)}")
                found[jid] = {"job": jid, "state": d.get("state"), "wall": float(m.get("wall_seconds") or 0),
                              "steps": numbers_only(m["step_seconds"])}  # fmt: skip
    return list(found.values())


def step_table(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Each step's median, mean and largest seconds over the jobs, its share of their summed time, and the check that
    a job's steps add up to its wall seconds (a failed job writes no wall seconds: its steps are its run's time)."""
    import statistics as st

    from tb_common.steptime import APPROVE_STEPS

    total = sum(sum(j["steps"].values()) for j in jobs)
    rows = []
    for k in APPROVE_STEPS:
        xs = [j["steps"].get(k, 0.0) for j in jobs]
        if not any(k in j["steps"] for j in jobs):
            continue
        rows.append({"step": k, "jobs": sum(k in j["steps"] for j in jobs), "median_s": round(st.median(xs), 3),
                     "mean_s": round(st.fmean(xs), 3), "max_s": round(max(xs), 3),
                     "share": round(sum(xs) / total, 4) if total else 0.0})  # fmt: skip
    off = [j["job"] for j in jobs if j["wall"] and abs(sum(j["steps"].values()) - j["wall"]) > 0.01 + 0.001 * j["wall"]]
    return {"schema_version": SCHEMA_VERSION, "tool": "python -m tools.public_accuracy.approve_profile --steps",
            "approve_jobs": len(jobs), "failed_jobs": sum(j["state"] == "failed" for j in jobs),
            "summed_s": round(total, 3), "rows": rows, "steps_differ_from_wall": off}  # fmt: skip


def render_steps(r: dict[str, Any]) -> str:
    out = [f"approve step seconds (H-45): {r['approve_jobs']} APPROVE job(s) with step seconds "
           f"({r['failed_jobs']} failed), {r['summed_s']} s in all",
           f"  {'step':28s} {'jobs':>5s} {'median s':>10s} {'mean s':>10s} {'max s':>10s} {'share':>7s}"]  # fmt: skip
    for x in r["rows"]:
        out.append(f"  {x['step']:28s} {x['jobs']:5d} {x['median_s']:10.3f} {x['mean_s']:10.3f} {x['max_s']:10.3f} "
                   f"{100 * x['share']:6.1f}%")  # fmt: skip
    out.append(f"  steps differ from wall_seconds: {', '.join(r['steps_differ_from_wall']) or 'none'}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.public_accuracy.approve_profile",
                                 description=(__doc__ or "").strip(),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    ap.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL, help="a made-up protocol (PDF or text)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--fake-translator", action="store_true", help="skip the JVM CQL-to-ELM translation")
    ap.add_argument("--site-list-rows", type=int, default=0, help="load a made-up site list of N rows first")
    ap.add_argument("--top", type=int, default=0, help="the K functions with the most cumulative time")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--steps", type=Path, nargs="+", help="read stored APPROVE jobs' step seconds; run nothing")
    a = ap.parse_args(argv)
    if a.steps:
        from tools.public_accuracy.replay import Refused

        try:
            found = approve_jobs(a.steps)
        except (Refused, OSError, ValueError) as exc:
            print(f"approve_profile: {exc}", file=sys.stderr)
            return 2
        if not found:
            print("approve_profile: no APPROVE job with step seconds in the records given", file=sys.stderr)
            return 2
        table = step_table(found)
        if a.json:
            a.json.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        sys.stdout.write(render_steps(table))
        return 0
    if not a.protocol.is_file() or a.runs < 1:
        print("approve_profile: --protocol must be a file and --runs at least 1", file=sys.stderr)
        return 2
    res = profile(a.protocol, a.runs, fake_translator=a.fake_translator, top=a.top, site_list_rows=a.site_list_rows)
    if a.json:
        a.json.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(render(res))
    return 0 if all(s == "approved" for s in res["statuses"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
