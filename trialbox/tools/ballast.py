"""The ballast stand-in (plan 10 card 10E-28; review 19's card 19-2 and its section 4.1): hold a larger NVIDIA card
down to the free memory of an RTX 5090, so the free runs O-1 to O-7 on the owner's card see what the 32 GB site box
would show, and set the two utilisations the 5090 profile needs on that larger card.

    python3 -m tools.ballast plan                               # checks and numbers only, allocates nothing
    python3 -m tools.ballast hold [--env-file deploy/.env]      # hold until Ctrl-C or SIGTERM, then release
    python3 -m tools.ballast release [--env-file deploy/.env]   # remove a ballast left by a killed `hold`

What it does. A 5090 reports 32,607 MiB (``deploy/docker-compose.rtx5090.yml``). ``hold`` starts one container from the
same vLLM image the profile serves with (``VLLM_IMAGE``, else the compose file's default), with no network and
``--pull never``; inside it, torch allocates until ``torch.cuda.mem_get_info()`` reports the target free (the measure
vLLM itself reads), so the ballast's own CUDA context is counted and the stand-in is never looser than the target.
``nvidia-smi`` then confirms the free memory is the target within the tolerance (512 MiB), and the script prints
what it holds and what is left. vLLM's utilisation is a share of the card's total, so the profile's 0.81 of 32,607
MiB becomes 26,412 MiB / total (0.537 on 49,140 MiB): ``hold`` prints both as ``export`` lines and, with
``--env-file``, writes them into that file (each under a ``# tb-ballast:`` line naming the value it replaced) and
puts the old values back on release. A record taken under it says ``--capped-to "RTX 5090 (32 GB), by ballast"``,
which ``tools/serving_config.py measured_for`` refuses as a tier record, as it should.

It refuses, with a named reason and before allocating anything: ``production`` (TB_ENV is PRODUCTION; this is a
measurement aid for a VALIDATION or DEV box), ``driver-tool-missing`` / ``driver-tool-failed`` (no working
``nvidia-smi``), ``no-such-card``, ``card-too-small`` (the card's total is below the target), ``card-is-the-target``
(a real 32 GB card: run without a ballast), ``memory-already-held`` (a compute process it was not told to expect, or
more memory in use than ``--expect-used``), ``docker-missing``, ``image-not-local`` (it never pulls),
``ballast-already-running``. After allocating: ``allocation-failed``, ``off-target`` (released at once), and
``ballast-lost`` when the holder dies while the servers may still be running (records after that are not "by
ballast"). Every wait has a deadline (60 s for nvidia-smi and docker, 30 s for the holder to end): a release
that cannot finish says what it left behind. Exit 0 on a clean release, 2 on a refusal, 1 on a lost ballast or
something left behind.

It is never started by the installer, compose or any service; it needs no network. Arithmetic and process control
only: nothing here was run on a card (see docs/plan/measurements/ballast-stand-in-2026-11-18.md).
"""

from __future__ import annotations

import argparse
import io
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]
PROFILE_COMPOSE = ROOT / "deploy" / "docker-compose.rtx5090.yml"
TARGET_MIB = 32607  # what a real 5090 reports (deploy/docker-compose.rtx5090.yml; review 19 section 3.1)
TOLERANCE_MIB = 512  # plan 10's 10E-28 "Done when": 32,607 MiB +/- 512
EXPECT_USED_MIB = 1024  # memory in use before the ballast that is taken as the driver's own, not another process
CAPPED_TO = "RTX 5090 (32 GB), by ballast"
CONTAINER = "tb-ballast"
UTIL_KEYS = ("JUDGE_GPU_MEM_UTIL", "VERIFIER_GPU_MEM_UTIL")
MARK = "# tb-ballast:"
CMD_TIMEOUT_S = 60.0  # nvidia-smi or docker that has not answered by then is not going to: refuse, or release anyway

Run = Callable[[Sequence[str]], str]


class Refused(Exception):
    """A named reason not to hold (or to stop holding)."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code
        self.text = text


@dataclass
class Card:
    index: int
    uuid: str
    name: str
    total: int
    used: int
    free: int


@dataclass
class Proc:
    pid: str
    name: str
    used: int | None


@dataclass
class Plan:
    card: Card
    target: int
    ballast: int  # MiB the holder is expected to take (before its own context)
    utils: dict[str, float] = field(default_factory=dict)


# ------------------------------------------------------------------------------------------------ reading the card


def run_cmd(cmd: Sequence[str], timeout: float = CMD_TIMEOUT_S) -> str:
    """Run a local tool and return its stdout; a missing, failing or silent driver tool is a named refusal."""
    if shutil.which(cmd[0]) is None:
        code = "driver-tool-missing" if cmd[0] == "nvidia-smi" else f"{cmd[0]}-missing"
        raise Refused(code, f"{cmd[0]} is not on PATH")
    try:
        p = subprocess.run(list(cmd), capture_output=True, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        code = "driver-tool-failed" if cmd[0] == "nvidia-smi" else f"{cmd[0]}-failed"
        raise Refused(code, f"{' '.join(cmd[:2])} did not answer in {timeout:.0f} s") from None
    if p.returncode != 0:
        first = (p.stderr or p.stdout).strip().splitlines()[:1]
        code = "driver-tool-failed" if cmd[0] == "nvidia-smi" else f"{cmd[0]}-failed"
        raise Refused(code, f"{' '.join(cmd[:2])} exited {p.returncode}: {first[0] if first else ''}")
    return p.stdout


def _int(v: str) -> int | None:
    v = v.strip()
    return int(float(v)) if re.fullmatch(r"\d+(\.\d+)?", v) else None


def read_card(index: int, run: Run = run_cmd) -> Card:
    out = run(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ]
    )
    seen = []
    for line in out.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 6:
            continue
        idx, total, used, free = _int(parts[0]), _int(parts[-3]), _int(parts[-2]), _int(parts[-1])
        if idx is None or total is None or used is None or free is None:
            raise Refused("driver-tool-failed", f"nvidia-smi gave no memory figures for card {parts[0]}: {line!r}")
        seen.append(idx)
        if idx == index:
            return Card(idx, parts[1], ", ".join(parts[2:-3]), total, used, free)
    raise Refused("no-such-card", f"nvidia-smi lists cards {seen or 'none'}, not {index}")


def read_procs(card: Card, run: Run = run_cmd) -> list[Proc]:
    out = run(
        ["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,process_name,used_memory", "--format=csv,noheader,nounits"]
    )
    procs = []
    for line in out.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 4 and parts[0] == card.uuid:
            procs.append(Proc(parts[1], ", ".join(parts[2:-1]), _int(parts[-1])))
    return procs


# ------------------------------------------------------------------------------------------------ the arithmetic


def profile_utils(compose: Path = PROFILE_COMPOSE) -> dict[str, float]:
    """The 5090 profile's default utilisations, from its compose file (``--gpu-memory-utilization=${KEY:-0.81}``)."""
    text = compose.read_text(encoding="utf-8")
    found = {k: float(v) for k, v in re.findall(r"--gpu-memory-utilization=\$\{(\w+):-([0-9.]+)\}", text)}
    missing = [k for k in UTIL_KEYS if k not in found]
    if missing:
        raise Refused("profile-unreadable", f"{compose.name} names no default for {', '.join(missing)}")
    return {k: found[k] for k in UTIL_KEYS}


def util_on(total: int, profile_util: float, target: int = TARGET_MIB) -> float:
    """The utilisation on a ``total`` MiB card that gives the budget ``profile_util`` gives on the target, rounded down
    to three places so the budget is never larger than the 5090's (0.81 -> 0.537 on 49,140 MiB)."""
    return math.floor(profile_util * target / total * 1000) / 1000


def tb_env(env_file: Path | None) -> str:
    """TB_ENV as the process sees it, else as ``env_file`` names it (read the way install.sh reads it)."""
    v = os.environ.get("TB_ENV", "")
    if not v and env_file is not None and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("TB_ENV="):
                v = line.split("=", 1)[1]
    return re.sub(r"[\"'\s]", "", v).upper()


def refuse_production(env_file: Path | None) -> None:
    if tb_env(env_file) == "PRODUCTION":
        raise Refused(
            "production", "TB_ENV is PRODUCTION: the ballast is a measurement aid for a VALIDATION or DEV box"
        )


def check(
    card: Card,
    procs: list[Proc],
    *,
    target: int = TARGET_MIB,
    tolerance: int = TOLERANCE_MIB,
    expect_used: int = EXPECT_USED_MIB,
    expect_procs: Sequence[str] = (),
    profile: dict[str, float] | None = None,
) -> Plan:
    if card.total < target:
        raise Refused("card-too-small", f"{card.name} has {card.total} MiB in all, below the target {target} MiB")
    if card.total - target <= tolerance:
        raise Refused(
            "card-is-the-target", f"{card.name} has {card.total} MiB: within {tolerance} of {target}, no ballast"
        )
    strangers = [p for p in procs if not any(e and e in p.name for e in expect_procs)]
    if strangers:
        named = "; ".join(f"pid {p.pid} {p.name} {p.used if p.used is not None else '?'} MiB" for p in strangers)
        raise Refused(
            "memory-already-held", f"compute processes already on the card: {named} (stop them, or --expect-process)"
        )
    if card.used > expect_used:
        raise Refused(
            "memory-already-held",
            f"{card.used} MiB already in use, more than the {expect_used} MiB expected (a display? another server?"
            " stop it, or --expect-used)",
        )
    if card.free <= target:
        raise Refused("memory-already-held", f"only {card.free} MiB free, not above the target {target} MiB")
    prof = profile if profile is not None else profile_utils()
    return Plan(card, target, card.free - target, {k: util_on(card.total, v, target) for k, v in prof.items()})


# ------------------------------------------------------------------------------------------------ the env file


def set_env(path: Path, values: dict[str, float]) -> None:
    """Write ``values`` into ``path``, each under a ``# tb-ballast:`` line naming what it replaced."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    if any(x.startswith(MARK) for x in lines):
        raise Refused(
            "ballast-already-running", f"{path} already holds tb-ballast values (`release --env-file {path}`)"
        )
    out = []
    old: dict[str, str] = {}
    for line in lines:
        k = line.split("=", 1)[0]
        if k in values and "=" in line:
            old[k] = line.split("=", 1)[1]
        else:
            out.append(line)
    for k, v in values.items():
        out.append(
            f"{MARK} set by tools/ballast.py; was {k}={old[k]}"
            if k in old
            else f"{MARK} set by tools/ballast.py; was unset"
        )
        out.append(f"{k}={v}")
    _write_keep_mode(path, out)


def restore_env(path: Path) -> list[str]:
    """Take out what ``set_env`` wrote and put the replaced values back; returns the keys restored."""
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    back: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(MARK) and i + 1 < len(lines) and "=" in lines[i + 1]:
            k = lines[i + 1].split("=", 1)[0]
            m = re.search(r"; was (\w+)=(.*)$", line)
            if m and m.group(1) == k:
                out.append(f"{k}={m.group(2)}")
            back.append(k)
            i += 2
            continue
        out.append(line)
        i += 1
    if back:
        _write_keep_mode(path, out)
    return back


def _write_keep_mode(path: Path, lines: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:  # in place: keeps the file's owner and mode (deploy/.env is 0600)
        f.write("\n".join(lines) + ("\n" if lines else ""))


# ------------------------------------------------------------------------------------------------ the holder


class Allocator(Protocol):
    def preflight(self) -> None: ...
    def start(self, target_free: int, index: int) -> tuple[int, int]: ...  # (MiB held, MiB free as the holder sees it)
    def alive(self) -> bool: ...
    def release(self) -> str: ...  # what is left behind, "" when nothing


# Runs inside the vLLM image: allocate until the device reports the target free, print what it holds, then wait.
HOLDER = """\
import signal, sys, time, torch
t = int(sys.argv[1]) << 20
held = []
for _ in range(8):
    f, _ = torch.cuda.mem_get_info()
    if f - t < (64 << 20):
        break
    held.append(torch.empty(f - t, dtype=torch.uint8, device="cuda"))
f, _ = torch.cuda.mem_get_info()
print("HELD %d FREE %d" % (sum(x.numel() for x in held) >> 20, f >> 20), flush=True)
signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
while True:
    time.sleep(3600)
"""


def default_image(compose: Path = PROFILE_COMPOSE) -> str:
    if os.environ.get("VLLM_IMAGE"):
        return os.environ["VLLM_IMAGE"]
    m = re.search(r"\$\{VLLM_IMAGE:-([^}]+)\}", compose.read_text(encoding="utf-8"))
    if not m:
        raise Refused("profile-unreadable", f"{compose.name} names no default VLLM_IMAGE")
    return m.group(1)


class DockerAllocator:
    """One ``tb-ballast`` container from the profile's own vLLM image: no network, never pulled, removed on release."""

    def __init__(self, image: str, run: Run = run_cmd, start_timeout: float = 600.0) -> None:
        self.image = image
        self.run = run
        self.start_timeout = start_timeout
        self.proc: subprocess.Popen[str] | None = None

    def preflight(self) -> None:
        try:
            self.run(["docker", "image", "inspect", "--format", "{{.Id}}", self.image])
        except Refused as e:
            if e.code == "docker-missing":
                raise
            raise Refused("image-not-local", f"{self.image} is not on this machine (the ballast never pulls)") from e
        if self.run(["docker", "ps", "-aq", "--filter", f"name=^{CONTAINER}$"]).strip():
            raise Refused(
                "ballast-already-running", f"a {CONTAINER} container exists (`python3 -m tools.ballast release`)"
            )

    def start(self, target_free: int, index: int) -> tuple[int, int]:
        cmd = [
            "docker", "run", "--rm", "--name", CONTAINER, "--label", "trialbox.ballast=1", "--network", "none",
            "--pull", "never", "--gpus", f"device={index}", "--entrypoint", "python3", self.image,
            "-c", HOLDER, str(target_free),
        ]  # fmt: skip
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines: queue.Queue[str | None] = queue.Queue()

        def pump() -> None:
            assert self.proc is not None and self.proc.stdout is not None
            for line in self.proc.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        tail: list[str] = []
        end = time.monotonic() + self.start_timeout
        while True:
            try:
                line = lines.get(timeout=max(0.1, end - time.monotonic()))
            except queue.Empty:
                raise Refused("allocation-failed", f"the holder said nothing in {self.start_timeout:.0f} s") from None
            if line is None:
                raise Refused("allocation-failed", "the holder ended: " + " | ".join(tail[-3:]))
            m = re.match(r"HELD (\d+) FREE (\d+)", line)
            if m:
                return int(m.group(1)), int(m.group(2))
            tail.append(line.strip())

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def release(self) -> str:
        """Remove the container and end the ``docker run`` client, each within a deadline; never waits for ever."""
        left = ""
        try:
            self.run(["docker", "rm", "-f", CONTAINER])
        except Refused as e:
            if e.code != "docker-failed" or "did not answer" in e.text:  # "no such container" is a clean release
                left = f"the {CONTAINER} container may remain ({e.text}): `python3 -m tools.ballast release`"
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    left += f"{'; ' if left else ''}the docker client (pid {self.proc.pid}) did not end"
        return left


# ------------------------------------------------------------------------------------------------ hold


class _Stop(Exception):
    pass


def _on_signal(signum: int, _frame: object) -> None:
    raise _Stop(signal.Signals(signum).name)


def _print_plan(plan: Plan, say: Callable[[str], None]) -> None:
    c = plan.card
    say(f"card {c.index}: {c.name}, {c.total} MiB in all, {c.used} MiB used, {c.free} MiB free")
    say(f"target: {plan.target} MiB free (a 5090), +/- {TOLERANCE_MIB}; ballast to hold: about {plan.ballast} MiB")
    for k, v in plan.utils.items():
        say(f"export {k}={v}")
    say(f'records taken under it: --capped-to "{CAPPED_TO}" (never a tier record)')


def hold(
    *,
    index: int,
    allocator: Allocator,
    run: Run = run_cmd,
    env_file: Path | None = None,
    target: int = TARGET_MIB,
    tolerance: int = TOLERANCE_MIB,
    expect_used: int = EXPECT_USED_MIB,
    expect_procs: Sequence[str] = (),
    profile: dict[str, float] | None = None,
    wait: Callable[[Allocator], None] | None = None,
    say: Callable[[str], None] = print,
) -> int:
    """Check, hold, confirm, wait, release. Returns the exit code; a refusal before allocating raises ``Refused``."""
    refuse_production(env_file)
    card = read_card(index, run)
    plan = check(card, read_procs(card, run), target=target, tolerance=tolerance, expect_used=expect_used,
                 expect_procs=expect_procs, profile=profile)  # fmt: skip
    _print_plan(plan, say)
    allocator.preflight()
    old = {s: signal.signal(s, _on_signal) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    code, env_set = 0, False
    try:
        if env_file is not None:
            set_env(env_file, plan.utils)  # refuses a file that already holds a ballast's values: those stay
            env_set = True
            say(f"{env_file}: {', '.join(plan.utils)} set (put back on release)")
        held, seen = allocator.start(target, index)
        after = read_card(index, run)
        say(
            f"holding {held} MiB (the holder sees {seen} MiB free);"
            f" nvidia-smi: {after.used} MiB used, {after.free} MiB free left"
        )
        if abs(after.free - target) > tolerance:
            raise Refused("off-target", f"{after.free} MiB free, not {target} +/- {tolerance}: released")
        say("ready: start the servers now; Ctrl-C or SIGTERM releases the ballast")
        (wait or _wait_alive)(allocator)
        if not allocator.alive():
            say("ballast-lost: the holder ended while held; records taken after this are not 'by ballast'")
            code = 1
    except _Stop as e:
        say(f"{e}: releasing")
    except Refused as e:
        say(f"refused: {e.code}: {e.text}")
        code = 2
    finally:
        for s in old:
            signal.signal(s, signal.SIG_IGN)  # a second Ctrl-C does not cut the release short
        left = allocator.release()
        if left:
            say(f"left behind: {left}")
            code = code or 1
        if env_file is not None and env_set:
            restore_env(env_file)
        for s, h in old.items():
            signal.signal(s, h)
        say("released")
    return code


def _wait_alive(allocator: Allocator, poll: float = 2.0) -> None:
    while allocator.alive():
        time.sleep(poll)


# ------------------------------------------------------------------------------------------------ CLI


def main(argv: Sequence[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)  # "ready" must reach a pipe at once, not when the buffer fills
    ap = argparse.ArgumentParser(prog="python3 -m tools.ballast", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "hold", "release"):
        p = sub.add_parser(name)
        p.add_argument("--env-file", type=Path, default=None, help="deploy/.env: set (hold) or put back (release)")
        if name == "release":
            continue
        p.add_argument("--gpu", type=int, default=0, help="nvidia-smi index of the card (default 0)")
        p.add_argument("--target-mib", type=int, default=TARGET_MIB)
        p.add_argument("--expect-used", type=int, default=EXPECT_USED_MIB, help="MiB in use taken as the driver's own")
        p.add_argument("--expect-process", action="append", default=[], help="a compute process name to tolerate")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "release":
            try:
                run_cmd(["docker", "rm", "-f", CONTAINER])
                print(f"{CONTAINER} removed")
            except Refused as e:
                print(f"no {CONTAINER} removed ({e.code})")
            if a.env_file is not None:
                keys = restore_env(a.env_file)
                print(f"{a.env_file}: {', '.join(keys) or 'nothing'} put back")
            return 0
        refuse_production(a.env_file if a.env_file is not None else ROOT / "deploy" / ".env")
        if a.cmd == "plan":
            card = read_card(a.gpu)
            _print_plan(check(card, read_procs(card), target=a.target_mib, expect_used=a.expect_used,
                              expect_procs=a.expect_process), print)  # fmt: skip
            return 0
        return hold(index=a.gpu, allocator=DockerAllocator(default_image()), env_file=a.env_file, target=a.target_mib,
                    expect_used=a.expect_used, expect_procs=a.expect_process)  # fmt: skip
    except Refused as e:
        print(f"refused: {e.code}: {e.text}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
