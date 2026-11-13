"""The scale gate's parts (T-687, D-471): the compose memory caps, a process run under one, the slow model stand-in,
and the ledger of today's known failures.

None of this imports a service: the gate's driver (``tools/scale_gate.py``) puts the product's own code in each
process. These parts are tested on every pull request (``tests/unit/test_scale_gate_logic.py``); the 50,000-patient
run is the nightly job's (``trialbox-e2e.yml`` job ``scale-50k``).

**The caps** come from ``deploy/docker-compose.yml`` (:func:`compose_caps`), never from a copied number: the
``mem_limit`` of each service, ``${TB_MEM_X:-6g}`` read as compose reads it (the environment, else the default).

**Enforcement** (:class:`Enforcer`). ``cgroup``: ``systemd-run --scope -p MemoryMax=<cap> -p MemorySwapMax=0`` puts
the process tree in a cgroup whose ``memory.max`` is the cap, which is what Docker's ``mem_limit`` is: the kernel
kills the tree when it would go over. ``measure``: where no cgroup can be made (a developer container, the
pull-request runner), the tree's resident memory is sampled and the tree is killed when the sum goes over the cap.
``ulimit -v`` / ``setrlimit(RLIMIT_AS)`` are not used: they limit virtual address space, which DuckDB, Arrow and the
JVM reserve far beyond what they touch, so they fail on reservations, not on use. The nightly job asks for
``cgroup`` (``TB_SCALE_ENFORCE=cgroup``) and the gate refuses to run without it.

**The stand-in** (:class:`SlowModel`) is ``services/llm_stub`` in its own process over real HTTP, with its
``TB_STUB_LATENCY_S`` / ``TB_STUB_OUTAGE_*`` settings, and a restart (the process killed and started again).

**The ledger** (:func:`verdict`): a check listed in ``expected`` with its finding ids and card is a strict expected
failure from its size up: it must fail, and a pass fails the gate until the line is removed (D-460's ``EXPECTED``).
"""

from __future__ import annotations

import contextlib
import csv
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import IO, Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "docker-compose.yml"
_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?)i?b?\s*$", re.IGNORECASE)
_VAR = re.compile(r"^\$\{(\w+)(?::?-([^}]*))?\}$")
STOP_GRACE_S = 30.0  # as `docker compose stop`'s default grace before SIGKILL (10 s) and then some
STALL_POLL_S = 0.5  # how often a wait for a process looks whether the gate still makes progress (D-674)
_CHAT = re.compile(r"\"path\": \"/v1/chat/completions\", \"status\": (\d+)")
_UNIT = {"": 1, "k": 2**10, "m": 2**20, "g": 2**30, "t": 2**40}


# ------------------------------------------------------------------------------------------------ the caps
def parse_size(text: str) -> int:
    """Compose's byte value (``6g``, ``256m``, ``1.5g``, ``512``) in bytes."""
    m = _SIZE.match(str(text))
    if not m:
        raise ValueError(f"not a memory size: {text!r}")
    return int(float(m.group(1)) * _UNIT[m.group(2).lower()])


def compose_caps(path: Path = COMPOSE, environ: Mapping[str, str] | None = None) -> dict[str, int]:
    """Every service's ``mem_limit`` in bytes, with ``${VAR:-default}`` resolved from ``environ`` (the process's
    environment by default) as compose resolves it."""
    env = os.environ if environ is None else environ
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, int] = {}
    for name, svc in (doc.get("services") or {}).items():
        raw = (svc or {}).get("mem_limit")
        if raw is None:
            continue
        raw = str(raw).strip()
        m = _VAR.match(raw)
        if m:
            raw = env.get(m.group(1)) or (m.group(2) or "")
            if not raw:
                raise ValueError(f"{path.name}: {name}'s mem_limit has no value and no default")
        out[str(name)] = parse_size(raw)
    return out


def compose_setting(service: str, key: str, path: Path = COMPOSE) -> str | None:
    """A literal value of ``service``'s ``environment`` in the compose file (``TB_VALIDATOR_XMX`` of the adapter: the
    validator's heap inside the adapter's cap), or None."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    env = ((doc.get("services") or {}).get(service) or {}).get("environment") or {}
    if isinstance(env, list):
        env = dict(x.split("=", 1) for x in env if "=" in x)
    v = env.get(key)
    return None if v is None or "${" in str(v) else str(v)


def gib(n: int | float) -> str:
    return f"{n / 2**30:.2f} GiB"


# ------------------------------------------------------------------------------------------------ enforcement
def _children() -> dict[int, list[int]]:
    kids: dict[int, list[int]] = {}
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            stat = (d / "stat").read_text()
        except OSError:
            continue
        ppid = int(stat[stat.rindex(")") + 2 :].split()[1])
        kids.setdefault(ppid, []).append(int(d.name))
    return kids


def tree(pid: int) -> list[int]:
    """``pid`` and every process below it."""
    kids, out, todo = _children(), [], [pid]
    while todo:
        p = todo.pop()
        out.append(p)
        todo.extend(kids.get(p, []))
    return out


def rss(pids: Sequence[int]) -> int:
    """The summed resident memory of ``pids`` in bytes (what a cgroup charges, page cache aside)."""
    total = 0
    for p in pids:
        try:
            for line in Path(f"/proc/{p}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1]) * 1024
                    break
        except OSError:
            continue
    return total


def cpu_ticks(pids: Sequence[int]) -> int:
    """The processor time ``pids`` have used so far, in the kernel's clock ticks (user and system, summed)."""
    total = 0
    for p in pids:
        try:
            stat = Path(f"/proc/{p}/stat").read_text()
            fields = stat[stat.rindex(")") + 2 :].split()
            total += int(fields[11]) + int(fields[12])  # utime, stime
        except (OSError, ValueError, IndexError):
            continue
    return total


class Stalled(RuntimeError):
    """A part of the gate made no progress for the stall limit (D-674): the gate ends here, with its report."""


#: the samplers of the gate's live processes: progress anywhere among them is progress of the gate (a part that
#: waits for the lake service is not stalled while the lake works)
_LIVE: set[TreeSampler] = set()


def quiet() -> tuple[float, str]:
    """How long none of the gate's live processes has used processor time or written to its log, and what each
    was last seen at. ``(0, "")`` when there is none."""
    live = [t for t in list(_LIVE) if t.is_alive()]
    if not live:
        return 0.0, ""
    return min(t.quiet_s() for t in live), "; ".join(t.seen() for t in live)


def stall_check(part: str, stall_s: float, watched: str = "") -> None:
    """Raise :class:`Stalled` when the gate's processes have been quiet for ``stall_s`` (0: never). ``watched``:
    what the waiting loop last saw of the thing it waits for."""
    if stall_s <= 0:
        return
    for_s, seen = quiet()
    if for_s > stall_s:
        raise Stalled(
            f"{part}: no progress for {for_s:.0f} s (TB_SCALE_STALL_S={stall_s:g}): no processor time used and no "
            f"log written by the gate's processes ({seen})" + (f"; last seen: {watched}" if watched else "")
        )


class TreeSampler(threading.Thread):
    """Samples the resident memory of a process tree; in ``measure`` mode it kills the tree at the cap, as the
    kernel kills a container at its ``mem_limit``. D-674: it also notes when the tree last used processor time or
    its log last grew, which is the gate's sign of progress."""

    def __init__(
        self,
        pid: int,
        cap: int | None,
        kill_at_cap: bool,
        every_s: float = 0.2,
        name: str = "",
        log: Path | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.pid, self.cap, self.kill_at_cap, self.every_s = pid, cap, kill_at_cap, every_s
        self.name_, self.log = name, log
        self.peak = 0
        self.killed = False
        self._halt = threading.Event()
        self._ticks, self._bytes = -1, -1
        self._changed = time.monotonic()
        self.quiet_max_s = 0.0

    def quiet_s(self) -> float:
        return time.monotonic() - self._changed

    def seen(self) -> str:
        return f"{self.name_ or self.pid}: processor time {self._ticks} ticks, log {max(self._bytes, 0)} bytes"

    def _progress(self, pids: Sequence[int]) -> None:
        ticks = cpu_ticks(pids)
        try:
            size = self.log.stat().st_size if self.log is not None else 0
        except OSError:
            size = 0
        if (ticks, size) != (self._ticks, self._bytes):
            self._ticks, self._bytes = ticks, size
            self._changed = time.monotonic()
        else:
            self.quiet_max_s = max(self.quiet_max_s, self.quiet_s())

    def run(self) -> None:
        _LIVE.add(self)
        try:
            self._sample()
        finally:
            _LIVE.discard(self)

    def _sample(self) -> None:
        while not self._halt.is_set():
            pids = tree(self.pid)
            now = rss(pids)
            self.peak = max(self.peak, now)
            self._progress(pids)
            if self.kill_at_cap and self.cap is not None and now > self.cap:
                self.killed = True
                for p in reversed(pids):
                    with contextlib.suppress(OSError):
                        os.kill(p, signal.SIGKILL)
                return
            self._halt.wait(self.every_s)

    def stop(self) -> None:
        self._halt.set()
        self.join(timeout=5)


@dataclass
class PhaseRun:
    """One process of the gate: what it was capped at and what it did."""

    name: str
    service: str
    cap: int
    mode: str
    rc: int | None = None
    seconds: float = 0.0
    peak: int = 0
    oom: bool = False
    tail: str = ""
    quiet_max_s: float = 0.0  # D-674: the longest time it used no processor time and wrote no log

    @property
    def ok(self) -> bool:
        return self.rc == 0 and not self.oom and self.peak <= self.cap

    def summary(self) -> str:
        why = "killed at the cap" if self.oom else f"exit {self.rc}" if self.rc else "ok"
        return (
            f"{self.name} ({self.service} cap {gib(self.cap)}, {self.mode}): {why}, peak {gib(self.peak)}, "
            f"{self.seconds:.0f} s"
        )


def _cgroup_prefix(cap: int) -> list[str]:
    base = ["systemd-run", "--scope", "--quiet", "--collect", "-p", f"MemoryMax={cap}", "-p", "MemorySwapMax=0"]
    if os.geteuid() == 0:
        return base
    # the runner user: a system scope needs root, the command keeps the runner's user, group and environment
    return ["sudo", "-n", "-E", *base, f"--uid={os.getuid()}", f"--gid={os.getgid()}"]


def cgroup_available() -> bool:
    """Can this host put a process in a cgroup with a memory cap (systemd as init, cgroup v2, root or sudo)?"""
    if not shutil.which("systemd-run") or not Path("/sys/fs/cgroup/cgroup.controllers").exists():
        return False
    try:
        r = subprocess.run([*_cgroup_prefix(64 * 2**20), "true"], capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


@dataclass
class Enforcer:
    """Runs a command under a memory cap: ``cgroup`` (systemd-run, the kernel enforces) or ``measure``."""

    mode: str
    #: D-674: a process that is run to its end is ended, and the gate with it, when nothing the gate started has
    #: made progress for this long (0: never; the gate sets it from ``TB_SCALE_STALL_S``)
    stall_s: float = 0.0

    @classmethod
    def detect(cls, require: str = "") -> Enforcer:
        """``require`` ``cgroup`` (the nightly job): refuse without one; ``measure``: never try one; empty: the best
        this host has."""
        if require not in ("", "cgroup", "measure"):
            raise ValueError(f"TB_SCALE_ENFORCE must be cgroup or measure, not {require!r}")
        if require == "measure":
            return cls("measure")
        if cgroup_available():
            return cls("cgroup")
        if require == "cgroup":
            raise RuntimeError(
                "TB_SCALE_ENFORCE=cgroup but this host cannot make a memory cgroup (systemd-run --scope with "
                "MemoryMax needs systemd as init, cgroup v2 and root or password-less sudo)"
            )
        return cls("measure")

    def argv(self, argv: Sequence[str], cap: int) -> list[str]:
        return [*_cgroup_prefix(cap), "--", *argv] if self.mode == "cgroup" else list(argv)

    @contextlib.contextmanager
    def start(
        self, name: str, service: str, cap: int, argv: Sequence[str], env: Mapping[str, str], cwd: Path, log: Path
    ) -> Iterator[tuple[subprocess.Popen[bytes], PhaseRun]]:
        """A background process under the cap (a service); stopped at the end of the block, its run filled in."""
        run = PhaseRun(name, service, cap, self.mode)
        log.parent.mkdir(parents=True, exist_ok=True)
        fh: IO[bytes] = log.open("wb")
        t0 = time.monotonic()
        proc = subprocess.Popen(
            self.argv(argv, cap), cwd=cwd, env=dict(env), stdout=fh, stderr=subprocess.STDOUT, start_new_session=True
        )
        sampler = TreeSampler(proc.pid, cap, kill_at_cap=self.mode == "measure", name=name, log=log)
        sampler.start()
        try:
            yield proc, run
        finally:
            if proc.poll() is None:
                with contextlib.suppress(OSError):
                    os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=STOP_GRACE_S)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(OSError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                stopped = True
            else:
                stopped = False
            sampler.stop()
            fh.close()
            run.seconds = time.monotonic() - t0
            run.peak = sampler.peak
            run.quiet_max_s = sampler.quiet_max_s
            rc = proc.returncode
            run.oom = sampler.killed or (not stopped and rc in (-signal.SIGKILL, 128 + signal.SIGKILL))
            run.rc = 0 if stopped else rc  # stopped by the gate: it lived to the end
            run.tail = _tail(log)

    def run(
        self, name: str, service: str, cap: int, argv: Sequence[str], env: Mapping[str, str], cwd: Path, log: Path
    ) -> PhaseRun:
        """A process under the cap, to its end."""
        with self.start(name, service, cap, argv, env, cwd, log) as (proc, run):
            while True:
                try:
                    proc.wait(timeout=STALL_POLL_S if self.stall_s > 0 else None)
                    break
                except subprocess.TimeoutExpired:
                    stall_check(name, self.stall_s)  # raises: the block's end stops the process and fills the run
            rc = proc.returncode
        run.rc = rc
        run.oom = run.oom or rc in (-signal.SIGKILL, 128 + signal.SIGKILL)
        return run


def _tail(log: Path, n: int = 3000) -> str:
    try:
        return log.read_bytes()[-n:].decode("utf-8", "replace")
    except OSError:
        return ""


# ------------------------------------------------------------------------------------------------ the stand-in
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_http(url: str, seconds: float, alive: Callable[[], bool] = lambda: True) -> bool:
    import httpx

    end = time.monotonic() + seconds
    while time.monotonic() < end and alive():
        with contextlib.suppress(httpx.HTTPError):
            if httpx.get(url, timeout=2).status_code < 500:
                return True
        time.sleep(0.2)
    return False


_WATCH_S = 0.5  # the restart watcher's longest pause between two looks at the stand-in's call count


@dataclass
class SlowModel:
    """``services/llm_stub`` as a slow, failing model server in its own process: ``latency_s`` per call, an outage of
    ``outage_s`` seconds of 502 from call ``outage_after``, and :meth:`restart`. Its access log counts the calls."""

    workdir: Path
    latency_s: float = 0.0
    outage_after: int = 0
    outage_s: float = 0.0
    restart_gap_s: float = 0.0
    outage_status: int = (
        502  # 502: what a restarting server behind a proxy answers; another to play a fault callers lose
    )
    port: int = field(default_factory=free_port)
    proc: subprocess.Popen[bytes] | None = None
    restarts: int = 0
    _logs: list[Path] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def env(self) -> dict[str, str]:
        e = {**os.environ, "PYTHONPATH": "libs:services:.", "TB_ENV": os.environ.get("TB_ENV", "DEV")}
        e["TB_STUB_LATENCY_S"] = str(self.latency_s) if self.latency_s else ""
        e["TB_STUB_OUTAGE_AFTER"] = str(self.outage_after) if self.outage_s else ""
        e["TB_STUB_OUTAGE_S"] = str(self.outage_s) if self.outage_s else ""
        e["TB_STUB_OUTAGE_STATUS"] = str(self.outage_status)
        return e

    def start(self, outage: bool = True) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)
        log = self.workdir / f"llm-stub-{len(self._logs)}.log"
        self._logs.append(log)
        env = self.env()
        if not outage:  # after a restart the outage is over: a new process would count from 0 again
            env["TB_STUB_OUTAGE_S"] = ""
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "llm_stub.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "info",
            ],
            cwd=ROOT,
            env=env,
            stdout=log.open("wb"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        proc = self.proc
        if not wait_http(f"{self.url}/models", 60, lambda: proc.poll() is None):
            raise RuntimeError(f"the model stand-in did not start: {_tail(log)}")

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            with contextlib.suppress(OSError):
                os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()

    def restart(self) -> None:
        """Kill the server and start it again (connections refused in between, its state gone)."""
        self.stop()
        if self.restart_gap_s:
            time.sleep(self.restart_gap_s)
        self.start(outage=False)
        self.restarts += 1

    def _requests(self) -> list[int]:
        """The status of every chat call in the stand-in's request log (the service's JSON lines), all processes."""
        out: list[int] = []
        for log in self._logs:
            with contextlib.suppress(OSError):
                for m in _CHAT.finditer(log.read_text(errors="replace")):
                    out.append(int(m.group(1)))
        return out

    def calls(self) -> int:
        """Chat calls the stand-in answered or refused, over all its processes."""
        return len(self._requests())

    def refused(self) -> int:
        """Chat calls it answered with the outage's status."""
        return sum(1 for s in self._requests() if s == self.outage_status)

    def restart_after(self, calls: int, done: threading.Event) -> threading.Thread:
        """A thread that restarts the stand-in once it has seen ``calls`` calls (unless ``done`` is set first)."""

        # how often it looks: twice per call of the stand-in, so the call that reaches ``calls`` is seen while the
        # next one is still being answered (each takes ``latency_s``). It looked every half second, whatever the
        # latency: a screen whose last calls took less than that ended between two looks and was never restarted
        # (train 5's CI: "0 restart(s) in 7 calls"). Without a latency there is nothing to derive it from
        look = min(_WATCH_S, self.latency_s / 2) if self.latency_s > 0 else _WATCH_S

        def watch() -> None:
            while not done.is_set():
                if self.calls() >= calls:
                    self.restart()
                    return
                done.wait(look)

        t = threading.Thread(target=watch, daemon=True)
        t.start()
        return t


# ------------------------------------------------------------------------------------------------ the ledger
PASS, KNOWN, FAIL, FIXED, BLOCKED = "pass", "known-open", "FAIL", "FIXED: remove its EXPECTED line", "blocked"


@dataclass(frozen=True)
class Expected:
    """A check that fails today: its finding ids, the card that fixes it, and the size from which it fails."""

    findings: tuple[str, ...]
    card: str
    from_patients: int = 0
    why: str = ""

    def applies(self, patients: int) -> bool:
        return patients >= self.from_patients

    def label(self) -> str:
        return f"{', '.join(self.findings)} ({self.card})"


@dataclass
class Check:
    """One check of the gate. ``passed`` None: not run, because ``blocked_by`` (a failed phase) left no input."""

    id: str
    passed: bool | None
    detail: str
    blocked_by: str = ""


def verdict(checks: Sequence[Check], expected: Mapping[str, Expected], patients: int) -> list[dict[str, Any]]:
    """Each check's state: pass; known-open (expected, failed); FIXED (expected, passed: the gate fails until the
    line is removed); FAIL (not expected); blocked (not run, with the phase that blocked it)."""
    rows: list[dict[str, Any]] = []
    for c in checks:
        exp = expected.get(c.id)
        exp = exp if exp is not None and exp.applies(patients) else None
        if c.passed is None:
            state = BLOCKED
        elif exp is None:
            state = PASS if c.passed else FAIL
        else:
            state = FIXED if c.passed else KNOWN
        rows.append(
            {
                "check": c.id,
                "state": state,
                "detail": c.detail,
                "blocked_by": c.blocked_by,
                "expected": exp.label() if exp else "",
            }
        )
    return rows


def gate_ok(rows: Sequence[Mapping[str, Any]]) -> bool:
    return all(r["state"] in (PASS, KNOWN, BLOCKED) for r in rows)


def markdown(rows: Sequence[Mapping[str, Any]], head: Sequence[str], runs: Sequence[PhaseRun]) -> str:
    out = ["# Scale gate (T-687)", "", *head, "", "| Check | State | Known as | Detail |", "| --- | --- | --- | --- |"]
    for r in rows:
        detail = str(r["detail"]).replace("|", "/").replace("\n", " ")[:300]
        if r["blocked_by"]:
            detail = f"blocked by {r['blocked_by']}: {detail}"
        out.append(f"| `{r['check']}` | {r['state']} | {r['expected']} | {detail} |")
    out += ["", "| Process | Service cap | Mode | Result | Peak | Seconds |", "| --- | --- | --- | --- | --- | --- |"]
    for p in runs:
        res = "killed at the cap" if p.oom else ("ok" if p.rc == 0 else f"exit {p.rc}")
        if p.rc is None and not p.oom:  # D-674: a report written while the process runs
            out.append(f"| {p.name} | {f'{p.service} {gib(p.cap)}' if p.cap else 'none'} | {p.mode} | still running "
                       "| not yet | not yet |")  # fmt: skip
            continue
        cap = f"{p.service} {gib(p.cap)}" if p.cap else "none"
        out.append(f"| {p.name} | {cap} | {p.mode} | {res} | {gib(p.peak)} | {p.seconds:.0f} |")
    out += [
        "",
        f"Gate: {'green' if gate_ok(rows) else 'RED'} (known-open findings keep it green; a FIXED or FAIL "
        "row turns it red).",
    ]
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------------------------- the dense profile
#: The dense profile (plan v7, wave 1, T-687; PERF-002): what one patient's chart holds. Not limits of the product:
#: the definition of the test hospital the night is measured on, from the plan's own words ("about 500 records and
#: 40 notes per patient").
DENSE_RECORDS = 500
DENSE_NOTES = 40
#: The feed's tables that are the chart's structured records; ``note`` is counted apart. The others (people, staff,
#: consent, bookings, claims) are not thickened: a patient is still one person with one consent.
RECORD_TABLES = ("encounter", "diagnosis", "lab", "medication", "vital", "procedure", "report")
_STEP_DAYS = 7  # a copy is whole weeks earlier: a clinic day stays a clinic day, an order of events stays an order
_KEEP_DATES = ("birth_date", "death_date")


def _count_rows(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return max(0, sum(1 for _ in csv.reader(fh)) - 1)


def _earlier(value: str, days: int) -> tuple[str, date] | None:
    """``value`` (``YYYY-MM-DD`` with or without a time) ``days`` earlier, in its own form, and its day; None when
    it is not a date."""
    head, sep, rest = value.partition(" ")
    try:
        day = date.fromisoformat(head) - timedelta(days=days)
    except ValueError:
        return None
    return f"{day.isoformat()}{sep}{rest}", day


def densify(src: Path, out: Path, records: int = DENSE_RECORDS, notes: int = DENSE_NOTES) -> dict[str, Any]:
    """Thicken the generated feed in ``src`` (the CSV tables ``tools.make_fixtures.write_site`` writes) into ``out``
    until it has ``records`` structured records and ``notes`` notes per patient.

    Every row of a chart table is written once as it is and then again as copies: copy ``c`` has the row's key with
    ``c`` appended (three digits), every date of the row ``c`` weeks earlier, and the same patient; a row that
    names its encounter names a copy of that encounter. A copy that would fall before the patient's birth is left
    out, and so is a row whose encounter copy was. How many copies comes from the feed itself: the smallest number
    that meets the target, counted, not estimated, so the profile holds for any generator and any size. In
    streams, row by row: 50,000 dense patients are tens of millions of rows and are never held in memory. The same
    input gives the same bytes.

    Returns the facts of the result (patients, copies, records and notes per patient)."""
    out.mkdir(parents=True, exist_ok=True)
    with (src / "patient.csv").open(encoding="utf-8-sig", newline="") as fh:
        born = {r["mrn"]: date.fromisoformat(r["birth_date"]) for r in csv.DictReader(fh) if r.get("birth_date")}
    patients = max(1, len(born))
    for needed in ("encounter", "note"):
        if not (src / f"{needed}.csv").is_file() or not _count_rows(src / f"{needed}.csv"):
            raise ValueError(f"the feed has no {needed} rows to thicken")

    def count(tables: Sequence[str], k: int, k_enc: int) -> int:
        gone: set[str] = set()
        return sum(_thicken(src, None, t, k, born, k_enc, gone) for t in tables)

    thin_records = count(RECORD_TABLES, 1, 1)
    k_rec = max(1, -(-records * patients // thin_records))
    while count(RECORD_TABLES, k_rec, k_rec) < records * patients:
        k_rec += 1
    k_note = max(1, -(-notes * patients // _count_rows(src / "note.csv")))
    while count(("encounter", "note"), k_note, k_rec) - count(("encounter",), k_note, k_rec) < notes * patients:
        k_note += 1
    written: dict[str, int] = {}
    gone: set[str] = set()  # encounter copies left out (before the patient's birth): no row names one
    for table in RECORD_TABLES:  # the encounter first: the others name its copies
        written[table] = _thicken(src, out, table, k_rec, born, k_rec, gone)
    written["note"] = _thicken(src, out, "note", k_note, born, k_rec, gone)
    for path in sorted(src.glob("*.csv")):
        if path.stem not in written:
            shutil.copyfile(path, out / path.name)
    total = sum(written[t] for t in RECORD_TABLES)
    return {
        "patients": patients,
        "record_copies": k_rec,
        "note_copies": k_note,
        "records": total,
        "notes": written["note"],
        "records_per_patient": round(total / patients, 1),
        "notes_per_patient": round(written["note"] / patients, 1),
    }


def _thicken(
    src: Path, out: Path | None, table: str, k: int, born: Mapping[str, date], k_enc: int, gone: set[str]
) -> int:
    """Write ``table`` with ``k`` copies per row, the original included (count only when ``out`` is None).
    ``k_enc``: how many copies an encounter has; ``gone``: the encounter copies left out, filled while the
    encounter table is written and read by the tables after it. Returns the rows written."""
    path = src / f"{table}.csv"
    if not path.is_file():
        return 0
    n = 0
    with contextlib.ExitStack() as stack:
        reader = csv.DictReader(stack.enter_context(path.open(encoding="utf-8-sig", newline="")))
        fields = list(reader.fieldnames or [])
        if not fields:  # a table the generator wrote without a single row has no header either
            if out is not None:
                shutil.copyfile(path, out / path.name)
            return 0
        writer = None
        if out is not None:
            writer = csv.DictWriter(
                stack.enter_context((out / path.name).open("w", encoding="utf-8", newline="")), fieldnames=fields
            )
            writer.writeheader()
        key = fields[0]
        dates = [f for f in fields if f not in _KEEP_DATES and (f.endswith("_date") or f.endswith("_datetime"))]
        for row in reader:
            n += 1
            if writer is not None:
                writer.writerow(row)
            birth = born.get(row.get("mrn", ""))
            for c in range(1, k):
                copy = dict(row)
                copy[key] = f"{row[key]}{c:03d}"
                if key != "enc_no" and copy.get("enc_no") and c % k_enc:
                    copy["enc_no"] = f"{copy['enc_no']}{c % k_enc:03d}"
                alive = copy.get("enc_no") not in gone or key == "enc_no"
                for col in dates:
                    got = _earlier(row[col], _STEP_DAYS * c) if row[col] else None
                    if got is None:
                        continue
                    copy[col] = got[0]
                    alive = alive and (birth is None or got[1] >= birth)
                if not alive:
                    if key == "enc_no":
                        gone.add(copy[key])
                    continue
                n += 1
                if writer is not None:
                    writer.writerow(copy)
    return n
