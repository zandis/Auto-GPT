"""10E-28 (review 19's 19-2): the ballast stand-in holds a larger card at a 5090's free memory and sets the two
utilisations, refusing with a named reason before it allocates anything. No card here: the driver tool and the
holder are stand-ins (an injected command runner and allocator, and a fake ``nvidia-smi`` and ``docker`` on PATH)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools import ballast as b

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
A6000 = "0, GPU-aaaa, NVIDIA RTX A6000, 49140, {used}, {free}"
PROFILE = {"JUDGE_GPU_MEM_UTIL": 0.81, "VERIFIER_GPU_MEM_UTIL": 0.81}


def _card(total: int = 49140, used: int = 300) -> b.Card:
    return b.Card(0, "GPU-aaaa", "NVIDIA RTX A6000", total, used, total - used)


class FakeCard:
    """nvidia-smi as a function: the ballast's holder moves memory from free to used."""

    def __init__(self, used: int = 300, apps: str = "") -> None:
        self.used = used
        self.apps = apps

    def __call__(self, cmd: Sequence[str]) -> str:
        assert cmd[0] == "nvidia-smi"
        if "--query-compute-apps" in cmd[1]:
            return self.apps
        return A6000.format(used=self.used, free=49140 - self.used) + "\n"


class FakeHolder:
    def __init__(self, card: FakeCard, overhead: int = 300, fail: str = "") -> None:
        self.card, self.overhead, self.fail = card, overhead, fail
        self.calls: list[str] = []
        self.up = False

    def preflight(self) -> None:
        self.calls.append("preflight")

    def start(self, target_free: int, index: int) -> tuple[int, int]:
        self.calls.append(f"start {target_free} {index}")
        if self.fail:
            raise b.Refused("allocation-failed", self.fail)
        held = 49140 - self.card.used - target_free - self.overhead
        self.card.used = 49140 - target_free + 40  # mem_get_info and nvidia-smi differ by a little
        self.up = True
        return held, target_free

    def alive(self) -> bool:
        return self.up

    def release(self) -> None:
        self.calls.append("release")
        self.card.used = 300
        self.up = False


# ------------------------------------------------------------------------------------------------ arithmetic


def test_the_profile_utilisations_come_from_the_5090_compose_file() -> None:
    assert b.profile_utils() == PROFILE


def test_the_5090_budget_on_a_48_gb_card_is_0_537() -> None:
    # review 19 section 4.1: 0.81 of 32,607 MiB is 26,412 MiB; 26,412 / 49,140 = 0.537
    assert b.util_on(49140, 0.81) == 0.537
    assert 0.537 * 49140 <= 0.81 * 32607  # rounded down: never a larger budget than the 5090's
    assert b.util_on(97887, 0.81) == 0.269


def test_a_plan_on_the_owners_card() -> None:
    plan = b.check(_card(), [], profile=PROFILE)
    assert plan.ballast == 49140 - 300 - 32607
    assert plan.utils == {"JUDGE_GPU_MEM_UTIL": 0.537, "VERIFIER_GPU_MEM_UTIL": 0.537}


# ------------------------------------------------------------------------------------------------ refusals


@pytest.mark.parametrize(
    ("card", "procs", "code"),
    [
        (_card(total=24564), [], "card-too-small"),
        (_card(total=32607), [], "card-is-the-target"),
        (_card(), [b.Proc("4242", "python3", 9000)], "memory-already-held"),
        (_card(used=4000), [], "memory-already-held"),
    ],
)
def test_each_refusal_is_named(card: b.Card, procs: list[b.Proc], code: str) -> None:
    with pytest.raises(b.Refused) as e:
        b.check(card, procs, profile=PROFILE)
    assert e.value.code == code


def test_an_expected_process_and_its_memory_are_tolerated() -> None:
    procs = [b.Proc("77", "/usr/lib/xorg/Xorg", None)]
    plan = b.check(_card(used=1500), procs, expect_procs=["Xorg"], expect_used=2000, profile=PROFILE)
    assert plan.ballast == 49140 - 1500 - 32607


def test_without_nvidia_smi_the_refusal_is_named(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(b.Refused) as e:
        b.read_card(0)
    assert e.value.code == "driver-tool-missing"


def test_the_card_index_must_exist() -> None:
    with pytest.raises(b.Refused) as e:
        b.read_card(1, FakeCard())
    assert e.value.code == "no-such-card"


def test_compute_processes_are_read_for_this_card_only() -> None:
    card = b.read_card(0, FakeCard())
    apps = "GPU-aaaa, 4242, python3, 9000\nGPU-bbbb, 99, other, 100\nGPU-aaaa, 7, Xorg, [N/A]\n"
    procs = b.read_procs(card, FakeCard(apps=apps))
    assert [(p.pid, p.name, p.used) for p in procs] == [("4242", "python3", 9000), ("7", "Xorg", None)]


@pytest.mark.parametrize("where", ["process", "file"])
def test_production_is_refused_before_the_card_is_read(
    where: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = tmp_path / ".env"
    env.write_text("TB_ENV=VALIDATION\n")
    if where == "process":
        monkeypatch.setenv("TB_ENV", "production")
    else:
        monkeypatch.delenv("TB_ENV", raising=False)
        env.write_text('TB_ENV="PRODUCTION"\n')
    card = FakeCard()
    holder = FakeHolder(card)
    with pytest.raises(b.Refused) as e:
        b.hold(index=0, allocator=holder, run=card, env_file=env, profile=PROFILE, say=lambda _s: None)
    assert e.value.code == "production"
    assert holder.calls == []


def test_a_refusal_comes_before_any_allocation() -> None:
    card = FakeCard(apps="GPU-aaaa, 4242, python3, 9000\n")
    holder = FakeHolder(card)
    with pytest.raises(b.Refused) as e:
        b.hold(index=0, allocator=holder, run=card, profile=PROFILE, say=lambda _s: None)
    assert e.value.code == "memory-already-held"
    assert holder.calls == []


# ------------------------------------------------------------------------------------------------ hold and release


def test_hold_prints_what_it_holds_and_what_is_left_then_releases(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TB_ENV=VALIDATION\nJUDGE_GPU_MEM_UTIL=0.81\n")
    before = env.read_text()
    card, out = FakeCard(), list[str]()
    holder = FakeHolder(card)
    seen_env: list[str] = []
    rc = b.hold(
        index=0, allocator=holder, run=card, env_file=env, profile=PROFILE, say=out.append,
        wait=lambda _a: seen_env.append(env.read_text()),
    )  # fmt: skip
    assert rc == 0
    assert holder.calls == ["preflight", "start 32607 0", "release"]
    text = "\n".join(out)
    assert "holding 15933 MiB" in text and "32567 MiB free left" in text
    assert "export JUDGE_GPU_MEM_UTIL=0.537" in text and b.CAPPED_TO in text
    assert "JUDGE_GPU_MEM_UTIL=0.537" in seen_env[0] and "VERIFIER_GPU_MEM_UTIL=0.537" in seen_env[0]
    assert "was JUDGE_GPU_MEM_UTIL=0.81" in seen_env[0]
    assert env.read_text() == before  # put back as it was
    assert out[-1] == "released"


def test_off_target_is_released_at_once() -> None:
    card, out = FakeCard(), list[str]()
    holder = FakeHolder(card)
    rc = b.hold(index=0, allocator=holder, run=card, profile=PROFILE, tolerance=10, say=out.append,
                wait=lambda _a: pytest.fail("waited off target"))  # fmt: skip
    assert rc == 2
    assert any(x.startswith("refused: off-target") for x in out)
    assert holder.calls[-1] == "release"


def test_a_failed_allocation_releases_and_puts_the_env_back(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TB_ENV=DEV\n")
    card, out = FakeCard(), list[str]()
    rc = b.hold(index=0, allocator=FakeHolder(card, fail="out of memory"), run=card, env_file=env, profile=PROFILE,
                say=out.append)  # fmt: skip
    assert rc == 2 and "refused: allocation-failed: out of memory" in out
    assert env.read_text() == "TB_ENV=DEV\n"


def test_sigterm_while_holding_releases(tmp_path: Path) -> None:
    card, out = FakeCard(), list[str]()
    holder = FakeHolder(card)

    def wait(_a: object) -> None:
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(5)
        pytest.fail("SIGTERM did not stop the wait")

    rc = b.hold(index=0, allocator=holder, run=card, profile=PROFILE, say=out.append, wait=wait)
    assert rc == 0 and "SIGTERM: releasing" in out and holder.calls[-1] == "release"
    assert card.used == 300
    assert signal.getsignal(signal.SIGTERM) is not b._on_signal  # handlers put back


def test_a_lost_holder_is_said_and_exits_1() -> None:
    card, out = FakeCard(), list[str]()
    holder = FakeHolder(card)

    def wait(a: FakeHolder) -> None:
        a.up = False

    rc = b.hold(index=0, allocator=holder, run=card, profile=PROFILE, say=out.append, wait=wait)  # type: ignore[arg-type]
    assert rc == 1 and any(x.startswith("ballast-lost") for x in out)


def test_an_env_file_already_holding_a_ballast_is_left_alone(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    b.set_env(env, {"JUDGE_GPU_MEM_UTIL": 0.537})
    marked = env.read_text()
    card = FakeCard()
    rc = b.hold(index=0, allocator=FakeHolder(card), run=card, env_file=env, profile=PROFILE, say=lambda _s: None)
    assert rc == 2
    assert env.read_text() == marked
    assert b.restore_env(env) == ["JUDGE_GPU_MEM_UTIL"] and env.read_text() == ""


# ------------------------------------------------------------------------------------------------ the CLI, fakes on PATH

FAKE_SMI = """#!{py}
import json, os, sys
s = json.load(open(os.environ["BALLAST_FAKE_STATE"]))
if any(a.startswith("--query-compute-apps") for a in sys.argv):
    sys.exit(0)
print("0, GPU-aaaa, NVIDIA RTX A6000, 49140, %d, %d" % (s["used"], 49140 - s["used"]))
"""

FAKE_DOCKER = """#!{py}
import json, os, signal, sys, time
p = os.environ["BALLAST_FAKE_STATE"]
s = json.load(open(p))
a = sys.argv[1:]
open(p + ".calls", "a").write(" ".join(a[:3]) + "\\n")
def save():
    json.dump(s, open(p, "w"))
if a[:2] == ["image", "inspect"]:
    print("sha256:" + "0" * 64)
elif a[0] == "ps":
    print(s.get("container", ""))
elif a[0] == "run":
    assert "--network" in a and a[a.index("--network") + 1] == "none" and "--pull" in a
    target = int(a[-1])
    held = 49140 - s["used"] - target - 300
    s["used"] = 49140 - target + 40
    s["container"] = str(os.getpid())
    save()
    print("HELD %d FREE %d" % (held, target), flush=True)
    signal.signal(signal.SIGTERM, lambda *x: sys.exit(0))
    while True:
        time.sleep(1)
elif a[:2] == ["rm", "-f"]:
    if not s.get("container"):
        sys.exit(1)
    os.kill(int(s.pop("container")), signal.SIGTERM)
    s["used"] = 300
    save()
"""


def _fakes(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, text in (("nvidia-smi", FAKE_SMI), ("docker", FAKE_DOCKER)):
        f = bindir / name
        f.write_text(text.replace("{py}", sys.executable))
        f.chmod(0o755)
    state = tmp_path / "gpu.json"
    state.write_text(json.dumps({"used": 300}))
    env = {k: v for k, v in os.environ.items() if k not in ("TB_ENV", "VLLM_IMAGE")}
    env.update(PATH=str(bindir), BALLAST_FAKE_STATE=str(state), PYTHONPATH=str(ROOT))
    return env, state


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_the_cli_holds_until_a_signal_and_releases_everything(sig: signal.Signals, tmp_path: Path) -> None:
    env, state = _fakes(tmp_path)
    dotenv = tmp_path / ".env"
    dotenv.write_text("TB_ENV=VALIDATION\n")
    p = subprocess.Popen(
        [sys.executable, "-m", "tools.ballast", "hold", "--env-file", str(dotenv)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )  # fmt: skip
    assert p.stdout is not None
    lines = []
    for line in p.stdout:
        lines.append(line)
        if line.startswith("ready"):
            break
    else:
        pytest.fail("".join(lines))
    assert "VERIFIER_GPU_MEM_UTIL=0.537" in dotenv.read_text()
    assert json.loads(state.read_text())["used"] == 49140 - 32607 + 40
    p.send_signal(sig)
    rest, _ = p.communicate(timeout=30)
    assert p.returncode == 0, "".join(lines) + rest
    assert rest.rstrip().endswith("released")
    assert json.loads(state.read_text()) == {"used": 300}  # the holder is gone, its memory free
    assert "rm -f tb-ballast" in Path(f"{state}.calls").read_text()
    assert dotenv.read_text() == "TB_ENV=VALIDATION\n"


def test_the_cli_without_the_driver_tool_refuses(tmp_path: Path) -> None:
    env, _ = _fakes(tmp_path)
    (tmp_path / "bin" / "nvidia-smi").unlink()
    p = subprocess.run([sys.executable, "-m", "tools.ballast", "plan", "--env-file", str(tmp_path / "none")],
                       check=False, cwd=ROOT,
                       env=env, capture_output=True, text=True, timeout=60)  # fmt: skip
    assert p.returncode == 2 and "refused: driver-tool-missing" in p.stderr


def test_the_cli_plan_allocates_nothing(tmp_path: Path) -> None:
    env, state = _fakes(tmp_path)
    p = subprocess.run([sys.executable, "-m", "tools.ballast", "plan", "--env-file", str(tmp_path / "none")],
                       check=False, cwd=ROOT,
                       env=env, capture_output=True, text=True, timeout=60)  # fmt: skip
    assert p.returncode == 0, p.stderr
    assert "ballast to hold: about 16233 MiB" in p.stdout and "export JUDGE_GPU_MEM_UTIL=0.537" in p.stdout
    assert not Path(f"{state}.calls").exists()  # docker never asked


# ------------------------------------------------------------------------------------------------ never started by default


def test_nothing_in_the_box_starts_the_ballast() -> None:
    hits = []
    for top in ("deploy", "services", "libs", "console", "orchestrator"):
        d = ROOT / top
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.suffix in {".sh", ".yml", ".yaml", ".py", ".service", ".timer", ".ps1", ""}:
                text = f.read_text(encoding="utf-8", errors="ignore")
                if "tools.ballast" in text or "tools/ballast" in text or "tb-ballast" in text:
                    hits.append(str(f.relative_to(ROOT)))
    assert hits == []
