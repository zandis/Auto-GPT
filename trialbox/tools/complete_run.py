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

After each console part the console is served on a free local port and ``tools/stage_shots.js`` takes one screenshot
per stage, signed in as the role that does it, in the part's language. Parts without a console of their own (install,
backup, update, scale) get a picture of their check table. The report (``<dir>/report/report.md`` and ``.json``)
holds per stage the checks, the time and the screenshot, and the git head it ran from.

Synthetic and public data only. The console password is random, from ``TB_DEMO_PASSWORD`` or made here, and never
printed; the GPU key comes from ``TB_GPU_KEY`` only. Exit 0 only when every check of every part passed.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import platform
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

LANGS = ("ja", "zh-TW")
JUDGE, VERIFIER = "local/gemma-4-26b-a4b-nvfp4", "local/qwen3.5-9b-awq"  # the vLLM served names (D-124)
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
    ("audit", "admin", "/audit"),
    ("8 ", "crc", f"/studies/{H_TRIAL}/sources"),
    ("9 ", "crc", f"/studies/{H_TRIAL}/conflicts?all=1"),
    ("10 ", "crc", f"/studies/{H_TRIAL}/forms"),
    ("11 ", "crc", f"/studies/{H_TRIAL}/subjects"),
    ("12 ", "crc", "/site?ws=newsite&study=SITE5B"),  # e2e_simple.SITE_WS, SITE_RS
    ("13 ", "admin", "/admin?tab=sources"),
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
    ("8 ", "admin", "/audit"),
]


# ---------------------------------------------------------------- helpers
def _stages(stages: list[Any]) -> list[dict[str, Any]]:
    return [
        {"name": st.name, "ok": st.ok, "seconds": round(st.seconds, 1), "checks": [list(c) for c in st.checks]}
        for st in stages
    ]


def _one(name: str, checks: list[tuple[str, bool, Any]], seconds: float) -> list[dict[str, Any]]:
    return [{"name": name, "ok": all(c[1] for c in checks), "seconds": round(seconds, 1), "checks": checks}]


def git_head() -> dict[str, Any]:
    def g(*a: str) -> str:
        r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=False)
        return r.stdout.strip()

    return {"head": g("rev-parse", "HEAD"), "subject": g("log", "-1", "--format=%s"),
            "dirty": bool(g("status", "--porcelain"))}  # fmt: skip


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
    if a.model != "pair":
        return None, None
    from tools.public_e2e import real_models

    os.environ["TB_CANARY_GATE"] = "on"  # plan v4 §5: screening with the pair and the canary gate
    return real_models(a.judge_url, a.verifier_url, os.environ["TB_GPU_KEY"])


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
    from tools import e2e_simple
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
    out = e2e_simple.run(work, a.password, a.lang)
    stages = _stages(out["stages"])
    lst = out["result"]["list"]
    box = lst["box"]
    sj = box.orch.db.get(out["jobs"]["screen"])
    scr = e2e_simple._json_output(box, sj, "screen_")
    extra = {
        "seconds": out["seconds"],
        "chain_seconds": out["chain_seconds"],
        "screen": {k: scr.get(k) for k in ("funnel", "tiers", "listed", "judging")},
        "canary": canary.get("status"),
    }
    fill = {"feas": out["jobs"]["feas"], "pid": lst["picks"][0]["pid"]}
    items = _page_items(f"hospital-{a.lang}", a.lang, stages, HOSPITAL_PAGES, fill)
    srv = Served(out["result"]["app"])
    try:
        _attach_shots(stages, shoot(items, a.shots, a.password, srv.base))
    finally:
        srv.stop()
    return {"stages": stages, **extra}


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


PARTS = {
    "prepare": part_prepare,
    "install": part_install,
    "hospital": part_hospital,
    "public": part_public,
    "walk": part_walk,
    "backup": lambda a: _drill(a, "backup, wipe and restore (tools.backup_drill)", "tools.backup_drill"),
    "update": lambda a: _drill(a, "signed update, two rollbacks (tools.update_drill)", "tools.update_drill"),
    "scale": part_scale,
}
NO_CONSOLE = ("prepare", "install", "backup", "update", "scale")
MODEL_PARTS = ("hospital", "public")  # the parts the pair serves; walk, backup, update and scale run on the stub


def run_part(a: argparse.Namespace) -> int:
    import logging

    logging.disable(logging.INFO)  # the in-process services log every request; the checks are the output
    a.password = os.environ.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    a.shots.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    try:
        res = PARTS[a.part](a)
    except Exception as exc:  # one broken part is a failed row in the report, not a lost run
        import traceback

        tb = traceback.format_exc().splitlines()[-3:]
        res = {"stages": _one(f"{a.part} crashed", [("part ran", False, f"{exc!r} {' | '.join(tb)}"[:300])], 0)}
    res["wall_seconds"] = round(time.perf_counter() - t0, 1)
    tag = a.part + (f"-{a.lang}" if a.part in ("hospital", "public") else "")
    if a.part in NO_CONSOLE:
        url = table_page(a.shots / f"{tag}.html", f"TrialBox complete run: {tag}", res["stages"])
        got = shoot([{"name": tag, "url": url}], a.shots, a.password)
        for st in res["stages"]:
            st["shot"] = f"{tag}.png"
        _attach_shots(res["stages"], {tag: got[tag]})
    (a.dir / "parts").mkdir(parents=True, exist_ok=True)
    (a.dir / "parts" / f"{tag}.json").write_text(json.dumps(res, default=str, ensure_ascii=False, indent=1), "utf-8")
    return 0 if all(st["ok"] for st in res["stages"]) else 1


# ---------------------------------------------------------------- the run and its report
def plan(a: argparse.Namespace) -> list[tuple[str, str]]:
    out = [("prepare", ""), ("install", "")]
    out += [("hospital", lang) for lang in a.langs]
    out += [("public", lang) for lang in a.langs]
    out += [("walk", ""), ("backup", ""), ("update", ""), ("scale", "")]
    return [p for p in out if p[0] not in a.skip]


def run_all(a: argparse.Namespace) -> int:
    a.dir.mkdir(parents=True, exist_ok=True)
    report_dir = a.dir / "report"
    shots = report_dir / "shots"
    shutil.rmtree(report_dir, ignore_errors=True)
    shots.mkdir(parents=True)
    shutil.rmtree(a.dir / "parts", ignore_errors=True)
    env = dict(os.environ, TB_ENV=os.environ.get("TB_ENV") or "DEV", PYTHONPATH="libs:services:.")
    env.setdefault("TB_DEMO_PASSWORD", secrets.token_urlsafe(12))  # one random password for every part, never printed
    started = datetime.now(UTC)
    head = git_head()
    todo = plan(a)
    rows: list[dict[str, Any]] = []
    for i, (part, lang) in enumerate(todo):
        cmd = [sys.executable, "-m", "tools.complete_run", "part", part, "--dir", str(a.dir), "--shots", str(shots),
               "--patients", str(a.patients), "--model", a.model]  # fmt: skip
        if lang:
            cmd += ["--lang", lang]
        if a.model == "pair":
            cmd += ["--judge-url", a.judge_url, "--verifier-url", a.verifier_url]
        if a.live_record:
            cmd += ["--live-record", str(a.live_record)]
        t = time.perf_counter()
        print(f"[{i + 1}/{len(todo)}] {part} {lang}".rstrip(), flush=True)
        rc = subprocess.run(cmd, cwd=ROOT, env=env, check=False).returncode
        tag = part + (f"-{lang}" if lang else "")
        f = a.dir / "parts" / f"{tag}.json"
        res = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {
            "stages": _one(f"{tag} did not report", [("part ran", False, f"exit {rc}")], 0)}  # fmt: skip
        res.update({"part": part, "lang": lang, "tag": tag, "seconds_total": round(time.perf_counter() - t, 1)})
        rows.append(res)
        bad = sum(1 for st in res["stages"] for c in st["checks"] if not c[1])
        print(f"      {'PASS' if bad == 0 else 'FAIL'} in {res['seconds_total']} s", flush=True)
        last_model_part = not any(p in MODEL_PARTS for p, _ in todo[i + 1 :])
        if a.after_models and part in MODEL_PARTS and last_model_part:
            # the paid card is no longer needed: the wrapper stops the VM while walk, backup, update and scale run
            print(f"      after the model parts: {a.after_models}", flush=True)
            subprocess.run(a.after_models, shell=True, cwd=ROOT, check=False)  # the operator's own command
    rep: dict[str, Any] = {
        "schema": "tb-complete-run/1",
        "git": head,
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": a.model,
        "models": [JUDGE, VERIFIER] if a.model == "pair" else ["stub"],
        "patients": a.patients,
        "langs": list(a.langs),
        "host": {"machine": platform.machine(), "cpus": os.cpu_count(), "python": platform.python_version()},
        "parts": rows,
    }
    rep["checks"] = sum(len(st["checks"]) for r in rows for st in r["stages"])
    rep["failed"] = sum(1 for r in rows for st in r["stages"] for c in st["checks"] if not c[1])
    rep["shots"] = sum(1 for r in rows for st in r["stages"] if st.get("shot"))
    rep["shots_ok"] = sum(1 for r in rows for st in r["stages"] if st.get("shot_ok"))
    rep["ok"] = rep["failed"] == 0 and rep["shots_ok"] == rep["shots"]
    rep["seconds"] = round(sum(r["seconds_total"] for r in rows), 1)
    (report_dir / "report.json").write_text(json.dumps(rep, default=str, ensure_ascii=False, indent=1), "utf-8")
    (report_dir / "report.md").write_text(markdown(rep), encoding="utf-8")
    verdict = "PASSED" if rep["ok"] else "FAILED"
    print(f"complete run {verdict}: {rep['checks'] - rep['failed']}/{rep['checks']} checks, "
          f"{rep['shots_ok']}/{rep['shots']} screenshots, {rep['seconds']} s; {report_dir / 'report.md'}")  # fmt: skip
    return 0 if rep["ok"] else 1


def markdown(rep: dict[str, Any]) -> str:
    g = rep["git"]
    lines = [
        "# TrialBox complete-platform run",
        "",
        f"Head `{g['head'][:12]}` ({g['subject']}){' with local changes' if g['dirty'] else ''}. "
        f"Model: {', '.join(rep['models'])}. Hospital: {rep['patients']:,} synthetic patients. "
        f"Languages: {', '.join(rep['langs'])}. Host: {rep['host']['machine']}, {rep['host']['cpus']} CPUs.",
        f"Started {rep['started']}, finished {rep['finished']}.",
        "",
        f"**{'PASSED' if rep['ok'] else 'FAILED'}**: {rep['checks'] - rep['failed']} of {rep['checks']} checks; "
        f"{rep['shots_ok']} of {rep['shots']} screenshots; {rep['seconds'] / 60:.1f} min in all.",
        "",
        "Screenshots are in the run's `report/shots/` folder (not committed).",
        "",
        "| part | stage | checks | result | seconds | screenshot |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rep["parts"]:
        for st in r["stages"]:
            n = len(st["checks"])
            bad = [c[0] for c in st["checks"] if not c[1]]
            shot = f"`{st['shot']}`" + ("" if st.get("shot_ok") else " (missing)") if st.get("shot") else ""
            lines.append(f"| {r['tag']} | {st['name']} | {n - len(bad)}/{n} | {'pass' if not bad else 'FAIL'} | "
                         f"{st['seconds']} | {shot} |")  # fmt: skip
    lines += ["", "## Part times", "", "| part | wall seconds |", "| --- | --- |"]
    lines += [f"| {r['tag']} | {r['seconds_total']} |" for r in rep["parts"]]
    fails = [(r["tag"], st["name"], c) for r in rep["parts"] for st in r["stages"] for c in st["checks"] if not c[1]]
    if fails:
        lines += ["", "## Failed checks", ""]
        lines += [f"- {t} / {s}: {c[0]}: {str(c[2])[:200]}" for t, s, c in fails]
    for r in rep["parts"]:
        for key in ("screen", "canary", "walk", "scale"):
            if r.get(key):
                lines += ["", f"## {r['tag']}: {key}", "", "```json", json.dumps(r[key], default=str)[:1500], "```"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_COMPLETE_DIR", "/tmp/tb-complete")))
    ap.add_argument("--model", choices=["stub", "pair"], default="stub")
    ap.add_argument("--patients", type=int, default=5000)
    ap.add_argument("--judge-url", default="", help="the pair's judge, e.g. http://<vm>/judge/v1 (key: TB_GPU_KEY)")
    ap.add_argument("--verifier-url", default="")
    ap.add_argument("--live-record", type=Path, help="the serving record of the card this run used")
    if argv[:1] == ["part"]:
        ap.add_argument("part", nargs="?", choices=sorted(PARTS))
        ap.add_argument("--lang", default="ja", choices=["ja", "zh-TW", "en"])
        ap.add_argument("--shots", type=Path, required=True)
        a = ap.parse_args(argv[1:])
        return run_part(a)
    ap.add_argument("--langs", nargs="+", default=list(LANGS), choices=["ja", "zh-TW", "en"])
    ap.add_argument("--skip", nargs="*", default=[], choices=sorted(set(PARTS) - {"prepare"}))
    ap.add_argument("--after-models", default="", help="a command to run once the model parts are done (stop the VM)")
    a = ap.parse_args(argv)
    if a.model == "pair" and not (a.judge_url and a.verifier_url and os.environ.get("TB_GPU_KEY")):
        ap.error("--model pair needs --judge-url, --verifier-url and TB_GPU_KEY in the environment")
    if "hospital" in a.skip:  # the shared synthetic hospital is only the hospital parts' input
        a.skip.append("prepare")
    return run_all(a)


if __name__ == "__main__":
    raise SystemExit(main())
