"""H-66: the 48 GB run of 2026-11-19 (m48-20261119T232459Z-d28f6c0305fa) ended at s07: the ballast said "holding
47551 MiB ... 49140 MiB free left" and "ready", then ``ballast48 plan`` refused "49776 MiB free, not 49140 +/- 512".
Driver 580 reserves memory that nvidia-smi counts neither used nor free (total = used + free + reserved); the holder
read ``memory.free`` and ballast48 took total minus used, 636 MiB more. Both now read ``tools.ballast.read_card``.

No card here: the card is a stand-in modelled on the run's own logs (97,887 MiB in all, 636 reserved by the driver,
the holder's context 560: 97,887 - 47,551 = 50,336 = 49,140 free + 636 reserved + 560 context), and so are the
holder and the driver tool on PATH."""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tools import ballast as b
from tools import ballast48 as b48

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
PROFILE = {"JUDGE_GPU_MEM_UTIL": 0.81, "VERIFIER_GPU_MEM_UTIL": 0.81}
TOTAL, RESERVED, CONTEXT, TARGET = 97887, 636, 560, b48.TARGET_MIB
UUID = "GPU-pro6000"


class Gpu:
    """The card: nvidia-smi as ``tools.ballast``'s runner (``smi``) and as ballast48's (``runner``), and docker ps."""

    def __init__(self, reserved: int = RESERVED, base: int = 0, apps: str = "") -> None:
        self.reserved, self.base, self.apps = reserved, base, apps
        self.held = 0
        self.up = False

    @property
    def used(self) -> int:
        return self.base + (CONTEXT + self.held if self.up else 0)

    @property
    def free(self) -> int:
        return TOTAL - self.used - self.reserved

    def _field(self, f: str) -> str:
        return {"index": "0", "uuid": UUID, "name": "NVIDIA RTX PRO 6000 Blackwell Server Edition",
                "memory.total": str(TOTAL), "memory.used": str(self.used), "memory.free": str(self.free),
                "memory.reserved": str(self.reserved), "driver_version": "580.178.04",
                "display_active": "Disabled"}[f]  # fmt: skip

    def smi(self, cmd: Sequence[str]) -> str:
        assert cmd[0] == "nvidia-smi"
        if "--query-compute-apps" in cmd[1]:
            return self.apps
        fields = cmd[1].split("=", 1)[1].split(",")
        return ", ".join(self._field(f) for f in fields) + "\n"

    def runner(self, cmd: list[str], timeout: int, env: dict[str, str] | None = None,
               stream: bool = False) -> tuple[int, str, str]:  # fmt: skip
        if cmd[0] == "nvidia-smi":
            return 0, self.smi(cmd), ""
        if cmd[:2] == ["docker", "ps"]:
            return 0, ("abc123\n" if self.up else ""), ""
        return 0, "", ""


class Holder:
    """The holder in its container: a CUDA context, then torch's own free figure (``skew`` MiB off nvidia-smi's) less
    the target as its first estimate; ``adjust`` moves what it holds by ``share`` of what is asked (1: all of it)."""

    def __init__(self, gpu: Gpu, skew: int = 0, share: float = 1.0) -> None:
        self.gpu, self.skew, self.share = gpu, skew, share
        self.calls: list[str] = []

    def preflight(self) -> None:
        self.calls.append("preflight")

    def start(self, target_free: int, index: int) -> tuple[int, int]:
        self.calls.append(f"start {target_free}")
        self.gpu.up = True
        self.gpu.held = self.gpu.free + self.skew - target_free
        return self.gpu.held, self.gpu.free + self.skew

    def adjust(self, delta: int) -> tuple[int, int]:
        self.calls.append(f"adjust {delta:+d}")
        self.gpu.held += int(delta * self.share)
        return self.gpu.held, self.gpu.free + self.skew

    def alive(self) -> bool:
        return self.gpu.up

    def release(self) -> str:
        self.calls.append("release")
        self.gpu.up, self.gpu.held = False, 0
        return ""


def _s07(gpu: Gpu, seen: list[Any]) -> Any:
    """What the VM script does once the ballast says "ready": ``ballast48 plan``'s check, against the same card."""

    def wait(_a: object) -> None:
        try:
            seen.append(b48.check(gpu.runner, TARGET))
        except b48.Refused as e:
            seen.append(f"ballast48: refused: {e}")

    return wait


def _hold(gpu: Gpu, holder: Holder, out: list[str], **kw: Any) -> int:
    kw.setdefault("settle", lambda: None)
    return b.hold(index=0, allocator=holder, run=gpu.smi, target=TARGET, profile=PROFILE, say=out.append, **kw)


# ------------------------------------------------------------------------------------------------ the run of 11-19


def test_the_stand_in_reproduces_the_runs_figures() -> None:
    gpu = Gpu()
    Holder(gpu).start(TARGET, 0)
    assert gpu.held == 47551 and gpu.free == 49140  # ballast.log: "holding 47551 MiB ... 49140 MiB free left"
    assert TOTAL - gpu.held == 50336 == gpu.free + RESERVED + CONTEXT  # the 1,196 is the reserve and the context
    assert TOTAL - gpu.used == 49776  # what ballast48 took as free before H-66: s07-ballast.log's figure
    assert TOTAL - gpu.used - gpu.free == RESERVED == 49776 - 49140


def test_the_ballast_and_s07_read_the_same_free_on_a_card_with_reserved_memory() -> None:
    """The run of 11-19 on the stand-in: before H-66 the hold said ready at 49,140 free and s07 then refused 49,776."""
    gpu, out, seen = Gpu(), list[str](), list[Any]()
    holder = Holder(gpu)
    # no settle stub: the 2 s wait before the re-read runs as on the card
    rc = b.hold(index=0, allocator=holder, run=gpu.smi, target=TARGET, profile=PROFILE, say=out.append,
                wait=_s07(gpu, seen))  # fmt: skip
    text = "\n".join(out)
    assert "holding 47551 MiB" in text and "49140 MiB free left" in text and "ready" in text
    assert seen and isinstance(seen[0], dict), seen  # before H-66: "ballast48: refused: 49776 MiB free, not 49140"
    assert seen[0]["free_mib"] == 49140 and seen[0]["reserved_mib"] == RESERVED
    assert rc == 0 and holder.calls == ["preflight", "start 49140", "release"]


def test_the_view_counts_the_servers_from_the_target_not_from_total_minus_used() -> None:
    gpu, out, seen = Gpu(), list[str](), list[Any]()
    _hold(gpu, Holder(gpu), out, wait=_s07(gpu, seen))
    card = seen[0]
    gpu.up, gpu.held = True, 47551  # the ballast holding, as at s08
    view = b48.BallastView(gpu.runner, card["total_mib"], TARGET, card["reserved_mib"])
    _, o, _ = view(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], 60)
    assert o.strip() == "0"  # at the target: nothing used yet as a 48 GB card
    gpu.base = 30000  # the servers
    _, o, _ = view(["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free", "--format=csv,noheader"], 60)
    assert [int(x) for x in o.split(",")] == [TARGET, 30000, TARGET - 30000]  # total = used + free in the view


def test_without_reserved_memory_the_old_figures_hold() -> None:
    gpu, out, seen = Gpu(reserved=0), list[str](), list[Any]()
    holder = Holder(gpu)
    assert _hold(gpu, holder, out, wait=_s07(gpu, seen)) == 0
    assert gpu.held == 0 and holder.calls[-1] == "release"
    assert seen[0]["free_mib"] == TARGET and seen[0]["reserved_mib"] == 0
    assert "holding 48187 MiB" in "\n".join(out)  # 97,887 - 560 - 49,140: no reserve, the same 49,140 free


def test_another_process_on_the_card_is_counted_by_the_measured_free() -> None:
    apps = f"{UUID}, 4242, display-server, 3000\n"
    gpu, out, seen = Gpu(base=3000, apps=apps), list[str](), list[Any]()
    holder = Holder(gpu)
    with pytest.raises(b.Refused) as e:  # not told to expect it: refused before anything is allocated
        _hold(gpu, holder, out)
    assert e.value.code == "memory-already-held" and holder.calls == []
    rc = _hold(gpu, holder, out, expect_procs=("display-server",), expect_used=3500, wait=_s07(gpu, seen))
    assert rc == 0 and seen[0]["free_mib"] == TARGET  # the holder took 3,000 less; the card is still at the target


@pytest.mark.parametrize("skew", [700, -700, 2000])
def test_the_holder_is_corrected_up_or_down_by_the_measured_free(skew: int) -> None:
    """torch's free and nvidia-smi's differ (the first estimate is off by ``skew``): hold corrects from nvidia-smi."""
    gpu, out, seen = Gpu(), list[str](), list[Any]()
    holder = Holder(gpu, skew=skew)
    assert _hold(gpu, holder, out, wait=_s07(gpu, seen)) == 0
    assert f"adjust {-skew:+d}" in holder.calls and any(x.startswith("correction 1:") for x in out)
    assert seen[0]["free_mib"] == TARGET


def test_a_holder_that_moves_by_halves_converges_in_steps() -> None:
    gpu, out, seen = Gpu(), list[str](), list[Any]()
    holder = Holder(gpu, skew=2000, share=0.5)
    assert _hold(gpu, holder, out, wait=_s07(gpu, seen)) == 0
    steps = [c for c in holder.calls if c.startswith("adjust")]
    assert len(steps) == 5 and abs(seen[0]["free_mib"] - TARGET) <= b.AIM_MIB  # 2000, 1000, 500, 250, 125, 62


def test_a_holder_that_cannot_be_corrected_is_refused_with_the_numbers() -> None:
    gpu, out = Gpu(), list[str]()
    holder = Holder(gpu, skew=2000, share=0.0)
    rc = _hold(gpu, holder, out, wait=lambda _a: pytest.fail("ready off target"))
    assert rc == 2  # the VM script's "^refused" line and exit 2: s07 fails, the run ends and the VM stops
    refusal = [x for x in out if x.startswith("refused: ")]
    assert refusal == [
        f"refused: off-target: 47140 MiB free after {b.MAX_STEPS} correction(s), not 49140 +/- 512"
        " (holding 49551 MiB; 97887 MiB in all, 50111 used, 636 reserved): released"
    ]
    assert holder.calls[-1] == "release" and len([c for c in holder.calls if c.startswith("adjust")]) == b.MAX_STEPS


def test_memory_given_back_before_ready_is_refused() -> None:
    gpu, out = Gpu(), list[str]()
    holder = Holder(gpu)

    def give_back() -> None:
        gpu.held -= 2000

    rc = _hold(gpu, holder, out, settle=give_back, wait=lambda _a: pytest.fail("ready while unsteady"))
    assert rc == 2 and "ready" not in "\n".join(out)
    assert "refused: unsteady: 51140 MiB free on the re-read, 49140 before it; not 49140 +/- 512: released" in out


def test_memory_given_back_after_ready_is_still_refused_at_s07() -> None:
    gpu, out, seen = Gpu(), list[str](), list[Any]()
    check = _s07(gpu, seen)

    def wait(a: object) -> None:
        gpu.held -= 2000  # the holder lost memory after "ready"
        check(a)

    assert _hold(gpu, Holder(gpu), out, wait=wait) == 0
    assert seen == [
        "ballast48: refused: 51140 MiB free, not 49140 +/- 512 (nvidia-smi memory.free; 46111 used, 636 reserved by"
        " the driver): the ballast is not holding the card at the target (or something else holds memory)"
    ]


def test_the_tolerance_and_the_ballast_guards_are_unchanged() -> None:
    assert b.TOLERANCE_MIB == b48.TOLERANCE_MIB == 512
    gpu = Gpu()
    gpu.up, gpu.held = True, 47551 - 600  # 49,740 free: 600 off
    with pytest.raises(b48.Refused, match="49740 MiB free, not 49140"):
        b48.check(gpu.runner, TARGET)
    gpu.held = 47551
    gpu.up = False  # no tb-ballast container: refused whatever the figures
    with pytest.raises(b48.Refused, match="no tb-ballast"):
        b48.check(gpu.runner, TARGET)
    assert b48.capped_to().endswith("by ballast")


def test_during_takes_free_at_peak_from_the_same_reading(tmp_path: Path) -> None:
    gpu = Gpu()
    gpu.up, gpu.held = True, 47551

    def screen(cmd: list[str], check: bool) -> subprocess.CompletedProcess[bytes]:
        gpu.base = 44000
        return subprocess.CompletedProcess(cmd, 0)

    rec = b48.during(["python", "-m", "x"], tmp_path / "d.json", gpu.runner, every=0.01, popen=screen)
    assert rec["free_at_peak_mib"] == TARGET - 44000 and rec["peak_used_mib_as_48gb"] == 44000


# ------------------------------------------------------------------------------------------------ the CLI, fakes on PATH

FAKE_SMI = """#!{py}
import json, os, sys
s = json.load(open(os.environ["BALLAST_FAKE_STATE"]))
if any(a.startswith("--query-compute-apps") for a in sys.argv):
    sys.exit(0)
used = s["held"] + (560 if s.get("container") else 0)
print("0, GPU-pro6000, NVIDIA RTX PRO 6000, 97887, %d, %d" % (used, 97887 - used - s["reserved"]))
"""

# the holder's protocol as tools/ballast.py HOLDER speaks it: "HELD n FREE f", then "+N" / "-N" lines on stdin; its
# torch figure is 700 MiB above nvidia-smi's, so hold must correct it over the pipe
FAKE_DOCKER = """#!{py}
import json, os, signal, sys, time
p = os.environ["BALLAST_FAKE_STATE"]
s = json.load(open(p))
a = sys.argv[1:]
def save():
    json.dump(s, open(p, "w"))
def free():
    return 97887 - s["held"] - 560 - s["reserved"]
if a[:2] == ["image", "inspect"]:
    print("sha256:" + "0" * 64)
elif a[0] == "ps":
    print(s.get("container", ""))
elif a[0] == "run":
    assert "-i" in a and "--network" in a and a[a.index("--network") + 1] == "none"
    s["container"] = str(os.getpid())
    s["held"] = free() + 700 - int(a[-1])
    save()
    print("HELD %d FREE %d" % (s["held"], free() + 700), flush=True)
    signal.signal(signal.SIGTERM, lambda *x: sys.exit(0))
    for line in sys.stdin:
        s["held"] += int(line)
        s["steps"] = s.get("steps", 0) + 1
        save()
        print("HELD %d FREE %d" % (s["held"], free() + 700), flush=True)
    while True:
        time.sleep(1)
elif a[:2] == ["rm", "-f"]:
    if not s.get("container"):
        sys.exit(1)
    os.kill(int(s.pop("container")), signal.SIGTERM)
    s["held"] = 0
    save()
"""


def test_the_cli_corrects_over_the_pipe_and_ballast48_plan_agrees(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir(mode=0o755)
    for name, text in (("nvidia-smi", FAKE_SMI), ("docker", FAKE_DOCKER)):
        f = bindir / name
        f.write_text(text.replace("{py}", sys.executable))
        f.chmod(0o755)
    state = tmp_path / "gpu.json"
    state.write_text(json.dumps({"held": 0, "reserved": RESERVED}))
    env = {k: v for k, v in os.environ.items() if k not in ("TB_ENV", "VLLM_IMAGE", "PYTHONUNBUFFERED")}
    env.update(PATH=f"{bindir}{os.pathsep}{os.path.dirname(sys.executable)}", BALLAST_FAKE_STATE=str(state),
               PYTHONPATH=str(ROOT))  # fmt: skip
    p = subprocess.Popen([sys.executable, "-m", "tools.ballast", "hold", "--target-mib", str(TARGET)], cwd=ROOT,
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # fmt: skip
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        assert p.stdout is not None
        for line in p.stdout:
            lines.put(line.rstrip("\n"))
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()

    def until(stop: str, deadline: float) -> list[str]:
        got: list[str] = []
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                continue
            if line is None:
                break
            got.append(line)
            if line.startswith(stop):
                break
        return got

    try:
        got = until("ready", time.monotonic() + 60)
        assert got and got[-1].startswith("ready"), "\n".join(got)
        assert any(x.startswith("correction 1: -700 MiB") and "49140 MiB free left" in x for x in got), "\n".join(got)
        assert json.loads(state.read_text())["steps"] == 1
        plan = subprocess.run([sys.executable, "tools/ballast48.py", "plan"], cwd=ROOT, env=env, capture_output=True,
                              text=True, timeout=60, check=False)  # fmt: skip
        assert plan.returncode == 0, plan.stderr
        assert "49,140 MiB free" in plan.stdout and "636 MiB reserved by the driver" in plan.stdout
    finally:
        p.send_signal(signal.SIGTERM)
        rest = until("released", time.monotonic() + 60)
        p.wait(timeout=60)
    assert rest and rest[-1] == "released" and p.returncode == 0
    assert "container" not in json.loads(state.read_text())
