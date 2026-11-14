"""Stand-in for the INSTALLED BOX's services and tools in the box-run rehearsal (synthetic; no model, no GPU, no
container). Nothing here is lane G's code under test: it answers the calls deploy/gcp/box-install-run.sh makes
(its d_* functions) the way the box would, and writes each call to calls.log. The paid run replaces it with the
box the real installer put on the VM: its containers (compose exec), its tools (python -m tools.<name>) and its
model servers.

Two ways in:
  box.py -m tools.<name> ARGS        the box's tools (the VM's tb-box-python points here): pin_model, serving_config,
                                     trialbox (eval qualify, doctor, selftest, backup-nightly)
  box.py <action> ARGS               what the docker shim forwards: compose ps / exec / restart / stop / start, the
                                     feed's docker run, an interruption
Knobs ($BR_S/knobs): fail-qualify, qualify-seconds, oom-ingest, list-differs, doctor-unexpected, job-seconds.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

S = Path(os.environ["BR_S"])
BOX = S / "box"
SERVICES = (
    "adapter",
    "lake",
    "orchestrator",
    "gateway",
    "db",
    "mail-gateway",
    "console",
    "llm-service",
    "llm-verifier",
)
CAPS = {"adapter": 6 << 30, "lake": 8 << 30, "orchestrator": 4 << 30, "db": 4 << 30, "llm-service": 48 << 30}
MIB = 1 << 20
IMAGE_ROOT = Path(__file__).resolve().parents[4]  # what the box's python image carries at /app (models/, libs/)


def knob(name: str, default: str = "") -> str:
    p = S / "knobs" / name
    return p.read_text().strip() if p.exists() else default


def flag(name: str) -> bool:
    return (S / "knobs" / name).exists()


def arg(argv: list[str], f: str) -> str:
    return argv[argv.index(f) + 1]


def called(what: str) -> None:
    with open(S / "calls.log", "a") as fh:
        fh.write(what + "\n")


def jload(p: Path, default: Any) -> Any:
    return json.loads(p.read_text()) if p.exists() else default


def jsave(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.with_suffix(".tmp").write_text(json.dumps(obj))
    p.with_suffix(".tmp").replace(p)


# ---------------------------------------------------------------- the containers' cgroups (memory, cgroup v2 files)
def cg(svc: str) -> Path:
    d = S / "cgroup" / "system.slice" / f"docker-cid-{svc}.scope"
    if not d.exists():
        d.mkdir(parents=True)
        for f, v in (("memory.current", 100 * MIB), ("memory.peak", 100 * MIB), ("memory.max", CAPS.get(svc, 2 << 30))):
            (d / f).write_text(f"{v}\n")
        (d / "memory.events").write_text("low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n")
    return d


def use(svc: str, nbytes: int, seconds: float) -> None:
    """The service holds ``nbytes`` for ``seconds`` (what the sampler and memory.peak see), then goes back."""
    d = cg(svc)
    (d / "memory.current").write_text(f"{nbytes}\n")
    peak = int((d / "memory.peak").read_text())
    (d / "memory.peak").write_text(f"{max(peak, nbytes)}\n")
    time.sleep(seconds)
    (d / "memory.current").write_text(f"{100 * MIB}\n")


# ---------------------------------------------------------------- the stack's health and the screen job
def interrupt(what: str) -> None:
    jsave(BOX / "unhealthy-until.json", time.time() + 0.6)
    job = jload(BOX / "job.json", None)
    if job and job["state"] == "running":
        job["last_interrupt"] = time.time()
        job["interruptions"] = job.get("interruptions", 0) + 1
        jsave(BOX / "job.json", job)
    called(what)


def ps(argv: list[str]) -> int:
    if "-q" in argv:
        svc = argv[-1]
        cg(svc)
        print(f"cid-{svc}")
        return 0
    down = set(jload(BOX / "stopped.json", []))
    sick = time.time() < jload(BOX / "unhealthy-until.json", 0.0)
    for svc in SERVICES:
        print(f"{svc} {'exited' if svc in down else 'running'} {'starting' if sick else 'healthy'}")
    return 0


def job_state(job: dict[str, Any]) -> str:
    if job["state"] != "running":
        return str(job["state"])
    if time.time() - job["last_interrupt"] >= float(knob("job-seconds", "8")):
        job["state"] = "done"
        jsave(BOX / "jobs" / f"{job['id']}.json", job)
        if (BOX / "job.json").exists() and jload(BOX / "job.json", {}).get("id") == job["id"]:
            jsave(BOX / "job.json", job)
    return str(job["state"])


def snippet(svc: str, text: str) -> int:
    """`docker compose exec -T <svc> python -` with a snippet of the VM script: its first line names it."""
    head = text.lstrip().splitlines()[0] if text.strip() else ""
    if not head.startswith("# tb-boxrun:"):
        print(f"box stand-in: a snippet without its name for {svc}", file=sys.stderr)
        return 2
    what, *rest = head.split(":", 1)[1].split()
    if what == "study-ready":
        called("study-ready")
        ok = not flag("no-study")
        print(200 if ok else 404)
        return 0 if ok else 1
    if what == "identity":  # the REAL registry and prompt registry of the installed host tree, read with the venv
        import subprocess

        called("identity")
        box = S / "box-root"
        code = (
            "import json, yaml, sys\n"
            "from tb_llm.prompt_registry import default_registry\n"
            f"reg = yaml.safe_load(open({str(IMAGE_ROOT / 'models' / 'registry.yaml')!r}))\n"
            "b = [{'build_id': x.get('build_id'), 'manifest_sha256': (x.get('expected') or {}).get('manifest_sha256'),"
            " 'revision': (x.get('expected') or {}).get('revision'),"
            " 'chat_template_sha256': (x.get('chat_template') or {}).get('sha256')}"
            " for x in reg.get('builds') or [] if str(x.get('build_id', '')).endswith('-rtxpro6000')]\n"
            "p = [{'id': e.id, 'version': e.version, 'sha256': e.sha256} for e in default_registry().served_set('PRODUCTION')]\n"
            "print(json.dumps({'builds': b, 'served_prompts': p}))\n"
        )
        env = {**os.environ, "PYTHONPATH": f"{box / 'libs'}:{box}"}
        return subprocess.run([os.environ["TB_BOX_PY"], "-c", code], env=env, check=False).returncode
    if what == "screen-start":
        n = len(list((BOX / "jobs").glob("*.json"))) + 1 if (BOX / "jobs").exists() else 1
        tag = "g9" if "g9" in text.split("comment", 1)[1].split("\n", maxsplit=1)[0] else "screen"
        job = {
            "id": f"standin-job-{n}",
            "tag": tag,
            "state": "running",
            "start": time.time(),
            "last_interrupt": time.time(),
            "interruptions": 0,
        }
        jsave(BOX / "jobs" / f"{job['id']}.json", job)
        jsave(BOX / "job.json", job)
        called(f"screen-start {tag}")
        print(job["id"])
        return 0
    if what == "screen-status":
        job = jload(BOX / "jobs" / f"{rest[0]}.json", None)
        if job is None:
            return 1
        print(json.dumps({"state": job_state(job), "error": None, "metrics": {"interruptions": job["interruptions"]}}))
        return 0
    if what == "candidates":
        job = jload(BOX / "jobs" / f"{rest[0]}.json", {})
        rows = [{"pid": f"P{i:04d}", "tier": "A" if i % 3 else "B"} for i in range(12)]
        if flag("list-differs") and job.get("tag") == "g9":
            rows = rows[1:]  # the disturbed run lost a patient
        print(json.dumps({"job": rest[0], "rows": rows}))
        return 0
    print(f"box stand-in: no snippet {what}", file=sys.stderr)
    return 2


def compose(argv: list[str]) -> int:
    i = next(k for k, a in enumerate(argv) if a in ("ps", "exec", "restart", "stop", "start"))
    cmd, rest = argv[i], argv[i + 1 :]
    if cmd == "ps":
        return ps(rest)
    if cmd in ("restart", "stop", "start"):
        svc = rest[-1]
        down = set(jload(BOX / "stopped.json", []))
        if cmd == "stop":
            down.add(svc)
            interrupt(f"compose-stop {svc}")
        elif cmd == "start":
            down.discard(svc)
            called(f"compose-start {svc}")
        else:
            interrupt(f"compose-restart {svc}")
        jsave(BOX / "stopped.json", sorted(down))
        return 0
    rest = [a for a in rest if a != "-T"]
    svc, prog = rest[0], rest[1:]
    if prog == ["python", "-"]:
        return snippet(svc, sys.stdin.read())
    if prog[:3] == ["python", "-m", "adapter.cli"]:
        called("ingest")
        use("adapter", 3 << 30, 0.6)
        if flag("oom-ingest"):  # T-692: the ingest needs more than the adapter's cap; the kernel kills it
            d = cg("adapter")
            (d / "memory.peak").write_text(f"{CAPS['adapter']}\n")
            (d / "memory.events").write_text("low 0\nhigh 0\nmax 9\noom 1\noom_kill 1\n")
            print("Killed", file=sys.stderr)
            return 137
        use("lake", 2 << 30, 0.3)
        (BOX / "current").write_text("snapshot-2026-10-04\n")
        return 0
    if prog[:1] == ["sha256sum"]:  # the judge's template inside its container: the pinned file (knob template-differs)
        import re

        reg = (IMAGE_ROOT / "models" / "registry.yaml").read_text()
        pinned = re.search(r"chat_template:.*?sha256: ([0-9a-f]{64})", reg, re.S)
        sha = "f" * 64 if flag("template-differs") or not pinned else pinned.group(1)
        print(f"{sha}  {prog[1]}")
        return 0
    if prog[:2] == ["cat", "/data/lake/CURRENT"]:
        p = BOX / "current"
        print(p.read_text().strip() if p.exists() else "snapshot-rehearsal-0")
        return 0
    print(f"box stand-in: compose exec {svc} {' '.join(prog)} is not rehearsed", file=sys.stderr)
    return 2


def feed(argv: list[str]) -> int:
    """`docker run ... -v <host>:/out <image> python -c <generator> N /out/site REF PROFILE`: a small synthetic feed."""
    host = next(a.split(":", 1)[0] for k, a in enumerate(argv) if k and argv[k - 1] == "-v" and a.endswith(":/out"))
    n = int(argv[argv.index("-c") + 2])
    site = Path(host) / "site"
    site.mkdir(parents=True, exist_ok=True)
    (site / "patient.csv").write_text("mrn,birth_date\n" + "".join(f"S{i:05d},1960-01-01\n" for i in range(min(n, 50))))
    called(f"feed {n}")
    print(json.dumps({"patients": n, "records_per_patient": 500, "notes_per_patient": 40}))
    return 0


# ---------------------------------------------------------------- the box's tools
def tool(name: str, argv: list[str]) -> int:
    if not (BOX / "wizard-done").exists() and not (S / "box-root" / "deploy" / "site" / "box" / "applied").exists():
        print(f"{name}: the box is not set up (the wizard has not run)", file=sys.stderr)
        return 1
    if name == "pin_model":
        if "--install" in argv:
            called("pin")
            roles = sorted(p.name for p in Path(arg(argv, "--models-root")).iterdir() if p.is_dir())
            return 0 if roles == ["judge", "verifier"] else 1
        if "--promote" in argv:
            called("promote " + arg(argv, "--promote"))
            if not json.loads(Path(arg(argv, "--record")).read_text()).get("passed"):
                return 1
            jsave(BOX / "promoted.json", [*jload(BOX / "promoted.json", []), arg(argv, "--promote")])
            return 0
        if "--verify-all" in argv:
            called("verify-weights")
            return 0
        if "--resolve" in argv:
            by = {b.split("-")[1]: b for b in jload(BOX / "promoted.json", [])}
            print(json.dumps({r: {"build": by.get(r, ""), "promoted": r in by} for r in ("judge", "verifier")}))
            return 0
    if name == "serving_config":
        called("capture")
        Path(arg(argv, "--out")).write_text(json.dumps({"standin": True, "containers": argv.count("--container")}))
        return 0
    if name == "trialbox" and argv[:2] == ["eval", "qualify"]:
        called("qualify")
        end = time.time() + float(knob("qualify-seconds", "0"))
        while time.time() < end:
            print("qualify: item", flush=True)
            time.sleep(0.2)
        if flag("fail-qualify"):
            print("qualify: FAIL stand-in gate: schema failures 3 of 54", flush=True)
            return 1
        rec = {
            "standin": True,
            "passed": True,
            "builds": {"judge": "standin-judge-1", "verifier": "standin-verifier-1"},
        }
        Path(arg(argv, "--out")).write_text(json.dumps(rec))
        return 0
    if name == "trialbox" and argv[:1] == ["doctor"]:
        called("doctor")
        checks = [
            {"name": "serving", "status": "PASS", "detail": "both pinned names served"},
            {"name": "backup", "status": "FAIL", "detail": "no backup target yet (expected on a cloud VM)"},
        ]
        if flag("doctor-unexpected"):
            checks.append({"name": "clock", "status": "FAIL", "detail": "not NTP-synchronised"})
        print(json.dumps(checks))
        return 1
    if name == "trialbox" and argv[:1] == ["selftest"]:
        called("selftest")
        return 0
    if name == "trialbox" and argv[:1] == ["backup-nightly"]:
        called("backup")
        use("db", 1 << 30, 0.4)
        return 0
    print(f"box stand-in: tools.{name} {' '.join(argv)} is not rehearsed", file=sys.stderr)
    return 2


def main() -> int:
    a = sys.argv[1:]
    if a[:1] == ["-m"]:
        return tool(a[1].removeprefix("tools."), a[2:])
    if a[:1] == ["compose"]:
        return compose(a[1:])
    if a[:1] == ["run"]:
        return feed(a[1:])
    if a[:1] == ["interrupt"]:
        interrupt(a[1])
        return 0
    if a[:1] == ["wizard-done"]:  # the real installer applied the owner's answers (its compose stand-in says so)
        (BOX / "wizard-done").parent.mkdir(parents=True, exist_ok=True)
        (BOX / "wizard-done").write_text("1")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
