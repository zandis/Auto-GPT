"""The complete-platform run (TB-PLAN-04 step 9, plan v4 §5, D-139): every stage, both languages, one report.

    python -m tools.complete_run --dir /tmp/tb-complete --model stub --patients 5000         # any laptop, no GPU
    TB_GPU_KEY=... python -m tools.complete_run --dir /tmp/tb-complete --model pair --patients 50000 \\
        --judge-url http://<vm>/judge/v1 --verifier-url http://<vm>/verifier/v1 --live-record <record.json>

``deploy/gcp/complete-run.sh`` starts the RTX PRO 6000 VM with the pair resident, runs the second line and stops the
VM. Each part runs in its own process (one box at a time, memory and environment kept apart):

    install       the tier and the serving record: ``large`` installs on the measured card, ``small`` is refused
    hospital:ja   the synthetic hospital of ``--patients`` (``tools.synth_hospital``, JP and TW site) through the
    hospital:zh-TW  ``e2e_simple`` path: data in, criteria, approval, screening (with the pair and the canary gate on
                  ``--model pair``), lists, marks, mail, REDCap two-way, the data core, built-in forms, the
                  lifecycle, site set-up, Japan (SS-MIX2, JP Core), audit, byte-identical re-run
    public:ja     the public-data site (``tools.public_e2e``: real notes) through the same path in the console
    public:zh-TW  ...
    walk          the browser walk on a fresh public console (``tools/public_walk.js``: 5 roles x 3 languages x desktop
                  and phone, axe-core, 44 px targets, tap counts); on the stub, so after the GPU has stopped
    backup        ``tools.backup_drill``: backed up, wiped, restored, the same box
    update        ``tools.update_drill``: a signed update applied, two bad ones rolled back
    scale         ``tools.hospital_sim scale``: the cascade S0..S5 at ``--patients``, timed
    scenario:<n>  the scenario matrix (``tools.scenarios``, D-141): one part per way a site gives TrialBox data
                  (SS-MIX2, FHIR, the site's Excel and CSV lists, pasted charts, chart files through OCR, REDCap and
                  the built-in forms, an IT dump with local codes, the offline registry) plus the gateway probe; the
                  hospital parts above are the database-feed scenario (``db-csv``)

``--resume`` keeps every part whose ``parts/<tag>.json`` exists with every check passed (a part writes its result
to a temporary file and renames it, so a killed part never leaves half a result). ``--estimate`` prints the hours and
US$ per scenario on the card without running anything (:func:`estimate`).

After each console part the console is served on a free local port and ``tools/stage_shots.js`` takes one screenshot
per stage, signed in as the role that does it, in the part's language. Parts without a console of their own (install,
backup, update, scale) get a picture of their check table. The report (``<dir>/report/report.md`` and ``.json``)
holds per stage the checks, the time and the screenshot, and the git head it ran from.

With ``--model pair`` every model call goes through the gateway built as an installed box builds it
(``tools.scenarios.models``; ``--direct`` bypasses it). Synthetic and public data only. The console password is
random, from ``TB_DEMO_PASSWORD`` or made here, and never printed; the GPU key comes from ``TB_GPU_KEY`` only. Exit 0
only when every check of every part passed (known findings of the review are reported, not counted).
"""

from __future__ import annotations

import argparse
import html
import itertools
import json
import math
import os
import platform
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools import pin_model  # noqa: E402  (after the path setup, as the parts import it)

LANGS = ("ja", "zh-TW")
JUDGE, VERIFIER = pin_model.JUDGE_SERVED, pin_model.VERIFIER_SERVED  # the vLLM served names (D-124)
VENDOR_RECORD = ROOT / "deploy" / "measured" / "serving_config.rtxpro6000.json"
NODE_TOOLS = Path("/opt/node-tools/node_modules")  # the preinstalled Playwright (never `playwright install`)

# the page that shows each stage's result, and who opens it: (stage name prefix, user, path)
H_TRIAL, H_COHORT = "GZQO", "GOUT-COH"
HOSPITAL_PAGES = [
    ("0 ", "admin", "/admin?tab=sources"),
    ("1 ", "pi", f"/studies/{H_TRIAL}/feasibility"),
    ("2 ", "pi", "/pilot/jobs/{feas}/approval"),
    ("3 ", "pi", f"/studies/{H_TRIAL}/week?list=all"),
    ("4 ", "pi", f"/studies/{H_TRIAL}/patients/{{pid}}"),
    ("5 ", "pi", f"/studies/{H_TRIAL}/week?list=needs"),
    ("7 ", "crc", f"/studies/{H_TRIAL}/screening-log"),
    ("audit", "stw", "/audit"),  # the steward reads the audit trail (T-211c, D-451), not the administrator
    ("8 ", "crc", f"/studies/{H_TRIAL}/sources"),
    ("9 ", "crc", f"/studies/{H_TRIAL}/conflicts?all=1"),
    ("10 ", "crc", f"/studies/{H_TRIAL}/forms"),
    ("11 ", "crc", f"/studies/{H_TRIAL}/subjects"),
    ("12 ", "crc", "/site?ws=newsite&study=SITE5B"),  # e2e_simple.SITE_WS, SITE_RS
    ("13 ", "admin", "/admin?tab=sources"),
    ("14 ", "admin", "/admin/notice"),  # the offline trial registry: its sources and licences (D-140)
    ("15 ", "pi", f"/studies/{H_TRIAL}/candidates"),  # the hospital's candidates, the log, referrals (D-147)
    ("16 ", "crc", f"/studies/{H_TRIAL}/edc"),  # EDC prefill: drafts, the CRC's review and e-signature (D-160, PR #56)
    ("17 ", "pi", f"/studies/{H_TRIAL}/week?list=clinic"),  # the new booked patient on the clinic list (D-397)
    ("re-run", "admin", "/jobs"),
    ("runtime", "admin", "/admin?tab=health"),
]
P_TRIAL = "PUB-ONC"
PUBLIC_PAGES = [
    ("0 ", "admin", "/admin?tab=sources"),
    ("1 ", "pi", f"/studies/{P_TRIAL}/feasibility"),
    ("2 ", "pi", f"/studies/{P_TRIAL}/week?list=all"),
    ("3 ", "pi", f"/studies/{P_TRIAL}/patients/{{pid}}"),
    ("4 ", "pi", "/notices/received"),
    ("5 ", "crc", f"/studies/{P_TRIAL}/screening-log"),
    ("5b ", "crc", f"/studies/{P_TRIAL}/subjects"),
    ("5c ", "crc", f"/site?ws=practice&study={P_TRIAL}"),
    ("6 ", "crc", "/reports"),
    ("7 ", "crc", "/pilot/jobs/{case}"),
    ("7b ", "pi", "/pilot/jobs/{case}"),  # D-143: the study's PI sees the CASE request's chart number, audited
    ("8 ", "stw", "/audit"),  # as above; the public walk makes the steward
]


# ---------------------------------------------------------------- helpers
def _stages(stages: list[Any]) -> list[dict[str, Any]]:
    return [
        {"name": st.name, "ok": st.ok, "seconds": round(st.seconds, 1), "checks": [list(c) for c in st.checks]}
        for st in stages
    ]


def _one(name: str, checks: list[tuple[str, bool, Any]], seconds: float) -> list[dict[str, Any]]:
    return [{"name": name, "ok": all(c[1] for c in checks), "seconds": round(seconds, 1), "checks": checks}]


DOOR_STATE = "door-secret.txt"  # complete-run.sh: the door's secret versions after a collect or stop (A8)
HEAD_FILE = "TB_HEAD.json"  # written into the uploaded archive by the driver (git archive --add-file): the VM's HEAD


def git_head() -> dict[str, Any]:
    """The commit this code is: from git when this is a checkout, else from :data:`HEAD_FILE`, which the driver adds
    to the archive it uploads (the VM has the archive, not the repository: the cloud run's first rehearsal died here
    on a missing ``git``, review M-08). Never raises."""

    def g(*a: str) -> str:
        try:
            r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=False)
        except OSError:
            return ""
        return r.stdout.strip() if r.returncode == 0 else ""

    head = g("rev-parse", "HEAD")
    if head:
        return {"head": head, "subject": g("log", "-1", "--format=%s"), "dirty": bool(g("status", "--porcelain")),
                "source": "git"}  # fmt: skip
    for p in (ROOT / HEAD_FILE, ROOT.parent / HEAD_FILE):
        if p.is_file():
            d = json.loads(p.read_text(encoding="utf-8"))
            return {"head": str(d.get("head", "")), "subject": str(d.get("subject", "")),
                    "dirty": bool(d.get("dirty", False)), "source": "archive"}  # fmt: skip
    return {"head": "", "subject": "", "dirty": False, "source": "unknown"}


def host_facts() -> dict[str, Any]:
    return {"machine": platform.machine(), "cpus": os.cpu_count(), "python": platform.python_version(),
            "node": platform.node()}  # fmt: skip


def run_identity(run_id: str) -> dict[str, Any]:
    """What a part result carries (review H-01, M-02): the run it belongs to, the commit and the host that made it."""
    g = git_head()
    return {"id": run_id, "head": g["head"], "subject": g["subject"], "dirty": g["dirty"], "host": host_facts()}


def base_run_id(run_id: str) -> str:
    """The run a run id belongs to: a VM of a run carries ``<run id>-s<N>`` (its shard, D-148), the driver ``<run
    id>``; both are one run (G1 bug A1)."""
    head, sep, tail = run_id.rpartition("-s")
    return head if sep and head and tail.isdigit() else run_id


def same_run(res: dict[str, Any], run_id: str, head: str) -> tuple[bool, str]:
    """``--resume`` keeps a part only when it was made by this run at this HEAD (review H-01: a disk that outlives
    a run must never carry a passed part into the next one). ``<run id>`` and ``<run id>-s<N>`` are the same run."""
    r = res.get("run") or {}
    if not r.get("id") or base_run_id(str(r["id"])) != base_run_id(run_id):
        return False, f"run {r.get('id') or '?'}"
    if not head or r.get("head") != head:
        return False, f"HEAD {str(r.get('head') or '?')[:12]}"
    return True, ""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


class Served:
    """The part's console on 127.0.0.1:<free port>, in a thread, for the screenshots and the walk."""

    def __init__(self, app: Any) -> None:
        import uvicorn

        self.port = _free_port()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.05)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _node_env(password: str) -> dict[str, str]:
    env = dict(os.environ, TB_SHOT_PASSWORD=password)
    if not env.get("NODE_PATH") and NODE_TOOLS.exists():
        env["NODE_PATH"] = str(NODE_TOOLS)
    return env


def shoot(items: list[dict[str, Any]], out: Path, password: str, base: str = "") -> dict[str, dict[str, Any]]:
    """Screenshots by tools/stage_shots.js; ``{item name: result}``. A missing node or browser is a failed shot,
    never a crash: the run still reports its checks."""
    out.mkdir(parents=True, exist_ok=True)
    arg = json.dumps({"base": base, "out": str(out), "items": items})
    try:
        r = subprocess.run(
            ["node", str(ROOT / "tools" / "stage_shots.js"), arg],
            env=_node_env(password),
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        rows = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else []
        err = r.stderr.strip().splitlines()[-1:] if r.returncode else []
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        rows, err = [], [str(exc)]
    got = {x["name"]: x for x in rows}
    return {it["name"]: got.get(it["name"], {"ok": False, "error": "; ".join(err) or "no result"}) for it in items}


def table_page(path: Path, title: str, stages: list[dict[str, Any]]) -> str:
    """A plain HTML page of a part's checks (for the parts without a console); returns its file:// URL."""
    rows: list[str] = []
    for st in stages:
        for what, ok, detail in st["checks"]:
            mark = "pass" if ok else "FAIL"
            rows.append(
                f"<tr><td>{html.escape(st['name'])}</td><td>{html.escape(str(what))}</td>"
                f"<td class={mark}>{mark}</td><td>{html.escape(str(detail))[:200]}</td></tr>"
            )
    path.write_text(
        "<!doctype html><meta charset=utf-8><title>" + html.escape(title) + "</title><style>body{font:14px sans-serif;"
        "margin:24px}td,th{border:1px solid #ccc;padding:4px 8px;text-align:left}.pass{color:#060}.FAIL{color:#b00;"
        "font-weight:bold}</style><h1>" + html.escape(title) + "</h1><table><tr><th>stage</th><th>check</th>"
        "<th>result</th><th>detail</th></tr>" + "".join(rows) + "</table>",
        encoding="utf-8",
    )
    return path.resolve().as_uri()


def _page_items(prefix: str, lang: str, stages: list[dict[str, Any]], pages: list[tuple[str, str, str]],
                fill: dict[str, str]) -> list[dict[str, Any]]:  # fmt: skip
    items = []
    for i, st in enumerate(stages):
        hit = next(((u, p) for pre, u, p in pages if st["name"].startswith(pre)), ("admin", "/home"))
        items.append({"name": f"{prefix}-{i:02d}", "user": hit[0], "lang": lang, "path": hit[1].format(**fill)})
        st["shot"] = f"{prefix}-{i:02d}.png"
    return items


def _attach_shots(stages: list[dict[str, Any]], got: dict[str, dict[str, Any]]) -> None:
    for st in stages:
        r = got.get(str(st.get("shot", "")).removesuffix(".png"), {})
        st["shot_ok"] = bool(r.get("ok"))
        st["shot_status"] = r.get("status")
        st["shot_lang"] = r.get("lang")
        if r.get("error"):
            st["shot_error"] = r["error"]


def _models(a: argparse.Namespace) -> tuple[Any, Any]:
    from tools import scenarios

    return scenarios.models(a, a.dir / f"gw-audit-{a.part}")


# ---------------------------------------------------------------- the parts (each in its own process)
def part_prepare(a: argparse.Namespace) -> dict[str, Any]:
    """The synthetic hospital of ``--patients``, generated once and shared by both languages (read only)."""
    from tools import feas_demo as fd
    from tools.synth_hospital import run as synth_run

    out = a.dir / f"synth-{a.patients}"
    t0 = time.perf_counter()
    checks: list[tuple[str, bool, Any]]
    if not (out / "summary.json").exists():
        jp = a.patients // 2
        res = synth_run(out, profile="ci", sites=f"jp-a:JP:{jp},tw-a:TW:{a.patients - jp}", ref_date=fd.REF)
        checks = [("synthetic hospital generated, TB-DS-21 §6 checks pass", res.passed, "; ".join(res.failures[:3]))]
    else:
        checks = [("synthetic hospital reused", True, str(out))]
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    n = sum(int(s["patients"]) for s in summary["sites"])
    checks.append((f"{a.patients} patients in two sites (JP and TW style)", n == a.patients, n))
    return {"stages": _one("synthetic hospital", checks, time.perf_counter() - t0), "patients": n}


def part_install(a: argparse.Namespace) -> dict[str, Any]:
    from tools import serving_config, tiers

    t0 = time.perf_counter()
    checks: list[tuple[str, bool, Any]] = []
    records = [("vendor", VENDOR_RECORD)] + ([("this run", a.live_record)] if a.live_record else [])
    card = ""
    for who, path in records:
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
        why = serving_config.measured_for(rec, "rtxpro6000")
        checks.append((f"the {who} serving record measures rtxpro6000 on its own card", not why, "; ".join(why)))
        card = str((rec.get("card") or {}).get("name") or card)
    try:
        gpu, rec_path = tiers.resolve("large", arch="x86_64", card=card)
        checks.append(("tier large installs on this card from a measured record", gpu == "rtxpro6000", rec_path.name))
    except tiers.Refused as exc:
        checks.append(("tier large installs on this card from a measured record", False, str(exc)))
    try:
        tiers.resolve("small", arch="x86_64", card=card)
        checks.append(("tier small is refused on this card", False, "installed"))
    except tiers.Refused as exc:
        checks.append(("tier small is refused on this card", True, str(exc)[:120]))
    return {"stages": _one("install: tier and serving record", checks, time.perf_counter() - t0), "card": card}


def part_hospital(a: argparse.Namespace) -> dict[str, Any]:
    from tools import e2e_simple, run_metrics
    from tools import feas_demo as fd

    work = a.dir / f"hospital-{a.lang}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    (work / "synth").symlink_to((a.dir / f"synth-{a.patients}").resolve(), target_is_directory=True)
    # TB-DS-04 §3.4.1 asks 15 minutes for the 5,000-patient gate; a larger hospital gets the same rate. With the pair
    # the models read the notes: the whole path must then fit one night (8 h, TB-PLAN-03 §8 "inside the night window")
    e2e_simple.BUDGET_S = max(15 * 60, 15 * 60 * a.patients // 5000) if a.model != "pair" else 8 * 3600
    llm, verifier = _models(a)
    canary: dict[str, Any] = {}
    if llm is not None:
        from tools.public_e2e import attach_models

        e2e_simple.PAIR = (JUDGE, VERIFIER)
        build = fd.build

        def with_pair(work: Path) -> tuple[Any, Any, Path, dict[str, Any]]:
            box, client, repo, summary = build(work)
            canary["status"] = attach_models(box, llm, verifier)
            return box, client, repo, summary

        fd.build = with_pair  # list_demo calls fd.build: the pair reads the notes in this box
    from tools import scenarios

    scenarios.capture_screens()
    out = e2e_simple.run(work, a.password, a.lang)
    stages = _stages(out["stages"])
    lst = out["result"]["list"]
    box = lst["box"]
    sj = box.orch.db.get(out["jobs"]["screen"])
    scr = e2e_simple._json_output(box, sj, "screen_")
    # the database-feed scenario (db-csv): model calls, and the models' exclusions against the generator's note truth
    summary = json.loads((a.dir / f"synth-{a.patients}" / "summary.json").read_text(encoding="utf-8"))
    truth = scenarios.note_truth([a.dir / f"synth-{a.patients}" / x["dir"] for x in summary["sites"]], fd.KEY)
    # the main SCREEN's own verdicts (its list is the job's), not a later stage's one-patient SCREEN (M1, 2026-11-12)
    main = main_candidates(box, sj)
    ours = [c for c in scenarios.CAPTURED if c["ruleset"] == e2e_simple.TRIAL]
    same = [c for c in ours if run_metrics.candidate_list(c["results"])["sha256"] == main["sha256"]]
    cap: dict[str, Any] = (same or ours or [{}])[0 if same else -1]
    ex = scenarios.model_exclusions(cap.get("results") or {}, truth)
    stages += _one("db-csv: model exclusions against the generator's note truth", [
        ("no false model exclusion (a note criterion the truth does not block on)", ex["false"] == 0,
         ex["patients"][:5])], 0)  # fmt: skip
    extra = {
        "seconds": out["seconds"],
        "chain_seconds": out["chain_seconds"],
        "screen": {k: scr.get(k) for k in ("funnel", "tiers", "listed", "judging")},
        "canary": canary.get("status"),
        # G-3: who the main SCREEN listed (the job whose funnel is above, from its own candidate_list_*.json), with a
        # hash: the list must be the same at every TB_SCREEN_LLM_CONCURRENCY
        "candidates": main,
        "scenario": {
            "title": "Hospital database feed (CGRD-style CSV)",
            "input": f"CGRD-style CSV export of {a.patients:,} synthetic patients (two sites, JP and TW style)",
            "counts": {"patients": a.patients, "screen_funnel": dict(scr.get("funnel") or [])},
            "expected": "e2e_simple stages 0-1: lake = generator counts; FEAS INC-01/02 = recount from the CSVs",
            "got": {st["name"]: f"{sum(1 for c in st['checks'] if c[1])}/{len(st['checks'])}" for st in stages[:2]},
            "model_calls": scenarios.llm_calls(box),
            "model_exclusions": ex,
        },
    }
    fill = {"feas": out["jobs"]["feas"], "pid": lst["picks"][0]["pid"]}
    # a repeat at its own concurrency keeps its own screenshots (hospital-ja@c4-00.png)
    items = _page_items(_tag("hospital", a.lang, getattr(a, "variant", "")), a.lang, stages, HOSPITAL_PAGES, fill)
    srv = Served(out["result"]["app"])
    try:
        _attach_shots(stages, shoot(items, a.shots, a.password, srv.base))
    finally:
        srv.stop()
    return {"stages": stages, **extra}


def main_candidates(box: Any, job: Any) -> dict[str, Any]:
    """The candidate list of the part's main SCREEN job (``job``: the one whose funnel and ``listed`` the part
    reports), from the job's own ``candidate_list_*.json``; ``of`` names the job. Not the last SCREEN captured in the
    process: a later stage screens one patient (the 2026-11-12 run's lists were of that one, ``count`` 1)."""
    from tools import e2e_simple, run_metrics

    try:
        doc = e2e_simple._json_output(box, job, "candidate_list_")
    except StopIteration:
        return {"count": 0, "sha256": "", "list": None, "of": getattr(job, "job_id", ""), "why": "no candidate list"}
    return {**run_metrics.candidate_list_of_rows(doc.get("rows") or []), "of": getattr(job, "job_id", "")}


def part_public(a: argparse.Namespace) -> dict[str, Any]:
    from tools import public_e2e

    work = a.dir / f"public-{a.lang}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    llm, verifier = _models(a)
    res = public_e2e.run(work, a.password, a.lang, llm, verifier)
    stages = _stages(res["stages"])
    w = res["walk"]
    fill = {"pid": w["pid_marked"], "case": w["case_job"] or w["feas_job"]}
    items = _page_items(f"public-{a.lang}", a.lang, stages, PUBLIC_PAGES, fill)
    srv = Served(res["app"])
    extra: dict[str, Any] = {"seconds": round(res["seconds"], 1), "screen": res.get("screen"),
                             "canary": res.get("canary")}  # fmt: skip
    try:
        _attach_shots(stages, shoot(items, a.shots, a.password, srv.base))
    finally:
        srv.stop()
    return {"stages": stages, **extra}


def part_scenario(a: argparse.Namespace) -> dict[str, Any]:
    """One scenario of the matrix (``tools.scenarios``), in its own work folder, with a screenshot of its key page."""
    from tools import scenarios

    work = a.dir / f"scenario-{a.scenario}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    from tools import pglocal

    pglocal.for_work(work)  # the scenario's trial database (TB_DB_URL, or the shared throwaway cluster)
    t0 = time.perf_counter()
    res = scenarios.RUNNERS[a.scenario](a, work)
    stages = _stages(res.stages)
    block = {**res.block, "seconds": round(time.perf_counter() - t0, 1), "title": scenarios.TITLES[a.scenario]}
    if res.app is not None and res.pages:
        items = []
        for i, st in enumerate(stages):
            user, path = res.pages[min(i, len(res.pages) - 1)]
            items.append({"name": f"scenario-{a.scenario}-{i:02d}", "user": user, "lang": a.lang, "path": path})
            st["shot"] = f"scenario-{a.scenario}-{i:02d}.png"
        srv = Served(res.app)
        try:
            _attach_shots(stages, shoot(items, a.shots, a.password, srv.base))
        finally:
            srv.stop()
    else:  # the gateway probe has no console: a picture of its check table, as install has
        url = table_page(a.shots / f"scenario-{a.scenario}.html", f"TrialBox scenario: {a.scenario}", stages)
        got = shoot([{"name": f"scenario-{a.scenario}", "url": url}], a.shots, a.password)
        for st in stages:
            st["shot"] = f"scenario-{a.scenario}.png"
        _attach_shots(stages, {f"scenario-{a.scenario}": got[f"scenario-{a.scenario}"]})
    if not a.keep_work:
        shutil.rmtree(work, ignore_errors=True)  # disk: a scenario's boxes and lakes are not kept
    return {"stages": stages, "scenario": block, "findings": res.findings}


def part_walk(a: argparse.Namespace) -> dict[str, Any]:
    """The browser walk on a fresh public console, always on the stub: it checks pages, not models, so on the card
    it runs after the VM has stopped."""
    from tools import public_e2e

    work = a.dir / "walk"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    res = public_e2e.run(work, a.password, "ja")
    built = _one("public console for the walk (public_e2e, stub)", [("built", all(st.ok for st in res["stages"]),
                 "")], res["seconds"])  # fmt: skip
    srv = Served(res["app"])
    try:
        st = walk(srv.base, work, res["walk"], a)
    finally:
        srv.stop()
    summary = st.pop("summary", None)
    return {"stages": [*built, st], "walk": summary}


def walk(base: str, work: Path, w: dict[str, Any], a: argparse.Namespace) -> dict[str, Any]:
    """The browser walk over the public console (as D-135: `node tools/public_walk.js` against `public_e2e --serve`)."""
    t0 = time.perf_counter()
    wfile, out = work / "walk.json", work / "walk-results.json"
    wfile.write_text(json.dumps(w), encoding="utf-8")
    shots = a.shots / "walk"
    shots.mkdir(parents=True, exist_ok=True)
    arg = json.dumps({"base": base, "walk": str(wfile), "shots": str(shots), "out": str(out)})
    checks: list[tuple[str, bool, Any]] = []
    summary: dict[str, Any] = {}
    try:
        r = subprocess.run(["node", str(ROOT / "tools" / "public_walk.js"), arg], env=_node_env(a.password),
                           capture_output=True, text=True, timeout=4 * 3600, check=False)  # fmt: skip
        line = json.loads(r.stdout.strip().splitlines()[-1])
        summary = {k: line.get(k) for k in ("checks", "failed", "summary")}
        fails = "; ".join(line["failures"][:5])
        checks.append((f"walk: {line['checks']} checks, 0 failures", line["failed"] == 0, fails))
        s = line.get("summary") or {}
        grave = {k: v for k, v in (s.get("axe_by_impact") or {}).items() if k in ("serious", "critical")}
        checks.append(("axe-core: no serious or critical issue", not grave, grave))
        small = s.get("targets_under_44")
        checks.append(("every interactive target at least 44 px", small == 0, small))
        over = {t: n for t, n in (s.get("taps") or {}).items() if n > (s.get("taps_max") or {}).get(t, n)}
        checks.append(("core tasks within the novice review's taps", not over, over or s.get("taps")))
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, IndexError, KeyError) as exc:
        checks.append(("walk ran", False, str(exc)[:200]))
    st = _one("walk (5 roles x 3 languages x desktop and phone)", checks, time.perf_counter() - t0)[0]
    st["summary"] = summary
    st["shot"] = "walk/"
    st["shot_ok"] = any(shots.glob("*.png"))
    return st


def _drill(a: argparse.Namespace, title: str, module: str) -> dict[str, Any]:
    import importlib

    base = a.dir / a.part
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    out = importlib.import_module(module).run(base)
    return {"stages": _one(title, [tuple(c) for c in out["checks"]], out["seconds"]), "seconds": out["seconds"]}


def part_scale(a: argparse.Namespace) -> dict[str, Any]:
    from tools import hospital_sim

    base = a.dir / "scale"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    hospital_sim.RESULTS = base / "results"  # never the committed eval/hospital_sim/results
    t0 = time.perf_counter()
    row = hospital_sim.scale([a.patients], ["GZQO"], base)[0]
    checks: list[tuple[str, bool, Any]] = [
        ("cascade S0..S5, DL-1 pack and recall certificate: every check", row["passed"], row["failed_checks"]),
        ("funnel never grows", all(v["in"] >= v["out"] for v in row["funnel"].values()), row["funnel"]),
    ]
    keep = ("patients", "generate_s", "pipeline_s", "ms_per_patient", "peak_rss_mb", "model_calls", "final_list")
    return {
        "stages": _one(f"cascade at {a.patients} patients (hospital_sim scale)", checks, time.perf_counter() - t0),
        "scale": {k: row[k] for k in keep},
    }


def part_embed(a: argparse.Namespace) -> dict[str, Any]:
    """Embedding comparison (``tools.bench_embed``): bge-m3 and Qwen3-Embedding-0.6B on the ja and zh-TW notes of a
    synthetic hospital: throughput, GPU memory, retrieval quality on the labelled set, halfvec size at 1024 dims."""
    from tools import bench_embed

    work = a.dir / "bench-embed"
    shutil.rmtree(work, ignore_errors=True)
    t0 = time.perf_counter()
    synth = _bench_synth(work, bench_embed.SYNTH_SITES)
    labelled = bench_embed.build_set(synth)
    (work / "set.json").write_text(json.dumps(labelled, ensure_ascii=False), encoding="utf-8")
    out = work / "result.json"
    runner = shlex.split(os.environ.get("TB_BENCH_EMBED_CMD", "")) or [sys.executable]
    cmd = [*runner, "-m", "tools.bench_embed", "run", "--set", str(work / "set.json"), "--out", str(out),
           "--backend", "hf" if a.model == "pair" else "hash"]  # fmt: skip
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=3 * 3600, check=False)
    res = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"models": []}
    checks: list[tuple[str, bool, Any]] = [("the bench ran", r.returncode == 0 and out.exists(), r.stderr[-300:])]
    n_q = labelled["counts"]["queries"]
    checks.append(("labelled set: at least 20 queries per language", all(v >= 20 for v in n_q.values()), n_q))
    for m in res.get("models") or []:
        checks.append((f"{m['name']}: {m['dims']} dims, every doc embedded", m["dims"] == bench_embed.DIMS and
                       m["throughput"]["docs"] == labelled["counts"]["docs_total"], m.get("error", "")))  # fmt: skip
    want = {"bge-m3", "qwen3-embedding-0.6b"} if a.model == "pair" else {"hash-stub"}
    checks.append(("every model compared", {m["name"] for m in res.get("models") or []} >= want, sorted(want)))
    return {"stages": _one("embedding comparison (tools.bench_embed)", checks, time.perf_counter() - t0),
            "embed": bench_embed.summary(res)}  # fmt: skip


def part_profile(a: argparse.Namespace) -> dict[str, Any]:
    """Profile cost stand-in (``tools.bench_profile``): the judge writes a cited summary per synthetic patient from
    that patient's facts; tokens in and out, seconds per patient, GPU-hours per 1,000, the extrapolations."""
    from tools import bench_profile

    work = a.dir / "bench-profile"
    shutil.rmtree(work, ignore_errors=True)
    t0 = time.perf_counter()
    synth = _bench_synth(work, bench_profile.SYNTH_SITES)
    call = bench_profile.make_call(a, work)
    res = bench_profile.run(synth, call, a.profile_patients, a.profile_workers, nightly=a.patients)
    (work / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    m = res["measured"]
    checks: list[tuple[str, bool, Any]] = [
        ("every sampled patient got a summary", m["answered"] == m["patients"], res.get("errors", [])[:3]),
        ("every sentence cites only that patient's facts", m["citations_valid"] == 1.0, m["citations_valid"]),
        ("tokens in and out counted", m["tokens_in"]["mean"] > 0 and m["tokens_out"]["mean"] > 0, m["tokens_out"]),
    ]
    findings: list[dict[str, Any]] = []
    if a.model == "pair" and not a.direct:
        # the bench measures the gateway path; a fallback to direct calls still measures the cost, but the installed
        # box's chain did not answer: that is a failed check and a finding, never a green row (review M-03/M-06)
        via_gateway = res["path"].startswith("gateway")
        checks.append(("the installed box's gateway answered (no fallback to direct calls)", via_gateway,
                       res.get("gateway_refused") or res["path"]))  # fmt: skip
        if not via_gateway:
            findings.append({"id": "PROFILE-GW", "what": "the profile bench fell back to direct calls",
                             "expected": "every call through the gateway", "got": res["path"],
                             "holds": False})  # fmt: skip
    return {"stages": _one(f"profile cost stand-in (tools.bench_profile, {res['path'][:40]})", checks,
                           time.perf_counter() - t0),
            "profile": bench_profile.summary(res), "findings": findings}  # fmt: skip


def part_selftest(a: argparse.Namespace) -> dict[str, Any]:
    """The rehearsal's silent part (``tests/rehearsal``; never in a plan unless ``--only`` names it): no output for
    ``TB_SELFTEST_SECONDS`` (default 300). ``selftest-busy`` works on the CPU the whole time, as a 50,000-patient
    SCREEN does between its log lines: the in-run heartbeat must keep the VM alive. ``selftest-hang`` sleeps, as a
    stuck part does: the VM's watchdog must power it off (review H-03)."""
    seconds = float(os.environ.get("TB_SELFTEST_SECONDS", "300"))
    t0 = time.perf_counter()
    n = 0
    while time.perf_counter() - t0 < seconds:
        if a.scenario == "hang":
            time.sleep(min(5.0, seconds))
        else:
            n += sum(i * i for i in range(20_000))
    took = time.perf_counter() - t0
    return {"stages": _one(f"selftest-{a.scenario}: silent for {seconds:.0f} s",
                           [("silent part ran to its end", took >= seconds, round(took, 1))], took)}  # fmt: skip


def _chat_template(a: argparse.Namespace) -> dict[str, Any]:
    """Review test G-1 (``tools.chat_template_check``): the passed chat template against the weights folder's own."""
    from tools import chat_template_check

    return chat_template_check.run(a)


def _bench_synth(work: Path, sites: str) -> Path:
    """A synthetic hospital of its own for a bench (fictional patients only), made once per work folder."""
    from tools import feas_demo as fd
    from tools.synth_hospital import run as synth_run

    out = work / "synth"
    if not (out / "summary.json").exists():
        synth_run(out, profile="ci", sites=sites, ref_date=fd.REF)
    return out


PARTS = {
    "prepare": part_prepare,
    "install": part_install,
    "hospital": part_hospital,
    "public": part_public,
    "walk": part_walk,
    "backup": lambda a: _drill(a, "backup, wipe and restore (tools.backup_drill)", "tools.backup_drill"),
    "update": lambda a: _drill(a, "signed update, two rollbacks (tools.update_drill)", "tools.update_drill"),
    "scale": part_scale,
    "scenario": part_scenario,
    "embed": part_embed,
    "profile": part_profile,
    "selftest": part_selftest,
    "chat-template": _chat_template,
}
NO_CONSOLE = ("prepare", "install", "backup", "update", "scale", "embed", "profile", "selftest", "chat-template")
# on the card; walk, backup, update, scale: stub
MODEL_PARTS = ("hospital", "public", "scenario", "embed", "profile", "chat-template")
G1_CHECK = "chat-template"  # review test G-1 (tools.chat_template_check): in a run only when --only names it
BENCH_PARTS = ("embed", "profile")  # in a run only when --only names them (not part of the complete run, G1)
STUB_PARTS = ("walk", "backup", "update", "scale")  # run on the driver after the VM has stopped
SELFTESTS = ("busy", "hang")  # the rehearsal's silent parts (selftest-busy, selftest-hang): only when --only names them


def _tag(part: str, lang: str = "", scenario: str = "") -> str:
    if part == "scenario":
        return f"scenario-{scenario}"
    if part == "selftest":
        return f"selftest-{scenario}"
    if part == "hospital" and scenario:  # a repeat at its own concurrency (G-3): hospital-ja@c4
        return f"hospital-{lang}@{scenario}"
    return part + (f"-{lang}" if part in ("hospital", "public") and lang else "")


def base_tag(tag: str) -> str:
    """``hospital-ja@c4`` -> ``hospital-ja``: the part a repeat at its own concurrency belongs to."""
    return tag.split("@", 1)[0]


# ---------------------------------------------------------------- model calls in flight (review G-3, D-142)
MAX_CONCURRENCY = 64  # screen_cascade.llm_concurrency's own ceiling


def parse_concurrency(text: str | None) -> tuple[int, ...]:
    """``--llm-concurrency``: ``"16"`` or ``"1,4,16,48"`` (commas or spaces) as whole numbers from 1 to 64, each once,
    in the order given. Empty: none given. Anything else raises ``ValueError``."""
    out: list[int] = []
    for x in (text or "").replace(",", " ").split():
        if not x.isdigit() or not 1 <= int(x) <= MAX_CONCURRENCY:
            raise ValueError(f"--llm-concurrency: whole numbers from 1 to {MAX_CONCURRENCY}, not {x!r}")
        if int(x) not in out:
            out.append(int(x))
    return tuple(out)


def record_max_seqs(record: Path | None = None) -> int:
    """The judge's ``max_num_seqs`` in the serving record of this run (``--live-record``), else in the vendor's
    measured record: what compose gives SCREEN as ``TB_SCREEN_LLM_CONCURRENCY`` on an installed box (D-142), and the
    run's default when ``--llm-concurrency`` is not given (review 2026-11-12). 1 when no record says."""
    for path in (record, VENDOR_RECORD):
        try:
            rec = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
        except (OSError, ValueError):
            continue
        n = next((s.get("max_num_seqs") for s in rec.get("servers") or [] if s.get("role") == "judge"), None)
        if isinstance(n, int) and n > 0:
            return min(n, MAX_CONCURRENCY)
    return 1


def concurrency_of(a: argparse.Namespace) -> tuple[int, ...]:
    """The run's concurrency settings, parsed once (``a.lc``); () when none was given or defaulted."""
    if not hasattr(a, "lc"):
        a.lc = parse_concurrency(getattr(a, "llm_concurrency", ""))
    lc: tuple[int, ...] = a.lc
    return lc


# ---------------------------------------------------------------- the data a part needs (review C-02, C-03)
# What is not in git and the part cannot run without; tools/fetch_run_data.py fetches each on the VM. A part whose data
# is missing fails at once with a "data missing" row: it never starts, so it costs no card time (review C-03).
def _data_cql() -> str:
    from criteria_compiler.compile_cql import translator

    try:
        translator.fhirhelpers_source()
    except (FileNotFoundError, OSError, KeyError) as exc:
        return f"the CQL translator's FHIRHelpers (quick-5.4.0.jar in {translator._lib_dir()}): {exc}"
    return ""


def _data_medtxt() -> str:
    from tools import medtxt_eval

    d = medtxt_eval.CACHE / "Test collection"
    return "" if any(d.glob("*/*.xml")) else f"MedTxt (CC BY 4.0) in {d}"


def _data_trec() -> str:
    from tools import trec_ct_eval

    need = ["sample_trials.json", "ctgov_fields.json"]
    need += [f"{k}{y}.{e}" for y in trec_ct_eval.YEARS for k, e in (("topics", "xml"), ("qrels", "txt"))]
    gone = [n for n in need if not (trec_ct_eval.CACHE / n).is_file()]
    return f"TREC CT 2021/2022 (NIST) in {trec_ct_eval.CACHE}: no {', '.join(gone)}" if gone else ""


DATA_CHECKS = {"cql": _data_cql, "medtxt": _data_medtxt, "trec": _data_trec}


def data_needs(tag: str) -> tuple[str, ...]:
    if tag.startswith("hospital-"):
        return ("cql",)
    if tag.startswith("public-"):  # the public console: MedTxt notes, and its FEAS compiles criteria
        return ("medtxt", "cql")
    return {"scenario-public-medtxt": ("medtxt",), "scenario-public-trec": ("trec",)}.get(tag, ())


def data_missing(tag: str) -> list[str]:
    """Why ``tag`` cannot run on this machine (empty: its data is here)."""
    return [why for need in data_needs(tag) if (why := DATA_CHECKS[need]())]


PENDING, STOPPED = "pending", "not run (VM stopped)"  # a part with no result yet (G1 bug A5)


def not_started(tag: str, state: str) -> dict[str, Any]:
    """The row of a part that has no result and is not known to have run: ``pending`` (its VM still runs, or it is
    later in this run) or ``not run (VM stopped)``. It has no check, so it never counts as a failure (G1 bug A5: the
    partial report said FAILED for every part a pre-empted VM never reached)."""
    return {"stages": [{"name": f"{tag}: {state}", "ok": None, "seconds": 0, "checks": []}], "state": state}


def _passed(res: dict[str, Any]) -> bool:
    return all(c[1] for st in res.get("stages") or [] for c in st["checks"]) and bool(res.get("stages"))


def run_part(a: argparse.Namespace) -> int:
    import logging

    logging.disable(logging.INFO)  # the in-process services log every request; the checks are the output
    a.password = os.environ.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    a.shots.mkdir(parents=True, exist_ok=True)
    tag = _tag(a.part, a.lang, getattr(a, "variant", "") if a.part == "hospital" else a.scenario)
    if getattr(a, "llm_concurrency", ""):  # this part's calls in flight (G-3); SCREEN reads it (screen_cascade)
        os.environ["TB_SCREEN_LLM_CONCURRENCY"] = str(int(a.llm_concurrency))
    final = a.dir / "parts" / f"{tag}.json"
    ident = run_identity(a.run_id)
    if a.resume and final.exists():
        old = json.loads(final.read_text(encoding="utf-8"))
        same, why = same_run(old, a.run_id, ident["head"])
        if same and _passed(old):
            print(f"      {tag}: done earlier in this run at this HEAD, kept (--resume)", flush=True)
            return 0
        if not same:
            print(f"      {tag}: a result from another {why} is on disk: not kept, the part runs again", flush=True)
        final.unlink()
    t0 = time.perf_counter()
    res: dict[str, Any]
    from tools import run_metrics

    began = datetime.now().astimezone()
    pair = a.model == "pair" and a.part in MODEL_PARTS
    servers = {"judge": getattr(a, "judge_url", ""), "verifier": getattr(a, "verifier_url", "")} if pair else {}
    monitor = run_metrics.Monitor(a.dir / "parts" / tag, servers, os.environ.get("TB_GPU_KEY", ""))
    if a.part in MODEL_PARTS:
        shutil.rmtree(monitor.folder, ignore_errors=True)  # an earlier attempt's samples are not this result's
        monitor.start()
    missing = data_missing(base_tag(tag))
    if missing:  # fail fast, before any box is built: no card time for a part that cannot run (review C-03)
        res = {"stages": _one(f"{tag}: data missing, not run", [("the part's data is on this machine", False,
                                                                 "; ".join(missing)[:300])], 0),
               "not_run": "data missing"}  # fmt: skip
    else:
        try:
            res = PARTS[a.part](a)
        except Exception as exc:  # one broken part is a failed row in the report, not a lost run
            import traceback

            tb = traceback.format_exc().splitlines()[-3:]
            res = {"stages": _one(f"{tag} crashed", [("part ran", False, f"{exc!r} {' | '.join(tb)}"[:300])], 0),
                   "not_run": "crashed"}  # fmt: skip
    res["run"] = ident
    # the calls in flight this part ran with, and what it measured (review G-3: tokens, queue, card, calls per second)
    from orchestrator.scenarios.screen_cascade import llm_concurrency

    res["llm_concurrency"] = llm_concurrency()
    if a.part in MODEL_PARTS:
        res["metrics"] = monitor.stop()
        calls = run_metrics.audit_calls(a.dir / f"gw-audit-{a.part}", began)
        refused = run_metrics.audit_refusals(a.dir / f"gw-audit-{a.part}", began)
        if calls:
            res["throughput"] = run_metrics.call_stats(calls)
        if calls or refused:  # M2: "N of M calls refused" (the PHI tripwire, the guard, ...), from the same audit
            res["refusals"] = run_metrics.refusal_stats(calls, refused)
    if a.model == "pair":
        from tools import scenarios

        res["run"]["weight_pins"] = scenarios.weight_pins()
        if "throughput" in res:
            res["throughput"]["breaker_opens"] = scenarios.breaker_opens()
    res["wall_seconds"] = round(time.perf_counter() - t0, 1)
    if a.part in NO_CONSOLE:
        url = table_page(a.shots / f"{tag}.html", f"TrialBox complete run: {tag}", res["stages"])
        got = shoot([{"name": tag, "url": url}], a.shots, a.password)
        for st in res["stages"]:
            st["shot"] = f"{tag}.png"
        _attach_shots(res["stages"], {tag: got[tag]})
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(".json.part")  # write, then rename: a killed part never leaves half a result
    tmp.write_text(json.dumps(res, default=str, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(final)
    return 0 if _passed(res) else 1


# ---------------------------------------------------------------- the run and its report
def plan(a: argparse.Namespace) -> list[tuple[str, str, str]]:
    """``(part, lang, scenario)`` in run order: the model parts first (the card is paid by the hour), then the
    parts that run on the stub after the VM has stopped."""
    from tools import scenarios

    out = [("prepare", "", ""), ("install", "", "")]
    out += [(G1_CHECK, "", "")] if G1_CHECK in (a.only or []) else []  # G-1 before the parts that depend on it
    # several --llm-concurrency values: the hospital part once per value, as hospital-<lang>@c<N> (G-3's curve);
    # each repeat reads the same prepared hospital
    lc = concurrency_of(a)
    variants = [f"c{n}" for n in lc] if len(lc) > 1 else [""]
    out += [("hospital", lang, v) for lang in a.langs for v in variants]
    out += [("public", lang, "") for lang in a.langs]
    out += [("scenario", a.langs[0], sc) for sc in (a.scenarios or scenarios.SCENARIOS)]
    out += [("walk", "", ""), ("backup", "", ""), ("update", "", ""), ("scale", "", "")]
    out += [(b, "", "") for b in BENCH_PARTS if b in (a.only or [])]
    out += [("selftest", "", s) for s in SELFTESTS if f"selftest-{s}" in (a.only or [])]
    keep = [p for p in out if p[0] not in a.skip]
    if a.only:
        keep = [p for p in keep if p[0] in a.only or _tag(*p) in a.only or base_tag(_tag(*p)) in a.only]
    return keep


def _cmd(a: argparse.Namespace, part: str, lang: str, scenario: str, shots: Path) -> list[str]:
    cmd = [sys.executable, "-m", "tools.complete_run", "part", part, "--dir", str(a.dir), "--shots", str(shots),
           "--patients", str(a.patients), "--model", a.model, "--ocr", a.ocr, "--run-id", a.run_id]  # fmt: skip
    if lang:
        cmd += ["--lang", lang]
    lc = concurrency_of(a)
    if part == "hospital" and scenario:  # a repeat at its own concurrency: the variant c<N>
        cmd += ["--variant", scenario, "--llm-concurrency", scenario.removeprefix("c")]
    else:
        cmd += ["--scenario", scenario] if scenario else []
        cmd += ["--llm-concurrency", str(lc[0])] if lc else []
    if a.model == "pair":
        cmd += ["--judge-url", a.judge_url, "--verifier-url", a.verifier_url]
    if a.direct:
        cmd.append("--direct")
    if a.live_record:
        cmd += ["--live-record", str(a.live_record)]
    if a.resume:
        cmd.append("--resume")
    if a.keep_work:
        cmd.append("--keep-work")
    if part == "profile":
        cmd += ["--profile-patients", str(a.profile_patients), "--profile-workers", str(a.profile_workers)]
    return cmd


def _tree_cpu(pid: int) -> float | None:
    """CPU seconds used so far by ``pid`` and every process below it (Linux ``/proc``; None elsewhere)."""
    proc = Path("/proc")
    if not (proc / str(pid)).exists():
        return None
    kids: dict[int, list[int]] = {}
    ticks: dict[int, int] = {}
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            f = (d / "stat").read_text().rsplit(")", 1)[1].split()
        except OSError:
            continue
        kids.setdefault(int(f[1]), []).append(int(d.name))  # f[1] = ppid
        ticks[int(d.name)] = int(f[11]) + int(f[12])  # utime + stime
    total, todo = 0, [pid]
    while todo:
        p = todo.pop()
        total += ticks.get(p, 0)
        todo += kids.get(p, [])
    return total / (os.sysconf("SC_CLK_TCK") or 100)


class Heartbeat:
    """The in-run heartbeat (review H-03): while a part runs, touch ``path`` every ``every`` seconds in which the
    part's processes used CPU. A 50,000-patient SCREEN is silent in the log for hours but always busy, so the VM's
    idle watchdog no longer depends on the driver being alive; a part that is stuck (no CPU at all) stops touching it
    and the watchdog powers the VM off after its idle limit, as before."""

    def __init__(self, path: str, pid: int, every: float = 30.0) -> None:
        self.path, self.pid, self.every = Path(path), pid, every
        self.stop = threading.Event()
        self.beats = 0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        # no /proc: keep the old behaviour (alive while running). With /proc, None means the part has ended (and
        # been reaped): no beat, so a beat between its end and close() cannot make a stopped part look busy
        no_proc = not Path("/proc").is_dir()
        last = _tree_cpu(self.pid)
        while not self.stop.wait(self.every):
            now = _tree_cpu(self.pid)
            if no_proc or (now is not None and last is not None and now > last):
                self.path.touch()
                self.beats += 1
            last = now

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=5)


def _run_part_process(a: argparse.Namespace, cmd: list[str], env: dict[str, str]) -> int:
    p = subprocess.Popen(cmd, cwd=ROOT, env=env)
    hb = Heartbeat(a.heartbeat, p.pid, a.heartbeat_seconds) if a.heartbeat else None
    try:
        return p.wait()
    finally:
        if hb is not None:
            hb.close()


def drop_stale_parts(parts: Path, run_id: str, head: str, tags: Iterable[str] | None = None) -> list[str]:
    """Remove the part results on disk that another run id or HEAD made (review H-01); returns their tags.

    ``tags``: only these parts are candidates, the ones this invocation is about to run. A result of a part it does
    not run is never touched: the collect's merge runs the stub parts with ``--resume`` over the VMs' finished parts,
    made under ``<run id>-s<N>`` at the archive's HEAD, and removed them (G1 bug A1). Nothing runs: nothing goes."""
    gone = []
    only = None if tags is None else set(tags)
    for f in sorted(parts.glob("*.json")) if parts.is_dir() else []:
        if only is not None and f.stem not in only:
            continue
        try:
            same, _ = same_run(json.loads(f.read_text(encoding="utf-8")), run_id, head)
        except (OSError, ValueError):
            same = False
        if not same:
            f.unlink()
            gone.append(f.stem)
    return gone


def run_all(a: argparse.Namespace) -> int:
    a.dir.mkdir(parents=True, exist_ok=True)
    report_dir = a.dir / "report"
    shots = report_dir / "shots"
    head = git_head()
    todo = plan(a)
    if not a.resume:
        shutil.rmtree(report_dir, ignore_errors=True)
        shutil.rmtree(a.dir / "parts", ignore_errors=True)
    else:  # only the parts this run is about to run (G1 bug A1: the collect's stub resume removed the VM's parts)
        gone = drop_stale_parts(a.dir / "parts", a.run_id, head["head"], [_tag(*p) for p in todo])
        if gone:
            print(f"      --resume: {len(gone)} part result(s) of another run or HEAD removed: {' '.join(gone)}",
                  flush=True)  # fmt: skip
    shots.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TB_ENV=os.environ.get("TB_ENV") or "DEV", PYTHONPATH="libs:services:.")
    env.setdefault("TB_DEMO_PASSWORD", secrets.token_urlsafe(12))  # one random password for every part, never printed
    started = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    lc = concurrency_of(a)
    if lc:
        print(f"      model calls in flight (TB_SCREEN_LLM_CONCURRENCY): {', '.join(map(str, lc))}"
              + (" (default: the serving record's max_num_seqs)" if getattr(a, "lc_default", False) else "")
              + ("; the hospital part runs once per value" if len(lc) > 1 else ""), flush=True)  # fmt: skip
    for i, (part, lang, scenario) in enumerate(todo):
        tag = _tag(part, lang, scenario)
        t = time.perf_counter()
        print(f"[{i + 1}/{len(todo)}] {tag}", flush=True)
        if a.heartbeat:
            Path(a.heartbeat).touch()
        rc = _run_part_process(a, _cmd(a, part, lang, scenario, shots), env)
        f = a.dir / "parts" / f"{tag}.json"
        res: dict[str, Any] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {
            "stages": _one(f"{tag} did not report", [("part ran", False, f"exit {rc}")], 0),
            "not_run": "did not report"}  # fmt: skip
        res.update({"part": part, "lang": lang, "tag": tag, "seconds_total": round(time.perf_counter() - t, 1)})
        rows.append(res)
        bad = sum(1 for st in res["stages"] for c in st["checks"] if not c[1])
        print(f"      {'PASS' if bad == 0 else 'FAIL'} in {res['seconds_total']} s", flush=True)
        # the report so far, then the operator's hook (the VM packs results.tgz: a stop at any moment loses at most
        # the part that was running, review M-10)
        later = [{**not_started(_tag(*p), PENDING), "part": p[0], "lang": p[1], "tag": _tag(*p), "seconds_total": 0}
                 for p in todo[i + 1 :]]  # fmt: skip
        _write_report(a, rows + later, head, started, report_dir)
        if a.after_part:
            subprocess.run(a.after_part, shell=True, cwd=ROOT, check=False)  # the operator's own command
        last_model_part = not any(p in MODEL_PARTS for p, _, _ in todo[i + 1 :])
        if a.after_models and part in MODEL_PARTS and last_model_part:
            # the paid card is no longer needed: the wrapper stops the VM while walk, backup, update and scale run
            print(f"      after the model parts: {a.after_models}", flush=True)
            subprocess.run(a.after_models, shell=True, cwd=ROOT, check=False)  # the operator's own command
    rep = _write_report(a, rows, head, started, report_dir)
    verdict = rep["verdict"]
    print(f"complete run {verdict}: {rep['checks'] - rep['failed']}/{rep['checks']} checks, "
          f"{rep['shots_ok']}/{rep['shots']} screenshots, {len(rep['findings'])} known findings, {rep['seconds']} s; "
          f"{report_dir / 'report.md'}")  # fmt: skip
    return 0 if rep["ok"] else 1


def _write_report(a: argparse.Namespace, rows: list[dict[str, Any]], head: dict[str, Any], started: datetime,
                  out: Path) -> dict[str, Any]:  # fmt: skip
    rep = report(a, rows, head, started)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, default=str, ensure_ascii=False, indent=1), "utf-8")
    (out / "report.md").write_text(markdown(rep), encoding="utf-8")
    return rep


def report_only(a: argparse.Namespace) -> int:
    """The report of a run whose parts ran elsewhere (the model parts on the VM, the stub parts here): every part of
    the plan from its ``parts/<tag>.json``; a missing one is a failed row."""
    # --report-parts: the report of a run of some parts only (a bench run, D-148); else the whole plan
    a.only, a.direct = getattr(a, "report_parts", None) or [], getattr(a, "direct", False)
    pending = set(getattr(a, "pending_parts", None) or [])  # the parts of VMs that still run (the driver says)
    rows = []
    for part, lang, scenario in plan(a):
        tag = _tag(part, lang, scenario)
        f = a.dir / "parts" / f"{tag}.json"
        # no result: pending while its VM runs, else not run (VM stopped); never a failed check (G1 bug A5)
        res: dict[str, Any] = (
            json.loads(f.read_text(encoding="utf-8"))
            if f.exists()
            else not_started(tag, PENDING if tag in pending else STOPPED)
        )
        res.update({"part": part, "lang": lang, "tag": tag, "seconds_total": res.get("wall_seconds", 0)})
        rows.append(res)
    rep = report(a, rows, made_by(rows) or git_head(), datetime.now(UTC))
    out = a.dir / "report"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, default=str, ensure_ascii=False, indent=1), "utf-8")
    (out / "report.md").write_text(markdown(rep), encoding="utf-8")
    print(f"report {rep['verdict']}: {rep['checks'] - rep['failed']}/{rep['checks']} checks; "
          f"{out / 'report.md'}")  # fmt: skip
    return 0 if rep["ok"] else 1


def made_by(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The commit the parts ran from, as their results record it (the VM's, not the driver's at collect time:
    review M-02). Model parts first; several commits are named, never hidden."""
    runs = [r["run"] for r in sorted(rows, key=lambda r: r.get("part") not in MODEL_PARTS) if r.get("run")]
    heads = list(dict.fromkeys(x.get("head", "") for x in runs if x.get("head")))
    if not heads:
        return {}
    first = next(x for x in runs if x.get("head") == heads[0])
    return {"head": heads[0], "subject": first.get("subject", ""), "dirty": bool(first.get("dirty")),
            "source": "parts", "heads": heads}  # fmt: skip


def planned_checks(path: Path | None) -> dict[str, int]:
    """Checks per part tag in a reference report (``--planned-from``: a full local run's report.json)."""
    if path is None or not path.exists():
        return {}
    rep = json.loads(path.read_text(encoding="utf-8"))
    rows = [r for r in rep.get("parts") or [] if not r.get("not_run")]
    return {r["tag"]: sum(len(st["checks"]) for st in r["stages"]) for r in rows}


def report(
    a: argparse.Namespace, rows: list[dict[str, Any]], head: dict[str, Any], started: datetime
) -> dict[str, Any]:
    # the host and the weight pins of the machine the model parts ran on (the VM), else this one (review M-02, M-09)
    runs = [r["run"] for r in sorted(rows, key=lambda r: r.get("part") not in MODEL_PARTS) if r.get("run")]
    host = (runs[0].get("host") if runs else None) or host_facts()
    pins = next((x["weight_pins"] for x in runs if x.get("weight_pins")), "")
    path = ("direct" if a.direct else "gateway (installed box)") if a.model == "pair" else "stub in process"
    if a.model == "pair" and not a.direct and pins == "synthetic":
        path = "gateway (installed box, synthetic weight pins)"
    rep: dict[str, Any] = {
        "schema": "tb-complete-run/3",
        "git": head,
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": a.model,
        "models": [JUDGE, VERIFIER] if a.model == "pair" else ["stub"],
        "path": path,
        "ocr": a.ocr,
        "patients": a.patients,
        "langs": list(a.langs),
        "host": host,
        "run_ids": sorted({str(x.get("id")) for x in runs if x.get("id")}),
        "parts": rows,
    }
    from tools import run_metrics

    # G-3: the calls in flight each part ran with, what it measured, and whether the lists agree across the settings
    rep["llm_concurrency"] = sorted({int(r["llm_concurrency"]) for r in rows
                                     if r.get("llm_concurrency") and r.get("part") in MODEL_PARTS})  # fmt: skip
    rep["throughput"] = run_metrics.curve(rows)
    rep["candidates_compare"] = run_metrics.lists_compare(rows)
    rep["candidates_identical"] = {lang: v["identical"] for lang, v in rep["candidates_compare"].items()}
    # A8: the door's secret after the collect (complete-run.sh writes door-secret.txt): none enabled, or what remains
    door = Path(a.dir) / DOOR_STATE if getattr(a, "dir", None) else None
    if door is not None and door.is_file():
        rep["door_secret"] = door.read_text(encoding="utf-8").strip()
    rep["checks"] = sum(len(st["checks"]) for r in rows for st in r["stages"])
    rep["failed"] = sum(1 for r in rows for st in r["stages"] for c in st["checks"] if not c[1])
    # a part that crashed, did not report or had no data counts one failed check; its own checks never ran (review
    # M-03): named in the headline, with their number when a reference run gives it
    ref = planned_checks(getattr(a, "planned_from", None))
    rep["not_run"] = [{"tag": r["tag"], "why": r["not_run"], "planned_checks": ref.get(r["tag"])}
                      for r in rows if r.get("not_run")]  # fmt: skip
    known = [x["planned_checks"] for x in rep["not_run"] if x["planned_checks"]]
    rep["checks_never_ran"] = sum(known) if rep["not_run"] and len(known) == len(rep["not_run"]) else None
    rep["shots"] = sum(1 for r in rows for st in r["stages"] if st.get("shot"))
    rep["shots_ok"] = sum(1 for r in rows for st in r["stages"] if st.get("shot_ok"))
    rep["findings"] = [{**f, "part": r["tag"]} for r in rows for f in r.get("findings") or []]
    # parts with no result that are not known to have run: pending, or not run (VM stopped); no check (G1 bug A5)
    rep["not_started"] = [{"tag": r["tag"], "state": r["state"]} for r in rows if r.get("state")]
    # FAILED only when a part that ran failed a check (or lost a screenshot); INCOMPLETE while parts are missing
    if rep["failed"] or rep["shots_ok"] != rep["shots"]:
        rep["verdict"] = "FAILED"
    else:
        rep["verdict"] = "INCOMPLETE" if rep["not_started"] else "PASSED"
    rep["ok"] = rep["verdict"] == "PASSED"
    rep["seconds"] = round(sum(r["seconds_total"] for r in rows), 1)
    return rep


def _scenario_sections(rep: dict[str, Any]) -> list[str]:
    """One section per scenario: input, counts, expected and got, model calls and exclusions, time, screenshot."""
    from tools import scenarios

    out: list[str] = ["", "## Scenarios", ""]
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    db = [r for r in rep["parts"] if r["part"] == "hospital"]
    if db:
        groups.append(("db-csv", db))
    groups += [(r["tag"].removeprefix("scenario-"), [r]) for r in rep["parts"] if r["part"] == "scenario"]
    for name, rs in groups:
        bad = [c for r in rs for st in r["stages"] for c in st["checks"] if not c[1]]
        n = sum(len(st["checks"]) for r in rs for st in r["stages"])
        waiting = [f"{r['tag']} {r['state']}" for r in rs if r.get("state")]
        out += [f"### {name}: {scenarios.TITLES.get(name, name)}", "",
                f"**{'pass' if not bad else 'FAIL'}**: {n - len(bad)} of {n} checks."
                + (f" No result yet: {', '.join(waiting)}." if waiting else "")]  # fmt: skip
        for r in rs:
            b = r.get("scenario") or {}
            lab = f" ({r['tag'].removeprefix('hospital-')})" if name == "db-csv" else ""
            out += [
                "",
                f"* Input{lab}: {b.get('input', '-')}",
                f"* Counts: `{json.dumps(b.get('counts', {}), ensure_ascii=False, default=str)[:600]}`",
                f"* Expected: `{json.dumps(b.get('expected', {}), ensure_ascii=False, default=str)[:400]}`",
                f"* Got: `{json.dumps(b.get('got', {}), ensure_ascii=False, default=str)[:400]}`",
                f"* Model calls: {b.get('model_calls', 0)}",
            ]
            if b.get("model_exclusions"):
                x = b["model_exclusions"]
                out.append(f"* Model exclusions: {x['excluded_by_models']} (true {x['true']}, false {x['false']}, "
                           f"true ones missed {x['missed_true']})")  # fmt: skip
                out += [f"  * `{p['pid']}` {', '.join(p['criteria'])}: truth {p['truth']}, "
                        f"{'correct' if p['correct'] else 'WRONG'}" for p in x["patients"][:20]]  # fmt: skip
            if b.get("extraction"):
                e = b["extraction"]
                out.append(f"* Extraction: precision {e['precision']}, recall {e['recall']} ({e['matched']} of "
                           f"{e['truth']} true facts, {e['proposed']} proposed; OCR {b.get('ocr', '-')})")  # fmt: skip
            if b.get("screen"):
                out.append(f"* Screening: `{json.dumps(b['screen'], ensure_ascii=False, default=str)[:400]}`")
            if b.get("note"):
                out.append(f"* Note: {b['note']}")
            shots = sorted({st["shot"] + ("" if st.get("shot_ok") else " (missing)") for st in r["stages"]
                            if st.get("shot")})  # fmt: skip
            out.append(f"* Time: {r['seconds_total']} s. Screenshot: {', '.join(f'`{x}`' for x in shots[:3]) or '-'}")
        out += [f"* FAILED: {c[0]}: {str(c[2])[:200]}" for c in bad]
        out.append("")
    if rep["findings"]:
        out += ["## Known findings (reported, not fixed in this run)", ""]
        out += ["| id | part | what | expected | got | holds |", "| --- | --- | --- | --- | --- | --- |"]
        for f in rep["findings"]:
            got = " ".join(str(f["got"]).split())[:200]
            out.append(
                f"| {f['id']} | {f['part']} | {f['what']} | {f['expected']} | {got} | {'yes' if f['holds'] else 'NO'} |"
            )
    return out


def _throughput_section(rep: dict[str, Any]) -> list[str]:
    """Review G-3: per part, the calls in flight, calls and tokens per second, call times, the card, the list."""
    from tools import run_metrics

    rows = rep.get("throughput") or []
    if not rows:
        return []

    def cell(v: Any) -> str:
        if isinstance(v, dict):
            return ", ".join(f"{k} {x}" for k, x in v.items()) or "-"
        return "-" if v is None else str(v)

    keys = ("tag", "llm_concurrency", "calls", "calls_per_second", "tokens_per_second", "p50_s", "p95_s",
            "queue_mean_s", "gpu_util_mean_pct", "gpu_memory_peak_mib", "breaker_opens", "candidates")  # fmt: skip
    out = ["", "## Throughput (model calls through the gateway)", "",
           "Calls and tokens per second are over the seconds in which a call was in flight (the gateway's audit); the "
           "servers' `/metrics` before and after, `gpu.csv` (every 10 s) and `vllm.csv` are in `parts/<part>/`.", "",
           "| part | in flight | calls | calls/s | tokens/s | p50 s | p95 s | queue s (vLLM) | GPU % mean | "
           "GPU MiB peak | breaker opened | listed | list sha256 | refused (of asked) |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    out += ["| " + " | ".join(cell(r.get(k)) for k in keys) + f" | `{str(r.get('candidates_sha256') or '-')[:12]}` | "
            f"{run_metrics.refused_cell(r.get('refused'))} |" for r in rows]  # fmt: skip
    old = rep.get("candidates_identical") or {}
    cmp = rep.get("candidates_compare") or {lang: {"identical": v, "differ": [], "why": ""} for lang, v in old.items()}
    for lang, c in cmp.items():
        if c["identical"] is None:
            verdict = f"**not compared**: {c['why']}."
        elif c["identical"]:
            verdict = "**identical**."
        else:
            verdict = (f"**DIFFERENT** (the list must not depend on the calls in flight): {len(c['differ'])} "
                       "patient(s) not listed alike (pseudonymous ids; `-`: not listed at that setting).")  # fmt: skip
        out += ["", f"Candidate lists of hospital-{lang} at every setting: {verdict}"]
        if c.get("differ"):
            tags = c.get("settings") or list(c["differ"][0]["tiers"])
            out += ["", "| pid | " + " | ".join(tags) + " |", "| --- |" + " --- |" * len(tags)]
            out += [f"| `{d['pid']}` | " + " | ".join(d["tiers"].get(t, "-") for t in tags) + " |"
                    for d in c["differ"][:50]]  # fmt: skip
    return out


def markdown(rep: dict[str, Any]) -> str:
    g = rep["git"]
    heads = g.get("heads") or []
    mixed = f" (parts from {len(heads)} commits: {', '.join(h[:12] for h in heads)})" if len(heads) > 1 else ""
    not_run = rep.get("not_run") or []
    never = ""
    if not_run:
        n = rep.get("checks_never_ran")
        never = (f" **{len(not_run)} part(s) crashed or never ran** ({', '.join(x['tag'] for x in not_run)}): "
                 + (f"{n} of their checks never ran" if n else "their own checks never ran (number unknown)")
                 + "; each counts as one failed check above.")  # fmt: skip
    waiting = rep.get("not_started") or []
    if waiting:
        by: dict[str, list[str]] = {}
        for x in waiting:
            by.setdefault(x["state"], []).append(x["tag"])
        never += (f" **{len(waiting)} part(s) have no result yet**, not counted as checks: "
                  + "; ".join(f"{state}: {', '.join(tags)}" for state, tags in by.items()) + ".")  # fmt: skip
    lines = [
        "# TrialBox complete-platform run",
        "",
        f"Head `{g['head'][:12]}` ({g['subject'] or g.get('source', '')}){' with local changes' if g['dirty'] else ''}"
        f"{mixed}. Run: {', '.join(rep.get('run_ids') or []) or '-'}. "
        f"Model: {', '.join(rep['models'])} ({rep.get('path', '')}). Hospital: {rep['patients']:,} synthetic patients. "
        f"Languages: {', '.join(rep['langs'])}. OCR: {rep.get('ocr', '-')}. "
        f"Model calls in flight: {', '.join(map(str, rep.get('llm_concurrency') or [])) or '-'}. "
        f"Host: {rep['host'].get('machine')}, {rep['host'].get('cpus')} CPUs.",
        f"Started {rep['started']}, finished {rep['finished']}.",
        "",
        f"**{rep.get('verdict') or ('PASSED' if rep['ok'] else 'FAILED')}**: {rep['checks'] - rep['failed']} of "
        f"{rep['checks']} checks; "
        f"{rep['shots_ok']} of {rep['shots']} screenshots; {rep['seconds'] / 60:.1f} min in all; "
        f"{len(rep.get('findings') or [])} known findings reported.{never}",
        "",
        "Screenshots are in the run's `report/shots/` folder (not committed).",
        "",
        *([f"Door secret after the collect (T-119): {rep['door_secret']}", ""] if rep.get("door_secret") else []),
        "| part | stage | checks | result | seconds | screenshot |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rep["parts"]:
        for st in r["stages"]:
            n = len(st["checks"])
            bad = [c[0] for c in st["checks"] if not c[1]]
            shot = f"`{st['shot']}`" + ("" if st.get("shot_ok") else " (missing)") if st.get("shot") else ""
            result = r.get("state") or ("pass" if not bad else "FAIL")
            lines.append(f"| {r['tag']} | {st['name']} | {n - len(bad)}/{n} | {result} | {st['seconds']} | {shot} |")
    lines += _scenario_sections(rep)
    lines += _throughput_section(rep)
    lines += ["", "## Part times", "", "| part | wall seconds |", "| --- | --- |"]
    lines += [f"| {r['tag']} | {r['seconds_total']} |" for r in rep["parts"]]
    fails = [(r["tag"], st["name"], c) for r in rep["parts"] for st in r["stages"] for c in st["checks"] if not c[1]]
    if fails:
        lines += ["", "## Failed checks", ""]
        lines += [f"- {t} / {s}: {c[0]}: {str(c[2])[:200]}" for t, s, c in fails]
    for r in rep["parts"]:
        for key in ("screen", "canary", "walk", "scale", "embed", "profile", "chat_template"):
            if r.get(key):
                lines += ["", f"## {r['tag']}: {key}", "", "```json", json.dumps(r[key], default=str)[:1500], "```"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the estimate
PRICE_PER_HOUR = 2.74  # g4-standard-48 spot with the RTX PRO 6000 (RUNBOOK §11)
# D-468 (G1 bug A3): a VM whose shard holds a hospital part runs on demand: a 5 h part cannot resume inside itself, and
# a pre-emption loses it whole. The owner's figure: on demand is about 3x the spot price (confirm on the billing page
# before a launch; the estimate and the cap's US$ use this number).
ON_DEMAND_PRICE_PER_HOUR = round(3 * PRICE_PER_HOUR, 2)


def provisioning(tags: list[str] | tuple[str, ...]) -> str:
    """The VM's Compute Engine provisioning model for these parts (D-468): STANDARD (on demand, never pre-empted)
    when a hospital part is among them, else SPOT. ``TB_PROVISIONING=SPOT|STANDARD`` overrides it for every VM: the
    owner's choice of price against the risk of a pre-emption inside a 5 h hospital part (setting, OD-10)."""
    forced = os.environ.get("TB_PROVISIONING", "").strip().upper()
    if forced:
        if forced not in ("SPOT", "STANDARD"):
            raise ValueError(f"TB_PROVISIONING must be SPOT or STANDARD, not {forced!r}")
        return forced
    return "STANDARD" if any(t.startswith("hospital-") for t in tags) else "SPOT"


def price_per_hour(model: str) -> float:
    return ON_DEMAND_PRICE_PER_HOUR if model == "STANDARD" else PRICE_PER_HOUR


def cap_hours(rows: list[dict[str, Any]], hours: float) -> int:
    """The hard cap of one VM that runs ``rows`` (``hours`` estimated): the estimate x 1.3 rounded up, and never below
    the same rows with no gain from the calls in flight (``floor_seconds``; speedup 1): the measured curve shortens the
    estimate, never the cap below what the run would take if the gain were not there."""
    floor = sum(float(r.get("floor_seconds", r["seconds"])) for r in rows) / 3600
    return math.ceil(max(hours * 1.3, floor))


def _priced(e: dict[str, Any], rows: list[dict[str, Any]], hours: float) -> dict[str, Any]:
    """Hours, cap and US$ of one VM that runs ``rows``: spot, or on demand when a hospital part is among them."""

    model = provisioning([t for r in rows for t in r["tags"]])
    price = price_per_hour(model)
    for r in rows:
        r["usd"] = round(r["hours"] * price, 2)
    cap = cap_hours(rows, hours)
    return {**e, "rows": rows, "hours": round(hours, 2), "usd": round(hours * price, 2), "cap_hours": cap,
            "cap_usd": round(cap * price, 2), "provisioning": model, "price_per_hour": price}  # fmt: skip


SETUP_HOURS = 0.25  # apt (PostgreSQL, tesseract jpn/chi_tra/eng, node), the venv, Playwright's Chromium, fonts
BOOT_HOURS = 0.25  # VM start, both models resident (PRO6000-RUN-READY in about 15 minutes, D-139)
CANARY_SECONDS = 300.0  # the pair canary (D-117, 54 cases) at the start of every box that has the pair
S3_SHARE = 92 / 5000  # GZQO patients reaching the note stage S3 (5,000-patient hospital, D-139; GOUT-COH: none)
PUBLIC_SECONDS = 1303.0  # public_e2e with the pair on the PRO 6000, 2026-11-08 (VALIDATION §3)
SECONDS_PER_CHECK = 0.3  # one criterion check by one model (2,030 checks in about 10 minutes, VALIDATION §3)
SCREEN_PARTS = ("emr-ssmix2", "emr-fhir", "site-excel", "redcap")
# A hospital part (db-csv), measured end to end on the RTX PRO 6000 with the pair (G1, run 20261111T183639Z-986d91c9,
# commit 986d91c): hospital-ja's wall_seconds 17,960 at 50,000 patients, of which the screening stage 8,584 s; the
# rest is prepare's lake at 50,000 and the other 19 stages. Source: docs/plan/measurements/g1-2026-11-11/
# hospital-ja.json (wall_seconds; stage "15 delegation, candidates and referral"). The old estimate counted only the
# screening (2.14 h) and made the hard cap stop an --only run mid-part (G1 bug A4). OD-10: scaled with the patients
# the part reads; a newer measurement replaces these two numbers.
HOSPITAL_PART_SECONDS = 17960.0
HOSPITAL_PART_PATIENTS = 50000
# The same measurement's model time: 6,704 calls in the 8,584 s of the screening stage, one call in flight (G1 ran
# with TB_SCREEN_LLM_CONCURRENCY unset): 0.78 calls per second. With N calls in flight the screening time is the
# calls over that rate times the gain at N (:func:`llm_speedup`); the rest of the part does not change with N.
G1_SCREEN_SECONDS = 8584.0
G1_SCREEN_CALLS = 6704
G1_CALLS_PER_SECOND = G1_SCREEN_CALLS / G1_SCREEN_SECONDS  # 0.78 at N = 1
# OD-10, measured: review test G-3's curve, run 20261112T165042Z-931a0f79 (commit 931a0f7), hospital-ja at 5,000
# patients, judge and verifier on one RTX PRO 6000: calls per second (over the seconds a call was in flight, the
# gateway's audit) at N calls in flight. Source: that run's report.json, "throughput". The estimate takes from it only
# the GAIN, rate(N) / rate(1) (2.60x at 4, 4.44x at 16, 4.87x at 48), and keeps G1's 0.78 calls/s as the rate at 1:
# G1's 0.78 is calls over the screening stage's wall seconds at 50,000 patients, measured in the same run as the part
# time this estimate scales (17,960 s); G-3's 0.40 at 1 is calls over busy seconds at 5,000 patients on another commit,
# a different quantity, so it is not mixed in. A ratio of two rates of one run cancels what differs between the runs.
# Between measured points the gain is interpolated linearly in log2(N) (8 and 32 lie between); above 48 it is held at
# 48's (the curve has flattened: 4.44x at 16, 4.87x at 48), below 1 it is 1. Not yet measured: zh-TW and 50,000
# patients (G-3 runs them next); a newer curve replaces these numbers. TB_ESTIMATE_LLM_SPEEDUP stays as the owner's
# override, with its old meaning: the gain is then min(N, that factor) (1 is the strict bound, no gain at any N).
G3_CALLS_PER_SECOND: dict[int, float] = {1: 0.400, 4: 1.041, 16: 1.774, 48: 1.947}
G3_RUN = "20261112T165042Z-931a0f79"


def measured_gain(n: int) -> float:
    """G-3's measured gain at ``n`` calls in flight: rate(n) / rate(1) of :data:`G3_CALLS_PER_SECOND`, interpolated
    linearly in log2(n) between the measured points, held at the last point above it, 1 at or below 1."""
    pts = sorted(G3_CALLS_PER_SECOND.items())
    base = G3_CALLS_PER_SECOND[1]
    if n <= pts[0][0]:
        return 1.0
    for (n0, r0), (n1, r1) in itertools.pairwise(pts):
        if n <= n1:
            f = (math.log2(n) - math.log2(n0)) / (math.log2(n1) - math.log2(n0))
            return round((r0 + f * (r1 - r0)) / base, 3)
    return round(pts[-1][1] / base, 3)


def speedup_override() -> float | None:
    """``TB_ESTIMATE_LLM_SPEEDUP`` (the owner's override of the measured curve), None when not set."""
    raw = os.environ.get("TB_ESTIMATE_LLM_SPEEDUP", "").strip()
    if not raw:
        return None
    try:
        factor = float(raw)
    except ValueError as exc:
        raise ValueError(f"TB_ESTIMATE_LLM_SPEEDUP must be a number from 1, not {raw!r}") from exc
    if not math.isfinite(factor) or factor < 1:
        raise ValueError(f"TB_ESTIMATE_LLM_SPEEDUP must be a number from 1, not {raw!r}")
    return factor


def llm_speedup(n: int) -> float:
    """What the estimate divides the single-call screening time by at ``n`` calls in flight: G-3's measured gain
    (:func:`measured_gain`), or ``min(n, TB_ESTIMATE_LLM_SPEEDUP)`` when the owner set it; never below 1."""
    factor = speedup_override()
    if factor is not None:
        return max(1.0, min(float(n), factor))
    return max(1.0, measured_gain(n))


def hospital_seconds(patients: int, n: int = 1, gain: bool = True) -> float:
    """A hospital part's wall seconds at ``patients`` with ``n`` model calls in flight: G1's measurement scaled with
    the patients, its screening share (the calls at 0.78 per second) divided by :func:`llm_speedup`. At ``n`` 1 it
    is the measurement itself."""
    scale = patients / HOSPITAL_PART_PATIENTS
    div = llm_speedup(n) if gain else 1.0
    return (HOSPITAL_PART_SECONDS - G1_SCREEN_SECONDS) * scale + G1_SCREEN_SECONDS * scale / div


# the benches (owner's approval of 2026-11-09; no card measurement yet, so set high): the embedding comparison is two
# small models over about 7,000 notes plus the weights' download; the profile stand-in samples ``--profile-patients``
# at 2 s each on the card's batch (16 sequences) plus a sequential latency sample and its synthetic hospital
EMBED_SECONDS = 900.0
PROFILE_FIXED_SECONDS = 400.0
PROFILE_SECONDS_PER_PATIENT = 2.0
# stub wall seconds per part on this laptop at 5,000 patients (the local run of 2026-11-09, D-141): the time a part
# takes besides the model, scaled with the patients it reads; --estimate-from a newer local report replaces them
STUB_SECONDS = {"hospital": 161.0, "emr-ssmix2": 144.0, "emr-fhir": 24.0, "site-excel": 65.0, "chart-paste": 59.0,
                "chart-files": 51.0, "redcap": 21.0, "it-dump": 13.0, "registry": 8.0, "public-mimic": 49.0,
                "public-medtxt": 15.0, "public-trec": 3.0, "gateway": 2.0}  # fmt: skip


def estimate(patients: int, langs: tuple[str, ...] = LANGS, local: dict[str, float] | None = None,
             local_patients: int = 5000, parts: tuple[str, ...] = ("g1",),
             profile_patients: int = 400, llm_concurrency: tuple[int, ...] = (1,)) -> dict[str, Any]:  # fmt: skip
    """Hours on the card per scenario and in all, and US$ at ``PRICE_PER_HOUR``. A hospital part: the G1
    measurement (:data:`HOSPITAL_PART_SECONDS` at :data:`HOSPITAL_PART_PATIENTS`) scaled with ``patients``, never
    below its model time. ``llm_concurrency``: the model calls in flight (:func:`hospital_seconds`; the default 1 is
    what G1 measured); several values: one hospital part per value and language, tagged ``hospital-<lang>@c<N>``
    (review G-3's curve). Model time: note-stage patients
    times the measured 6.3 s per patient on the RTX PRO 6000 (VALIDATION §3; a chart read counts as one), criterion
    checks at 0.3 s each, the canary once per box with the pair. Other time: the part's stub time on the local run,
    scaled with its patients. The walk, backup, update and scale run after the VM has stopped: no card time.
    ``parts``: ``g1`` (the complete run) and the benches ``embed`` and ``profile`` (:data:`EMBED_SECONDS`,
    :data:`PROFILE_SECONDS_PER_PATIENT`).
    Every work row carries the ``tags`` of the parts it times (``--only``), for :func:`shard_plan`."""

    from tools import scenarios

    z, base = scenarios.sizes(patients), scenarios.sizes(local_patients)
    sec = scenarios.SECONDS_PER_NOTE_PATIENT
    stub = {**STUB_SECONDS, **(local or {})}

    def other(part: str, n: int, n0: int) -> float:
        return stub.get(part, 30.0) * max(1.0, n / max(1, n0))

    def row(name: str, n: int, items: float, seconds: float, tags: tuple[str, ...] = ()) -> dict[str, Any]:
        return {"scenario": name, "patients": n, "model_items": round(items), "seconds": seconds, "tags": list(tags)}

    rows = [
        row("VM start, both models resident", 0, 0, BOOT_HOURS * 3600),
        row("VM setup: packages, venv, browser, fonts", 0, 0, SETUP_HOURS * 3600),
    ]
    g1 = "g1" in parts
    lc = tuple(llm_concurrency) or (1,)
    for lang in langs if g1 else ():
        notes = S3_SHARE * patients
        for n in lc:
            # the G1 measurement scaled with the patients (G1 bug A4) and the calls in flight; never below the model
            # time of the old sum at that concurrency, which is most of a small hospital (the canary, the stub time)
            measured = hospital_seconds(patients, n)
            model = notes * sec / llm_speedup(n) + CANARY_SECONDS + other("hospital", patients, local_patients)
            many = len(lc) > 1
            rows.append(row(f"db-csv ({lang}{f', {n} in flight' if many else ''})", patients, notes,
                            max(measured, model), (f"hospital-{lang}" + (f"@c{n}" if many else ""),)))  # fmt: skip
            # the cap's floor: the same part with no gain at all from the calls in flight (the curve is measured at
            # 5,000 ja only; a cap below the part stops it mid-run, G1 bug A4)
            no_gain = notes * sec + CANARY_SECONDS + other("hospital", patients, local_patients)
            rows[-1]["floor_seconds"] = max(hospital_seconds(patients, 1, gain=False), no_gain)
        rows.append(row(f"public ({lang})", 90, 90, PUBLIC_SECONDS, (f"public-{lang}",)))
    for name in scenarios.SCENARIOS if g1 else ():
        t = (f"scenario-{name}",)
        if name in SCREEN_PARTS:
            n = z["site-feed"] if name == "site-excel" else (300 if name == "redcap" else z[name])
            n0 = base["site-feed"] if name == "site-excel" else (300 if name == "redcap" else base[name])
            screens = 2 if name == "site-excel" else 1  # before and after the lists
            items = S3_SHARE * n * screens
            rows.append(row(name, n, items, items * sec + CANARY_SECONDS + other(name, n, n0), t))
        elif name in ("chart-paste", "chart-files", "public-medtxt"):
            charts = z[name] * (1.25 if name != "public-medtxt" else 1)
            rows.append(row(name, z[name], charts, charts * sec + CANARY_SECONDS + other(name, z[name], base[name]), t))
        elif name == "public-trec":
            checks = 2 * z[name] * 19 * 2  # pairs of both labels, about 19 criteria each, two models
            rows.append(row(name, 2 * z[name], checks, checks * SECONDS_PER_CHECK + other(name, 1, 1), t))
        else:  # no model call on the card (the IT dump, the registry, MIMIC on the stub path, the probe)
            items = 2 if name == "gateway" else 0
            rows.append(row(name, z.get(name, 0), items, other(name, z.get(name, 1), base.get(name, 1)), t))
    if "embed" in parts:
        rows.append(row("bench: embeddings (bge-m3, Qwen3-0.6B)", 0, 0, EMBED_SECONDS, ("embed",)))
    if "profile" in parts:
        s = PROFILE_FIXED_SECONDS + profile_patients * PROFILE_SECONDS_PER_PATIENT
        rows.append(row("bench: profile stand-in (judge)", profile_patients, profile_patients, s, ("profile",)))
    for r in rows:
        r["hours"] = round(r["seconds"] / 3600, 2)
    hours = sum(r["seconds"] for r in rows) / 3600
    head = {"patients": patients, "seconds_per_note_patient": sec, "parts": list(parts), "llm_concurrency": list(lc),
            "llm_speedup": [llm_speedup(n) for n in lc], "llm_speedup_override": speedup_override(),
            "max_num_seqs": record_max_seqs()}  # fmt: skip
    return _priced(head, rows, hours)


def restrict(e: dict[str, Any], only: list[str]) -> dict[str, Any]:
    """The estimate of a bounded run (``--only`` tags, e.g. the first paid launch after a failed one): the start and
    setup rows, and only the work rows of those parts. ``install`` and ``prepare`` have no row of their own."""

    if not only:
        return e
    selftests = [f"selftest-{s}" for s in SELFTESTS if f"selftest-{s}" in only]  # the rehearsal's (tests/rehearsal)
    tags = {t for r in e["rows"] for t in r["tags"]}
    # a hospital part named without its concurrency (hospital-ja) is every repeat of it (hospital-ja@c1, @c4 ...)
    known = tags | {base_tag(t) for t in tags} | {"install", "prepare", G1_CHECK, *selftests}
    unknown = sorted(set(only) - known)
    if unknown:
        raise ValueError(f"--only: no such part in the plan: {' '.join(unknown)}")
    rows = [dict(r) for r in e["rows"]
            if not r["tags"] or set(r["tags"]) & set(only) or {base_tag(t) for t in r["tags"]} & set(only)]  # fmt: skip
    fixed = [r for r in rows if not r["tags"]]
    extra = [{"scenario": t, "patients": 0, "model_items": 0, "seconds": 600.0, "tags": [t], "hours": 0.17}
             for t in selftests]  # fmt: skip
    if G1_CHECK in only:  # review test G-1 (tools.chat_template_check), before the parts that depend on it
        from tools.chat_template_check import N_PROMPTS, SECONDS

        extra.insert(0, {"scenario": "G-1 chat template (sha256, token identity)", "patients": 0,
                         "model_items": N_PROMPTS, "seconds": SECONDS, "tags": [G1_CHECK],
                         "hours": round(SECONDS / 3600, 2)})  # fmt: skip
    rows = fixed + [r for r in extra if r["tags"] == [G1_CHECK]] + [r for r in rows if r["tags"]] + [
        r for r in extra if r["tags"] != [G1_CHECK]]  # fmt: skip
    hours = sum(r["seconds"] for r in rows) / 3600
    return _priced({**e, "only": list(only)}, rows, hours)


def shard_plan(e: dict[str, Any], vms: int) -> dict[str, Any]:
    """Split the estimate's work over ``vms`` VMs, each a whole RTX PRO 6000 with both models resident.

    A shard is a set of whole parts (``--only`` tags), so every part runs exactly as on one VM and the merged report
    is comparable with the single-VM run: nothing is split by patient range (each hospital part reads the whole
    hospital). Longest part first onto the least-loaded VM (LPT, deterministic). Every VM pays its own start and
    setup; ``prepare`` (the shared synthetic hospital) goes with every shard that has a hospital part, ``install``
    (the serving records) with the first. Each VM has its own hard cap: its estimate x 1.3, rounded up."""

    fixed = [r for r in e["rows"] if not r["tags"]]
    work = sorted((r for r in e["rows"] if r["tags"]), key=lambda r: (-r["seconds"], r["scenario"]))
    bins: list[list[dict[str, Any]]] = [[] for _ in range(max(1, vms))]
    for r in work:
        i = min(range(len(bins)), key=lambda k: (sum(x["seconds"] for x in bins[k]), k))
        bins[i].append(r)
    bins = [b for b in bins if b] or [[]]
    fixed_s = sum(r["seconds"] for r in fixed)
    shards = []
    for i, b in enumerate(bins):
        tags = [t for r in b for t in r["tags"]]
        tags.sort(key=lambda t: t != G1_CHECK)  # G-1 first on its VM (stable: the others keep their order)
        if "g1" in e.get("parts", ["g1"]):
            if any(t.startswith("hospital-") for t in tags):
                tags = ["prepare", *tags]
            if i == 0 and (not e.get("only") or "install" in e["only"]):
                tags = ["install", *tags]
        sec = fixed_s + sum(r["seconds"] for r in b)
        h = sec / 3600
        cap = cap_hours([*fixed, *b], h)
        model = provisioning(tags)  # D-468: on demand for a VM with a hospital part, spot for the others
        price = price_per_hour(model)
        shards.append({"shard": i + 1, "tags": tags, "rows": [r["scenario"] for r in b], "hours": round(h, 2),
                       "usd": round(h * price, 2), "cap_hours": cap, "cap_usd": round(cap * price, 2),
                       "provisioning": model, "price_per_hour": price})  # fmt: skip
    total = sum(x["hours"] for x in shards)
    return {"vms": len(shards), "shards": shards, "wall_hours": max(x["hours"] for x in shards),
            "hours": round(total, 2), "usd": round(sum(x["usd"] for x in shards), 2),
            "cap_usd": round(sum(x["cap_usd"] for x in shards), 2)}  # fmt: skip


def _done(dirs: list[Path], tag: str, run_id: str, head: str) -> bool:
    for d in dirs:
        f = d / f"{tag}.json"
        try:
            res = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
        except (OSError, ValueError):
            res = None
        if res is not None and _passed(res) and same_run(res, run_id, head)[0]:
            return True
    return False


def shard_now(doc: dict[str, Any], i: int, dirs: list[Path], run_id: str, head: str) -> dict[str, Any]:
    """Shard ``i`` of a run's plan (``plan.json``) as it stands now (D-468; G1 bug A3/A4): the parts it has left, its
    estimate, hard cap, provisioning model and price. A part is done when a result in ``dirs`` passed and was made by
    this shard (``<run id>-s<i>``) at ``head`` (the archive the VM runs): exactly what the VM's ``--resume`` keeps.
    A restarted shard (``TB_RUN_ID=<run id> complete-run.sh --shard i`` after a pre-emption) then gets a cap for what
    is left, and spot once its hospital parts are done. Nothing known (no results, no HEAD): the whole shard."""
    s = doc["plan"]["shards"][i - 1]
    left = [t for t in s["tags"] if not (head and _done(dirs, t, f"{run_id}-s{i}", head))]
    e = estimate(int(doc["patients"]), parts=tuple(doc.get("parts") or ("g1",)),
                 llm_concurrency=tuple(doc.get("llm_concurrency") or (1,)))  # fmt: skip
    now = restrict(e, left or ["install"])  # nothing left: the start and setup rows only
    return {"left": left, "done": [t for t in s["tags"] if t not in left], "hours": now["hours"], "usd": now["usd"],
            "cap_hours": now["cap_hours"], "cap_usd": now["cap_usd"], "provisioning": provisioning(left),
            "price_per_hour": price_per_hour(provisioning(left))}  # fmt: skip


CPUS_PER_VM = 48  # g4-standard-48


def _quota(quotas: list[dict[str, Any]], match: Any) -> dict[str, float] | None:
    q = next((x for x in quotas if match(str(x.get("metric", "")))), None)
    return None if q is None else {"limit": float(q.get("limit", 0)), "usage": float(q.get("usage", 0))}


def quota_problems(project: dict[str, Any], regions: dict[str, dict[str, Any]], zones: list[str],
                   cpus_per_vm: int = CPUS_PER_VM, standard: list[str] | None = None) -> list[str]:  # fmt: skip
    """Why ``len(zones)`` Spot RTX PRO 6000 VMs (one per zone) cannot run now, from ``gcloud compute project-info
    describe --format=json`` and ``gcloud compute regions describe <region> --format=json`` (review H-05). Spot VMs
    draw on the PREEMPTIBLE_ quota when the project has one (limit > 0), else on the regular one; the project's
    GPUS_ALL_REGIONS bounds them all. ``standard``: the zones whose VM runs on demand (D-468, a hospital part): they
    draw on the regular quota. Empty: the quota is there. A quota that cannot be read is a problem too."""
    out: list[str] = []
    q = _quota(project.get("quotas") or [], lambda m: m == "GPUS_ALL_REGIONS")
    if q is None:
        out.append("project quota GPUS_ALL_REGIONS not readable")
    elif q["limit"] - q["usage"] < len(zones):
        out.append(f"project quota GPUS_ALL_REGIONS: limit {q['limit']:g}, in use {q['usage']:g}, free "
                   f"{q['limit'] - q['usage']:g}; this run needs {len(zones)} GPU(s)")  # fmt: skip
    need: dict[tuple[str, bool], int] = {}
    for z in zones:
        key = (z.rsplit("-", 1)[0], z in (standard or []))
        need[key] = need.get(key, 0) + 1
    for (region, on_demand), n in need.items():
        qs = (regions.get(region) or {}).get("quotas") or []
        for what, per_vm, regular, pre in (
            ("RTX PRO 6000 GPUs", 1, lambda m: "RTX_PRO_6000" in m and not m.startswith("PREEMPTIBLE"),
             lambda m: m.startswith("PREEMPTIBLE") and "RTX_PRO_6000" in m),
            ("CPUs", cpus_per_vm, lambda m: m == "CPUS", lambda m: m == "PREEMPTIBLE_CPUS"),
        ):  # fmt: skip
            p, r = _quota(qs, pre), _quota(qs, regular)
            use, name = (p, "PREEMPTIBLE") if p is not None and p["limit"] > 0 else (r, "regular")
            if on_demand:
                use, name = r, "regular"
            if use is None and what.startswith("RTX") and qs and q is not None:
                # Compute Engine does not list a per-region RTX PRO 6000 metric in ``regions describe`` (2026-11-10;
                # the region's other quotas are there): GPUS_ALL_REGIONS above is the readable bound, and a start
                # beyond the regional quota fails at create time before anything is billed
                continue
            if use is None:
                out.append(f"{region}: {what} quota not readable")
            elif use["limit"] - use["usage"] < n * per_vm:
                who = "on-demand VMs (a hospital part, D-468) use" if on_demand else "Spot VMs use here"
                out.append(f"{region}: {what} ({name} quota, which {who}): limit {use['limit']:g}, in use "
                           f"{use['usage']:g}; {n} VM(s) need {n * per_vm}")  # fmt: skip
    return out


def quota_check(folder: Path, zones: list[str], standard: list[str] | None = None) -> int:
    """``--quota-check DIR``: DIR holds ``project.json`` and ``region-<region>.json`` (the driver writes them with
    read-only gcloud calls). Exit 0 when the quota is there, 4 with every shortfall printed otherwise."""
    project = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    regions = {p.stem.removeprefix("region-"): json.loads(p.read_text(encoding="utf-8"))
               for p in folder.glob("region-*.json")}  # fmt: skip
    bad = quota_problems(project, regions, zones, standard=standard)
    for b in bad:
        print(f"quota: {b}", file=sys.stderr)
    if bad:
        print(f"quota: {len(zones)} VM(s) cannot run now; nothing was started or made. Ask for a quota increase "
              "(IAM & Admin > Quotas) or use fewer VMs (--vms).", file=sys.stderr)  # fmt: skip
        return 4
    print(f"quota: enough for {len(zones)} VM(s) in {', '.join(zones)}")
    return 0


# ---------------------------------------------------------------- free checks before a paid start (2026-11-12: A6, A7)
def door_reach_problem(env: Mapping[str, str]) -> str:
    """A6: the door is TLS straight to the VM's address (``door_curl --noproxy '*'``, its own pinned certificate). A
    machine whose outbound HTTPS goes through a proxy (``HTTPS_PROXY`` set; often a TLS-inspecting one) cannot reach
    it, and the VM waited for its code and idled out (2026-11-12, about US$3.50). Without ``TB_BUCKET`` and with a
    proxy set this is the refusal's text; ``TB_DOOR_DIRECT=1`` says this machine does reach the VM directly. "" when
    the launch may go on. The proxy's address is never printed (it may carry a credential)."""
    if str(env.get("TB_BUCKET") or "").strip():
        return ""
    if not str(env.get("HTTPS_PROXY") or env.get("https_proxy") or "").strip():
        return ""
    if str(env.get("TB_DOOR_DIRECT") or "").strip().lower() in ("1", "true", "yes", "on"):
        return ""
    return ("door: HTTPS_PROXY is set here, so this machine's outbound HTTPS goes through a proxy, and the door is TLS "
            "straight to the VM's address (no proxy, the VM's own pinned certificate): the code could not be uploaded "
            "and the VM would idle out (2026-11-12). Set TB_BUCKET=gs://<bucket> (code and results through the "
            "bucket; `TB_BUCKET=gs://<bucket> bash deploy/gcp/setup-gcp.sh <project>` makes it and grants "
            "access), or TB_DOOR_DIRECT=1 if this machine does reach the VM's address directly. Nothing was "
            "started.")  # fmt: skip


def _gcloud_error(text: str) -> str:
    """What a failed read-only gcloud call says: ``disabled`` (the API is off), ``denied``, ``missing`` or ``other``."""
    t = text.lower()
    if "service_disabled" in t or "has not been used in project" in t or "it is disabled" in t:
        return "disabled"
    if "permission_denied" in t or "permission denied" in t or "403" in t or "does not have" in t:
        return "denied"
    if "not_found" in t or "not found" in t or "404" in t or "bucketnotfound" in t:
        return "missing"
    return "other"


def _member(account: str) -> str:
    return ("serviceAccount:" if account.endswith(".gserviceaccount.com") else "user:") + (account or "<deployer>")


def _bound(policy: dict[str, Any], member: str, roles: set[str]) -> bool:
    return any(b.get("role") in roles and member in (b.get("members") or []) for b in policy.get("bindings") or [])


def preflight_problems(folder: Path, secret: str = "tb-gpu-door") -> tuple[list[str], list[str]]:
    """A7: every reason a launch would fail in the cloud, from the read-only gcloud answers the driver saved in
    ``folder`` (``complete-run.sh --preflight``; the same at the start of a real launch, before any VM starts):
    ``project.txt``, ``account.txt``, ``mode.txt`` (door or bucket), ``vms.txt`` (``name zone`` lines),
    ``secret.json|.err``, ``secret-iam.json|.err``, ``vm-<name>.json|.err``, ``firewall.err``,
    ``firewall-<name>.txt`` (door_firewall_check's refusals), ``bucket.txt``, ``bucket-ls.err``,
    ``bucket-iam.json|.err``. Returns (problems, each with the exact fix command; checks that could not be confirmed
    read-only, e.g. a role granted on the project rather than on the resource)."""

    def read(name: str) -> str:
        p = folder / name
        return p.read_text(encoding="utf-8", errors="replace").strip() if p.is_file() else ""

    def doc(name: str) -> dict[str, Any] | None:
        raw = read(name)
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None

    project, account, mode = read("project.txt") or "<project>", read("account.txt"), read("mode.txt") or "door"
    member = _member(account)
    bad: list[str] = []
    notes: list[str] = []
    setup = f"bash deploy/gcp/setup-gcp.sh {project}"
    err = read("secret.err")
    if err:
        kind = _gcloud_error(err)
        if kind == "disabled":
            bad.append(f"Secret Manager API is disabled in {project}: gcloud services enable "
                       f"secretmanager.googleapis.com --project {project}   (a project owner; or {setup})")  # fmt: skip
        elif kind == "missing":
            bad.append(f"no secret {secret}: run deploy/gcp/setup-gcp.sh once ({setup}), or gcloud secrets create "
                       f"{secret} --replication-policy=automatic --project {project}")  # fmt: skip
        elif kind == "denied":
            bad.append(f"the deployer {account or '?'} cannot read secret {secret} (secretmanager.secrets.get): gcloud "
                       f"secrets add-iam-policy-binding {secret} --member={member} --role=roles/secretmanager.viewer "
                       f"--project {project}   (a project owner; {setup} grants it)")  # fmt: skip
        else:
            bad.append(f"secret {secret}: gcloud secrets describe failed: {err.splitlines()[-1][:200]}")
    vm_sas: list[str] = []
    for line in read("vms.txt").splitlines():
        if not line.split():
            continue
        name, zone = [*line.split(), ""][:2]
        verr = read(f"vm-{name}.err")
        if verr:
            kind = _gcloud_error(verr)
            if kind == "missing":
                bad.append(f"VM {name} does not exist in {zone}: deploy/gcp/complete-run.sh --provision --vms N "
                           "--zones ... makes the clones of tb-gpu-sim (tb-gpu-sim itself: RUNBOOK §11)")  # fmt: skip
            elif kind == "denied":
                bad.append(f"the deployer cannot describe VM {name}: gcloud projects add-iam-policy-binding {project} "
                           f"--member={member} --role=roles/compute.instanceAdmin.v1   (or {setup})")  # fmt: skip
            else:
                last = verr.splitlines()[-1][:200]
                bad.append(f"VM {name} ({zone}): gcloud compute instances describe failed: {last}")
            continue
        vm = doc(f"vm-{name}.json") or {}
        sa = ((vm.get("serviceAccounts") or [{}])[0]).get("email", "")
        if not sa:
            bad.append(f"VM {name} has no service account (it reads its door from Secret Manager with it): gcloud "
                       f"compute instances set-service-account {name} --zone {zone} --service-account "
                       f"<project-number>-compute@developer.gserviceaccount.com --scopes cloud-platform")  # fmt: skip
        else:
            vm_sas.append(sa)
        if mode == "door":
            fw = read(f"firewall-{name}.txt")
            bad += [f"VM {name}: {x}" for x in fw.splitlines() if x.strip()]
    ferr = read("firewall.err")
    if ferr and mode == "door":
        bad.append(f"the firewall rules are not readable (the door needs tcp:443 open and tcp:80 closed): gcloud "
                   f"projects add-iam-policy-binding {project} --member={member} --role=roles/compute.securityAdmin   "
                   f"(or {setup})")  # fmt: skip
    pol = doc("secret-iam.json")
    if pol is not None:
        sm = "roles/secretmanager."
        if account and not _bound(pol, member, {sm + "secretVersionManager", sm + "admin"}):
            notes.append(f"the deployer is not granted on secret {secret} itself to add and destroy its versions "
                         f"(fine if granted on the project): gcloud secrets add-iam-policy-binding {secret} "
                         f"--member={member} --role={sm}secretVersionManager --project {project}")  # fmt: skip
        for sa in sorted(set(vm_sas)):
            if not _bound(pol, f"serviceAccount:{sa}", {sm + "secretAccessor", sm + "admin"}):
                notes.append(f"the VMs' service account {sa} is not granted on secret {secret} itself to read it "
                             f"(fine if granted on the project): gcloud secrets add-iam-policy-binding {secret} "
                             f"--member=serviceAccount:{sa} --role={sm}secretAccessor --project {project}")  # fmt: skip
    elif read("secret-iam.err") and not err:
        notes.append(f"secret {secret}'s policy is not readable by the deployer: who may read and add versions is not "
                     "checked (roles/secretmanager.viewer on the secret lets the pre-flight read it)")  # fmt: skip
    if mode == "bucket":
        bucket = read("bucket.txt") or "gs://<bucket>"
        berr = read("bucket-ls.err")
        if berr:
            kind = _gcloud_error(berr)
            if kind == "missing":
                bad.append(f"bucket {bucket} does not exist: TB_BUCKET={bucket} {setup}   (makes it in the run's "
                           "region and grants objectAdmin to the deployer and the VMs' service account)")  # fmt: skip
            elif kind == "denied":
                bad.append(f"the deployer cannot use bucket {bucket}: gcloud storage buckets add-iam-policy-binding "
                           f"{bucket} --member={member} --role=roles/storage.objectAdmin   (or TB_BUCKET={bucket} "
                           f"{setup})")  # fmt: skip
            else:
                bad.append(f"bucket {bucket}: gcloud storage ls failed: {berr.splitlines()[-1][:200]}")
        bpol = doc("bucket-iam.json")
        admin = {"roles/storage.objectAdmin", "roles/storage.admin"}
        if bpol is not None:  # the bucket's own policy must show both: the code goes up, the results come back
            for who in sorted({member, *(f"serviceAccount:{s}" for s in vm_sas)}):
                if not _bound(bpol, who, admin):
                    bad.append(f"{who} has no objectAdmin on {bucket} (the code goes up and the results come back "
                               f"through it): gcloud storage buckets add-iam-policy-binding {bucket} --member={who} "
                               f"--role=roles/storage.objectAdmin   (or TB_BUCKET={bucket} {setup})")  # fmt: skip
        elif not berr:
            bad.append(f"{bucket}'s policy is not readable by the deployer, so the VMs' access cannot be checked: "
                       f"gcloud storage buckets add-iam-policy-binding {bucket} --member={member} "
                       f"--role=roles/storage.legacyBucketOwner   (or TB_BUCKET={bucket} {setup})")  # fmt: skip
        stale = [x for x in read("bucket-stale.txt").splitlines() if x.strip()]
        if stale:
            run = read("run-id.txt") or "<run id>"
            bad.append(f"{len(stale)} object(s) already under {bucket}/runs/{run}-s*: a stale run with this new run's "
                       f"id; remove them: gcloud storage rm -r '{bucket}/runs/{run}-s*'")  # fmt: skip
    return bad, notes


def preflight_check(folder: Path) -> int:
    """``--preflight-check DIR``: print every problem at once, each with its fix; exit 6 when there is one."""
    bad, notes = preflight_problems(folder)
    for n in notes:
        print(f"preflight: check: {n}")
    for b in bad:
        print(f"preflight: PROBLEM: {b}", file=sys.stderr)
    if bad:
        print(f"preflight: {len(bad)} problem(s); nothing was started (read-only calls only)", file=sys.stderr)
        return 6
    print("preflight: the project is ready for this launch (read-only calls only; nothing was started)")
    return 0


def parts_missing(doc: dict[str, Any], parts: Path) -> list[str]:
    """A8: the plan's part tags with no result in ``parts`` yet (empty: every part is in, the door may go)."""
    tags = [t for s in doc["plan"]["shards"] for t in s["tags"]]
    return [t for t in tags if not (parts / f"{t}.json").is_file()]


def print_shards(e: dict[str, Any], p: dict[str, Any]) -> str:
    lines = [f"Split over {p['vms']} VM(s), each one RTX PRO 6000 (g4-standard-48: spot US${PRICE_PER_HOUR}/h, on "
             f"demand US${ON_DEMAND_PRICE_PER_HOUR}/h for a VM with a hospital part, D-468); "
             f"parts: {', '.join(e['parts'])}", "",
             f"{'VM':<4}{'hours':>7}{'US$':>8}{'cap h':>7}{'cap US$':>9}  {'model':<9} parts"]  # fmt: skip
    for x in p["shards"]:
        lines.append(f"{x['shard']:<4}{x['hours']:>7.2f}{x['usd']:>8.2f}{x['cap_hours']:>7}{x['cap_usd']:>9.2f}  "
                     f"{x.get('provisioning', 'SPOT'):<9} {' '.join(x['tags'])}")  # fmt: skip
    lines += ["", f"total: {p['hours']:.2f} VM-hours, US${p['usd']:.2f}; wall about {p['wall_hours']:.2f} h; "
              f"every VM at its cap: at most US${p['cap_usd']:.2f}",
              "each VM pays its own start and setup (0.5 h); the stub parts run on the driver after."]  # fmt: skip
    return "\n".join(lines)


def concurrency_lines(e: dict[str, Any]) -> list[str]:
    """The estimate's and the plan's lines about the model calls in flight (``--llm-concurrency``, review G-3)."""
    lc = [int(n) for n in e.get("llm_concurrency") or []]
    if not lc:
        return []
    seqs = e.get("max_num_seqs")
    out = [f"model calls in flight (TB_SCREEN_LLM_CONCURRENCY): {', '.join(map(str, lc))}"
           + (f" (not given: the serving record's max_num_seqs, {seqs})" if e.get("llm_concurrency_default") else "")
           + ("; the hospital part runs once per value (hospital-<lang>@c<N>), on one prepared hospital"
              if len(lc) > 1 else "")]  # fmt: skip
    if any(n > 1 for n in lc):
        gains = ", ".join(f"{n}: {g:g}x" for n, g in zip(lc, e.get("llm_speedup") or [], strict=False) if n > 1)
        if e.get("llm_speedup_override"):
            out.append(f"  screening time: G1's {G1_CALLS_PER_SECOND:.2f} calls/s at 1 in flight, divided by min(N, "
                       f"{e['llm_speedup_override']:g}) (TB_ESTIMATE_LLM_SPEEDUP, the owner's override of G-3's "
                       f"measured curve; {gains})")  # fmt: skip
        else:
            out.append(f"  screening time: G1's {G1_CALLS_PER_SECOND:.2f} calls/s at 1 in flight, times the gain G-3 "
                       f"measured at N in flight (run {G3_RUN}, hospital-ja at 5,000; {gains}; between points "
                       "interpolated, above 48 held at 48's)")  # fmt: skip
    over = [n for n in lc if seqs and n > int(seqs)]
    if over:
        out.append(f"  note: {', '.join(map(str, over))} in flight is above the servers' max_num_seqs ({seqs}) and "
                   "the gateway's slots: the calls beyond wait in the gateway (it measures the queue, not a larger "
                   "batch)")  # fmt: skip
    return out


def print_estimate(e: dict[str, Any]) -> str:
    lines = [f"TrialBox complete run on the RTX PRO 6000: {e['patients']:,} patients, US${e['price_per_hour']}/h, "
             f"{e['seconds_per_note_patient']} s per note-stage patient (VALIDATION §3)", "",
             f"{'scenario':<42}{'patients':>10}{'model items':>13}{'hours':>8}{'US$':>9}"]  # fmt: skip
    for r in e["rows"]:
        lines.append(
            f"{r['scenario']:<42}{r['patients']:>10,}{r['model_items']:>13,}{r['hours']:>8.2f}{r['usd']:>9.2f}"
        )
    lines += ["", f"{'total':<42}{'':>10}{'':>13}{e['hours']:>8.2f}{e['usd']:>9.2f}", *concurrency_lines(e),
              f"hard cap (estimate x 1.3, rounded up): {e['cap_hours']} h, at most US${e['cap_usd']}",
              f"one VM: {'on demand (a hospital part, D-468)' if e.get('provisioning') == 'STANDARD' else 'spot'}, "
              f"US${e['price_per_hour']}/h",
              f"a bounded run: only {' '.join(e['only'])}" if e.get("only") else
              "walk, backup, update and scale run on the stub after the VM stops: no card time."]  # fmt: skip
    return "\n".join(lines)


def _local_timings(path: Path | None) -> tuple[dict[str, float], int]:
    """Stub wall seconds per scenario from a local report (``--estimate-from``), when one is given."""
    if path is None or not path.exists():
        return {}, 5000
    rep = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    for r in rep.get("parts") or []:
        key = r["part"] if r["part"] in ("hospital", "public") else r["tag"].removeprefix("scenario-")
        out[key] = max(out.get(key, 0.0), float(r.get("seconds_total") or 0))
    return out, int(rep.get("patients") or 5000)


def main(argv: list[str] | None = None) -> int:
    from tb_common.config import adopt_site_tz

    from tools import scenarios

    adopt_site_tz()  # synthetic sites on one VM: the example site's site.tz as TB_TZ, for every part (D-315)
    argv = list(sys.argv[1:] if argv is None else argv)
    from tools.pglocal import scratch_root  # D-201: never a fixed /tmp path

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--dir", type=Path, default=Path(os.environ.get("TB_COMPLETE_DIR") or scratch_root() / "tb-complete")
    )
    ap.add_argument("--model", choices=["stub", "pair"], default="stub")
    ap.add_argument("--patients", type=int, default=5000)
    ap.add_argument("--judge-url", default="", help="the pair's judge, e.g. http://<vm>/judge/v1 (key: TB_GPU_KEY)")
    ap.add_argument("--verifier-url", default="")
    ap.add_argument("--direct", action="store_true", help="--model pair: call the card directly, not the gateway")
    ap.add_argument("--ocr", choices=["fake", "tesseract"], default="fake", help="scanned charts (VM: tesseract)")
    ap.add_argument("--live-record", type=Path, help="the serving record of the card this run used")
    ap.add_argument("--resume", action="store_true", help="keep parts already done with every check passed")
    ap.add_argument("--keep-work", action="store_true", help="keep each scenario's work folder (disk)")
    ap.add_argument("--profile-patients", type=int, default=400, help="profile bench: patients sampled")
    ap.add_argument("--profile-workers", type=int, default=16, help="profile bench: parallel calls (vLLM batch)")
    ap.add_argument("--run-id", default=os.environ.get("TB_RUN_ID", ""),
                    help="the run's id: --resume keeps only parts of this run id and HEAD (H-01)")  # fmt: skip
    ap.add_argument("--llm-concurrency", default="", metavar="N[,N...]",
                    help="model calls in flight (TB_SCREEN_LLM_CONCURRENCY) for every part; several values: the "
                    "hospital part once per value, as hospital-<lang>@c<N> (review G-3). Not given with --model "
                    "pair: the serving record's max_num_seqs")  # fmt: skip
    if argv[:1] == ["part"]:
        ap.add_argument("part", nargs="?", choices=sorted(PARTS))
        ap.add_argument("--lang", default="ja", choices=["ja", "zh-TW", "en"])
        ap.add_argument("--scenario", default="", choices=["", *scenarios.SCENARIOS, *SELFTESTS])
        ap.add_argument("--variant", default="", help="a hospital part's repeat, c<N>: the tag hospital-<lang>@c<N>")
        ap.add_argument("--shots", type=Path, required=True)
        a = ap.parse_args(argv[1:])
        return run_part(a)
    ap.add_argument("--langs", nargs="+", default=list(LANGS), choices=["ja", "zh-TW", "en"])
    ap.add_argument("--skip", nargs="*", default=[], choices=sorted(set(PARTS) - {"prepare"}))
    ap.add_argument("--only", nargs="*", default=[], help="run only these parts or tags (e.g. scenario-it-dump)")
    ap.add_argument("--scenarios", nargs="*", default=[], choices=scenarios.SCENARIOS)
    ap.add_argument("--after-models", default="", help="a command to run once the model parts are done (stop the VM)")
    ap.add_argument("--heartbeat", default="", help="a file to touch before each part and while a part works (the "
                    "VM's watchdog; review H-03)")  # fmt: skip
    ap.add_argument("--heartbeat-seconds", type=float, default=30.0, help="--heartbeat: how often a busy part beats")
    ap.add_argument("--after-part", default="", help="a command to run after each part (the VM packs results.tgz)")
    ap.add_argument("--planned-from", type=Path, default=os.environ.get("TB_PLANNED_FROM") or None,
                    help="a full run's report.json: the checks a crashed part would have run (M-03)")  # fmt: skip
    ap.add_argument("--quota-check", type=Path, help="a folder of gcloud quota JSON: refuse when too small (H-05)")
    ap.add_argument("--quota-zones", default="", help="--quota-check: the run's zones, comma list (one VM each)")
    ap.add_argument("--quota-standard", default="", help="--quota-check: the zones whose VM runs on demand (D-468)")
    ap.add_argument("--shard-now", type=Path, help="a run's plan.json: print shard --shard-index as it stands (D-468)")
    ap.add_argument("--shard-index", type=int, default=1, help="--shard-now: the shard")
    ap.add_argument("--parts-dir", type=Path, nargs="*", default=[], help="--shard-now: folders of collected parts")
    ap.add_argument("--head-file", type=Path, help="--shard-now: the archive's TB_HEAD.json (the VM's HEAD)")
    ap.add_argument("--estimate", action="store_true", help="print hours and US$ per scenario on the card and exit")
    ap.add_argument("--estimate-from", type=Path, help="a local stub report.json whose part times to scale")
    ap.add_argument("--json", action="store_true", help="--estimate: print JSON")
    ap.add_argument("--vms", type=int, default=1, help="--estimate: split the parts over this many VMs (shard plan)")
    ap.add_argument("--parts", default="g1", help="--estimate: g1 (the complete run), embed, profile; comma list")
    ap.add_argument("--report-only", action="store_true", help="build the report from parts/ (the VM's and these)")
    ap.add_argument("--report-parts", nargs="*", default=[], help="--report-only: only these parts or tags")
    ap.add_argument("--pending-parts", nargs="*", default=[],
                    help="--report-only: tags whose VM still runs (pending, not 'VM stopped')")  # fmt: skip
    ap.add_argument("--door-reach-check", action="store_true",
                    help="exit 2 with the reason when the door cannot be reached from here (A6)")  # fmt: skip
    ap.add_argument("--preflight-check", type=Path, help="a folder of read-only gcloud answers: every problem (A7)")
    ap.add_argument("--parts-missing", type=Path, help="a run's plan.json: print its tags with no result in "
                    "--parts-dir (A8)")  # fmt: skip
    a = ap.parse_args(argv)
    if a.door_reach_check:
        why = door_reach_problem(os.environ)
        if why:
            print(why, file=sys.stderr)
        return 2 if why else 0
    if a.preflight_check:
        return preflight_check(a.preflight_check)
    if a.parts_missing:
        doc = json.loads(a.parts_missing.read_text(encoding="utf-8"))
        print(" ".join(parts_missing(doc, (a.parts_dir or [a.dir / "parts"])[0])))
        return 0
    try:
        a.lc = parse_concurrency(a.llm_concurrency)
    except ValueError as exc:
        ap.error(str(exc))
    a.lc_default = False
    if not a.lc and (a.estimate or (a.model == "pair" and not a.report_only)):
        # not given: what an installed box runs SCREEN with, the serving record's max_num_seqs (D-142; review G-3)
        a.lc, a.lc_default = (record_max_seqs(a.live_record),), True
    if a.quota_check:
        return quota_check(a.quota_check, [z for z in a.quota_zones.split(",") if z],
                           [z for z in a.quota_standard.split(",") if z])  # fmt: skip
    if a.shard_now:
        hf = a.head_file
        head = str(json.loads(hf.read_text(encoding="utf-8")).get("head", "")) if hf and hf.is_file() else ""
        doc = json.loads(a.shard_now.read_text(encoding="utf-8"))
        print(json.dumps(shard_now(doc, a.shard_index, list(a.parts_dir), a.run_id, head)))
        return 0
    if a.estimate:
        local, n = _local_timings(a.estimate_from)
        parts = tuple(x for x in a.parts.split(",") if x)
        if not parts or set(parts) - {"g1", *BENCH_PARTS}:
            ap.error(f"--parts: g1, {', '.join(BENCH_PARTS)}")
        try:
            e = estimate(a.patients, tuple(a.langs), local, n, parts, a.profile_patients, a.lc)
            e["llm_concurrency_default"] = a.lc_default
            e = restrict(e, a.only)
        except ValueError as exc:
            ap.error(str(exc))
        e["plan"] = shard_plan(e, a.vms)
        many = a.vms > 1 or parts != ("g1",) or bool(a.only)
        text = print_estimate(e) + ("\n\n" + print_shards(e, e["plan"]) if many else "")
        print(json.dumps(e, indent=1) if a.json else text)
        return 0
    if a.report_only:
        return report_only(a)
    if a.model == "pair" and not (a.judge_url and a.verifier_url and os.environ.get("TB_GPU_KEY")):
        ap.error("--model pair needs --judge-url, --verifier-url and TB_GPU_KEY in the environment")
    if "hospital" in a.skip:  # the shared synthetic hospital is only the hospital parts' input
        a.skip.append("prepare")
    return run_all(a)


if __name__ == "__main__":
    raise SystemExit(main())
