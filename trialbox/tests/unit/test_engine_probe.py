"""Card 24-4 (root review 24): the engine probe's parsing, decisions and file, with faked command outputs.

No Docker, no GPU, no pull: every command the probe would run is answered by a fake runner that records it. What is
shown: the check's line is parsed; each failure is named for what it is (driver, no GPU runtime, a kernel that does
not run, disk, a failed pull); the verdict takes the first form that runs, in the order pinned, compatibility switch,
compatibility libraries, CUDA 12.9 build; one image at a time, each removed after its tests unless it was there
before; the disk is checked before a pull; and the result file names no host, serial, UUID, address or user."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import engine_probe as ep

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb

GOOD = {"available": True, "capability": "8.6", "compat_dir": True, "compat_libs": ["libcuda.so.1"],
        "device": "NVIDIA RTX A6000", "matmul": 262144.0, "torch": "2.9.0+cu130", "torch_cuda": "13.0",
        "vllm": "0.32.0", "vllm_ops": True, "vllm_moe_ops": True}  # fmt: skip
DRIVER_SAYS = ("RuntimeError: The NVIDIA driver on your system is too old (found version 12020). Please update your "
               "GPU driver")  # fmt: skip

NO_MOE = {k: v for k, v in GOOD.items() if k != "vllm_moe_ops"} | {
    "vllm_moe_ops_error": "ImportError: undefined symbol"
}
ERR_804 = "RuntimeError: Error 804: forward compatibility was attempted on non supported HW"
NO_RUNTIME = 'docker: Error response from daemon: could not select device driver "" with capabilities: [[gpu]].'
REQUIRE_CUDA = ("nvidia-container-cli: requirement error: unsatisfied condition: cuda>=13.0, please update your driver "
                "to a newer version")  # fmt: skip


def line(d: dict[str, Any]) -> str:
    return "some log line\nTBPROBE " + json.dumps(d) + "\n"


# ------------------------------------------------------------------------------------------------ parsing, statuses
def test_the_check_line_is_found_after_other_output() -> None:
    assert ep.parse_probe(line(GOOD)) == GOOD
    assert ep.parse_probe("no line") is None
    assert ep.parse_probe("TBPROBE {not json") is None


@pytest.mark.parametrize(
    ("rc", "out", "err", "status"),
    [
        (0, line(GOOD), "", "PASS"),
        (0, line({**GOOD, "matmul": None, "matmul_error": "RuntimeError: CUDA error: no kernel image"}), "", "PARTIAL"),
        (0, line(NO_MOE), "", "PARTIAL"),
        (0, line({"available": False, "vllm": "0.32.0", "compat_dir": True, "compat_libs": []}), DRIVER_SAYS, "DRIVER"),
        (0, line({"available": False, "vllm": "0.32.0", "compat_dir": False, "compat_libs": []}), "", "DRIVER"),
        (0, line({"available_error": ERR_804, "vllm": "0.32.0"}), "", "DRIVER"),
        (125, "", NO_RUNTIME, "NO-GPU"),
        (125, "", REQUIRE_CUDA, "DRIVER"),
        (1, "", "write /var/lib/docker/tmp: no space left on device", "DISK"),
        (137, "", "Killed", "ERROR"),
    ],
)
def test_each_outcome_is_named(rc: int, out: str, err: str, status: str) -> None:
    got, _, why = ep.classify(rc, out, err)
    assert got == status
    assert (why == "") == (status == "PASS")


# ------------------------------------------------------------------------------------------------ the verdict
def _results(**statuses: str) -> list[dict[str, Any]]:
    return [{"name": t["name"], "status": statuses.get(t["name"].replace("+", "_"), "DRIVER")} for t in ep.TESTS]


@pytest.mark.parametrize(
    ("statuses", "use", "pinned"),
    [
        ({"pinned": "PASS", "cu129": "PASS"}, "pinned", True),
        ({"pinned_compat": "PASS", "cu129": "PASS"}, "pinned+compat", True),
        ({"pinned_libs": "PASS"}, "pinned+libs", True),
        ({"cu129": "PASS"}, "cu129", False),
        ({}, None, False),
        ({"pinned": "PARTIAL"}, None, False),
    ],
)
def test_the_verdict_takes_the_first_form_that_runs(statuses: dict[str, str], use: str | None, pinned: bool) -> None:
    v = ep.verdict(_results(**statuses))
    assert v["use"] == use
    assert v["pinned_engine"] is pinned
    if use is None:
        assert "Stop here" in v["next"]
    if use == "cu129":
        assert "not the pinned engine" in v["next"] and "not a profile" in v["next"]
    if use == "pinned+compat":
        assert v["env"] == {"VLLM_ENABLE_CUDA_COMPATIBILITY": "1"}


def test_a_partial_result_is_said_in_the_verdict() -> None:
    assert "pinned: the card is seen but a kernel fails" in ep.verdict(_results(pinned="PARTIAL"))["next"]


# ------------------------------------------------------------------------------------------------ the run
PULL_ERR = "Get https://registry-1.docker.io/v2/: dial tcp 10.0.0.7:443: i/o timeout"
PINNED = "vllm/vllm-openai:v0.32.0@sha256:" + "be" * 32


class Fake:
    """Answers the probe's commands; ``outcomes`` maps a test name to (rc, stdout, stderr) of its check."""

    def __init__(self, outcomes: dict[str, tuple[int, str, str]], free_kb: int = 200 * 1048576,
                 present: tuple[str, ...] = (), pull_rc: int = 0) -> None:  # fmt: skip
        self.calls: list[list[str]] = []
        self.outcomes, self.free_kb, self.present, self.pull_rc = outcomes, free_kb, set(present), pull_rc
        self.pulled: set[str] = set()

    def __call__(self, cmd: list[str], timeout: int) -> tuple[int, str, str]:
        self.calls.append(cmd)
        if cmd[0] == "nvidia-smi":
            return 0, "NVIDIA RTX A6000, 49140, 535.183.01, 8.6\n", ""
        if cmd[0] == "df":
            return 0, f"Filesystem 1024-blocks Used Available Capacity Mounted\n/dev/x 9 9 {self.free_kb} 90% /\n", ""
        sub = cmd[1:3]
        if sub == ["version", "--format"]:
            return 0, "27.3.1\n", ""
        if sub == ["info", "--format"]:
            return 0, ('{"nvidia":{"path":"nvidia-container-runtime"},"runc":{}}' if "Runtimes" in cmd[3]
                       else "/var/lib/docker\n"), ""  # fmt: skip
        if cmd[1] == "pull":
            self.pulled.add(cmd[2])
            return self.pull_rc, "", "" if self.pull_rc == 0 else PULL_ERR
        if sub == ["image", "inspect"]:
            ref = cmd[-1]
            if "--format" in cmd:
                return 0, json.dumps([ref.replace(":v0.32.0", "").replace(":v0.32.0-cu129", "")]) + "|24500000000\n", ""
            return (0 if ref in self.present or ref in self.pulled else 1), "", ""
        if sub == ["image", "rm"]:
            return 0, "", ""
        if cmd[1] == "run":
            env = " ".join(cmd)
            ref = cmd[cmd.index("--entrypoint") + 2]
            name = ("cu129" if ref == ep.CU129 else
                    "pinned+compat" if "VLLM_ENABLE_CUDA_COMPATIBILITY=1" in env else
                    "pinned+libs" if "LD_LIBRARY_PATH=" in cmd[-1] else "pinned")  # fmt: skip
            return self.outcomes.get(name, (0, line({"available": False, "vllm": "0.32.0"}), DRIVER_SAYS))
        raise AssertionError(f"unexpected command {cmd}")


def _probe(fake: Fake, **kw: Any) -> dict[str, Any]:
    return ep.probe(fake, pinned=PINNED, hostname="igx-lab-07", say=lambda s: None, **kw)


def test_one_image_at_a_time_each_removed_before_the_next_pull() -> None:
    fake = Fake({"pinned+compat": (0, line(GOOD), "")})
    rec = _probe(fake)
    order = [(c[1], c[-1]) for c in fake.calls if c[0] == "docker" and c[1] in ("pull", "image") and
             (c[1] == "pull" or c[2] == "rm")]  # fmt: skip
    assert order == [("pull", PINNED), ("image", PINNED), ("pull", ep.CU129), ("image", ep.CU129)]
    runs = [c for c in fake.calls if c[1] == "run"]
    assert len(runs) == 4 and all("--network" in c and "none" in c and "--gpus" in c for c in runs)
    assert [t["status"] for t in rec["tests"]] == ["DRIVER", "PASS", "DRIVER", "DRIVER"]
    assert rec["verdict"]["use"] == "pinned+compat"
    assert rec["images"]["pinned"]["removed"] and rec["images"]["cu129"]["removed"]
    assert rec["host"] == {"arch": rec["host"]["arch"], "card": "NVIDIA RTX A6000", "memory_total_mib": 49140,
                           "driver": "535.183.01", "compute_cap": "8.6", "docker": "27.3.1",
                           "nvidia_runtime": True, "free_gb_before": 200.0}  # fmt: skip


def test_an_image_that_was_there_is_left_and_not_pulled() -> None:
    fake = Fake({"pinned": (0, line(GOOD), "")}, present=(PINNED,))
    rec = _probe(fake, only=["pinned"])
    assert not any(c[1] == "pull" for c in fake.calls)
    assert not any(c[1:3] == ["image", "rm"] for c in fake.calls)
    assert rec["verdict"]["use"] == "pinned"
    assert [t["status"] for t in rec["tests"]] == ["PASS", "NOT-RUN", "NOT-RUN", "NOT-RUN"]


def test_too_little_disk_pulls_nothing() -> None:
    fake = Fake({}, free_kb=12 * 1048576)
    rec = _probe(fake)
    assert not any(c[1] == "pull" for c in fake.calls)
    assert {t["status"] for t in rec["tests"]} == {"DISK"}
    assert rec["verdict"]["use"] is None


def test_a_failed_pull_is_said_and_scrubbed() -> None:
    rec = _probe(Fake({}, pull_rc=1))
    assert {t["status"] for t in rec["tests"]} == {"PULL-FAILED"}
    assert all("10.0.0.7" not in t["error"] and "<address>" in t["error"] for t in rec["tests"])


def test_the_result_file_names_no_host_serial_uuid_address_or_user(tmp_path: Path) -> None:
    leaky = ("RuntimeError: CUDA error on GPU-5f3c2a1b-77aa-4d2e-9b10-0123456789ab at /home/someone/x, host igx-lab-07 "
             "addr 192.168.1.20 fe80::1ff:fe23:4567:890a mac 00:1b:44:11:3a:b7 serial: 1324021012345 "
             "driver too old")  # fmt: skip
    fake = Fake({"pinned": (1, "", leaky), "cu129": (0, line({**GOOD, "matmul": None, "matmul_error": leaky}), "")})
    rec = _probe(fake)
    text = json.dumps(rec)
    for secret in ("5f3c2a1b", "someone", "igx-lab-07", "192.168.1.20", "fe80", "00:1b:44", "1324021012345"):
        assert secret not in json.dumps(rec["tests"]), secret
    assert "igx-lab-07" not in text
    assert set(rec) == {"schema", "at", "host", "images", "tests", "verdict"}
    # the check's own result keeps the card's model and its numbers, not the leaky error unscrubbed
    cu = next(t for t in rec["tests"] if t["name"] == "cu129")
    assert cu["status"] == "PARTIAL" and cu["probe"]["device"] == "NVIDIA RTX A6000"


def test_scrub_keeps_what_says_what_failed() -> None:
    s = ep.scrub("ImportError: libcuda.so.1: cannot open shared object file (CUDA 12.9, sm_86) at 12:34:56")
    assert "libcuda.so.1" in s and "12.9" in s and "sm_86" in s and "12:34:56" in s
    assert len(ep.scrub("x" * 5000)) == 400


def test_the_table_reads_the_record() -> None:
    rec = _probe(Fake({"pinned+compat": (0, line(GOOD), "")}))
    out = ep.table(rec)
    assert "NVIDIA RTX A6000" in out and "535.183.01" in out
    assert "pinned+compat   PASS" in out and "verdict: pinned+compat" in out


def test_the_run_command_passes_the_check_and_the_switch() -> None:
    compat = next(t for t in ep.TESTS if t["name"] == "pinned+compat")
    cmd = ep.run_command(compat, PINNED, ["--gpus", "all"])
    assert cmd[:6] == ["docker", "run", "--rm", "--network", "none", "--gpus"]
    assert "VLLM_ENABLE_CUDA_COMPATIBILITY=1" in cmd and "ENGINE_PROBE_PY" in cmd
    libs = next(t for t in ep.TESTS if t["name"] == "pinned+libs")
    assert ep.run_command(libs, PINNED, [])[-1].startswith("LD_LIBRARY_PATH=/usr/local/cuda/compat:")


def test_the_check_itself_is_valid_python() -> None:
    compile(ep.PROBE_PY, "<probe>", "exec")


def test_the_pinned_image_is_the_lock_and_cu129_is_not_in_it() -> None:
    lock = json.loads((ROOT / "deploy/images.lock").read_text(encoding="utf-8"))
    v = lock["third_party"]["vllm"]
    assert ep.pinned_ref() == f"{v['image']}@{v['digest']}"
    assert ep.CU129.split("@")[1] not in (ROOT / "deploy/images.lock").read_text(encoding="utf-8")


def test_dry_run_and_show_run_with_a_bare_host_python(tmp_path: Path) -> None:
    """The owner runs it with the host's python3: standard library only, from the checkout, nothing pulled."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV"))}
    res = subprocess.run([sys.executable, "-S", "-s", "tools/engine_probe.py", "run", "--dry-run"], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=False)  # fmt: skip
    assert res.returncode == 0, res.stderr
    assert "docker pull vllm/vllm-openai:v0.32.0@sha256:" in res.stdout and ep.CU129 in res.stdout
    rec = _probe(Fake({"cu129": (0, line(GOOD), "")}))
    f = tmp_path / "probe.json"
    f.write_text(json.dumps(rec), encoding="utf-8")
    res = subprocess.run([sys.executable, "-S", "-s", "tools/engine_probe.py", "show", str(f)], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=False)  # fmt: skip
    assert res.returncode == 0 and "verdict: cu129" in res.stdout
    assert ep.main(["run", "--only", "nonsense"]) == 2
