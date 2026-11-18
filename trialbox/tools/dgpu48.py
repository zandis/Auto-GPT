"""The DRAFT 48 GB card class (cards 24-5 and 24-6, root review 24): its arithmetic, and the measuring run. UNMEASURED.

``deploy/dgpu48-profile.yaml`` holds the options (both models resident at 32k, the same at 16k, the judge alone, the
verifier alone, and two that are arithmetic only); ``deploy/docker-compose.dgpu48.yml`` serves them. Nothing here is
a supported profile: install.sh and poc.sh refuse ``dgpu48``, and this tool starts it only with
``TB_UNMEASURED_DGPU48_MEASURING_RUN=1``.

    python3 tools/dgpu48.py arith                         # each option's card arithmetic from the 96 GB figures
    TB_UNMEASURED_DGPU48_MEASURING_RUN=1 python3 tools/dgpu48.py measure --option pair-32k [--dry-run]

**arith** carries the 96 GB card's measured figures (``basis``) to the class's card: each server's budget (its
fraction of the card), its cache after the memory it needs without one, the tokens that cache holds, whether one
sequence of the full context fits, the memory outside the budgets, the spare at peak, and the slack (how much more the
judge may need on this card than on the measured one before the option fails). The planner check (``--planner``,
the project environment) asks ``tools.box.plan.memory_caps`` about the host.

**measure** runs on the owner's machine, after the engine probe (``tools/engine_probe.py``): it refuses without the
switch, on a card outside the class, with the box running, without the weights, or when the probe found no form of
the engine. It starts only the option's model servers from the overlay (with the engine form the probe chose),
samples card memory and each container's host memory, takes the serving record with the repository's own
``tools/serving_config.py capture`` (the tool that took the 96 GB record), runs the pair canary (``tools/canary.py``,
54 stored cases) inside ``trialbox-py`` when the option serves the judge, and stops the servers. It writes, in
``--out-dir``: ``serving_config.dgpu48.<option>.json`` (the record, the 96 GB record's shape; the host name, device
UUIDs and host paths withheld), ``canary.<option>.json`` and ``measure.<option>.json`` (the summary to paste back).
Standard library and PyYAML only, Python 3.10 or newer (Ubuntu 22.04's python3 with python3-yaml, RUNBOOK §28
step 3).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__" and str(ROOT) not in sys.path:  # `python3 tools/dgpu48.py` on the host: tools.engine_probe
    sys.path.insert(0, str(ROOT))
PROFILE = ROOT / "deploy" / "dgpu48-profile.yaml"
OVERLAY = "deploy/docker-compose.dgpu48.yml"
SWITCH = "TB_UNMEASURED_DGPU48_MEASURING_RUN"
SERVICE = {"judge": "llm-service", "verifier": "llm-verifier"}
ALIAS = {"judge": "llm-service-vllm", "verifier": "llm-verifier-vllm"}
DIR_VAR = {
    "judge": ("JUDGE_MODEL_DIR", "gemma-4-26b-a4b-it-4bit"),
    "verifier": ("VERIFIER_MODEL_DIR", "qwen3.5-9b-4bit"),
}
TEMPLATE = ("JUDGE_CHAT_TEMPLATE", "chat-templates/gemma-4-26b-a4b-it/chat_template.jinja")
BACKEND_NET = "trialbox-model-backend"  # deploy/docker-compose.yml model-backend-net (internal, fixed name)
PROJECT = "trialbox"  # deploy/docker-compose.yml name:
COMPAT_DIR = "/usr/local/cuda/compat"
STORED_CANARY = "53 of 54 for the judge on the 96 GB card, 2026-11-08 (superseded record: a comparison, not evidence)"
WITHHELD = "withheld (the owner's machine; a measuring run)"
Runner = Callable[[list[str], int, dict[str, str] | None], tuple[int, str, str]]


def load(path: Path = PROFILE) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "tb-dgpu48-profile/1":
        raise ValueError(f"{path}: not a tb-dgpu48-profile/1 file")
    return doc


def option(doc: dict[str, Any], oid: str) -> dict[str, Any]:
    for o in doc["options"]:
        if o["id"] == oid:
            return dict(o)
    raise KeyError(f"no option {oid!r}: {', '.join(o['id'] for o in doc['options'])}")


# ------------------------------------------------------------------------------------------------ the arithmetic
def arith(doc: dict[str, Any], o: dict[str, Any], card_mib: int | None = None) -> dict[str, Any]:
    """One option's card memory from the measured basis, in MiB (see the module's text)."""
    card = int(card_mib or doc["card"]["memory_total_mib"])
    basis, env = doc["basis"], o.get("env") or {}
    out: dict[str, Any] = {"option": o["id"], "card_mib": card, "servers": {}}
    used = 0.0
    fits = True
    slack = []
    for role in o["serves"]:
        b = basis[role]
        prefix = "JUDGE" if role == "judge" else "VERIFIER"
        if f"{prefix}_GPU_MEM_UTIL" not in env:
            return {"option": o["id"], "card_mib": card, "scripted": False, "servers": {}, "fits": None}
        util = float(env[f"{prefix}_GPU_MEM_UTIL"])
        length = int(env[f"{prefix}_MAX_LEN"])
        budget = util * card
        cache = budget - b["inside_mib"]
        tokens = int(cache * 1024 / b["cache_kib_per_token"]) if cache > 0 else 0
        one_seq = length * b["cache_kib_per_token"] / 1024  # MiB for one sequence of the full context
        ok = cache >= one_seq
        fits = fits and ok
        used += budget + b["outside_mib"]
        slack.append(cache - one_seq)
        out["servers"][role] = {
            "util": util,
            "budget_mib": round(budget),
            "inside_mib": b["inside_mib"],
            "outside_mib": b["outside_mib"],
            "cache_mib": round(cache),
            "cache_tokens": tokens,
            "max_len": length,
            "one_sequence_mib": round(one_seq),
            "one_sequence_fits": ok,
        }
    spare = card - used
    out["used_mib"] = round(used)
    out["spare_mib"] = round(spare)
    out["min_free_mib"] = basis["min_free_mib"]
    out["fits"] = bool(fits and spare >= basis["min_free_mib"])
    # how much more memory than on the measured card the servers may need before the option fails: within a budget
    # it comes out of the cache, outside the budgets out of the spare
    out["slack_mib"] = round(min([*slack, spare - basis["min_free_mib"]]))
    return out


def planner(ram_gib: float, profile: str = "dgpu48") -> dict[str, Any]:
    """``tools.box.plan.memory_caps`` on this host (the project environment): accepted with which factor, or why not,
    and the least memory for the caps as the overlay sets them (factor 1) and for the planner's floor (0.5)."""
    from tools.box import plan as bp  # the project environment (tb_common); not needed by `measure`

    try:
        caps, notes = bp.memory_caps(ram_gib, profile)
        res: dict[str, Any] = {"ram_gib": ram_gib, "accepted": True, "notes": notes, "caps": caps}
    except bp.PlanError as exc:
        res = {"ram_gib": ram_gib, "accepted": False, "notes": [str(exc)], "caps": {}}
    files = [bp.DEPLOY / "docker-compose.yml", bp.DEPLOY / "docker-compose.identity.yml", ROOT / OVERLAY]
    var, fixed = bp.compose_caps(files)
    total = sum(var.values())
    # memory_caps: avail = ram - max(4, ram/10) - fixed; factor = avail / total
    res["least_gib_unshrunk"] = round(max((total + fixed) / 0.9, total + fixed + 4), 1)
    res["least_gib_floor"] = round(max((total * bp.MIN_SERVICE_SHARE + fixed) / 0.9,
                                       total * bp.MIN_SERVICE_SHARE + fixed + 4), 1)  # fmt: skip
    res["model_caps_gib"] = {k: v for k, v in var.items() if k in ("TB_MEM_LLM", "TB_MEM_VERIFIER")}
    return res


def arith_table(doc: dict[str, Any], card_mib: int | None = None) -> str:
    rows = [f"card {card_mib or doc['card']['memory_total_mib']:,} MiB; basis: the 96 GB card's figures "
            f"({doc['basis']['source']})", "",
            f"{'option':<18} {'server':<9} {'util':>5} {'budget':>8} {'cache':>7} {'tokens':>8} {'ctx':>6} "
            f"{'1 seq':>6} {'used':>7} {'spare':>6} {'slack':>6} fits"]  # fmt: skip
    for o in sorted(doc["options"], key=lambda x: x["order"]):
        a = arith(doc, o, card_mib)
        if not a["servers"]:
            rows.append(f"{o['id']:<18} {'-':<9} (not scripted: arithmetic in the profile's text only)")
            continue
        for i, (role, s) in enumerate(a["servers"].items()):
            tail = (f"{a['used_mib']:>7,} {a['spare_mib']:>6,} {a['slack_mib']:>6,} {'yes' if a['fits'] else 'NO'}"
                    if i == 0 else "")  # fmt: skip
            rows.append(f"{o['id'] if i == 0 else '':<18} {role:<9} {s['util']:>5.2f} {s['budget_mib']:>8,} "
                        f"{s['cache_mib']:>7,} {s['cache_tokens']:>8,} {s['max_len']:>6} {s['one_sequence_mib']:>6,} "
                        f"{tail}")  # fmt: skip
    rows += ["", "MiB throughout. used = the budgets + each server's memory outside its budget; spare = card - used; "
             "slack = how much more than on the 96 GB card the servers may need before the option fails."]  # fmt: skip
    return "\n".join(rows)


# ------------------------------------------------------------------------------------------------ the measuring run
class Refused(RuntimeError):
    pass


def _real_runner(cmd: list[str], timeout: int, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False,
                           env={**os.environ, **env} if env else None)  # fmt: skip
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout} s"
    return p.returncode, p.stdout, p.stderr


def models_dir(environ: dict[str, str], root: Path = ROOT) -> Path:
    """TB_MODELS_DIR as typed (relative to the checkout), else deploy/models: the folder compose mounts."""
    m = environ.get("TB_MODELS_DIR") or ""
    if not m:
        return root / "deploy" / "models"
    p = Path(m)
    return p if p.is_absolute() else (root / p)


def engine_from_probe(probe: dict[str, Any] | None, forced: str = "") -> dict[str, Any]:
    """The engine form to run (the probe's verdict, or ``--engine``): its compose variables and whether it is the
    pinned engine. Refused when the probe found none and nothing was forced."""
    from tools import engine_probe as ep  # the same folder; standard library only

    use = forced or ((probe or {}).get("verdict") or {}).get("use")
    if not use:
        raise Refused("the engine probe found no form of the engine that runs on this card (or no probe file): run "
                      "tools/engine_probe.py first (RUNBOOK §29 step 2); --engine forces one")  # fmt: skip
    forms = {
        "pinned": {"env": {}, "libs_first": False, "pinned_engine": True},
        "pinned+compat": {"env": {"VLLM_ENABLE_CUDA_COMPATIBILITY": "1"}, "libs_first": False, "pinned_engine": True},
        "pinned+libs": {"env": {}, "libs_first": True, "pinned_engine": True},
        "cu129": {"env": {"VLLM_IMAGE": ep.CU129}, "libs_first": False, "pinned_engine": False},
    }
    if use not in forms:
        raise Refused(f"unknown engine form {use!r}: one of {', '.join(forms)}")
    return {"use": use, **forms[use]}


def compose(files: list[str]) -> list[str]:
    out = ["docker", "compose", "--project-directory", "deploy"]
    for f in files:
        out += ["-f", f]
    return [*out, "--profile", "gpu"]


def preflight(
    run: Runner, doc: dict[str, Any], o: dict[str, Any], environ: dict[str, str], root: Path = ROOT
) -> dict[str, Any]:
    """Everything the run needs, checked before anything starts; Refused names what is missing."""
    if environ.get(SWITCH) != "1":
        raise Refused(f"{SWITCH}=1 is not set: dgpu48 is UNMEASURED and only a measuring run starts it (RUNBOOK §29)")
    if not o.get("scripted"):
        raise Refused(f"option {o['id']} is arithmetic only (not scripted in this card)")
    rc, out, _ = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                     60, None)  # fmt: skip
    if rc != 0 or not out.strip():
        raise Refused("nvidia-smi finds no card")
    cells = [c.strip() for c in out.strip().splitlines()[0].split(",")]
    total = int(cells[1]) if len(cells) > 1 and cells[1].isdigit() else 0
    lo, hi = doc["card"]["memory_range_mib"]
    if not lo <= total <= hi:
        raise Refused(f"the card has {total} MiB: dgpu48 is for one card of {lo} to {hi} MiB")
    if not (root / "deploy" / ".env").exists():
        raise Refused("deploy/.env is missing: start the stub box once first (deploy/poc.sh, RUNBOOK §28 step 7)")
    rc, out, _ = run(["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}"], 60, None)
    if rc != 0:
        raise Refused("docker does not answer")
    if out.strip():
        raise Refused("the box is running: stop it first (deploy/poc.sh down); the measuring run needs the memory")
    models = models_dir(environ, root)
    for role in o["serves"]:
        var, default = DIR_VAR[role]
        d = models / (environ.get(var) or default)
        if not (d / "config.json").is_file():
            raise Refused(f"no {role} weights in {d} (no config.json): RUNBOOK §27 'The weights'")
    if "judge" in o["serves"]:
        tpl = models / (environ.get(TEMPLATE[0]) or TEMPLATE[1])
        if not tpl.is_file():
            raise Refused(f"no chat template {tpl} (RUNBOOK §27 'The weights')")
    return {"card": cells[0], "memory_total_mib": total, "driver": cells[2] if len(cells) > 2 else "",
            "models": models}  # fmt: skip


def libs_override(run: Runner, image: str, workdir: Path) -> Path:
    """A compose file for this run only (in the output folder, not the checkout): the engine's compatibility
    libraries first in its LD_LIBRARY_PATH, the image's own folders after them (the probe's ``pinned+libs``)."""
    rc, out, _ = run(["docker", "image", "inspect", "--format", "{{json .Config.Env}}", image], 60, None)
    own = ""
    if rc == 0:
        try:
            own = next((e.split("=", 1)[1] for e in json.loads(out) if e.startswith("LD_LIBRARY_PATH=")), "")
        except ValueError:
            own = ""
    value = f"{COMPAT_DIR}:{own}" if own else COMPAT_DIR
    f = workdir / "dgpu48-libs-first.yml"
    body = {"services": {s: {"environment": {"LD_LIBRARY_PATH": value}} for s in SERVICE.values()}}
    f.write_text("# written by tools/dgpu48.py for one measuring run\n" + yaml.safe_dump(body), encoding="utf-8")
    return f


def plan_commands(o: dict[str, Any], engine: dict[str, Any], files: list[str], models: Path,
                  key: str = "") -> dict[str, Any]:  # fmt: skip
    """The run's commands and the environment compose reads: pure, so the dry run and the tests see them."""
    env = {**{k: str(v) for k, v in (o.get("env") or {}).items()}, **engine["env"], "TB_MODELS_DIR": str(models)}
    services = [SERVICE[r] for r in o["serves"]]
    base = compose(files)
    up = [*base, "up", "-d", "--wait", "--wait-timeout", "2400"]
    if o["serves"] == ["verifier"]:
        up.append("--no-deps")  # the verifier waits for a judge in the overlay; alone it has none
    canary = None
    if "judge" in o["serves"]:
        canary = ["docker", "run", "--rm", "--network", BACKEND_NET, "-e", "TB_GPU_KEY", "trialbox-py:1.0.0",
                  "python", "-m", "tools.canary", "--judge-url", f"http://{ALIAS['judge']}:8000/v1"]  # fmt: skip
        if "verifier" in o["serves"]:
            canary += ["--verifier-url", f"http://{ALIAS['verifier']}:8000/v1"]
    return {
        "env": env,
        "up": [*up, *services],
        "ps": [[*base, "ps", "-q", s] for s in services],
        "canary": canary,
        "canary_env": {"TB_GPU_KEY": key or "measuring-run-no-key"},
        "down": [*base, "rm", "-sf", *services],
    }


def sanitize(rec: dict[str, Any], models: Path) -> dict[str, Any]:
    """The record as public text: no host name, no device UUID, no host path (the 96 GB record's shape kept)."""
    out: dict[str, Any] = json.loads(json.dumps(rec))
    out["host"] = WITHHELD
    for s in out.get("servers") or []:
        if s.get("gpu_devices"):
            s["gpu_devices"] = ["GPU-<withheld>" if str(d).startswith("GPU-") else "<withheld>"
                                for d in s["gpu_devices"]]  # fmt: skip
        md = str(s.get("model_dir") or "")
        if md.startswith(str(models)):
            s["model_dir"] = "/models" + md[len(str(models)) :]
        elif md and not md.startswith("/models"):
            s["model_dir"] = "<withheld>/" + Path(md).name
    return out


_KV = re.compile(r"Available KV cache memory: ([0-9.]+) GiB|GPU KV cache size: ([0-9,]+) tokens")


def kv_lines(log: str) -> dict[str, Any]:
    """The engine's own start-up lines: cache memory and tokens (what the arithmetic predicted)."""
    got: dict[str, Any] = {}
    for m in _KV.finditer(log or ""):
        if m.group(1):
            got["kv_cache_gib"] = float(m.group(1))
        if m.group(2):
            got["kv_cache_tokens"] = int(m.group(2).replace(",", ""))
    return got


class Sampler:
    """Card memory every 2 s and each container's host memory every 10 s, highest seen (a thread)."""

    def __init__(self, run: Runner, names: list[str]) -> None:
        self.run, self.names = run, names
        self.card_peak_mib = 0
        self.host_peak_mib: dict[str, float] = {}
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._t.start()

    def stop(self) -> None:
        self._stop.set()
        self._t.join(timeout=30)

    def sample(self) -> None:
        rc, out, _ = self.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], 30, None)
        if rc == 0 and out.strip().splitlines() and out.strip().splitlines()[0].strip().isdigit():
            self.card_peak_mib = max(self.card_peak_mib, int(out.strip().splitlines()[0]))
        if not self.names:
            return
        rc, out, _ = self.run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}", *self.names],
                              60, None)  # fmt: skip
        for line in out.splitlines() if rc == 0 else []:
            parts = line.split()
            if len(parts) >= 2:
                mib = to_mib(parts[1])
                if mib is not None:
                    self.host_peak_mib[parts[0]] = max(self.host_peak_mib.get(parts[0], 0.0), mib)

    def _loop(self) -> None:
        n = 0
        while not self._stop.is_set():
            try:
                if n % 5 == 0:
                    self.sample()
                else:
                    self._card_only()
            except Exception:  # a sample that fails is skipped; the run goes on
                pass
            n += 1
            self._stop.wait(2)

    def _card_only(self) -> None:
        names, self.names = self.names, []
        try:
            self.sample()
        finally:
            self.names = names


def to_mib(text: str) -> float | None:
    m = re.match(r"^([0-9.]+)\s*([KMGT]i?B)$", text.strip())
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2)[0]
    return round(n * {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}[unit], 1)


def measure(run: Runner, oid: str, out_dir: Path, probe_file: Path | None, forced_engine: str = "",
            dry_run: bool = False, keep: bool = False, environ: dict[str, str] | None = None,
            say: Callable[[str], None] = print, root: Path = ROOT) -> dict[str, Any]:  # fmt: skip
    """The measuring run of one option (see the module's text). Returns the summary written to measure.<option>.json."""
    environ = dict(os.environ if environ is None else environ)
    doc = load()
    o = option(doc, oid)
    probe = None
    if probe_file and probe_file.is_file():
        probe = json.loads(probe_file.read_text(encoding="utf-8"))
    engine = engine_from_probe(probe, forced_engine)
    summary: dict[str, Any] = {
        "schema": "tb-dgpu48-measure/1",
        "status": "UNMEASURED profile; a measuring run, not a profile",
        "option": oid,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 (the host's Python 3.10)
        "engine": dict(engine),
        "predicted": arith(doc, o),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    files = ["deploy/docker-compose.yml", OVERLAY]
    if dry_run:
        models = models_dir(environ, root)
        if engine["libs_first"]:
            files.append(str(out_dir / "dgpu48-libs-first.yml"))
        cmds = plan_commands(o, engine, files, models)
        say(f"dry run: option {oid}, engine {engine['use']}; nothing is started")
        say("environment: " + " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(cmds["env"].items())))
        for key in ("up", "canary", "down"):
            if cmds[key]:
                say(f"{key}: " + " ".join(shlex.quote(x) for x in cmds[key]))
        say(f"record: {sys.executable} tools/serving_config.py capture --container judge=<llm-service container> "
            f"--container verifier=<llm-verifier container> --models-dir {models} --out <record>")  # fmt: skip
        summary["dry_run"] = True
        summary["commands"] = {k: cmds[k] for k in ("up", "canary", "down")}
        return summary
    facts = preflight(run, doc, o, environ, root)
    models = facts["models"]
    summary["card"] = {k: facts[k] for k in ("card", "memory_total_mib", "driver")}
    summary["predicted"] = arith(doc, o, facts["memory_total_mib"])
    if engine["libs_first"]:
        image = environ.get("VLLM_IMAGE") or _pinned_image()
        files.append(str(libs_override(run, image, out_dir)))
    key = _vllm_key(root)
    cmds = plan_commands(o, engine, files, models, key)
    if engine["use"] == "cu129":
        say("NOTE: the engine is the CUDA 12.9 build, NOT the pinned one: this run is evidence for a model change only")
    names: list[str] = []
    sampler = Sampler(run, names)
    sampler.start()
    t0 = time.monotonic()
    say(f"starting {', '.join(SERVICE[r] for r in o['serves'])} (option {oid}); loading takes 5 to 35 minutes")
    rc, _, err = run(cmds["up"], 2700, cmds["env"])
    summary["start_seconds"] = round(time.monotonic() - t0)
    summary["started"] = rc == 0
    containers: dict[str, str] = {}
    for role, ps in zip(o["serves"], cmds["ps"], strict=True):
        prc, cid, _ = run(ps, 60, cmds["env"])
        if prc == 0 and cid.strip():
            nrc, name, _ = run(["docker", "inspect", "--format", "{{.Name}}|{{.RestartCount}}", cid.strip()], 60, None)
            if nrc == 0 and "|" in name:
                cname, restarts = name.strip().lstrip("/").rsplit("|", 1)
                containers[role] = cname
                names.append(cname)
                summary.setdefault("restarts", {})[role] = int(restarts) if restarts.isdigit() else None
            _, logs, logs_err = run(["docker", "logs", cid.strip()], 120, None)
            summary.setdefault("engine_log", {})[role] = kv_lines(logs + logs_err)
    if rc != 0:
        summary["start_error"] = _tail(err)
    sampler.sample()
    if rc == 0 and containers:
        rec_tmp = out_dir / f".serving_config.{oid}.raw.json"
        unpinned = "" if engine["pinned_engine"] else " (not the pinned engine)"
        notes = (f"dgpu48 UNMEASURED, option {oid} (deploy/dgpu48-profile.yaml); engine {engine['use']}{unpinned}; "
                 "a measuring run, not a profile")  # fmt: skip
        cap = [sys.executable, str(ROOT / "tools" / "serving_config.py"), "capture", "--models-dir", str(models),
               "--notes", notes, "--out", str(rec_tmp)]  # fmt: skip
        for role, cname in containers.items():
            cap[3:3] = ["--container", f"{role}={cname}"]
        say("taking the serving record (hashes every weight file: a few minutes)")
        crc, cout, cerr = run(cap, 3600, None)
        summary["record_complete"] = crc == 0
        if rec_tmp.is_file():
            rec = sanitize(json.loads(rec_tmp.read_text(encoding="utf-8")), models)
            (out_dir / f"serving_config.dgpu48.{oid}.json").write_text(json.dumps(rec, indent=1, sort_keys=True) +
                                                                        "\n", encoding="utf-8")  # fmt: skip
            rec_tmp.unlink()
            summary["memory_used_mib_at_record"] = rec.get("memory_used_mib")
        else:
            summary["record_error"] = _tail(cerr or cout)
        if cmds["canary"]:
            say("the pair canary (54 stored cases; tools/canary.py in trialbox-py)")
            krc, kout, kerr = run(cmds["canary"], 3600, cmds["canary_env"])
            (out_dir / f"canary.{oid}.json").write_text(kout, encoding="utf-8")
            summary["canary"] = canary_summary(krc, kout, kerr)
            summary["canary"]["stored_control"] = STORED_CANARY
        else:
            summary["canary"] = {"run": False, "why": "the option serves no judge; the canary's cases are the judge's"}
    sampler.stop()
    summary["card_peak_mib"] = sampler.card_peak_mib
    summary["host_peak_mib"] = dict(sampler.host_peak_mib)
    if not keep:
        run(cmds["down"], 600, cmds["env"])
    summary["outcome"] = outcome(summary)
    (out_dir / f"measure.{oid}.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n",
                                                  encoding="utf-8")  # fmt: skip
    return summary


def canary_summary(rc: int, out: str, err: str) -> dict[str, Any]:
    try:
        rep = json.loads(out)
    except ValueError:
        return {"run": True, "ok": False, "error": _tail(err or out)}
    models = [{k: m.get(k) for k in ("role", "model", "cases", "answered", "correct", "flips", "seconds")}
              for m in rep.get("models") or [] if isinstance(m, dict)]  # fmt: skip
    pair = rep.get("pair") or {}
    return {"run": True, "ok": bool(rep.get("ok")) and rc == 0, "models": models, "seconds": rep.get("seconds"),
            "pair": {k: v for k, v in pair.items() if isinstance(v, (int, float, str, bool))},
            "problems": [_tail(p, 200) for p in rep.get("problems") or []]}  # fmt: skip


def outcome(s: dict[str, Any]) -> str:
    if s.get("dry_run"):
        return "dry run"
    if not s.get("started"):
        return "DID NOT START: send measure.<option>.json; next, the next option of RUNBOOK §29"
    if any((n or 0) > 0 for n in (s.get("restarts") or {}).values()):
        return "STARTED AFTER A RESTART: a server failed once; send the files"
    if not s.get("record_complete"):
        return "STARTED, RECORD INCOMPLETE: send the files"
    can = s.get("canary") or {}
    if can.get("run") and not can.get("ok"):
        return "STARTED, CANARY FAILED: the servers run but the answers differ; send the files"
    return "STARTED, RECORD TAKEN" + (", CANARY PASSED" if can.get("ok") else "") + ": send the files"


def _tail(text: str, n: int = 600) -> str:
    from tools import engine_probe as ep

    return ep.scrub(text or "", n)


def _pinned_image() -> str:
    from tools import engine_probe as ep

    return ep.pinned_ref()


def _vllm_key(root: Path = ROOT) -> str:
    """VLLM_API_KEY from the vLLM servers' own env file, when the box has one (never printed, never written)."""
    f = root / "deploy" / "secrets" / "model" / "vllm.env"
    if not f.is_file():
        return ""
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.startswith("VLLM_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_ = sub.add_parser("arith", help="each option's card arithmetic")
    a_.add_argument("--card-mib", type=int, default=None)
    a_.add_argument("--planner", type=float, default=None, metavar="RAM_GIB", help="also ask the box planner (venv)")
    m = sub.add_parser("measure", help=f"the measuring run on the machine ({SWITCH}=1)")
    m.add_argument("--option", required=True)
    m.add_argument("--probe", type=Path, default=Path.home() / "tb-engine-probe.json")
    m.add_argument("--engine", default="", help="force an engine form instead of the probe's verdict")
    m.add_argument("--out-dir", type=Path, default=None)
    m.add_argument("--keep", action="store_true", help="leave the servers running afterwards")
    m.add_argument("--dry-run", action="store_true", help="print the commands; start nothing")
    a = ap.parse_args(argv)
    doc = load()
    if a.cmd == "arith":
        print(arith_table(doc, a.card_mib))
        if a.planner is not None:
            print(json.dumps(planner(a.planner), indent=1))
        return 0
    try:
        option(doc, a.option)
        out_dir = a.out_dir or Path.home() / f"tb-dgpu48-{a.option}"
        s = measure(_real_runner, a.option, out_dir, a.probe, a.engine, a.dry_run, a.keep)
    except (Refused, KeyError) as exc:
        print(f"dgpu48: refused: {exc}", file=sys.stderr)
        return 2
    if not a.dry_run:
        shown = ("option", "engine", "started", "start_seconds", "card_peak_mib", "host_peak_mib", "engine_log",
                 "canary", "outcome")  # fmt: skip
        print(json.dumps({k: s.get(k) for k in shown}, indent=1))
        print(f"\nfiles in {out_dir}: send measure.{a.option}.json, serving_config.dgpu48.{a.option}.json and "
              f"canary.{a.option}.json (no host name, no serial or UUID, no address, no key)")  # fmt: skip
    return 0 if (a.dry_run or s.get("started")) else 1


if __name__ == "__main__":
    sys.exit(main())
