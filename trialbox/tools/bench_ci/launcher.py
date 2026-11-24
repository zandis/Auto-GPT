"""The bench host's CI runner launcher (card H-105): one single-use container per CI job, then gone.

A systemd unit runs one slot (``tb-bench-runner@<profile>-<n>``) as the unprivileged ``tb-bench`` user; each run of
the unit is one job's life:

1. read the settings file (a root-owned file on the host; the repository holds only
   ``tools/bench_ci/settings.example.env``) and refuse a placeholder, an unknown key or a missing one;
2. a GPU slot: check the CI cards (``gpu_check.host_check``): never a card of the walk or the bench, none busy;
3. ask the code host for a just-in-time runner configuration (one job, then the registration is gone), with the
   minting token from the file systemd hands the unit (``--token-file``); the token goes to the code host's API
   address written below and nowhere else (``http.client`` reads no proxy setting from any environment), never in
   an argument, never in a log;
4. start the job's container (``container_args``) with that configuration on its standard input, in a fresh scratch
   folder made for this job; wait for it; remove the registration if it is still there; delete the scratch folder.

The harms this file stands between (the page names them): a job that escapes its container reaches the owner's
data and keys (so: a rootless engine as its own user, no host folder but the job's scratch, no engine socket, no host
network); a leaked token lets another machine join as a runner (so: root-only file, systemd credential, never in an
argument or the environment). Which code reaches this runner at all is the workflow's part
(``.github/workflows/trialbox-bench-ci.yml``, ``tests/unit/test_bench_ci_workflow_h105.py``).

    python3 -s -E -m tools.bench_ci.launcher check --settings FILE
    python3 -s -E -m tools.bench_ci.launcher get --settings FILE KEY   (one setting; the settings hold no secret)
    python3 -s -E -m tools.bench_ci.launcher run --settings FILE --token-file FILE --slot cpu-1
    python3 -s -E -m tools.bench_ci.launcher proxy --settings FILE
    python3 -s -E -m tools.bench_ci.launcher probe --settings FILE

Standard library only: the host's python3 runs it from /opt/tb-bench-ci (root's, read-only to the tb-bench user),
where install.sh lays out tools/bench_ci/ as in the repository; -E: no PYTHON* variable of a caller is read.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.bench_ci import gpu_check

API_HOST = "api.github.com"  # the code host's API; the token goes here and nowhere else
JOBS_NET = "tb-bench-jobs"  # internal: no route out
EGRESS_NET = "tb-bench-egress"  # the proxy's way out
PROXY_NAME = "tb-bench-proxy"
PROXY_PORT = 3128
JOB_UID = 1001  # the job image's own non-root user
CONTAINER_LABEL = "tb-bench-ci=1"
PROFILES = ("cpu", "engine", "gpu")
SLOT = re.compile(r"^(cpu|engine|gpu)-([1-9][0-9]?)$")
API_SECONDS = 60
PLACEHOLDER = re.compile(r"<[^>]*>")
WALK_CARD = "1"

REQUIRED = (
    "TB_BENCH_REPO",
    "TB_BENCH_LABEL",
    "TB_BENCH_IMAGE",
    "TB_BENCH_ENGINE",
    "TB_BENCH_SCRATCH",
    "TB_BENCH_CPU_SLOTS",
    "TB_BENCH_ENGINE_SLOTS",
    "TB_BENCH_GPU_SLOTS",
    "TB_BENCH_CPUS",
    "TB_BENCH_MEMORY",
    "TB_BENCH_PIDS",
    "TB_BENCH_TMP_SIZE",
    "TB_BENCH_JOB_HOURS",
    "TB_BENCH_ALLOW_HOSTS",
    "TB_BENCH_RUNNER_VERSION",
    "TB_BENCH_RUNNER_SHA256",
)
GPU_KEYS = (
    "TB_BENCH_CI_GPUS",
    "TB_BENCH_RESERVED_GPUS",
    "TB_BENCH_GPU_QUERY",
    "TB_BENCH_GPU_DEVICE",
    "TB_BENCH_GPU_BUSY_MIB",
    "TB_BENCH_GPU_BUSY_UTIL",
)
KEYS = frozenset(REQUIRED + GPU_KEYS)
WHOLE_NUMBERS = (
    "TB_BENCH_CPU_SLOTS",
    "TB_BENCH_ENGINE_SLOTS",
    "TB_BENCH_GPU_SLOTS",
    "TB_BENCH_CPUS",
    "TB_BENCH_PIDS",
    "TB_BENCH_JOB_HOURS",
)


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
    if s.num("TB_BENCH_GPU_SLOTS") > 1:
        raise SettingsError("TB_BENCH_GPU_SLOTS is 0 or 1: the CI cards are one set, for one job at a time")
    if s.num("TB_BENCH_GPU_SLOTS"):
        _gpu_settings(values)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", values["TB_BENCH_REPO"]):
        raise SettingsError("TB_BENCH_REPO is owner/name")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,30}", values["TB_BENCH_LABEL"]):
        raise SettingsError("TB_BENCH_LABEL is a short lower-case label")
    if not re.fullmatch(r"[0-9a-f]{64}", values["TB_BENCH_RUNNER_SHA256"]):
        raise SettingsError("TB_BENCH_RUNNER_SHA256 is the 64 hex digits the runner's release page gives")
    for key in ("TB_BENCH_ENGINE", "TB_BENCH_SCRATCH", "TB_BENCH_GPU_QUERY"):
        if values.get(key) and not values[key].startswith("/"):
            raise SettingsError(f"{key} is an absolute path")
    return s


def _gpu_settings(values: dict[str, str]) -> None:
    missing = [k for k in GPU_KEYS if not values.get(k)]
    if missing:
        raise SettingsError(f"a GPU slot needs: {', '.join(missing)}")
    for key in ("TB_BENCH_GPU_BUSY_MIB", "TB_BENCH_GPU_BUSY_UTIL"):
        if not values[key].isdigit():
            raise SettingsError(f"{key} must be a whole number")
    reserved = gpu_check.parse_ids(values["TB_BENCH_RESERVED_GPUS"])
    problems = gpu_check.set_problems(gpu_check.parse_ids(values["TB_BENCH_CI_GPUS"]), reserved)
    if problems:
        raise SettingsError("; ".join(problems))
    if int(WALK_CARD) not in reserved:
        raise SettingsError(f"TB_BENCH_RESERVED_GPUS must keep card {WALK_CARD} (the walk's)")


def read_settings(path: Path) -> Settings:
    st = path.stat()
    if st.st_uid != 0 or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise SettingsError(f"{path} must be owned by root and writable by root only")
    return parse_settings(path.read_text(encoding="utf-8"))


def read_token(path: Path) -> str:
    """The minting token, from the file systemd hands the unit (a copy of a root-only file). Never printed."""
    st = path.stat()
    if st.st_mode & 0o077:
        raise SettingsError("the token file is readable by others: it must be mode 0600 or 0400")
    token = path.read_text(encoding="utf-8").strip()
    if not token or any(c.isspace() for c in token):
        raise SettingsError("the token file is empty or holds more than one token")
    return token


def labels(s: Settings, profile: str) -> list[str]:
    return [s["TB_BENCH_LABEL"], f"{s['TB_BENCH_LABEL']}-{profile}"]


def proxy_env() -> list[str]:
    url = f"http://{PROXY_NAME}:{PROXY_PORT}"
    out: list[str] = []
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        out += ["--env", f"{key}={url}"]
    out += ["--env", "NO_PROXY=localhost,127.0.0.1,::1", "--env", "no_proxy=localhost,127.0.0.1,::1"]
    out += ["--env", f"JAVA_TOOL_OPTIONS=-Dhttps.proxyHost={PROXY_NAME} -Dhttps.proxyPort={PROXY_PORT}"]
    return out


def container_args(s: Settings, profile: str, name: str, scratch: Path) -> list[str]:
    """The job container's whole command line. tests/unit/test_bench_ci_launcher_h105.py holds every choice:

    * the image's own non-root user, the host's ``tb-bench`` user mapped onto it (rootless: root in no namespace);
    * one host folder: this job's scratch folder, at /scratch; no engine socket, no home, no other folder;
    * the internal jobs network only (the proxy is the one way out); never the host's network;
    * cpu: read-only root, every capability dropped, no new privileges;
    * engine and gpu: a nested rootless engine of the job's own (it needs the fuse and tun devices, the default
      capabilities and set-uid id mapping, so the root is writable and new privileges are not blocked);
    * gpu: the CI cards by index, nothing else.
    """
    if profile not in PROFILES:
        raise ValueError(f"no such profile: {profile}")
    args = [s["TB_BENCH_ENGINE"], "run", "--rm", "--interactive", "--pull=never"]
    args += ["--name", name, "--hostname", name, "--label", CONTAINER_LABEL]
    args += [f"--userns=keep-id:uid={JOB_UID},gid={JOB_UID}", "--user", f"{JOB_UID}:{JOB_UID}"]
    args += ["--network", JOBS_NET]
    args += ["--cpus", s["TB_BENCH_CPUS"], "--memory", s["TB_BENCH_MEMORY"], "--pids-limit", s["TB_BENCH_PIDS"]]
    args += ["--tmpfs", f"/tmp:rw,nosuid,nodev,size={s['TB_BENCH_TMP_SIZE']}"]
    args += ["--volume", f"{scratch}:/scratch:rw", "--workdir", "/scratch"]
    args += ["--env", "HOME=/scratch/home", "--env", f"TB_BENCH_PROFILE={profile}", *proxy_env()]
    if profile == "cpu":
        args += ["--read-only", "--cap-drop=all", "--security-opt", "no-new-privileges"]
    else:
        args += ["--device", "/dev/fuse", "--device", "/dev/net/tun", "--security-opt", "label=disable"]
    if profile == "gpu":
        for i in gpu_check.parse_ids(s["TB_BENCH_CI_GPUS"]):
            args += ["--device", f"{s['TB_BENCH_GPU_DEVICE']}={i}"]
    return [*args, s["TB_BENCH_IMAGE"]]


def proxy_args(s: Settings) -> list[str]:
    """The egress proxy's container: on both networks, read-only, no capability, the allow-list on its line."""
    args = [s["TB_BENCH_ENGINE"], "run", "--rm", "--pull=never", "--replace"]
    args += ["--name", PROXY_NAME, "--label", CONTAINER_LABEL, "--network", JOBS_NET, "--network", EGRESS_NET]
    args += ["--user", f"{JOB_UID}:{JOB_UID}", "--read-only", "--cap-drop=all", "--security-opt", "no-new-privileges"]
    args += ["--memory", "1g", "--pids-limit", "256", "--entrypoint", "python3", s["TB_BENCH_IMAGE"]]
    return [
        *args,
        "/opt/tb-bench/egress_proxy.py",
        "--listen",
        f"0.0.0.0:{PROXY_PORT}",
        "--allow",
        s["TB_BENCH_ALLOW_HOSTS"],
    ]


def api(method: str, path: str, token: str, body: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
    """One call to the repository's runner endpoints, straight to API_HOST over TLS (no proxy, no redirect)."""
    if not path.startswith("/repos/") or "/actions/runners/" not in path:
        raise ValueError("the launcher calls the repository's runner endpoints only")
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


def jit_config(s: Settings, token: str, name: str, profile: str) -> tuple[str, int]:
    body: dict[str, object] = {"name": name, "runner_group_id": 1, "labels": labels(s, profile), "work_folder": "_work"}
    status, got = api("POST", f"/repos/{s['TB_BENCH_REPO']}/actions/runners/generate-jitconfig", token, body)
    runner = got.get("runner")
    config = got.get("encoded_jit_config")
    if status != 201 or not isinstance(config, str) or not isinstance(runner, dict):
        raise RuntimeError(f"the code host gave no runner configuration (HTTP {status})")
    runner_id = runner.get("id")
    if not isinstance(runner_id, int):
        raise RuntimeError("the code host's answer had no runner id")
    return config, runner_id


def remove_runner(s: Settings, token: str, runner_id: int) -> None:
    status, _ = api("DELETE", f"/repos/{s['TB_BENCH_REPO']}/actions/runners/{runner_id}", token)
    if status not in (204, 404):  # 404: the single-use runner already removed itself
        print(f"bench CI: the runner registration {runner_id} could not be removed (HTTP {status})", file=sys.stderr)


def new_scratch(s: Settings, name: str) -> Path:
    path = Path(s["TB_BENCH_SCRATCH"]) / name
    path.mkdir(mode=0o700)
    (path / "home").mkdir(mode=0o700)
    (path / ".tb-bench").mkdir(mode=0o700)
    return path


def drop_scratch(s: Settings, path: Path) -> None:
    """The job's files belong to ids of the rootless namespace: remove them from inside it."""
    if path.parent != Path(s["TB_BENCH_SCRATCH"]) or not path.name.startswith("tb-bench-"):
        raise ValueError(f"not a job scratch folder: {path}")
    subprocess.run([s["TB_BENCH_ENGINE"], "unshare", "rm", "-rf", "--one-file-system", str(path)], check=False)


def gpu_spec(s: Settings) -> tuple[list[str], dict[str, object]]:
    """The host's check of the CI cards, and what the job's own check reads (job.json)."""
    problems, uuids = gpu_check.host_check(
        s["TB_BENCH_GPU_QUERY"],
        gpu_check.parse_ids(s["TB_BENCH_CI_GPUS"]),
        gpu_check.parse_ids(s["TB_BENCH_RESERVED_GPUS"]),
        s.num("TB_BENCH_GPU_BUSY_MIB"),
        s.num("TB_BENCH_GPU_BUSY_UTIL"),
    )
    spec: dict[str, object] = {
        "profile": "gpu",
        "tool": s["TB_BENCH_GPU_QUERY"],
        "uuids": uuids,
        "busy_mib": s.num("TB_BENCH_GPU_BUSY_MIB"),
        "busy_util": s.num("TB_BENCH_GPU_BUSY_UTIL"),
    }
    return problems, spec


def run_slot(s: Settings, token_file: Path, slot: str) -> int:
    m = SLOT.match(slot)
    if not m:
        print(f"bench CI: {slot!r} is not a slot (cpu-N, engine-N or gpu-N)", file=sys.stderr)
        return 2
    profile = m.group(1)
    spec: dict[str, object] = {"profile": profile}
    if profile == "gpu":
        problems, spec = gpu_spec(s)
        if problems:
            for p in problems:
                print(f"bench CI: {p}", file=sys.stderr)
            print("bench CI: no GPU runner is registered until the CI cards are free", file=sys.stderr)
            return 3
    token = read_token(token_file)
    name = f"tb-bench-{slot}-{secrets.token_hex(4)}"
    scratch = new_scratch(s, name)
    runner_id = 0
    try:
        (scratch / ".tb-bench" / "job.json").write_text(json.dumps(spec), encoding="utf-8")
        config, runner_id = jit_config(s, token, name, profile)
        print(f"bench CI: {name} registered for one job ({', '.join(labels(s, profile))})", flush=True)
        rc = run_container(s, container_args(s, profile, name, scratch), config, name)
        print(f"bench CI: {name} ended (exit {rc})", flush=True)
        return 0
    finally:
        if runner_id:
            remove_runner(s, token, runner_id)
        drop_scratch(s, scratch)


def run_container(s: Settings, args: list[str], config: str, name: str) -> int:
    """The configuration goes on the container's standard input: never an argument or a variable on the host."""
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, text=True)
    if proc.stdin is None:
        raise RuntimeError("no standard input to the container")
    proc.stdin.write(config + "\n")
    proc.stdin.close()
    try:
        return proc.wait(timeout=s.num("TB_BENCH_JOB_HOURS") * 3600)
    except subprocess.TimeoutExpired:
        subprocess.run([s["TB_BENCH_ENGINE"], "rm", "--force", name], check=False)
        print(f"bench CI: {name} passed {s['TB_BENCH_JOB_HOURS']} h and was stopped", file=sys.stderr)
        return proc.wait()


def probe_args(s: Settings, scratch: Path) -> list[str]:
    """The verify step's container: the cpu profile's arguments exactly, with the probe instead of the runner."""
    args = container_args(s, "cpu", scratch.name, scratch)
    return [*args[:-1], "--entrypoint", "/opt/tb-bench/probe.sh", args[-1]]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("check", "get", "run", "proxy", "probe"):
        p = sub.add_parser(cmd)
        p.add_argument("--settings", type=Path, default=Path("/etc/tb-bench-ci/settings.env"))
        if cmd == "get":
            p.add_argument("key", choices=sorted(KEYS))
        if cmd == "run":
            p.add_argument("--token-file", type=Path, required=True)
            p.add_argument("--slot", required=True)
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
        slots = {p: s.num(f"TB_BENCH_{p.upper()}_SLOTS") for p in PROFILES}
        print(f"bench CI: settings complete; slots {slots}; label {s['TB_BENCH_LABEL']}")
        if not s.num("TB_BENCH_GPU_SLOTS"):
            return 0
        try:
            problems, _ = gpu_spec(s)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            problems = [f"the CI cards could not be checked: {exc}"]
        for problem in problems:
            print(f"bench CI: {problem}", file=sys.stderr)
        print("bench CI: the CI cards are free" if not problems else "bench CI: the CI cards are NOT free now")
        return 0 if not problems else 3
    if args.cmd == "proxy":
        os.execv(s["TB_BENCH_ENGINE"], proxy_args(s))
    if args.cmd == "probe":
        scratch = new_scratch(s, f"tb-bench-probe-{secrets.token_hex(4)}")
        try:
            return subprocess.run(probe_args(s, scratch), stdin=subprocess.DEVNULL, check=False).returncode
        finally:
            drop_scratch(s, scratch)
    try:
        return run_slot(s, args.token_file, args.slot)
    except (OSError, SettingsError, RuntimeError, http.client.HTTPException) as exc:
        print(f"bench CI: {args.slot}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
