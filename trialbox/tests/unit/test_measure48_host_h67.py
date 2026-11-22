"""H-67: the 48 GB measuring run's host form (tools/measure48-host.sh) rehearsed on stand-ins: no card, no Docker, no
root, no network. The VM rig of tests/unit/test_measure48_vm_h53.py, extended for a host: nvidia-smi is a stand-in
machine of eight cards (the run's card in the middle), Docker is a stand-in daemon that keeps its containers,
networks, volumes and images in a file (so what the run makes and removes is seen), every repository tool is one
stand-in program, and the programs the host form must never run (systemctl, shutdown, poweroff, reboot, gcloud,
apt-get) are traps on PATH that write what called them."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="bash and GNU tools")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "measure48-host.sh"
VM_SCRIPT = ROOT / "tools" / "measure48-vm.sh"
KEY = "sk-standin-key-0123456789abcdef"
ADMIN = "standin-admin-pass-42"
CARD = 3
UUIDS = [f"GPU-{i}{i}{i}{i}aaaa-0000-0000-0000-00000000000{i}" for i in range(8)]
TOTAL = 183359  # a large card of the existing host
DRIVER = "590.44.01"  # at or above deploy/images.lock gpu.driver_min, not the rented run's 580 branch (H-72)

SMI = r"""#!@PY@
import json, os, sys
s = json.load(open(os.environ["M48_SMI"]))
a = sys.argv[1:]
with open(os.environ["M48_SMI"] + ".calls", "a") as f:
    f.write(" ".join(a) + "\n")
idx = int(a[a.index("-i") + 1]) if "-i" in a else None
cards = [c for c in s["cards"] if idx is None or c["index"] == idx]
if not cards:
    print("No devices were found", file=sys.stderr)
    sys.exit(6)
q = next((x for x in a if x.startswith("--query-")), "")
fields = q.split("=", 1)[1].split(",") if q else []
if q.startswith("--query-compute-apps"):
    for p in s.get("apps", []):
        c = s["cards"][p["index"]]
        if idx is None or p["index"] == idx:
            row = {"gpu_uuid": c["uuid"], "pid": str(p["pid"]), "process_name": p["name"], "used_memory": str(p["mib"])}
            print(", ".join(row[f] for f in fields))
    sys.exit(0)
for c in cards:
    row = {"index": str(c["index"]), "uuid": c["uuid"], "name": c["name"], "memory.total": str(c["total"]),
           "memory.used": str(c["used"]), "memory.free": str(c["total"] - c["used"] - c["reserved"]),
           "driver_version": s["driver"]}
    print(", ".join(row[f] for f in fields))
"""

DOCKER = r"""#!@PY@
import json, os, re, sys
p = os.environ["M48_DOCKER"]
s = json.load(open(p))
a = sys.argv[1:]
with open(p + ".calls", "a") as f:
    f.write(" ".join(a) + "\n")
def save():
    json.dump(s, open(p, "w"))
def opt(name):
    return a[a.index(name) + 1] if name in a else None
def filt():
    return [a[i + 1] for i, x in enumerate(a) if x == "--filter"]
def render(fmt, name):
    return fmt.replace("{{.Names}}", name).replace("{{.Name}}", name).replace("\\t", "\t")
if not s.get("up", True):
    print("Cannot connect to the Docker daemon", file=sys.stderr)
    sys.exit(1)
if a[0] == "info":
    f = opt("--format") or ""
    print(json.dumps({r: {} for r in s["runtimes"]}) if "Runtimes" in f else s["root"])
elif a[:3] == ["compose", "version", "--short"]:
    print(s["compose"])
elif a[0] == "ps":
    names = sorted(s["containers"])
    for f in filt():
        k, _, v = f.partition("=")
        if k == "label":
            lk, _, lv = v.partition("=")
            names = [n for n in names if s["containers"][n].get(lk) == lv]
        elif k == "name":
            names = [n for n in names if re.search(v, n)]
    fmt = opt("--format")
    for n in names:
        print(render(fmt, n) if fmt else n)
elif a[0] in ("network", "volume") and a[1] == "ls":
    kind = a[0] + "s"
    names = [n for n in s[kind] if all(re.search(f.partition("=")[2], n) for f in filt())]
    fmt = opt("--format")
    for n in names:
        print(render(fmt, n) if fmt else n)
elif a[0] in ("network", "volume") and a[1] == "rm":
    for n in a[2:]:
        if n in s[a[0] + "s"]:
            s[a[0] + "s"].remove(n)
    save()
elif a[0] == "rm":
    for n in [x for x in a[1:] if not x.startswith("-")]:
        s["containers"].pop(n, None)
    save()
elif a[:2] == ["image", "inspect"]:
    sys.exit(0 if a[-1] in s["images"] else 1)
elif a[:2] == ["image", "ls"]:
    print("\n".join(s["images"]))
elif a[0] == "pull":
    s["images"].append(a[1])
    save()
elif a[0] == "inspect":
    print("172.17.0.2" if "IPAddress" in " ".join(a) else "true")
elif a[0] == "system":
    print("Images 0 0 0B 0B")
"""

STANDIN = r"""#!@PY@
import json, os, pathlib, signal, sys, time
a = sys.argv[1:]
with open(os.environ["M48_CALLS"], "a") as f:
    f.write(" ".join(a) + "\n")
KEY = "@KEY@"
dp = os.environ["M48_DOCKER"]
def docker(change):
    s = json.load(open(dp))
    change(s)
    json.dump(s, open(dp, "w"))
def arg(n):
    return a[a.index(n) + 1]
ck = pathlib.Path(os.environ["M48_CK"])
t = a[0]
if t == "fetch_weights":
    print("All present and pinned." if os.environ.get("M48_WEIGHTS_RC", "0") == "0" else "NOT OK: j-workhorse")
    sys.exit(int(os.environ.get("M48_WEIGHTS_RC", "0")))
if t == "pinned_ref":
    print("vllm/vllm-openai:v0.32.0@sha256:0000")
    sys.exit(0)
if t == "poc":
    if len(a) == 1:
        (ck / "deploy/secrets/model").mkdir(parents=True, exist_ok=True)
        (ck / "deploy/.env").write_text("TB_ADMIN_PASSWORD=@ADMIN@\n")
        (ck / "deploy/secrets/model/vllm.env").write_text('VLLM_API_KEY="' + KEY + '"\n')
        def up(s):
            s["volumes"] += ["trialbox_db", "trialbox_objects"]
            s["networks"] += ["trialbox-net", "trialbox-model-backend"]
            s["images"] += ["trialbox-py:1.0.0"]
            for n in ("trialbox-db-1", "trialbox-console-1"):
                s["containers"][n] = {"com.docker.compose.project": "trialbox"}
        docker(up)
        print("the box is up; sign in as admin with @ADMIN@")
    if a[1:] == ["down"]:
        def down(s):
            for n in ("trialbox-db-1", "trialbox-console-1"):
                s["containers"].pop(n, None)
        docker(down)
    sys.exit(0)
if t == "ballast":
    if a[1] == "plan":
        if os.environ.get("M48_BALLAST_PLAN_REFUSED"):
            print("refused: " + os.environ["M48_BALLAST_PLAN_REFUSED"], file=sys.stderr)
            sys.exit(2)
        print("card 3: stand-in\ntarget: 49140 MiB free, +/- 512; ballast to hold: about 133000 MiB")
        sys.exit(0)
    if a[1] == "hold":
        name = arg("--ballast-container")  # the host form names its own: a missing option fails the step
        docker(lambda s: s["containers"].__setitem__(name, {"trialbox.ballast": "1"}))
        def bye(*_):
            docker(lambda s: s["containers"].pop(name, None))
            print("released", flush=True)
            sys.exit(0)
        signal.signal(signal.SIGTERM, bye)
        print("ready: start the servers now", flush=True)
        while True:
            time.sleep(0.05)
    sys.exit(0)
if t == "ballast48":
    sub = a[1]
    if sub == "measure":
        opt, out = arg("--option"), pathlib.Path(arg("--out-dir"))
        out.mkdir(parents=True, exist_ok=True)
        print("measuring " + opt + " with the key " + KEY, flush=True)
        def servers(s):
            for n in ("trialbox-llm-service-1", "trialbox-llm-verifier-1"):
                s["containers"][n] = {"com.docker.compose.project": "trialbox"}
        docker(servers)
        (out / "gpu-pin.yml").write_text("device_ids: [" + arg("--gpu-uuid") + "]\n")
        if os.environ.get("M48_HANG") == opt:
            try:
                while True:
                    time.sleep(0.05)
            except KeyboardInterrupt:
                (out / ("measure." + opt + ".json")).write_text(json.dumps({"option": opt, "started": False,
                    "interrupted": True, "outcome": "BY BALLAST: stopped"}))
                sys.exit(130)
        started = opt not in os.environ.get("M48_FAIL", "").split()
        (out / ("measure." + opt + ".json")).write_text(json.dumps({"option": opt, "started": started,
            "outcome": "BY BALLAST", "card_peak_mib": 45000, "ballast": {"free_at_peak_mib": 4100},
            "engine_log": {"judge": {"kv_cache_tokens": 98304}}}))
        if started:
            (out / ("canary." + opt + ".json")).write_text(json.dumps({"models": [{"role": "judge", "cases": 54,
                "seconds": 108.0}]}))
            (out / ("serving_config.dgpu48." + opt + ".json")).write_text("{}")
            if "--keep" in a:
                (out / "down.json").write_text(json.dumps({"cmd": ["docker"], "env": {"VLLM_API_KEY": KEY}}))
                sys.exit(0)
        docker(lambda s: [s["containers"].pop(n, None) for n in ("trialbox-llm-service-1",
                                                                  "trialbox-llm-verifier-1")])
        sys.exit(0 if started else 1)
    if sub == "down":
        docker(lambda s: [s["containers"].pop(n, None) for n in ("trialbox-llm-service-1", "trialbox-llm-verifier-1")])
        sys.exit(0)
    if sub == "plan" and os.environ.get("M48_PLAN_REFUSED"):
        print("ballast48: refused: " + os.environ["M48_PLAN_REFUSED"], file=sys.stderr)
        sys.exit(2)
    if sub == "during":
        parts = pathlib.Path(arg("--dir")) / "parts"
        parts.mkdir(parents=True, exist_ok=True)
        (parts / "hospital-ja.json").write_text(json.dumps({"wall_seconds": 640.0}))
        (parts / "prepare.json").write_text("{}")
        pathlib.Path(arg("--out")).write_text(json.dumps({"wall_seconds": 700.0, "exit_code": 0,
            "free_at_peak_mib": 3900, "ballast_held_at_end": True}))
        sys.exit(0)
    if sub == "canary-diff":
        pathlib.Path(arg("--json")).write_text(json.dumps({"verdicts_differ": 2, "exact": True, "runs": {}}))
    sys.exit(0)
if t == "canary":
    print(json.dumps({"ok": True, "models": []}))
sys.exit(0)
""".replace("@KEY@", KEY).replace("@ADMIN@", ADMIN)

FORBIDDEN = ("systemctl", "shutdown", "poweroff", "reboot", "halt", "gcloud", "apt-get", "systemd-run", "nvidia-ctk")


class Rig:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir(mode=0o755)
        self.run_dir = tmp / "the-run"
        self.weights = tmp / "weights"
        self.weights.mkdir(mode=0o755)
        self.docker_root = tmp / "docker-root"
        self.docker_root.mkdir(mode=0o755)
        self.calls = tmp / "calls.txt"
        self.forbidden = tmp / "forbidden.txt"
        self.smi_state = tmp / "smi.json"
        self.docker_state = tmp / "docker.json"
        for name, text in (("nvidia-smi", SMI), ("docker", DOCKER), ("standin", STANDIN)):
            (self.bin / name).write_text(text.replace("@PY@", sys.executable))
            (self.bin / name).chmod(0o755)
        for name in FORBIDDEN:
            (self.bin / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.forbidden}"\nexit 0\n')
            (self.bin / name).chmod(0o755)
        cards = [{"index": i, "uuid": UUIDS[i], "name": "NVIDIA stand-in 192 GB", "total": TOTAL, "used": 0,
                  "reserved": 650} for i in range(8)]  # fmt: skip
        self.smi(cards=cards, driver=DRIVER, apps=[])
        self.dock(up=True, runtimes=["io.containerd.runc.v2", "nvidia", "runc"], root=str(self.docker_root),
                  compose="2.29.7", images=["vllm/vllm-openai:v0.32.0@sha256:0000", "someone/else:1"],
                  containers={"someone-elses-db": {"com.docker.compose.project": "theirs"}},
                  networks=["bridge", "their-net"], volumes=["their_data"])  # fmt: skip
        # the checkout: a git repository of a trialbox folder (the run copies its HEAD into the run folder)
        self.co = tmp / "checkout"
        (self.co / "tools").mkdir(parents=True, mode=0o755)
        (self.co / "tools" / "ballast48.py").write_text("# stand-in\n")
        (self.co / "README").write_text("stand-in checkout\n")
        git = ["git", "-C", str(self.co), "-c", "user.name=rig", "-c", "user.email=rig@example.invalid"]
        for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "stand-in"]):
            subprocess.run([*git, *cmd], check=True, capture_output=True)

    def smi(self, **kv: Any) -> None:
        s = json.loads(self.smi_state.read_text()) if self.smi_state.exists() else {}
        s.update(kv)
        self.smi_state.write_text(json.dumps(s))

    def dock(self, **kv: Any) -> None:
        s = json.loads(self.docker_state.read_text()) if self.docker_state.exists() else {}
        s.update(kv)
        self.docker_state.write_text(json.dumps(s))

    @property
    def docker(self) -> dict[str, Any]:
        d: dict[str, Any] = json.loads(self.docker_state.read_text())
        return d

    def env(self, **env: str) -> dict[str, str]:
        e = {k: v for k, v in os.environ.items() if k not in ("PYTHONUNBUFFERED", "TB_ENV", "HF_TOKEN")}
        e.update({"PATH": f"{self.bin}:{e['PATH']}", "TB_M48_STANDIN": str(self.bin / "standin"),
                  "TB_M48_POLL_S": "0.2", "TB_M48_FREE_BYTES": str(200 * 10**9),
                  "TB_M48_DOCKER_FREE_BYTES": str(200 * 10**9), "M48_CALLS": str(self.calls),
                  "M48_SMI": str(self.smi_state), "M48_DOCKER": str(self.docker_state),
                  "M48_CK": str(self.run_dir / "src" / "trialbox")})  # fmt: skip
        e.update(env)
        return e

    def args(self, cmd: str, *more: str) -> list[str]:
        return ["bash", str(SCRIPT), cmd, "--gpu-index", str(CARD), "--run-dir", str(self.run_dir), "--weights-dir",
                str(self.weights), "--checkout", str(self.co), "--run-id", "t1", *more]  # fmt: skip

    def go(self, cmd: str, *more: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(self.args(cmd, *more), env=self.env(**env), capture_output=True, text=True, timeout=240,
                              check=False)  # fmt: skip

    @property
    def out(self) -> Path:
        return self.run_dir / "out"

    def steps(self) -> dict[str, dict[str, Any]]:
        return {s["step"]: s for s in json.loads((self.out / "steps.json").read_text())["steps"]}

    def ended(self) -> str:
        return str(json.loads((self.out / "steps.json").read_text())["ended"])

    def box_objects(self) -> list[str]:
        d = self.docker
        return sorted([c for c, lab in d["containers"].items() if lab.get("com.docker.compose.project") == "trialbox"
                       or c.startswith("tb-ballast")] + [n for n in d["networks"] if n.startswith("trialbox-")]
                      + [v for v in d["volumes"] if v.startswith("trialbox_")])  # fmt: skip

    def assert_nothing_forbidden_and_others_untouched(self) -> None:
        assert not self.forbidden.exists(), self.forbidden.read_text()
        d = self.docker
        assert "someone-elses-db" in d["containers"] and "their-net" in d["networks"]
        assert "their_data" in d["volumes"] and "someone/else:1" in d["images"]
        dcalls = (self.tmp / "docker.json.calls").read_text() if (self.tmp / "docker.json.calls").exists() else ""
        assert not re.search(r"\bprune\b", dcalls), "a prune"
        for line in dcalls.splitlines():
            if line.startswith(("rm ", "network rm", "volume rm")):
                assert "someone" not in line and "their" not in line, line
        smi = (self.tmp / "smi.json.calls").read_text().splitlines()
        assert smi and all(f"-i {CARD}" in c for c in smi), [c for c in smi if f"-i {CARD}" not in c]


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def _all_text(d: Path) -> str:
    return "\n".join(p.read_text(errors="replace") for p in d.rglob("*") if p.is_file())


# ------------------------------------------------------------------------------------------------ the preflight


def test_the_preflight_passes_and_changes_nothing(rig: Rig) -> None:
    r = rig.go("preflight")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "preflight: ok: passed: nothing was changed" in r.stdout
    assert f"card {CARD}: NVIDIA stand-in 192 GB, {TOTAL} MiB in all; driver {DRIVER}" in r.stdout
    assert f"driver {DRIVER} is not the rented run's branch (580): recorded" in r.stdout  # a note, not a refusal
    assert "the NVIDIA runtime is registered with Docker" in r.stdout
    assert "the engine image is here by digest" in r.stdout
    assert f"card {CARD}: NVIDIA driver {DRIVER} runs CUDA" in r.stdout  # deploy/images.lock gpu.driver_min (H-72)
    assert "no images of the box's names on this host" in r.stdout
    assert "Docker's data root: 200.0 GB free, 14 GB needed" in r.stdout
    assert "the run folder: 200.0 GB free, 10 GB needed" in r.stdout
    assert not rig.run_dir.exists()
    dcalls = (rig.tmp / "docker.json.calls").read_text()
    assert not re.search(r"^(rm|run|pull|create|network rm|volume rm|compose up)", dcalls, re.M), dcalls
    assert not list(rig.co.rglob("__pycache__"))
    calls = rig.calls.read_text()
    assert f"ballast plan --gpu-index {CARD} --gpu-uuid {UUIDS[CARD]}" in calls
    assert f"fetch_weights --profile rtxpro6000 --models-dir {rig.weights} --verify-only" in calls
    rig.assert_nothing_forbidden_and_others_untouched()


@pytest.mark.parametrize(
    ("setup", "env", "args", "said"),
    [
        ({"docker": {"up": False}}, {}, (), "Docker does not answer"),
        ({"docker": {"runtimes": ["runc"]}}, {}, (), "the NVIDIA runtime is not registered with Docker"),
        ({"docker": {"images": []}}, {}, (), "the engine image is not here by digest"),
        ({"docker": {"compose": "2.20.2"}}, {}, (), "docker compose 2.20.2: 2.24.4 or newer is needed"),
        (
            {"docker": {"containers": {"trialbox-db-1": {"com.docker.compose.project": "trialbox"}}}},
            {},
            (),
            "this host has 1 Docker object(s) of the box's names already (1 container)",
        ),
        ({"docker": {"volumes": ["trialbox_db"]}}, {}, (), "of the box's names already (1 volume)"),
        (
            {"docker": {"images": ["vllm/vllm-openai:v0.32.0@sha256:0000", "trialbox-py:1.0.0", "trialbox-jvm:1.0.0"]}},
            {},
            (),
            "this host has 2 image(s) of the box's names already (trialbox-jvm:1.0.0, trialbox-py:1.0.0)",
        ),
        (
            {"smi": {"driver": "575.57.08"}},
            {},
            (),
            f"card {CARD}: NVIDIA driver 575.57.08 is below 580.65.06, the lowest that runs the vLLM image",
        ),
        ({}, {"M48_WEIGHTS_RC": "1"}, (), "the weights in --weights-dir are not the pinned builds: NOT OK"),
        ({}, {"TB_M48_DOCKER_FREE_BYTES": str(10 * 10**9)}, (), "Docker's data root: 10.0 GB free, 14 GB needed"),
        ({}, {"TB_M48_DOCKER_FREE_BYTES": str(40 * 10**9)}, ("--pull",), "40.0 GB free, 44 GB needed"),
        ({}, {"TB_M48_FREE_BYTES": str(5 * 10**9)}, (), "the run folder: 5.0 GB free, 10 GB needed"),
        (
            {},
            {"M48_BALLAST_PLAN_REFUSED": "card-too-small: 48000 MiB in all"},
            (),
            "the ballast refuses this card: refused: card-too-small: 48000 MiB in all",
        ),
    ],
)
def test_each_preflight_refusal_is_named_and_nothing_changes(rig: Rig, setup: dict[str, Any], env: dict[str, str],
                                                             args: tuple[str, ...], said: str) -> None:  # fmt: skip
    if "docker" in setup:
        rig.dock(**setup["docker"])
    if "smi" in setup:
        rig.smi(**setup["smi"])
    r = rig.go("preflight", *args, **env)
    assert r.returncode == 2, r.stdout
    assert said in r.stdout, r.stdout
    assert "problem(s): nothing was changed" in r.stdout
    assert not rig.run_dir.exists() and not rig.forbidden.exists()


def test_another_process_on_the_chosen_card_refuses_by_count_and_memory_only(rig: Rig) -> None:
    rig.smi(apps=[{"index": CARD, "pid": 4242, "name": "someones-trainer", "mib": 5000}])
    r = rig.go("preflight")
    assert r.returncode == 2
    assert f"card {CARD}: 1 other process(es) on it, 5000 MiB: the card must be free" in r.stdout
    assert "4242" not in r.stdout and "someones-trainer" not in r.stdout


def test_a_process_on_another_card_does_not_matter(rig: Rig) -> None:
    rig.smi(apps=[{"index": 5, "pid": 4242, "name": "someones-trainer", "mib": 90000}])
    r = rig.go("preflight")
    assert r.returncode == 0, r.stdout
    assert f"card {CARD}: no other process on it" in r.stdout


def test_a_card_that_is_not_there_refuses(rig: Rig) -> None:
    r = subprocess.run([*rig.args("preflight")[:4], "9", *rig.args("preflight")[5:]], env=rig.env(),
                       capture_output=True, text=True, timeout=120, check=False)  # fmt: skip
    assert r.returncode == 2 and "nvidia-smi has no card 9: No devices were found" in r.stdout


def test_with_pull_a_missing_engine_is_a_note(rig: Rig) -> None:
    rig.dock(images=[])
    r = rig.go("preflight", "--pull")
    assert r.returncode == 0, r.stdout
    assert "the engine image is not here: s06 pulls it (--pull" in r.stdout


def test_a_run_folder_in_use_is_refused(rig: Rig) -> None:
    rig.run_dir.mkdir()
    (rig.run_dir / "something").write_text("x")
    r = rig.go("run")
    assert r.returncode == 2 and "--run-dir is not empty" in r.stdout
    assert sorted(p.name for p in rig.run_dir.iterdir()) == ["something"]


def test_the_gpu_index_and_the_run_dir_are_required(rig: Rig) -> None:
    r = subprocess.run(["bash", str(SCRIPT), "run", "--run-dir", str(rig.run_dir)], env=rig.env(), capture_output=True,
                       text=True, timeout=60, check=False)  # fmt: skip
    assert r.returncode == 2 and "--gpu-index N is required" in r.stderr
    r = subprocess.run(["bash", str(SCRIPT), "preflight", "--gpu-index", "3"], env=rig.env(), capture_output=True,
                       text=True, timeout=60, check=False)  # fmt: skip
    assert r.returncode == 2 and "--run-dir DIR is required" in r.stderr


# ------------------------------------------------------------------------------------------------ the run


def test_a_full_pass_runs_s05_to_s14_on_the_chosen_card_and_leaves_nothing(rig: Rig) -> None:
    r = rig.go("run")
    assert r.returncode == 0, (r.stdout[-3000:], r.stderr[-2000:])
    steps = rig.steps()
    assert list(steps) == ["s05-stub", "s06-engine", "s07-ballast", "s08-ladder", "s09-tools", "s10-screen", "s11-o",
                           "s12-down", "s13-host53", "s14-release"]  # fmt: skip
    assert all(s["rc"] == 0 for s in steps.values()), steps
    assert rig.ended().startswith("complete")
    for rel in (
        "records/tb-dgpu48-pair-32k/measure.pair-32k.json",
        "records/screen-during.json",
        "records/canary-verifier-flag-diff.json",
        "records/ballast.log",
        "records/head.json",
        "records/docker-objects.json",
        "preflight.txt",
        "host.log",
        "decisions.json",
        "logs/s08-ladder.log",
    ):
        assert (rig.out / rel).is_file(), rel
    # every tool on the chosen card, by index and by the UUID read at the preflight
    calls = rig.calls.read_text()
    pin = f"--gpu-index {CARD} --gpu-uuid {UUIDS[CARD]}"
    assert f"ballast hold --target-mib 49140 {pin}" in calls
    assert f"ballast48 plan {pin}" in calls
    assert (
        f"ballast48 measure --option pair-32k --keep --out-dir {rig.run_dir}/run/records/tb-dgpu48-pair-32k {pin}"
        in calls
    )
    assert f"ballast48 during --out {rig.run_dir}/run/records/screen-during.json {pin} --" in calls
    assert f"ballast48 measure --option pair-32k-host53 --out-dir {rig.run_dir}/run/records/tb-dgpu48-pair-32k-host53 " \
           f"{pin}" in calls  # fmt: skip
    # what the run made is listed and removed; nothing else is touched; nothing pulled (the image was there)
    objs = json.loads((rig.out / "records" / "docker-objects.json").read_text())
    made = {o["name"] for o in objs["objects"]}
    assert {"trialbox-net", "trialbox-model-backend", "trialbox_db", "trialbox-llm-service-1", "tb-ballast-t1"} <= made
    assert all(o["removed"] for o in objs["objects"]) and "someone-elses-db" not in made
    assert objs["left"] == [] and objs["images_made_and_kept"] == ["trialbox-py:1.0.0"]
    assert rig.box_objects() == []
    assert "pull " not in (rig.tmp / "docker.json.calls").read_text()
    rig.assert_nothing_forbidden_and_others_untouched()
    # the packed records: no key, no password, no card UUID, no pin file
    text = _all_text(rig.out)
    assert KEY not in text and ADMIN not in text and not any(u in text for u in UUIDS)
    assert not list(rig.out.rglob("gpu-pin.yml")) and not list(rig.out.rglob("kv"))
    # nothing written outside the run folder: the checkout is as it was
    st = subprocess.run(["git", "-C", str(rig.co), "status", "--porcelain", "--ignored"], capture_output=True, text=True,
                        check=True)  # fmt: skip
    assert st.stdout == ""


def test_a_failure_at_s07_ends_cleanly_with_its_reason(rig: Rig) -> None:
    why = "49776 MiB free, not 49140 +/- 512 (nvidia-smi memory.free; 48111 used, 650 reserved by the driver)"
    r = rig.go("run", M48_PLAN_REFUSED=why)
    assert r.returncode == 1, r.stdout[-2000:]
    steps = rig.steps()
    assert steps["s07-ballast"]["rc"] == 1 and "s08-ladder" not in steps and steps["s14-release"]["rc"] == 0
    assert rig.ended().startswith("s07-ballast failed: ballast48 plan refused") and "49776 MiB free" in rig.ended()
    assert "released" in (rig.out / "records" / "ballast.log").read_text()
    objs = json.loads((rig.out / "records" / "docker-objects.json").read_text())
    assert objs["left"] == [] and rig.box_objects() == []
    rig.assert_nothing_forbidden_and_others_untouched()


def _until(rig: Rig, text: str, p: subprocess.Popen[str], seconds: float = 90) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if rig.calls.exists() and text in rig.calls.read_text():
            return
        if p.poll() is not None:
            pytest.fail(f"the run ended before {text!r}")
        time.sleep(0.1)
    pytest.fail(f"never reached {text!r}")


def test_sigterm_mid_run_ends_the_steps_and_removes_what_the_run_made(rig: Rig) -> None:
    p = subprocess.Popen(rig.args("run"), env=rig.env(M48_HANG="pair-32k"), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)  # fmt: skip
    try:
        _until(rig, "measure --option pair-32k", p)
        time.sleep(1)
        assert "trialbox-llm-service-1" in rig.docker["containers"]  # the servers are up, the ballast holds
        p.send_signal(signal.SIGTERM)
        out, _ = p.communicate(timeout=180)
    finally:
        if p.poll() is None:
            p.kill()
        subprocess.run(["pkill", "-f", str(rig.bin / "standin")], check=False)
    assert p.returncode == 143, out[-2000:]
    assert rig.ended() == "stopped: SIGTERM"
    assert rig.steps()["s14-release"]["rc"] == 0
    assert rig.box_objects() == []
    rig.assert_nothing_forbidden_and_others_untouched()


def test_the_cap_ends_the_steps_and_cleans_up_without_powering_anything_off(rig: Rig) -> None:
    # the cap 6 s away (240 min less 6 s used already); the stop line past the cap, so the cap is what ends it
    p = subprocess.Popen(rig.args("run"), env=rig.env(M48_HANG="pair-32k", TB_M48_USED0_S=str(240 * 60 - 6),
                                                      TB_M48_LINE_MIN="400"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # fmt: skip
    try:
        out, _ = p.communicate(timeout=180)
    finally:
        if p.poll() is None:
            p.kill()
        subprocess.run(["pkill", "-f", str(rig.bin / "standin")], check=False)
    assert p.returncode == 3, out[-2000:]
    assert rig.ended() == "stopped: the cap of 240 minutes"
    assert rig.box_objects() == []
    assert "s07-ballast" not in rig.steps() or "released" in (rig.out / "records" / "ballast.log").read_text()
    rig.assert_nothing_forbidden_and_others_untouched()


def test_the_stop_line_interrupts_the_runs_measure_and_no_other_process_of_that_name(rig: Rig) -> None:
    """The stop line 64 minutes in, a second counted as 150: the ladder starts in time, then the hang reaches the
    line. Another user's process whose command line matches the measure's pattern is not the run's: untouched."""
    decoy = subprocess.Popen(["bash", "-c", "exec -a 'their ballast48 measure --option x' sleep 300"])
    try:
        r = rig.go("run", M48_HANG="pair-32k", TB_M48_LINE_MIN="64", TB_M48_TIME_SCALE="150")
        alive = decoy.poll() is None
    finally:
        decoy.kill()
        subprocess.run(["pkill", "-f", str(rig.bin / "standin")], check=False)
    assert r.returncode == 1, r.stdout[-2000:]
    assert "the stop line (64 min): SIGINT" in (rig.out / "host.log").read_text()
    rec = json.loads((rig.out / "records/tb-dgpu48-pair-32k/measure.pair-32k.json").read_text())
    assert rec["interrupted"] is True
    assert alive, "the stop line's SIGINT reached a process that is not the run's"
    assert rig.box_objects() == []
    rig.assert_nothing_forbidden_and_others_untouched()


def test_with_pull_a_missing_engine_image_is_pulled_at_s06(rig: Rig) -> None:
    rig.dock(images=["someone/else:1"])
    r = rig.go("run", "--pull")  # without --pull the preflight refuses it (above): nothing is pulled unasked
    assert r.returncode == 0, r.stdout[-2000:]
    assert "pull vllm/vllm-openai:v0.32.0@sha256:0000" in (rig.tmp / "docker.json.calls").read_text()


# ------------------------------------------------------------------------------------------------ never the VM's part


def test_the_vm_scripts_self_stop_is_not_even_defined_in_the_host_form(tmp_path: Path) -> None:
    probe = (f"cd {tmp_path} && TB_M48_FUNCTIONS_ONLY=1 . {VM_SCRIPT} && "
             "for f in off poweroff_vm step_host step_card step_source step_weights docker_toolkit md pack end_run; do "
             "declare -F $f > /dev/null && echo DEFINED $f; done; "
             "for f in steps_s05_on step_stub step_engine step_ballast step_ladder step_release watched run_step; do "
             "declare -F $f > /dev/null || echo MISSING $f; done; echo done")  # fmt: skip
    r = subprocess.run(["bash", "-c", probe], capture_output=True, text=True, timeout=60, check=False)
    assert r.stdout.split() == ["done"], r.stdout + r.stderr
    assert list(tmp_path.iterdir()) == []  # sourcing it wrote nothing
    ran = subprocess.run(["bash", str(VM_SCRIPT)], env={**os.environ, "TB_M48_FUNCTIONS_ONLY": "1",
                                                        "TB_M48_ROOT": str(tmp_path / "vm")},
                         capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert ran.returncode == 0 and ran.stdout == "" and not (tmp_path / "vm").exists()


def test_the_host_script_has_no_command_that_stops_a_machine_or_reaches_the_cloud() -> None:
    text = SCRIPT.read_text()
    text = text[: text.index("<<'PY'")] + text[text.index("\nPY\n") :]  # the record's own words name what it never does
    code = [x.split(" #", 1)[0] for x in text.splitlines() if not x.lstrip().startswith("#")]
    text = "\n".join(code)
    for word in (
        "poweroff",
        "systemctl",
        "shutdown",
        "reboot",
        "halt",
        "gcloud",
        "gsutil",
        "metadata.google",
        "computeMetadata",
        "systemd-run",
        "apt-get",
        "prune",
        "--with-deps",
        "set -x",
    ):
        assert word not in text, word
    # nvidia-ctk is named only in the words that tell the owner how to register the runtime; the rehearsal's trap
    # program of that name proves it is never run
    assert all("nvidia-ctk" not in x or "pf NO" in x for x in code)


def test_the_stop_line_and_the_cap_are_the_vm_forms() -> None:
    from tools import measure48_vm as m

    text = SCRIPT.read_text()
    assert "CAP_MIN=${TB_M48_CAP_MIN:-240}" in text and m.CAP_HOURS * 60 == 240
    assert "h stop-line-min" in text and m.vm_stop_line_min() == 204
    assert m.host_need() == {"docker_root_gb": 14.0, "run_dir_gb": 10.0}
    assert m.host_need(pull=True)["docker_root_gb"] == 44.0


def test_the_script_is_bash_clean() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


# ------------------------------------------------------------------------------------------------ H-72


def test_a_driver_below_the_engines_minimum_refuses_the_run_before_anything_starts(rig: Rig) -> None:
    """H-72: the existing host's 575 driver cannot start the CUDA 13 engine image (deploy/images.lock gpu.driver_min);
    the run is refused at its preflight, with the driver found and the one needed, and nothing is made."""
    rig.smi(driver="575.57.08")
    r = rig.go("run")
    assert r.returncode == 2, r.stdout
    assert "NVIDIA driver 575.57.08 is below 580.65.06" in r.stdout
    assert "this script never installs a driver" in r.stdout
    assert not rig.run_dir.exists()
    assert not rig.calls.exists() or "poc" not in rig.calls.read_text()
    rig.assert_nothing_forbidden_and_others_untouched()


def test_an_installed_boxs_images_refuse_the_run_and_are_left_as_they_were(rig: Rig) -> None:
    """H-72: the stub builds trialbox-* images; a host with an installed box's images is refused, never built over."""
    imgs = ["vllm/vllm-openai:v0.32.0@sha256:0000", "someone/else:1", "trialbox-py:1.0.0"]
    rig.dock(images=imgs)
    r = rig.go("run")
    assert r.returncode == 2, r.stdout
    assert "1 image(s) of the box's names already (trialbox-py:1.0.0)" in r.stdout
    assert rig.docker["images"] == imgs and not rig.run_dir.exists()
    rig.assert_nothing_forbidden_and_others_untouched()
