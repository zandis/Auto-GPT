"""The ballast stand-in (plan 10 card 10E-28; review 19's card 19-2 and its section 4.1): hold a larger NVIDIA card
down to the free memory of an RTX 5090, so the free runs O-1 to O-7 on the owner's card see what the 32 GB site box
would show, and set the two utilisations the 5090 profile needs on that larger card.

    python3 -m tools.ballast plan                               # checks and numbers only, allocates nothing
    python3 -m tools.ballast hold [--env-file deploy/.env]      # hold until Ctrl-C or SIGTERM, then release
    python3 -m tools.ballast release [--env-file deploy/.env]   # remove a ballast left by a killed `hold`

What it does. A 5090 reports 32,607 MiB (``deploy/docker-compose.rtx5090.yml``). ``hold`` starts one container from the
same vLLM image the profile serves with (``VLLM_IMAGE``, else the compose file's default), with no network and
``--pull never``; inside it, torch allocates until ``torch.cuda.mem_get_info()`` reports about the target free (a
first estimate), and the ballast's own CUDA context is counted.

Free has ONE meaning here (card H-66): ``nvidia-smi --query-gpu=memory.free`` as ``read_card`` reads it, the memory a
new process (a model server) is offered on the card. A driver that reserves memory (580 on the RTX PRO 6000: about
636 MiB in the 48 GB run's logs of 2026-11-19) counts it neither used nor free: total = used + free + reserved, so
total minus used is NOT free. ``tools/ballast48.py`` checks the card with this same function. After the first
estimate ``hold`` reads free, asks the holder for more or less (``Allocator.adjust``, steps of the measured
difference, at most 8) until it is within 64 MiB of the target, refuses ``off-target`` with the numbers when it is
still outside the tolerance (512 MiB), then waits 2 s, reads again (``unsteady`` when it moved out of the tolerance)
and only then says ``ready``. The holder never gives memory back by itself: the tensors stay referenced, and the
allocator's cache is emptied only when ``hold`` asks it to hold less. The script prints what it holds and what is
left.

vLLM's utilisation is a share of the card's total, so the profile's 0.81 of 32,607 MiB becomes 26,412 MiB / total
(0.537 on 49,140 MiB): ``hold`` prints both as ``export`` lines and, with ``--env-file``, writes them into that file
(each under a ``# tb-ballast:`` line naming the value it replaced) and puts the old values back on release. A record
taken under it says ``--capped-to "RTX 5090 (32 GB), by ballast"``,
which ``tools/serving_config.py measured_for`` refuses as a tier record, as it should.

It refuses, with a named reason and before allocating anything: ``production`` (TB_ENV is PRODUCTION; this is a
measurement aid for a VALIDATION or DEV box), ``driver-tool-missing`` / ``driver-tool-failed`` (no working
``nvidia-smi``), ``no-such-card``, ``card-too-small`` (the card's total is below the target), ``card-is-the-target``
(a real 32 GB card: run without a ballast), ``memory-already-held`` (a compute process it was not told to expect, or
more memory in use than ``--expect-used``), ``docker-missing``, ``image-not-local`` (it never pulls),
``ballast-already-running``. After allocating: ``allocation-failed``, ``off-target`` and ``unsteady`` (released at
once, the free figures named), and
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
CONTAINER_BASE = "tb-ballast"
# the holder's container: tb-ballast, or tb-ballast-<run id> when a run names it (TB_BALLAST_CONTAINER, the host form
# of the 48 GB run: every Docker object it makes carries its run id); anything else is not taken
_NAME = os.environ.get("TB_BALLAST_CONTAINER", "") or CONTAINER_BASE
CONTAINER = _NAME if re.fullmatch(r"tb-ballast(-[A-Za-z0-9_.-]{1,64})?", _NAME) else CONTAINER_BASE
UTIL_KEYS = ("JUDGE_GPU_MEM_UTIL", "VERIFIER_GPU_MEM_UTIL")
MARK = "# tb-ballast:"
AIM_MIB = 64  # hold corrects until nvidia-smi's free is this close to the target (the tolerance still decides)
MAX_STEPS = 8  # corrections after the first estimate; still outside the tolerance after them: off-target
SETTLE_S = 2.0  # the wait before the re-read that comes before "ready"
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
    """One card as nvidia-smi reports it. ``free`` is THE free figure (see the module): what a new process is
    offered. ``reserved`` is what the driver keeps back, counted neither used nor free (0 on a driver without it)."""

    index: int
    uuid: str
    name: str
    total: int
    used: int
    free: int

    @property
    def reserved(self) -> int:
        return max(0, self.total - self.used - self.free)


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


def read_card(index: int, run: Run = run_cmd, uuid: str | None = None) -> Card:
    """The one reading of the card for the ballast and for ``tools/ballast48.py``: ``memory.free`` is used as reported,
    never derived from total and used (a driver's reserved memory is in neither).

    One card only (H-67): nvidia-smi is asked about card ``index`` (``-i``), never about the others, and a line for
    another index is not taken. ``uuid``: the card's UUID as first read; a card at ``index`` with another UUID is
    refused (``card-changed``), so a later read can never be of a different card."""
    try:
        out = run(
            [
                "nvidia-smi",
                "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
                "-i",
                str(index),
            ]
        )
    except Refused as e:
        if e.code == "driver-tool-failed" and re.search(r"no devices|invalid|not found|not a valid", e.text, re.I):
            raise Refused("no-such-card", f"nvidia-smi has no card {index}: {e.text}") from None
        raise
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
            if uuid is not None and parts[1] != uuid:
                raise Refused(
                    "card-changed",
                    f"card {index} is not the card read first (its UUID changed between two reads): nothing more is"
                    " read or held on it",
                )
            return Card(idx, parts[1], ", ".join(parts[2:-3]), total, used, free)
    raise Refused("no-such-card", f"nvidia-smi lists cards {seen or 'none'}, not {index}")


def read_procs(card: Card, run: Run = run_cmd) -> list[Proc]:
    out = run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
            "-i",
            str(card.index),
        ]
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


def hold_mib(card: Card, target: int) -> int:
    """What the holder must take so that ``memory.free`` reads ``target``: the card's own free as read less the target,
    i.e. its total less what is used, less what the driver reserves, less the target. No card's total is assumed."""
    return card.total - card.used - card.reserved - target


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
    if card.total - card.reserved <= target:
        raise Refused(
            "card-too-small",
            f"{card.name} has {card.total} MiB in all and the driver reserves {card.reserved}: at most"
            f" {card.total - card.reserved} MiB can be free, not above the target {target} MiB",
        )
    strangers = [p for p in procs if not any(e and e in p.name for e in expect_procs)]
    if strangers:
        # a shared machine: how many and how much, never whose (no process name, no pid)
        mib = sum(p.used or 0 for p in strangers)
        unknown = sum(1 for p in strangers if p.used is None)
        raise Refused(
            "memory-already-held",
            f"{len(strangers)} compute process(es) already on card {card.index}, {mib} MiB"
            f"{f' (and {unknown} of unknown size)' if unknown else ''} (stop them, or --expect-process)",
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
    return Plan(card, target, hold_mib(card, target), {k: util_on(card.total, v, target) for k, v in prof.items()})


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
    def adjust(self, delta: int) -> tuple[int, int]: ...  # hold ``delta`` MiB more (less when negative); as start
    def alive(self) -> bool: ...
    def release(self) -> str: ...  # what is left behind, "" when nothing


# Runs inside the vLLM image: allocate until the device reports about the target free (the first estimate), print what
# it holds, then take corrections on stdin ("+N" / "-N" MiB), printing what it holds after each, until SIGTERM. The
# tensors stay in ``held`` for the life of the process (nothing frees them); the allocator's cache is emptied only on a
# "-N", so memory goes back to the driver only when hold asks for less.
HOLDER = """\
import signal, sys, time, torch
M = 1 << 20
t = int(sys.argv[1]) * M
held = []
def report():
    f, _ = torch.cuda.mem_get_info()
    print("HELD %d FREE %d" % (sum(x.numel() for x in held) // M, f // M), flush=True)
for _ in range(8):
    f, _ = torch.cuda.mem_get_info()
    if f - t < 64 * M:
        break
    held.append(torch.empty((f - t) // M * M, dtype=torch.uint8, device="cuda"))
report()
signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
for line in sys.stdin:
    try:
        n = int(line.strip() or "0") * M
        if n > 0:
            held.append(torch.empty(n, dtype=torch.uint8, device="cuda"))
        while n < 0 and held:
            x = held.pop()
            size = x.numel()
            del x
            torch.cuda.empty_cache()
            if size > -n:
                held.append(torch.empty(size + n, dtype=torch.uint8, device="cuda"))
            n += size
    except Exception as e:
        print("ERR %s" % str(e).splitlines()[0][:200] if str(e) else "ERR", flush=True)
    report()
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
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.uuid = ""  # the card's UUID (``pin``): the holder sees that card and no other

    def pin(self, uuid: str) -> None:
        """The card the holder runs on, by UUID (H-67): ``--gpus device=<uuid>`` and NVIDIA_VISIBLE_DEVICES in its
        environment, so it cannot land on another card of a machine with several."""
        if not re.fullmatch(r"(GPU|MIG)-[0-9A-Za-z-]+", uuid):
            raise Refused("no-such-card", "the card's UUID as read is not one the holder can be pinned to")
        self.uuid = uuid

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
        if not self.uuid:
            raise Refused("allocation-failed", f"card {index}'s UUID was not read: the holder is pinned by UUID only")
        cmd = [
            "docker", "run", "--rm", "--name", CONTAINER, "--label", "trialbox.ballast=1", "--network", "none",
            "--pull", "never", "--gpus", f"device={self.uuid}", "-e", f"NVIDIA_VISIBLE_DEVICES={self.uuid}",
            "-e", "CUDA_DEVICE_ORDER=PCI_BUS_ID", "-i", "--entrypoint", "python3", self.image,
            "-c", HOLDER, str(target_free),
        ]  # fmt: skip
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )

        def pump() -> None:
            assert self.proc is not None and self.proc.stdout is not None
            for line in self.proc.stdout:
                self.lines.put(line)
            self.lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        return self._report(self.start_timeout)

    def adjust(self, delta: int) -> tuple[int, int]:
        """Ask the holder for ``delta`` MiB more (less when negative) and return what it then holds and sees."""
        if self.proc is None or self.proc.stdin is None or self.proc.poll() is not None:
            raise Refused("allocation-failed", "the holder is not running")
        try:
            self.proc.stdin.write(f"{delta:+d}\n")
            self.proc.stdin.flush()
        except OSError as e:
            raise Refused("allocation-failed", f"the holder does not take corrections: {e}") from None
        return self._report(CMD_TIMEOUT_S)

    def _report(self, timeout: float) -> tuple[int, int]:
        tail: list[str] = []
        end = time.monotonic() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0.1, end - time.monotonic()))
            except queue.Empty:
                raise Refused("allocation-failed", f"the holder said nothing in {timeout:.0f} s") from None
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
    say(
        f"card {c.index}: {c.name}, {c.total} MiB in all, {c.used} MiB used, {c.free} MiB free, {c.reserved} MiB"
        " reserved by the driver (its UUID is checked at every read)"
    )
    say(
        f"target: {plan.target} MiB free, +/- {TOLERANCE_MIB}; ballast to hold: about {plan.ballast} MiB"
        f" ({c.total} - {c.used} used - {c.reserved} reserved - {plan.target})"
    )
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
    settle: Callable[[], None] | None = None,
    uuid: str | None = None,
) -> int:
    """Check, hold, correct, confirm, wait, release. Returns the exit code; a refusal before allocating raises
    ``Refused``. Every free figure is ``read_card``'s (nvidia-smi ``memory.free``), the one ``ballast48`` checks.

    One card (H-67): card ``index`` only, its UUID taken at the first read (or ``uuid``, as the run read it before)
    and checked at every later read; the holder is pinned to that UUID. Other cards are never read or touched."""
    refuse_production(env_file)
    card = read_card(index, run, uuid)
    uuid = card.uuid
    plan = check(card, read_procs(card, run), target=target, tolerance=tolerance, expect_used=expect_used,
                 expect_procs=expect_procs, profile=profile)  # fmt: skip
    _print_plan(plan, say)
    pin = getattr(allocator, "pin", None)
    if pin is not None:
        pin(uuid)
    allocator.preflight()
    old = {s: signal.signal(s, _on_signal) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    code, env_set = 0, False
    try:
        if env_file is not None:
            set_env(env_file, plan.utils)  # refuses a file that already holds a ballast's values: those stay
            env_set = True
            say(f"{env_file}: {', '.join(plan.utils)} set (put back on release)")
        held, seen = allocator.start(target, index)
        after = read_card(index, run, uuid)
        say(
            f"holding {held} MiB (the holder sees {seen} MiB free);"
            f" nvidia-smi: {after.used} MiB used, {after.free} MiB free left"
        )
        steps = 0
        while abs(after.free - target) > AIM_MIB and steps < MAX_STEPS:
            steps += 1
            off = after.free - target  # more free than the target: hold more
            held, seen = allocator.adjust(off)
            after = read_card(index, run, uuid)
            say(
                f"correction {steps}: {off:+d} MiB; holding {held} MiB (the holder sees {seen} MiB free);"
                f" nvidia-smi: {after.used} MiB used, {after.free} MiB free left"
            )
        if abs(after.free - target) > tolerance:
            raise Refused(
                "off-target",
                f"{after.free} MiB free after {steps} correction(s), not {target} +/- {tolerance}"
                f" (holding {held} MiB; {after.total} MiB in all, {after.used} used, {after.reserved} reserved):"
                " released",
            )
        (settle or (lambda: time.sleep(SETTLE_S)))()
        again = read_card(index, run, uuid)
        if abs(again.free - target) > tolerance:
            raise Refused(
                "unsteady",
                f"{again.free} MiB free on the re-read, {after.free} before it; not {target} +/- {tolerance}: released",
            )
        say(
            f"steady: nvidia-smi {again.free} MiB free on the re-read ({again.reserved} MiB reserved by the driver,"
            " neither used nor free; free is what a server starting now is offered)"
        )
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
        p.add_argument(
            "--gpu",
            "--gpu-index",
            dest="gpu",
            type=int,
            default=0,
            help="nvidia-smi index of the card (default 0); no other card is read or touched",
        )
        p.add_argument("--gpu-uuid", default=None, help="the card's UUID as read before: refused if it differs")
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
            card = read_card(a.gpu, run_cmd, a.gpu_uuid)
            _print_plan(check(card, read_procs(card), target=a.target_mib, expect_used=a.expect_used,
                              expect_procs=a.expect_process), print)  # fmt: skip
            return 0
        return hold(index=a.gpu, allocator=DockerAllocator(default_image()), env_file=a.env_file, target=a.target_mib,
                    expect_used=a.expect_used, expect_procs=a.expect_process, uuid=a.gpu_uuid)  # fmt: skip
    except Refused as e:
        print(f"refused: {e.code}: {e.text}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
