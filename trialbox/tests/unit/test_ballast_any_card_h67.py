"""H-67: the ballast and ballast48 on any card of any size, one card chosen by index on a machine of several. No card
here: a stand-in machine of eight cards answers nvidia-smi (``-i`` honoured, every question written down), the
holder is a stand-in (a CUDA context, then what it is asked to hold), and Docker's answers for the servers' pin are
stand-ins. The target's meaning is unchanged: ``memory.free`` on the chosen card at 49,140 MiB (the class's
``memory_total_mib``) within 512 MiB; what the ballast holds comes from the card's own total, use and reserve."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tools import ballast as b
from tools import ballast48 as b48
from tools import dgpu48

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
PROFILE = {"JUDGE_GPU_MEM_UTIL": 0.81, "VERIFIER_GPU_MEM_UTIL": 0.81}
TARGET = b48.TARGET_MIB
CONTEXT = 560  # the holder's own CUDA context (the 11-19 run's figure)
UUIDS = [f"GPU-{i}{i}{i}{i}bbbb-0000-0000-0000-00000000000{i}" for i in range(8)]


class Machine:
    """Eight cards; ``chosen`` is the one the run uses. Every nvidia-smi question is kept in ``asked``."""

    def __init__(self, total: int, reserved: int, chosen: int = 3, apps: list[tuple[int, int]] | None = None) -> None:
        self.cards: list[dict[str, Any]] = [
            {"index": i, "uuid": UUIDS[i], "total": total, "used": 0, "reserved": reserved} for i in range(8)
        ]
        self.chosen = chosen
        self.apps = apps or []  # (card index, MiB)
        self.held = 0
        self.up = False
        self.asked: list[list[str]] = []
        self.ballast_up = True

    @property
    def card(self) -> dict[str, Any]:
        return self.cards[self.chosen]

    def used(self, c: dict[str, Any]) -> int:
        mine = (CONTEXT + self.held) if (self.up and c is self.card) else 0
        return int(c["used"]) + mine + sum(m for i, m in self.apps if i == c["index"])

    def free(self, c: dict[str, Any]) -> int:
        return int(c["total"]) - self.used(c) - int(c["reserved"])

    def smi(self, cmd: Sequence[str]) -> str:
        cmd = list(cmd)
        assert cmd[0] == "nvidia-smi"
        self.asked.append(cmd)
        idx = int(cmd[cmd.index("-i") + 1]) if "-i" in cmd else None
        q = next(a for a in cmd if a.startswith("--query-"))
        fields = q.split("=", 1)[1].split(",")
        rows = []
        if q.startswith("--query-compute-apps"):
            for n, (i, mib) in enumerate(self.apps):
                if idx is None or i == idx:
                    row: dict[str, str] = {"gpu_uuid": self.cards[i]["uuid"], "pid": str(77000 + n), "process_name": "their-job",
                           "used_memory": str(mib)}  # fmt: skip
                    rows.append(", ".join(row[f] for f in fields))
            return "".join(r + "\n" for r in rows)
        for c in self.cards:
            if idx is None or c["index"] == idx:
                row2: dict[str, str] = {
                    "index": str(c["index"]),
                    "uuid": c["uuid"],
                    "name": "NVIDIA stand-in",
                    "memory.total": str(c["total"]),
                    "memory.used": str(self.used(c)),
                    "memory.free": str(self.free(c)),
                    "driver_version": "575.57.08",
                    "display_active": "Disabled",
                }
                rows.append(", ".join(row2[f] for f in fields))  # fmt: skip
        return "".join(r + "\n" for r in rows)

    def runner(self, cmd: list[str], timeout: int, env: dict[str, str] | None = None,
               stream: bool = False) -> tuple[int, str, str]:  # fmt: skip
        if cmd[0] == "nvidia-smi":
            return 0, self.smi(cmd), ""
        if cmd[:2] == ["docker", "ps"]:
            return 0, ("abc123\n" if self.ballast_up else ""), ""
        return 0, "", ""


class Holder:
    """The holder: its first estimate exact, ``adjust`` moves it by what is asked; ``pin`` keeps the UUID."""

    def __init__(self, m: Machine) -> None:
        self.m = m
        self.calls: list[str] = []
        self.pinned = ""

    def pin(self, uuid: str) -> None:
        self.pinned = uuid
        self.calls.append("pin")

    def preflight(self) -> None:
        self.calls.append("preflight")

    def start(self, target_free: int, index: int) -> tuple[int, int]:
        self.calls.append(f"start {target_free} {index}")
        self.m.up = True
        self.m.held = self.m.free(self.m.card) - target_free
        return self.m.held, self.m.free(self.m.card)

    def adjust(self, delta: int) -> tuple[int, int]:
        self.calls.append(f"adjust {delta:+d}")
        self.m.held += delta
        return self.m.held, self.m.free(self.m.card)

    def alive(self) -> bool:
        return self.m.up

    def release(self) -> str:
        self.calls.append("release")
        self.m.up, self.m.held = False, 0
        return ""


def _hold(m: Machine, holder: Holder, out: list[str], **kw: Any) -> int:
    kw.setdefault("settle", lambda: None)
    kw.setdefault("wait", lambda _a: None)
    return b.hold(index=m.chosen, allocator=holder, run=m.smi, target=TARGET, profile=PROFILE, say=out.append, **kw)


# ------------------------------------------------------------------------------------------------ any size


@pytest.mark.parametrize(("total", "reserved"), [(97887, 636), (97887, 0), (183359, 0), (183359, 650)])
def test_the_hold_reaches_the_same_target_on_any_card_from_its_own_figures(total: int, reserved: int) -> None:
    m, out, at_ready = Machine(total, reserved), list[str](), list[int]()
    holder = Holder(m)
    assert _hold(m, holder, out, wait=lambda _a: at_ready.append(m.held)) == 0, out
    assert holder.calls[:3] == ["pin", "preflight", f"start {TARGET} 3"] and holder.pinned == UUIDS[3]
    # the holder took the card's own free as read, less the target: total - its context - reserved - target
    assert at_ready[0] + CONTEXT == total - reserved - TARGET
    plan = [x for x in out if x.startswith("target:")]
    assert plan == [f"target: {TARGET} MiB free, +/- 512; ballast to hold: about {total - reserved - TARGET} MiB"
                    f" ({total} - 0 used - {reserved} reserved - {TARGET})"]  # fmt: skip
    assert any(f"steady: nvidia-smi {TARGET} MiB free on the re-read ({reserved} MiB reserved" in x for x in out)


def test_the_arithmetic_names_no_card_total() -> None:
    src = (ROOT / "tools" / "ballast.py").read_text() + (ROOT / "tools" / "ballast48.py").read_text()
    code = "\n".join(x.split("#", 1)[0] for x in src.splitlines())
    for literal in ("97887", "97_887", "183359", "183_359"):
        assert literal not in code, literal
    card = b.Card(5, UUIDS[5], "x", 183359, 300, 183359 - 300 - 650)
    assert card.reserved == 650 and b.hold_mib(card, TARGET) == 183359 - 300 - 650 - TARGET == card.free - TARGET


@pytest.mark.parametrize(
    ("total", "reserved", "code", "said"),
    [
        (24564, 0, "card-too-small", "24564 MiB in all, below the target 49140"),
        (49140, 0, "card-is-the-target", "within 512 of 49140"),
        (49800, 700, "card-too-small", "49800 MiB in all and the driver reserves 700: at most 49100 MiB can be free"),
    ],
)
def test_a_card_that_cannot_offer_the_target_refuses_with_numbers(total: int, reserved: int, code: str,
                                                                  said: str) -> None:  # fmt: skip
    m = Machine(total, reserved)
    holder = Holder(m)
    with pytest.raises(b.Refused) as e:
        _hold(m, holder, [])
    assert e.value.code == code and said in e.value.text
    assert holder.calls == []  # before anything is allocated


# ------------------------------------------------------------------------------------------------ one card of eight


def test_only_the_chosen_card_is_read_on_a_machine_of_eight() -> None:
    m, out = Machine(183359, 650, chosen=3), list[str]()
    m.cards[0]["used"] = 70000  # card 0 busy: it must not matter, and it must not be read
    assert _hold(m, Holder(m), out) == 0
    assert m.asked and all(c[c.index("-i") + 1] == "3" for c in m.asked), m.asked
    assert all(c["used"] == (70000 if c["index"] == 0 else 0) for c in m.cards)  # nothing else changed


def test_a_process_on_the_chosen_card_refuses_by_count_and_memory_only() -> None:
    m = Machine(183359, 650, apps=[(3, 2500), (3, 1500)])
    with pytest.raises(b.Refused) as e:
        _hold(m, Holder(m), [])
    assert e.value.code == "memory-already-held"
    assert e.value.text.startswith("2 compute process(es) already on card 3, 4000 MiB")
    assert "their-job" not in e.value.text and "7700" not in e.value.text and "pid" not in e.value.text


def test_a_process_on_another_card_does_not_matter() -> None:
    m, out, at_ready = Machine(183359, 650, apps=[(5, 90000), (0, 2000)]), list[str](), list[int]()
    assert _hold(m, Holder(m), out, wait=lambda _a: at_ready.append(m.held)) == 0
    assert at_ready[0] + CONTEXT == 183359 - 650 - TARGET


def test_a_card_whose_uuid_changes_between_reads_is_refused_and_released() -> None:
    m, out = Machine(183359, 650), list[str]()
    holder = Holder(m)

    def swap() -> None:  # before the re-read: another card now answers at index 3
        m.cards[3]["uuid"] = UUIDS[6]

    assert _hold(m, holder, out, settle=swap) == 2
    assert any(x.startswith("refused: card-changed: card 3 is not the card read first") for x in out), out
    assert holder.calls[-1] == "release" and "ready" not in "\n".join(out)


def test_a_uuid_given_from_before_is_checked_at_the_first_read() -> None:
    m = Machine(183359, 650)
    with pytest.raises(b.Refused) as e:
        _hold(m, Holder(m), [], uuid=UUIDS[4])
    assert e.value.code == "card-changed"


def test_the_holder_is_pinned_to_the_card_by_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    class Popen:
        def __init__(self, cmd: list[str], **_: Any) -> None:
            seen.append(cmd)
            self.stdout = iter(["HELD 1 FREE 49140\n"])
            self.stdin = None

        def poll(self) -> None:
            return None

    monkeypatch.setattr(subprocess, "Popen", Popen)
    a = b.DockerAllocator("img@sha256:0", run=lambda c: "")
    with pytest.raises(b.Refused, match="pinned by UUID only"):
        a.start(TARGET, 3)
    with pytest.raises(b.Refused):
        a.pin("3")  # an index is not a UUID
    a.pin(UUIDS[3])
    assert a.start(TARGET, 3) == (1, 49140)
    cmd = seen[0]
    assert cmd[cmd.index("--gpus") + 1] == f"device={UUIDS[3]}"
    assert f"NVIDIA_VISIBLE_DEVICES={UUIDS[3]}" in cmd and "device=3" not in cmd
    assert cmd[cmd.index("--network") + 1] == "none" and cmd[cmd.index("--pull") + 1] == "never"


def test_the_ballast_container_carries_the_run_id_when_a_run_names_it() -> None:
    code = "from tools import ballast; print(ballast.CONTAINER)"
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    for given, want in (
        ("tb-ballast-m48h-1", "tb-ballast-m48h-1"),
        ("", "tb-ballast"),
        ("other; rm -rf", "tb-ballast"),
    ):
        out = subprocess.run([sys.executable, "-c", code], env={**env, "TB_BALLAST_CONTAINER": given},
                             capture_output=True, text=True, check=True, cwd=ROOT).stdout.strip()  # fmt: skip
        assert out == want, given


# ------------------------------------------------------------------------------------------------ ballast48


def _held(m: Machine) -> Machine:
    m.up, m.held = True, m.free(m.card) - TARGET - CONTEXT
    return m


def test_ballast48_checks_the_chosen_card_and_its_view_asks_only_about_it() -> None:
    m = _held(Machine(183359, 650))
    card = b48.check(m.runner, TARGET, 3)
    assert card["free_mib"] == TARGET and card["total_mib"] == 183359 and card["reserved_mib"] == 650
    view = b48.BallastView(m.runner, card["total_mib"], TARGET, card["reserved_mib"], index=3, uuid=card["uuid"])
    rc, out, _ = view(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                      60)  # fmt: skip
    assert rc == 0 and out == f"NVIDIA stand-in, {TARGET}, 575.57.08\n"  # one line, the UUID asked and taken off
    m.cards[3]["used"] = 30000  # the servers
    _, out, _ = view(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], 60)
    assert out.strip() == "30000"
    assert all(c[c.index("-i") + 1] == "3" for c in m.asked)
    m.cards[3]["uuid"] = UUIDS[1]
    rc, out, err = view(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], 60)
    assert rc == 1 and out == "" and "UUID changed" in err and view.card_changed


def test_the_pin_file_puts_both_servers_on_the_card_by_uuid() -> None:
    text = b48.pin_text(UUIDS[3])
    for svc in dgpu48.SERVICE.values():
        assert f"  {svc}:\n" in text
    assert text.count(f'devices: !override [{{driver: nvidia, device_ids: ["{UUIDS[3]}"], capabilities: [gpu]}}]') == 2
    assert "count" not in text


def _compose(m: Machine, devices: Any, running: Any) -> Any:
    """Docker's answers: compose's resolved configuration and each container's device request."""
    calls: list[list[str]] = []

    def run(cmd: list[str], timeout: int, env: dict[str, str] | None = None,
            stream: bool = False) -> tuple[int, str, str]:  # fmt: skip
        calls.append(list(cmd))
        if "config" in cmd:
            svc = {
                s: {"deploy": {"resources": {"reservations": {"devices": devices}}}} for s in dgpu48.SERVICE.values()
            }
            return 0, json.dumps({"services": svc}), ""
        if "ps" in cmd and "compose" in cmd:
            return 0, f"c-{cmd[-1]}\n", ""
        if cmd[:2] == ["docker", "inspect"]:
            return 0, json.dumps(running), ""
        return m.runner(cmd, timeout, env, stream)

    return run, calls


def _up_measure(view: Any, oid: str, out_dir: Path, *_: Any, **__: Any) -> dict[str, Any]:
    """Lane J's measure as far as the start: the overlay's up through the view, then the summary written."""
    up = [*dgpu48.compose(["deploy/docker-compose.yml", dgpu48.OVERLAY, str(out_dir / "dgpu48-run.yml")]), "up", "-d",
          "--wait", "llm-service", "llm-verifier"]  # fmt: skip
    s = {"option": oid, "started": True, "outcome": "STARTED"}
    try:
        view(up, 60, {"JUDGE_GPU_MEM_UTIL": "0.57", "VERIFIER_GPU_MEM_UTIL": "0.27"})
    finally:
        (out_dir / f"measure.{oid}.json").write_text(json.dumps(s))
    return s


def test_the_servers_are_pinned_and_proven_before_and_after_the_start(tmp_path: Path) -> None:
    m = _held(Machine(183359, 650))
    pinned = [{"driver": "nvidia", "device_ids": [UUIDS[3]], "capabilities": ["gpu"]}]
    run, calls = _compose(m, pinned, [{"Driver": "nvidia", "Count": 0, "DeviceIDs": [UUIDS[3]]}])
    s = b48.measure(run, "pair-32k", tmp_path, "pinned", True, False, measure_fn=_up_measure, say=lambda _: None,
                    gpu_index=3, pin=True)  # fmt: skip
    pin = str((tmp_path / b48.PIN_FILE).resolve())
    up = next(c for c in calls if "up" in c)
    assert up[up.index(pin) - 1] == "-f" and up.index(pin) < up.index("--profile")  # after the overlay's files
    assert s["ballast"]["servers_pin"] == {"pinned": True, "before_start": "proven", "after_start": "proven"}
    assert s["ballast"]["gpu_index"] == 3 and s["ballast"]["card_checked_by_uuid"] is True
    rec = (tmp_path / "measure.pair-32k.json").read_text()
    assert not any(u in rec for u in UUIDS)  # the UUID is checked, never written to a record
    down = json.loads((tmp_path / "down.json").read_text())
    assert pin in down["cmd"] and down["pin"]["uuid"] == UUIDS[3]


def test_a_server_that_could_land_on_another_card_is_never_started(tmp_path: Path) -> None:
    m = _held(Machine(183359, 650))
    run, calls = _compose(m, [{"driver": "nvidia", "count": 1, "capabilities": ["gpu"]}], [])
    with pytest.raises(b48.Refused, match="not proven, nothing was started"):
        b48.measure(run, "pair-32k", tmp_path, "pinned", True, False, measure_fn=_up_measure, say=lambda _: None,
                    gpu_index=3, pin=True)  # fmt: skip
    assert not any("up" in c for c in calls)
    rec = json.loads((tmp_path / "measure.pair-32k.json").read_text())
    assert rec["outcome"].startswith("REFUSED") and "by ballast" in rec["ballast"]["capped_to"]
    assert rec["ballast"]["tier_record"] is False


def test_a_server_that_did_land_elsewhere_is_stopped_and_refused(tmp_path: Path) -> None:
    m = _held(Machine(183359, 650))
    pinned = [{"driver": "nvidia", "device_ids": [UUIDS[3]], "capabilities": ["gpu"]}]
    run, calls = _compose(m, pinned, [{"Driver": "nvidia", "Count": 0, "DeviceIDs": [UUIDS[0]]}])
    with pytest.raises(b48.Refused, match="not proven after the start, they were stopped"):
        b48.measure(run, "pair-32k", tmp_path, "pinned", True, False, measure_fn=_up_measure, say=lambda _: None,
                    gpu_index=3, pin=True)  # fmt: skip
    assert any(c[-4:] == ["rm", "-sf", "llm-service", "llm-verifier"] for c in calls)  # stopped by the view itself


def test_the_recreated_verifier_is_proven_on_the_same_card(tmp_path: Path) -> None:
    m = _held(Machine(183359, 650))
    base = ["docker", "compose", "-f", dgpu48.OVERLAY, "-f", "pin.yml", "--profile", "gpu"]
    (tmp_path / "down.json").write_text(json.dumps({"cmd": [*base, "rm", "-sf", "llm-service", "llm-verifier"],
                                                    "env": {}, "pin": {"uuid": UUIDS[3]}}))  # fmt: skip
    pinned = [{"driver": "nvidia", "device_ids": [UUIDS[3]], "capabilities": ["gpu"]}]
    run, calls = _compose(m, pinned, [{"Count": 0, "DeviceIDs": [UUIDS[3]]}])
    assert b48.verifier_flag(tmp_path, run) == 0
    run, calls = _compose(m, pinned, [{"Count": 0, "DeviceIDs": [UUIDS[2]]}])
    assert b48.verifier_flag(tmp_path, run) == 2
    assert calls[-1][-3:] == ["rm", "-sf", "llm-verifier"]


def test_during_says_when_the_card_changed_under_it(tmp_path: Path) -> None:
    m = _held(Machine(183359, 650))

    def screen(cmd: list[str], check: bool) -> subprocess.CompletedProcess[bytes]:
        m.cards[3]["uuid"] = UUIDS[7]
        return subprocess.CompletedProcess(cmd, 0)

    rec = b48.during(["python", "-m", "x"], tmp_path / "d.json", m.runner, every=0.01, popen=screen, index=3,
                     uuid=UUIDS[3])  # fmt: skip
    assert rec["card_changed"] is True and rec["gpu_index"] == 3


# ------------------------------------------------------------------------------------------------ the CLI on PATH

FAKE_SMI = """#!{py}
import sys
a = sys.argv[1:]
i = int(a[a.index("-i") + 1]) if "-i" in a else None
if any(x.startswith("--query-compute-apps") for x in a):
    sys.exit(0)
for n in range(8):
    if i is None or n == i:
        print("%d, GPU-%d%d%d%dbbbb-0000-0000-0000-00000000000%d, NVIDIA stand-in, 183359, 0, 182709" % (n, n, n, n, n, n))
if i is not None and i > 7:
    print("No devices were found", file=sys.stderr)
    sys.exit(6)
"""


def test_the_plan_cli_reads_the_chosen_card_and_checks_its_uuid(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir(mode=0o755)
    (bindir / "nvidia-smi").write_text(FAKE_SMI.replace("{py}", sys.executable))
    (bindir / "nvidia-smi").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("TB_ENV", "PYTHONUNBUFFERED")}
    env.update(PATH=f"{bindir}{os.pathsep}{os.path.dirname(sys.executable)}", PYTHONPATH=str(ROOT))

    def plan(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-m", "tools.ballast", "plan", "--target-mib", str(TARGET), *args],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=60, check=False)  # fmt: skip

    r = plan("--gpu-index", "3", "--gpu-uuid", UUIDS[3])
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("card 3: NVIDIA stand-in, 183359 MiB in all, 0 MiB used, 182709 MiB free, 650 MiB")
    assert UUIDS[3] not in r.stdout  # checked, not printed
    r = plan("--gpu-index", "3", "--gpu-uuid", UUIDS[5])
    assert r.returncode == 2 and "refused: card-changed" in r.stderr
    r = plan("--gpu-index", "9")
    assert r.returncode == 2 and "refused: no-such-card" in r.stderr
