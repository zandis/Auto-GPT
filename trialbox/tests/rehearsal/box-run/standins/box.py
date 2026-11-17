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
Knobs ($BR_S/knobs): fail-qualify, qualify-seconds, oom-ingest, list-differs, doctor-unexpected, job-seconds; the
accuracy group's: acc-job-seconds (how long a FEAS, APPROVE or SCREEN job runs), acc-tripwire (the first protocol of
each screened set is refused by the PHI tripwire, as the gateway refused public protocols in the dry run),
acc-blocked (the gateway's routes refuse the screen's judge call: the VALIDATION ceiling of today's tree),
tripwire-setting (the tree declares a tripwire setting).
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


def standin_ids(msgs: list[dict[str, str]]) -> list[int]:
    """A stand-in tokenizer: one id per character of the rendered messages (the server's and the folder's agree;
    knob tokens-differ: the server's differ at the first prompt)."""
    return [ord(c) for c in json.dumps(msgs, ensure_ascii=False)][:64]


def may_call(svc: str, key: str) -> bool:
    """Whether the orchestrator's own table (services/orchestrator/route_callers.yaml, T-713) lets the service whose
    container a snippet runs in reach the route ``key``. D-1125: the stand-in took any service's token for
    ``GET /models``, and launch P2 stopped on the real box's 403 to the mail gateway."""
    import yaml

    doc = yaml.safe_load((IMAGE_ROOT / "services" / "orchestrator" / "route_callers.yaml").read_text(encoding="utf-8"))
    row = (doc.get("services") or {}).get(svc) or {}
    return any(key in (doc["groups"].get(g) or []) for g in row.get("groups") or [])


def refused(svc: str, key: str) -> bool:
    if may_call(svc, key):
        return False
    called(f"refused {svc} {key}")
    return True


def snippet(svc: str, text: str) -> int:
    """`docker compose exec -T <svc> python -` with a snippet of the VM script: its first line names it."""
    head = text.lstrip().splitlines()[0] if text.strip() else ""
    if not head.startswith("# tb-boxrun:"):
        print(f"box stand-in: a snippet without its name for {svc}", file=sys.stderr)
        return 2
    what, *rest = head.split(":", 1)[1].split()
    if what == "canary-gate":  # D2: GET /models with the service token, from a service's container (once | wait)
        mode = rest[0] if rest else "once"
        called(f"canary-gate {mode}")
        if "auth_headers()" not in text:
            print(json.dumps({"gate": {"error": "HTTP 401", "status": 401}}))  # the orchestrator's reads need the token
            return 3
        if refused(svc, "GET /models"):  # the orchestrator's 403 to a service outside the route's row
            print(json.dumps({"gate": {"error": "HTTP 403", "status": 403}}))
            return 3
        if flag("gate-401"):  # knob gate-401: the box refuses the token: a failure at once, never waited on
            print(json.dumps({"gate": {"error": "HTTP 401", "status": 401}}))
            return 3
        # the gate is open once step 07's canary is its result (D-916), unless a knob closes it: gate-closed opens
        # after the orchestrator's restart (its own canary at start), gate-never stays closed
        restarted = (BOX / "orchestrator-restarted").exists()
        ok = not flag("gate-never") and (not flag("gate-closed") or (mode == "wait" and restarted))
        if mode == "wait":
            print(json.dumps({"elapsed_s": 15, "running": False, "at": "t1", "allows_block": ok}))
        print(json.dumps({"gate": {"gate": "on", "allows_block": ok, "code": "ok" if ok else "none",
                                   "reason": "" if ok else "the model self-test (canary) has not run on this box yet",
                                   "running": False, "at": "t1" if restarted else "t0", "ok": ok, "cases": 54,
                                   "pair_correct": 52 if ok else None, "pair_decided_wrong": 0}}))  # fmt: skip
        return 0
    if what == "study-ready":
        called("study-ready")
        if refused(svc, "GET /rulesets/{ruleset}"):
            print(403)
            return 1
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
    if what == "g1-tokens":  # the judge server's /tokenize through model-guard (D-739): a stand-in tokenizer
        import base64
        import re

        called("g1-tokenize")
        b64 = re.search(r'b64decode\("([A-Za-z0-9+/=]+)"\)', text)
        msgs = json.loads(base64.b64decode(b64.group(1)).decode()) if b64 else []
        print(json.dumps({"ids": [standin_ids(m) for m in msgs], "errors": [], "url": "http://llm-service:8000/tokenize",
                          "keyed": True}))  # fmt: skip
        return 0
    if what == "screen-start":
        if refused(svc, "POST /jobs"):
            return 1
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
        if refused(svc, "GET /jobs/{job_id}"):
            return 1
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
    i = next(k for k, a in enumerate(argv) if a in ("ps", "exec", "restart", "stop", "start", "up", "run", "logs"))
    cmd, rest = argv[i], argv[i + 1 :]
    if cmd == "logs":  # the set's progress line and its services' lines (F23): an embed request and a screen stage
        called("compose-logs " + " ".join(a for a in rest if not a.startswith("-")))
        print('INFO: 172.18.0.9:0 - "POST /embed HTTP/1.1" 200 OK')
        print("orchestrator: screen stage S2b: 3 patients, embedder e-embed-1")
        return 0
    if cmd == "run":  # a one-off service command (the direct route's adapter keys-init)
        called("compose-run " + " ".join(a for a in rest if not a.startswith("-")))
        return 0
    if cmd == "up":  # the stack recreated on new settings (the acc group's settings step)
        called("compose-up " + " ".join(a for a in rest if not a.startswith("-")))
        return 0
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
            if svc == "orchestrator":
                (BOX / "orchestrator-restarted").touch()
        jsave(BOX / "stopped.json", sorted(down))
        return 0
    rest = [a for a in rest if a != "-T"]
    svc, prog = rest[0], rest[1:]
    if prog == ["python", "-"]:
        return snippet(svc, sys.stdin.read())
    if prog[:2] == ["python", "-"]:  # the accuracy run's onbox.py: its first line names it, its command follows
        return onbox(svc, sys.stdin.read(), prog[2:])
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


def mapped(argv: list[str]) -> list[str]:
    """``docker run`` arguments with each container path of a ``-v src:dst`` mount put back to its host path."""
    vols = [a.split(":")[:2] for k, a in enumerate(argv) if k and argv[k - 1] == "-v"]
    vols.sort(key=lambda v: -len(v[1]))
    out = []
    for a in argv:
        for src, dst in vols:
            if a == dst or a.startswith(dst + "/"):
                a = src + a[len(dst) :]
                break
        out.append(a)
    return out


def img_run(argv: list[str]) -> int:
    """`docker run ... <the box's python image> python -m tools.<name> ARGS` (img_tool): the box's tool, with its
    container paths put back to the host's."""
    i = argv.index("-m")
    name = argv[i + 1].removeprefix("tools.")
    return tool(name, mapped(argv)[i + 2 :])


def g1_prompts() -> int:
    """`docker run ... python -c '...tools.chat_template_check prompts...'`: the REAL prompts, with the venv."""
    import subprocess

    called("g1-prompts")
    code = (
        "import json; from tools.chat_template_check import prompts; print(json.dumps(prompts(), ensure_ascii=False))"
    )
    env = {**os.environ, "PYTHONPATH": f"{IMAGE_ROOT / 'libs'}:{IMAGE_ROOT}"}
    return subprocess.run([os.environ["TB_BOX_PY"], "-c", code], env=env, check=False).returncode


def g1_hf(argv: list[str]) -> int:
    """The tokenizer side in the model server's image (`--entrypoint python3 ... -m tools.chat_template_check hf`):
    the stand-in tokenizer over the prompts; the folder's template is the passed one unless knob tokens-differ."""
    import hashlib

    called("g1-hf")
    m = mapped(argv)
    prompts = json.loads(Path(arg(m, "--prompts")).read_text())
    out = Path(arg(m, "--out"))
    ids = [standin_ids(x) for x in prompts]
    folder_tpl = "{{ standin template }}" + (" differs" if flag("tokens-differ") else "")
    sha = hashlib.sha256(folder_tpl.encode()).hexdigest()
    passed_sha = hashlib.sha256(b"{{ standin template }}").hexdigest()
    if flag("tokens-differ"):
        ids[0] = [*ids[0][:-1], 0]
    out.write_text(json.dumps({"model": arg(m, "--model"), "transformers": "standin", "folder_template_sha256": sha,
                               "folder_template_chars": len(folder_tpl), "ids": ids, "ids_passed": ids,
                               "passed_template_sha256": passed_sha}))  # fmt: skip
    (out.parent / "chat_template.folder.jinja").write_text(folder_tpl)
    return 0


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


# ---------------------------------------------------------------- the accuracy group (onbox.py, the data, the limits)
def acc_limits() -> int:
    """settings.yaml's rate_limits_per_day for the run, as the image's python would write it (then --check)."""
    lim = BOX / "limits.json"
    before = jload(lim, {})
    jsave(lim, {**before, "FEAS": 0, "SCREEN": 0})
    called("acc-limits")
    print({"before": before, "after": jload(lim, {})})
    return 0


def acc_data(argv: list[str]) -> int:
    """`docker run ... -v <host>:/work ... python -m tools.public_accuracy fetch|build ...`: acc_fixture.py, with the
    host folder in place of /work."""
    import subprocess

    work = next(
        (x.split(":", 1)[0] for k, x in enumerate(argv) if k and argv[k - 1] == "-v" and x.endswith(":/work")), ""
    )
    i = argv.index("tools.public_accuracy")
    rest = [work if x == "/work" else x for x in argv[i + 1 :]]
    called("acc-data " + " ".join(rest[:3]))
    fixture = Path(__file__).with_name("acc_fixture.py")
    return subprocess.run([os.environ["TB_BOX_PY"], str(fixture), *rest], check=False).returncode


def _env_val(name: str) -> str:
    env = S / "box-root" / "deploy" / ".env"
    vals = (
        [x.split("=", 1)[1] for x in env.read_text().splitlines() if x.startswith(name + "=")] if env.exists() else []
    )
    return vals[-1] if vals else ""


def _env_of_box() -> str:
    env = S / "box-root" / "deploy" / ".env"
    vals = [x.split("=", 1)[1] for x in env.read_text().splitlines() if x.startswith("TB_ENV=")] if env.exists() else []
    return vals[-1] if vals else "PRODUCTION"


def _acc_job(kind: str, rs: str, mid: str) -> dict[str, Any]:
    """A job of the stand-in box for a mailed request: one per message id (a mail delivered twice is one job)."""
    by_mid = jload(BOX / "acc-mids.json", {})
    if mid in by_mid:
        called(f"acc-send {kind} {rs} dup")
        old: dict[str, Any] = jload(BOX / "acc-jobs" / f"{by_mid[mid]}.json", {})
        return old
    n = len(by_mid) + 1
    first = sorted(jload(BOX / "acc-first.json", {}).values())
    job = {"id": f"acc-job-{n}", "kind": kind, "ruleset": rs, "start": time.time(), "version": "1.0.0"}
    if kind == "FEAS" and flag("acc-tripwire") and rs in first:
        job["fail"] = (
            "ir_extract: the model did not return usable criteria (tb_refusal phi_tripwire: PHI tripwire hit on a "
            "D1 call (PASSPORT)); send the protocol again"
        )
    by_mid[mid] = job["id"]
    jsave(BOX / "acc-mids.json", by_mid)
    jsave(BOX / "acc-jobs" / f"{job['id']}.json", job)
    called(f"acc-send {kind} {rs} new")
    return job


def _acc_state(job: dict[str, Any]) -> tuple[str, Any]:
    if time.time() - job["start"] < float(knob("acc-job-seconds", "0.3")):
        return "running", None
    if job.get("fail"):
        return "failed", job["fail"]
    return ("awaiting_approval" if job["kind"] == "FEAS" else "done"), None


def _acc_outputs(job: dict[str, Any]) -> dict[str, bytes]:
    import io
    import zipfile

    rs, v = job["ruleset"], job["version"]
    if job["kind"] == "FEAS":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for i, (kind, text) in enumerate((("inclusion", "Type 2 diabetes"), ("exclusion", "Pregnancy")), 1):
                z.writestr(f"{rs}/ir/{kind[:3]}-{i}.json", json.dumps(
                    {"id": f"{kind[:3]}-{i}", "kind": kind, "class": "note", "text": {"source": text},
                     "logic": {"domain": "condition"}}))  # fmt: skip
        return {
            f"review_{rs}_v{v}_r1.xlsx": b"PK standin review workbook",
            f"ruleset_{rs}_v{v}-draft.zip": buf.getvalue(),
        }
    if job["kind"] == "SCREEN":
        import csv

        pract = job.get("pract", "")
        appts = S / "feed" / "acc" / "appointment.csv"
        mrns = sorted({r["mrn"] for r in csv.DictReader(appts.open(encoding="utf-8-sig")) if r["staff_id"] == pract})
        rows: list[dict[str, Any]] = []
        excl: list[dict[str, Any]] = []
        if flag("acc-screen-empty"):  # F22: the screen finishes and answers nobody (the phase-C tcga of 2026-11-15)
            mrns = []
        for i, m in enumerate(mrns):
            pid = _pid(m)
            if i % 2:  # the product's excluded list (screen.excluded_doc): the excluding criteria, no "verdict" key
                excl.append({"pid": pid, "criteria": [{"id": "exc-2", "source": "notes", "quote": "pregnant"}],
                             "actions": []})  # fmt: skip
            else:
                rows.append({"pid": pid, "tier": "high", "actions": [],
                             "criteria": [{"id": "exc-2", "verdict": "pass", "basis": "pair", "evidence": None}]})  # fmt: skip
        return {f"candidate_list_{rs}_v{v}.json": json.dumps({"rows": rows}).encode(),
                f"excluded_{rs}_v{v}.json": json.dumps({"rows": excl}).encode()}  # fmt: skip
    return {}


def _pid(mrn: str) -> str:
    import hashlib

    return hashlib.sha256(f"standin-site-key:{mrn}".encode()).hexdigest()[:32]


def onbox(svc: str, text: str, args: list[str]) -> int:
    """tools/public_accuracy/onbox.py piped into a container: the stand-in answers each command as the box would."""
    import base64

    head = text.lstrip().splitlines()[0] if text.strip() else ""
    if head != "# tb-boxrun: acc" or not args:
        print(f"box stand-in: not onbox.py for {svc}", file=sys.stderr)
        return 2
    cmd = args[0]
    raw = args[1] if len(args) > 1 else ""
    if not raw:  # F30: a long argument comes in the program text (_ONBOX_ARG_B64 = '...'), as onbox.py reads it
        import re

        m = re.search(r"^_ONBOX_ARG_B64 = '([A-Za-z0-9+/=]*)'$", text, re.M)
        raw = m.group(1) if m else ""
        if m:
            called(f"onbox-long-arg {svc} {cmd}")
    a = json.loads(base64.b64decode(raw).decode()) if raw else {}
    called(f"onbox {svc} {cmd}")
    if cmd == "env":
        lim = jload(BOX / "limits.json", {})
        print(json.dumps({"environment": _env_of_box(), "senders": ["crc1@hospa.test"], "reviewers": ["pi@hospa.test"],
                          "intake": "trialbox@hospa.test", "authserv": "mx.acc.invalid", "require_spf_dkim": True,
                          "rate_limit_per_sender_per_day": 20, "rate_limits_per_day": lim,
                          "mail_per_recipient_per_day": _env_val("TB_MAIL_PER_RECIPIENT_PER_DAY"),
                          "jobs_per_sender_per_day": _env_val("TB_JOBS_PER_SENDER_PER_DAY"),
                          "tripwire_settings": {"TB_GATEWAY_PHI_TRIPWIRE": _env_val("TB_GATEWAY_PHI_TRIPWIRE")},
                          "data_class": ""}))  # fmt: skip
        return 0
    if cmd == "routes":
        env = _env_of_box()
        rows = []
        for role, dc in a["calls"]:
            if role == "judge" and flag("acc-blocked"):
                rows.append({"role": role, "class": dc, "routes": False,
                             "why": f"{dc} data is not allowed in the {env} environment (ceiling D2)"})  # fmt: skip
            else:
                b = [{"alias": "j-workhorse", "build": "standin-judge-1", "routes": True}]
                if role == "judge":
                    b.append({"alias": "v-verifier", "build": "standin-verifier-1", "routes": True})
                rows.append({"role": role, "class": dc, "route": "standin", "builds": b, "routes": True})
        print(json.dumps({"environment": env, "profile": "P-PRO6000", "routes": rows,
                          "served_prompts": ["ir_extract@3", "judge@5"] if env != "PRODUCTION" else ["ir_extract@2", "judge@4"]}))  # fmt: skip
        return 0
    if cmd == "embedder":
        print(json.dumps({"embedder": "hash stand-in (HashEmbedder): S2b cannot rank; #589 is not in this build",
                          "hash_in_screen": True}))  # fmt: skip
        return 0
    if cmd == "send":
        subj = str(a["subject"]).split()
        kind, rs = subj[0], subj[1]
        firsts = jload(BOX / "acc-first.json", {})
        if kind == "FEAS":
            st = rs.rstrip("0123456789")  # the set's prefix + NCT: the first protocol of each set
            firsts.setdefault(st[:1], rs)
            jsave(BOX / "acc-first.json", firsts)
        job = _acc_job(kind, rs, str(a["mid"]))
        for opt in subj[2:]:
            if opt.startswith("pract="):
                job["pract"] = opt.split("=", 1)[1]
                jsave(BOX / "acc-jobs" / f"{job['id']}.json", job)
        print(json.dumps({"folder": "Processed", "action": "job", "job": job["id"], "reason": ""}))
        return 0
    if cmd == "wait":
        job = jload(BOX / "acc-jobs" / f"{a['job']}.json", None)
        if job is None:
            return 1
        end = time.time() + float(a["timeout_s"])
        while True:
            state, err = _acc_state(job)
            print(f"job {job['id']} {state}", flush=True)
            if state in a["until"] or time.time() > end:
                break
            time.sleep(0.1)
        outs = [{"filename": k, "key": f"standin/{k}"} for k in _acc_outputs(job)] if state != "running" else []
        print(json.dumps({"job": job["id"], "type": job["kind"], "ruleset": job["ruleset"],
                          "ruleset_version": job["version"], "state": state, "error": err, "outputs": outs,
                          "metrics": {}, "waited": "ended" if state in a["until"] else "timeout"}))  # fmt: skip
        return 0
    if cmd == "fetch":
        job = jload(BOX / "acc-jobs" / f"{a['job']}.json", {})
        if job.get("fail"):
            print(json.dumps({"job": a["job"], "files": {}}))
            return 0
        files = {k: base64.b64encode(v).decode() for k, v in _acc_outputs(job).items()
                 if k.endswith(tuple(a["suffixes"])) and k.startswith(tuple(a.get("prefixes") or ("",)))}  # fmt: skip
        print(json.dumps({"job": a["job"], "files": files}))
        return 0
    if cmd == "pidmap":
        print(json.dumps({m: _pid(m) for m in a["mrns"]}))
        return 0
    if cmd == "audit":
        n = len(jload(BOX / "acc-mids.json", {}))
        print(json.dumps({"since": a.get("since"), "calls_by_prompt": {"ir_extract@3": n, "judge@5": 2 * n},
                          "refusals": {"phi_tripwire": 1} if flag("acc-tripwire") else {}, "refusals_by_job": {}}))  # fmt: skip
        return 0
    if cmd == "traces":  # the trace store's raw answers since a time: one synthetic row per mailed request
        mids = jload(BOX / "acc-mids.json", {})
        rows = [{"call_id": f"standin-call-{i}", "prompt": "[synthetic]", "output": '{"verdict": "met"}'}
                for i, _ in enumerate(mids)]  # fmt: skip
        print(json.dumps({"since": a.get("since"), "calls": len(rows), "traces": rows}))
        return 0
    print(f"box stand-in: onbox {cmd} is not rehearsed", file=sys.stderr)
    return 2


# ---------------------------------------------------------------- the box's tools
def tool(name: str, argv: list[str]) -> int:
    if not (BOX / "wizard-done").exists() and not (S / "box-root" / "deploy" / "site" / "box" / "applied").exists():
        print(f"{name}: the box is not set up (the wizard has not run)", file=sys.stderr)
        return 1
    if name == "pin_model":
        if "--install" in argv:
            called("pin")
            if "--out" in argv:  # the direct route: pin_model --install in the image, the site pins written
                Path(arg(argv, "--out")).parent.mkdir(parents=True, exist_ok=True)
                pins = "".join(f"  {b}: {{sha256: '{'a' * 64}', status: candidate}}\n"
                               for b in ("gemma-4-26b-a4b-it-rtxpro6000", "qwen3.5-9b-rtxpro6000", "e-embed-1"))  # fmt: skip
                Path(arg(argv, "--out")).write_text("builds:\n" + pins)
                return 0
            roles = sorted(p.name for p in Path(arg(argv, "--models-root")).iterdir() if p.is_dir())
            return 0 if roles == ["judge", "verifier"] else 1
        if "--promote" in argv:
            called("promote " + arg(argv, "--promote"))
            if json.loads(Path(arg(argv, "--record")).read_text()).get("status") != "passed":
                return 1
            jsave(BOX / "promoted.json", [*jload(BOX / "promoted.json", []), arg(argv, "--promote")])
            return 0
        if "--verify-all" in argv:
            called("verify-weights")
            return 0
        if "--resolve" in argv:  # D-738: one line a role and class; a candidate does not route in PRODUCTION
            called("resolve")
            by = {b.split("-")[1]: b for b in jload(BOX / "promoted.json", [])}
            print("PRODUCTION, topology A, profile P-PRO6000, site pins /d/site/registry.site.yaml")
            for role, rec in (("judge", "judge"), ("second_opinion", "verifier")):
                for cls in ("D1", "D3"):
                    b = by.get(rec)
                    print(f"{role} {cls} -> {b} (j-workhorse@serving, served standin; route patient)" if b
                          else f"{role} {cls} -> none (route patient): j-workhorse@serving: no_eligible_build")  # fmt: skip
            return 0
    if name == "medtxt_eval":
        called("medtxt-fetch")
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
        if "--box" not in argv:
            print("qualify: the box run asks for --box (D-737)", file=sys.stderr)
            return 2
        qrec: dict[str, Any] = {
            "standin": True,
            "status": "passed",
            "failed_steps": [],
            "builds": {
                "judge": {"build_id": "standin-judge-1", "registry_status": "candidate"},
                "verifier": {"build_id": "standin-verifier-1", "registry_status": "candidate"},
            },
            "steps": {"pin": {"status": "passed", "reason": "stand-in"}},
        }
        if flag("fail-qualify"):  # a record that failed a gate: a result in validation mode, a stop in production
            qrec.update(status="failed", failed_steps=["schema"])
            qrec["steps"]["schema"] = {"status": "failed", "reason": "stand-in gate: schema failures 3 of 54"}
        out = Path(arg(argv, "--out"))
        if out.is_dir():  # qualify's --out is the records' folder (<profile>-<build>-<time>.json in it)
            out = out / "rtxpro6000-standin-judge-1-20261120T000000Z.json"
        out.write_text(json.dumps(qrec))
        return 1 if flag("fail-qualify") else 0
    if name == "trialbox" and argv[:1] in (["secrets"], ["db-up"]):  # the direct route's host tools
        called(f"trialbox-{argv[0]}")
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
        if "tools.public_accuracy" in a:
            return acc_data(a[1:])
        if any("optional_tables" in x for x in a):  # the site's optional tables for a public feed (54)
            called("acc-optional")
            print(json.dumps({"after": {"optional_tables": ["claim", "lab"]}}))
            return 0
        if any("settings_wizard" in x for x in a):
            return acc_limits()
        if "--entrypoint" in a and "tools.chat_template_check" in a:
            return g1_hf(a[1:])
        if "-c" in a and "chat_template_check" in a[a.index("-c") + 1]:
            return g1_prompts()
        if "-m" in a and a[a.index("-m") + 1].startswith("tools."):
            return img_run(a[1:])
        if a[-2:] == ["python", "-"]:  # a snippet on stdin in the box image (07g's gate, with the operator token)
            return snippet("box-image", sys.stdin.read())
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
