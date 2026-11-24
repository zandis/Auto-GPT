"""The bench host's CI runner launcher (card H-105): one single-use container per CI job, then gone.

One service unit per slot (``tb-bench-runner@<profile>-<n>``); each start of the unit is one job's life, in three
steps with two users (the security review's F2: no process of the jobs' user ever holds the long-lived token):

1. ``mint`` (root, the unit's ExecStartPre with full privileges): read the settings and the long-lived token
   (``/etc/tb-bench-ci/token``, root's, mode 0600); a GPU slot first checks the CI cards (never the walk's or the
   bench's, none busy beyond the cap); read master's blob of the bench workflow from the code host; ask the code host
   for a one-job runner configuration; make the slot's fresh scratch folder and write into it, for the jobs' user,
   only the one-job configuration (``runner.jit``, read and deleted by the container's entry point: never an
   argument) and the job file the gate reads (``job.json``). The runner's id stays in a root-only state file;
2. ``run`` (the ``tb-bench`` user): the slot's own internal network (no route out, no name service), the egress
   proxy joined to it at a fixed address, then the job's container (``container_args``); on a stop (TERM) the
   container is stopped and the network removed;
3. ``cleanup`` (root, ExecStopPost, also after a failure or a stop): remove the runner registration if it is still
   there, and the slot's scratch folder.

The token goes to the code host's API address below and nowhere else (``http.client`` reads no proxy setting).
Which jobs may run is the gate's part (``gate.py``, the runner's job-started hook); the workflow and its test only
schedule. Commands (each with ``--settings FILE``)::

    python3 -s -E -m tools.bench_ci.launcher check | get KEY | proxy
    python3 -s -E -m tools.bench_ci.launcher mint --slot cpu-1 | run --slot cpu-1 | cleanup --slot cpu-1
    python3 -s -E -m tools.bench_ci.launcher probe --profile cpu

Standard library only: the host's python3 runs it from /opt/tb-bench-ci (root's, read-only to the tb-bench user),
where install.sh lays out tools/bench_ci/ as in the repository; -E: no PYTHON* variable of a caller is read.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import pwd
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from tools.bench_ci import gpu_check

API_HOST = "api.github.com"  # the code host's API; the token goes here and nowhere else
WORKFLOW = ".github/workflows/trialbox-bench-ci.yml"
EGRESS_NET = "tb-bench-egress"  # the proxy's way out
PROXY_NAME = "tb-bench-proxy"
PROXY_PORT = 3128
RUN_USER = "tb-bench"
JOB_UID = 1001  # the job image's own non-root user
CONTAINER_LABEL = "tb-bench-ci=1"
PROFILES = ("cpu", "engine", "gpu")
SLOT = re.compile(r"^(cpu|engine|gpu)-([1-9][0-9]?)$")
OCTET_BASE = {"cpu": 0, "engine": 100, "gpu": 150, "probe": 240}  # the slot's /24: <prefix>.<base + n>.0
API_SECONDS = 60
PLACEHOLDER = re.compile(r"<[^>]*>")
WALK_CARD = "1"
STATE = Path("/run/tb-bench-ci")  # root's: the runner ids, for the cleanup
TOKEN = Path("/etc/tb-bench-ci/token")
# the set-id pair the nested rootless engine's id-mapping helpers need (F5): the only capabilities an engine or GPU
# job keeps, and the reason no-new-privileges is not set for them
ENGINE_CAPS = ("SETUID", "SETGID")

REQUIRED = (
    "BENCH_REPO",
    "BENCH_LABEL",
    "BENCH_IMAGE",
    "BENCH_ENGINE",
    "BENCH_SCRATCH",
    "BENCH_SUBNET_PREFIX",
    "BENCH_CPU_SLOTS",
    "BENCH_ENGINE_SLOTS",
    "BENCH_GPU_SLOTS",
    "BENCH_CPUS",
    "BENCH_MEMORY",
    "BENCH_PIDS",
    "BENCH_JOB_HOURS",
    "BENCH_ALLOW_HOSTS",
    "BENCH_RUNNER_VERSION",
    "BENCH_RUNNER_SHA256",
)
GPU_KEYS = (
    "BENCH_CI_GPUS",
    "BENCH_RESERVED_GPUS",
    "BENCH_GPU_QUERY",
    "BENCH_GPU_DEVICE",
    "BENCH_GPU_CAP_MIB",
    "BENCH_GPU_CAP_UTIL",
    "BENCH_WEIGHTS",
)
KEYS = frozenset(REQUIRED + GPU_KEYS)
WHOLE_NUMBERS = (
    "BENCH_CPU_SLOTS",
    "BENCH_ENGINE_SLOTS",
    "BENCH_GPU_SLOTS",
    "BENCH_CPUS",
    "BENCH_PIDS",
    "BENCH_JOB_HOURS",
)
MAX_SLOTS = {"cpu": 99, "engine": 49, "gpu": 49}


class SettingsError(ValueError):
    """The settings file is not complete or not well formed."""


@dataclass(frozen=True)
class Settings:
    values: dict[str, str]

    def __getitem__(self, key: str) -> str:
        return self.values[key]

    def num(self, key: str) -> int:
        return int(self.values[key])


def parse_settings(text: str) -> Settings:
    """``KEY=value`` lines and ``#`` comments; never sourced by a shell, so a value is only ever text."""
    values: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in KEYS:
            raise SettingsError(f"line {n}: not a known KEY=value line ({key or raw[:20]!r})")
        if key in values:
            raise SettingsError(f"line {n}: {key} given twice")
        if PLACEHOLDER.search(value):
            raise SettingsError(f"line {n}: {key} still holds a placeholder: fill it in on the bench host")
        values[key] = value
    missing = [k for k in REQUIRED if not values.get(k)]
    if missing:
        raise SettingsError(f"missing: {', '.join(missing)}")
    s = Settings(values)
    for key in WHOLE_NUMBERS:
        if not values[key].isdigit():
            raise SettingsError(f"{key} must be a whole number")
    for profile, most in MAX_SLOTS.items():
        if s.num(f"BENCH_{profile.upper()}_SLOTS") > most:
            raise SettingsError(f"BENCH_{profile.upper()}_SLOTS is at most {most}")
    if s.num("BENCH_GPU_SLOTS"):
        _gpu_settings(values)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", values["BENCH_REPO"]):
        raise SettingsError("BENCH_REPO is owner/name")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,30}", values["BENCH_LABEL"]):
        raise SettingsError("BENCH_LABEL is a short lower-case label")
    if not re.fullmatch(r"[0-9a-f]{64}", values["BENCH_RUNNER_SHA256"]):
        raise SettingsError("BENCH_RUNNER_SHA256 is the 64 hex digits the runner's release page gives")
    if not re.fullmatch(r"(25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})\.(25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})",
                        values["BENCH_SUBNET_PREFIX"]):  # fmt: skip
        raise SettingsError("BENCH_SUBNET_PREFIX is the first two numbers of a private /16, written a.b")
    for key in ("BENCH_ENGINE", "BENCH_SCRATCH", "BENCH_GPU_QUERY", "BENCH_WEIGHTS"):
        if values.get(key) and not values[key].startswith("/"):
            raise SettingsError(f"{key} is an absolute path")
    return s


def _gpu_settings(values: dict[str, str]) -> None:
    missing = [k for k in GPU_KEYS if not values.get(k)]
    if missing:
        raise SettingsError(f"a GPU slot needs: {', '.join(missing)}")
    for key in ("BENCH_GPU_CAP_MIB", "BENCH_GPU_CAP_UTIL"):
        if not values[key].isdigit():
            raise SettingsError(f"{key} must be a whole number")
    reserved = gpu_check.parse_ids(values["BENCH_RESERVED_GPUS"])
    problems = gpu_check.set_problems(gpu_check.parse_ids(values["BENCH_CI_GPUS"]), reserved)
    if problems:
        raise SettingsError("; ".join(problems))
    if int(WALK_CARD) not in reserved:
        raise SettingsError(f"BENCH_RESERVED_GPUS must keep card {WALK_CARD} (the walk's)")


def read_settings(path: Path) -> Settings:
    st = path.stat()
    if st.st_uid != 0 or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise SettingsError(f"{path} must be owned by root and writable by root only")
    return parse_settings(path.read_text(encoding="utf-8"))


def read_token(path: Path) -> str:
    """The long-lived minting token: root's file, readable by root alone; only the root mint step reads it."""
    st = path.stat()
    if st.st_uid != os.geteuid() or st.st_mode & 0o077:  # the mint step runs as root: root's file, 0600 or 0400
        raise SettingsError("the token file must be the reading user's (root's), mode 0600 or 0400")
    token = path.read_text(encoding="utf-8").strip()
    if not token or any(c.isspace() for c in token):
        raise SettingsError("the token file is empty or holds more than one token")
    return token


def labels(s: Settings, profile: str) -> list[str]:
    return [s["BENCH_LABEL"], f"{s['BENCH_LABEL']}-{profile}"]


def slot_profile(slot: str) -> tuple[str, int]:
    m = SLOT.match(slot)
    if not m:
        raise ValueError(f"{slot!r} is not a slot (cpu-N, engine-N or gpu-N)")
    return m.group(1), int(m.group(2))


def job_net(slot: str) -> str:
    """The slot's own internal network (F7): no other job's container is on it."""
    return f"tb-bench-job-{slot}"


def subnet(s: Settings, slot: str) -> tuple[str, str]:
    """The slot's /24 and the proxy's fixed address on it (F4: no name service: the jobs reach the proxy by address)."""
    kind, _, n = slot.partition("-")
    octet = OCTET_BASE[kind] + (int(n) if n.isdigit() else PROFILES.index(n) if n in PROFILES else -1)
    if not 0 < octet < 255:
        raise ValueError(f"no subnet for {slot!r}")
    net = f"{s['BENCH_SUBNET_PREFIX']}.{octet}"
    return f"{net}.0/24", f"{net}.2"


def scratch_of(s: Settings, slot: str) -> Path:
    return Path(s["BENCH_SCRATCH"]) / f"tb-bench-{slot}"


def proxy_env(proxy_ip: str) -> list[str]:
    url = f"http://{proxy_ip}:{PROXY_PORT}"
    out: list[str] = []
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        out += ["--env", f"{key}={url}"]
    out += ["--env", "NO_PROXY=localhost,127.0.0.1,::1", "--env", "no_proxy=localhost,127.0.0.1,::1"]
    out += ["--env", f"JAVA_TOOL_OPTIONS=-Dhttps.proxyHost={proxy_ip} -Dhttps.proxyPort={PROXY_PORT}"]
    return out


def container_args(s: Settings, profile: str, name: str, scratch: Path, slot: str) -> list[str]:
    """The job container's whole command line. tests/unit/test_bench_ci_launcher_h105.py holds every choice:

    * the image's own non-root user, the host's ``tb-bench`` user mapped onto it (rootless: root in no namespace);
    * host folders: this job's scratch folder at /scratch; a GPU job also the weights folder at /weights, read-only;
      no engine socket, no home, nothing else;
    * the slot's own internal network, no name service, the proxy by its fixed address the only way out;
    * every profile: read-only root (the engine's own tmpfs on its temporary folders), every capability dropped, no
      fuse or tun device; TMPDIR in the scratch folder;
    * cpu: also no new privileges;
    * engine and gpu (F5): the nested rootless engine maps its user namespace with the set-id helpers, so these keep
      SETUID and SETGID and cannot set no-new-privileges; they run on trains and the owner's runs only;
    * gpu: the CI cards by index, nothing else (shared by the GPU slots, each job checked against the set's cap).
    """
    if profile not in PROFILES:
        raise ValueError(f"no such profile: {profile}")
    _, proxy_ip = subnet(s, slot)
    args = [s["BENCH_ENGINE"], "run", "--rm", "--pull=never"]
    args += ["--name", name, "--hostname", name, "--label", CONTAINER_LABEL]
    args += [f"--userns=keep-id:uid={JOB_UID},gid={JOB_UID}", "--user", f"{JOB_UID}:{JOB_UID}"]
    args += ["--network", job_net(slot), "--dns", "none"]
    args += ["--cpus", s["BENCH_CPUS"], "--memory", s["BENCH_MEMORY"], "--pids-limit", s["BENCH_PIDS"]]
    args += ["--volume", f"{scratch}:/scratch:rw", "--workdir", "/scratch"]
    args += ["--env", "HOME=/scratch/home", "--env", "TMPDIR=/scratch/tmp", "--env", f"BENCH_PROFILE={profile}"]
    args += proxy_env(proxy_ip)
    args += ["--read-only", "--read-only-tmpfs=true", "--cap-drop=all"]
    if profile == "cpu":
        args += ["--security-opt", "no-new-privileges"]
    else:
        for cap in ENGINE_CAPS:
            args += ["--cap-add", cap]
    if profile == "gpu":
        for i in gpu_check.parse_ids(s["BENCH_CI_GPUS"]):
            args += ["--device", f"{s['BENCH_GPU_DEVICE']}={i}"]
        args += ["--volume", f"{s['BENCH_WEIGHTS']}:/weights:ro"]
    return [*args, s["BENCH_IMAGE"]]


def proxy_args(s: Settings) -> list[str]:
    """The egress proxy's container: on its way out only (the slots' networks join it per job), read-only."""
    args = [s["BENCH_ENGINE"], "run", "--rm", "--pull=never", "--replace"]
    args += ["--name", PROXY_NAME, "--label", CONTAINER_LABEL, "--network", EGRESS_NET]
    args += ["--user", f"{JOB_UID}:{JOB_UID}", "--read-only", "--cap-drop=all", "--security-opt", "no-new-privileges"]
    args += ["--memory", "1g", "--pids-limit", "256", "--entrypoint", "python3", s["BENCH_IMAGE"]]
    listen = f"0.0.0.0:{PROXY_PORT}"
    return [*args, "/opt/tb-bench/egress_proxy.py", "--listen", listen, "--allow", s["BENCH_ALLOW_HOSTS"]]


def api(method: str, path: str, token: str, body: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
    """One call to the repository's runner endpoints, or the read of the bench workflow's blob on master, straight
    to API_HOST over TLS (no proxy, no redirect)."""
    runners = path.startswith("/repos/") and "/actions/runners/" in path
    workflow = path.startswith("/repos/") and path.endswith(f"/contents/{WORKFLOW}?ref=master") and method == "GET"
    if not runners and not workflow:
        raise ValueError("the launcher calls the repository's runner endpoints and reads master's workflow only")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "tb-bench-ci",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    conn = http.client.HTTPSConnection(API_HOST, timeout=API_SECONDS)
    try:
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
    finally:
        conn.close()
    try:
        got = json.loads(raw) if raw else {}
    except ValueError:
        got = {}
    return resp.status, got if isinstance(got, dict) else {}


def master_blob(s: Settings, token: str) -> str:
    """Master's blob of the bench workflow, read by the host (the gate compares the job's against it)."""
    status, got = api("GET", f"/repos/{s['BENCH_REPO']}/contents/{WORKFLOW}?ref=master", token)
    blob = got.get("sha")
    if status != 200 or not isinstance(blob, str) or not re.fullmatch(r"[0-9a-f]{40}", blob):
        raise RuntimeError(f"master's bench workflow could not be read (HTTP {status})")
    return blob


def jit_config(s: Settings, token: str, name: str, profile: str) -> tuple[str, int]:
    body: dict[str, object] = {"name": name, "runner_group_id": 1, "labels": labels(s, profile), "work_folder": "_work"}
    status, got = api("POST", f"/repos/{s['BENCH_REPO']}/actions/runners/generate-jitconfig", token, body)
    runner = got.get("runner")
    config = got.get("encoded_jit_config")
    if status != 201 or not isinstance(config, str) or not isinstance(runner, dict):
        raise RuntimeError(f"the code host gave no runner configuration (HTTP {status})")
    runner_id = runner.get("id")
    if not isinstance(runner_id, int):
        raise RuntimeError("the code host's answer had no runner id")
    return config, runner_id


def remove_runner(s: Settings, token: str, runner_id: int) -> None:
    status, _ = api("DELETE", f"/repos/{s['BENCH_REPO']}/actions/runners/{runner_id}", token)
    if status not in (204, 404):  # 404: the single-use runner already removed itself
        print(f"bench CI: the runner registration {runner_id} could not be removed (HTTP {status})", file=sys.stderr)


def gpu_spec(s: Settings) -> tuple[list[str], dict[str, object]]:
    """The host's check of the CI cards, and what the job's own check reads (job.json)."""
    problems, uuids = gpu_check.host_check(
        s["BENCH_GPU_QUERY"],
        gpu_check.parse_ids(s["BENCH_CI_GPUS"]),
        gpu_check.parse_ids(s["BENCH_RESERVED_GPUS"]),
        s.num("BENCH_GPU_CAP_MIB"),
        s.num("BENCH_GPU_CAP_UTIL"),
    )
    spec: dict[str, object] = {
        "tool": s["BENCH_GPU_QUERY"],
        "uuids": uuids,
        "cap_mib": s.num("BENCH_GPU_CAP_MIB"),
        "cap_util": s.num("BENCH_GPU_CAP_UTIL"),
    }
    return problems, spec


def _write_for_jobs(path: Path, text: str, uid: int, gid: int) -> None:
    """A file only the jobs' user reads (0600), written by root without following a link."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chown(path, uid, gid)


def fresh_scratch(s: Settings, slot: str, uid: int, gid: int) -> Path:
    """The slot's scratch folder, emptied of anything an earlier job left (F8), owned by the jobs' user."""
    path = scratch_of(s, slot)
    if path.is_symlink():
        raise RuntimeError(f"{path} is a link")
    if path.exists():
        shutil.rmtree(path)
    for sub in ("", "home", "tmp", ".tb-bench"):
        (path / sub).mkdir(mode=0o700, exist_ok=sub == "")
        os.chown(path / sub, uid, gid)
    return path


def mint(s: Settings, slot: str, token_file: Path = TOKEN, state: Path = STATE) -> int:
    """Root: the long-lived token stays here; the job gets a one-job configuration and the gate's facts."""
    profile, _ = slot_profile(slot)
    if os.geteuid() != 0:
        print("bench CI: mint runs as root (the unit's ExecStartPre with full privileges)", file=sys.stderr)
        return 2
    facts: dict[str, object] = {"profile": profile, "repo": s["BENCH_REPO"], "workflow": WORKFLOW}
    if profile == "gpu":
        problems, spec = gpu_spec(s)
        if problems:
            for p in problems:
                print(f"bench CI: {p}", file=sys.stderr)
            print("bench CI: no GPU runner is registered while a CI card is busy beyond its cap", file=sys.stderr)
            return 3
        facts |= spec
    token = read_token(token_file)
    _, proxy_ip = subnet(s, slot)
    facts |= {"workflow_blob": master_blob(s, token), "proxy": f"{proxy_ip}:{PROXY_PORT}"}
    user = pwd.getpwnam(RUN_USER)
    scratch = fresh_scratch(s, slot, user.pw_uid, user.pw_gid)
    name = f"tb-bench-{slot}-{secrets.token_hex(4)}"
    config, runner_id = jit_config(s, token, name, profile)
    state.mkdir(mode=0o700, exist_ok=True)
    (state / f"{slot}.json").write_text(json.dumps({"runner_id": runner_id, "name": name}), encoding="utf-8")
    _write_for_jobs(scratch / ".tb-bench" / "job.json", json.dumps(facts), user.pw_uid, user.pw_gid)
    _write_for_jobs(scratch / ".tb-bench" / "runner.jit", config + "\n", user.pw_uid, user.pw_gid)
    print(f"bench CI: {name} registered for one job ({', '.join(labels(s, profile))})", flush=True)
    return 0


def cleanup(s: Settings, slot: str, token_file: Path = TOKEN, state: Path = STATE) -> int:
    """Root, after the job, a failure or a stop (F8): the registration and the scratch folder go."""
    slot_profile(slot)
    record = state / f"{slot}.json"
    if record.exists():
        try:
            runner_id = int(json.loads(record.read_text(encoding="utf-8"))["runner_id"])
            remove_runner(s, read_token(token_file), runner_id)
        except (OSError, ValueError, KeyError, SettingsError, http.client.HTTPException) as exc:
            print(f"bench CI: {slot}: the registration could not be removed ({type(exc).__name__})", file=sys.stderr)
        record.unlink(missing_ok=True)
    path = scratch_of(s, slot)
    if path.exists() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    return 0


def _engine(s: Settings, *args: str) -> int:
    return subprocess.run([s["BENCH_ENGINE"], *args], check=False, capture_output=True).returncode


def net_up(s: Settings, slot: str) -> None:
    """The slot's network: internal (no route out), no name service; the proxy joins it at its fixed address."""
    cidr, proxy_ip = subnet(s, slot)
    net_down(s, slot)
    if _engine(s, "network", "create", "--internal", "--disable-dns", "--subnet", cidr, job_net(slot)) != 0:
        raise RuntimeError(f"the network {job_net(slot)} could not be made")
    if _engine(s, "network", "connect", "--ip", proxy_ip, job_net(slot), PROXY_NAME) != 0:
        raise RuntimeError("the egress proxy could not join the job's network (is tb-bench-proxy running?)")


def net_down(s: Settings, slot: str) -> None:
    _engine(s, "network", "disconnect", "--force", job_net(slot), PROXY_NAME)
    _engine(s, "network", "rm", "--force", job_net(slot))


def run_slot(s: Settings, slot: str) -> int:
    """The jobs' user: the container of the job the mint step registered. Never reads the long-lived token."""
    profile, _ = slot_profile(slot)
    scratch = scratch_of(s, slot)
    if not (scratch / ".tb-bench" / "runner.jit").exists():
        print(f"bench CI: {slot}: no one-job configuration (the mint step did not run)", file=sys.stderr)
        return 2
    name = f"tb-bench-{slot}"
    _engine(s, "rm", "--force", name)  # a container a killed run left behind (F8)
    net_up(s, slot)
    proc = subprocess.Popen(container_args(s, profile, name, scratch, slot), stdin=subprocess.DEVNULL)

    def stop(_sig: int, _frame: FrameType | None) -> None:  # F8: a unit stop stops the job and its network
        _engine(s, "stop", "--time", "10", name)

    signal.signal(signal.SIGTERM, stop)
    try:
        try:
            rc = proc.wait(timeout=s.num("BENCH_JOB_HOURS") * 3600)
        except subprocess.TimeoutExpired:
            _engine(s, "rm", "--force", name)
            print(f"bench CI: {name} passed {s['BENCH_JOB_HOURS']} h and was stopped", file=sys.stderr)
            rc = proc.wait()
        print(f"bench CI: {name} ended (exit {rc})", flush=True)
        return 0
    finally:
        with contextlib.suppress(OSError):
            _engine(s, "rm", "--force", name)
        net_down(s, slot)


def probe_args(s: Settings, profile: str, scratch: Path) -> list[str]:
    """The verify step's container: the profile's arguments exactly, with the probe instead of the runner."""
    args = container_args(s, profile, scratch.name, scratch, f"probe-{profile}")
    return [*args[:-1], "--entrypoint", "/opt/tb-bench/probe.sh", args[-1]]


def probe(s: Settings, profile: str) -> int:
    slot = f"probe-{profile}"
    scratch = Path(s["BENCH_SCRATCH"]) / f"tb-bench-{slot}"
    _engine(s, "unshare", "rm", "-rf", "--one-file-system", str(scratch))
    for sub in ("", "home", "tmp", ".tb-bench"):
        (scratch / sub).mkdir(mode=0o700, exist_ok=sub == "")
    net_up(s, slot)
    try:
        return subprocess.run(probe_args(s, profile, scratch), stdin=subprocess.DEVNULL, check=False).returncode
    finally:
        net_down(s, slot)
        _engine(s, "unshare", "rm", "-rf", "--one-file-system", str(scratch))


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("check", "get", "mint", "run", "cleanup", "proxy", "probe"):
        p = sub.add_parser(cmd)
        p.add_argument("--settings", type=Path, default=Path("/etc/tb-bench-ci/settings.env"))
        if cmd == "get":
            p.add_argument("key", choices=sorted(KEYS))
        if cmd in ("mint", "run", "cleanup"):
            p.add_argument("--slot", required=True)
        if cmd == "probe":
            p.add_argument("--profile", choices=PROFILES, required=True)
    args = ap.parse_args(argv)
    try:
        s = read_settings(args.settings)
    except (OSError, SettingsError) as exc:
        print(f"bench CI: settings: {exc}", file=sys.stderr)
        return 2
    if args.cmd == "get":
        print(s.values.get(args.key, ""))
        return 0
    if args.cmd == "check":
        return check(s)
    if args.cmd == "proxy":
        os.execv(s["BENCH_ENGINE"], proxy_args(s))
    try:
        if args.cmd == "probe":
            return probe(s, args.profile)
        if args.cmd == "mint":
            return mint(s, args.slot)
        if args.cmd == "cleanup":
            return cleanup(s, args.slot)
        return run_slot(s, args.slot)
    except (OSError, SettingsError, RuntimeError, ValueError, KeyError, http.client.HTTPException) as exc:
        print(f"bench CI: {args.cmd} {getattr(args, 'slot', '')}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def check(s: Settings) -> int:
    slots = {p: s.num(f"BENCH_{p.upper()}_SLOTS") for p in PROFILES}
    print(f"bench CI: settings complete; slots {slots}; label {s['BENCH_LABEL']}")
    if not s.num("BENCH_GPU_SLOTS"):
        return 0
    try:
        problems, _ = gpu_spec(s)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        problems = [f"the CI cards could not be checked: {exc}"]
    for problem in problems:
        print(f"bench CI: {problem}", file=sys.stderr)
    print("bench CI: the CI cards are within their cap" if not problems else "bench CI: the CI cards are busy")
    return 0 if not problems else 3


if __name__ == "__main__":
    sys.exit(main())
