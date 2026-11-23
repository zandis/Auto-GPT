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
        (125, "", REQUIRE_CUDA, "REQUIRE"),
        (125, "", "nvidia-container-cli: initialization error: load library failed: libnvidia-ml.so.1", "TOOLKIT"),
        (1, "", "RuntimeError: CUDA error: all CUDA-capable devices are busy or unavailable", "BUSY"),
        (0, line({**GOOD, "matmul": None, "matmul_error": "OutOfMemoryError: CUDA out of memory"}), "", "BUSY"),
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
    assert v["answer"] == ("pass" if use else "none")
    if use is None:
        assert "Stop here" in v["next"]
    if use == "cu129":
        assert "not the pinned engine" in v["next"] and "not a profile" in v["next"]
    if use == "pinned+compat":
        assert v["env"] == {"NVIDIA_DISABLE_REQUIRE": "1", "VLLM_ENABLE_CUDA_COMPATIBILITY": "1"}


def test_a_partial_result_is_said_in_the_verdict() -> None:
    assert "pinned: the card is seen but a kernel fails" in ep.verdict(_results(pinned="PARTIAL"))["next"]


@pytest.mark.parametrize(
    ("status", "error", "fix"),
    [
        ("NO-GPU", "", "nvidia-ctk runtime configure"),
        ("PULL-FAILED", "dial tcp: i/o timeout", "curl -sI https://registry-1.docker.io/v2/"),
        ("PULL-FAILED", "toomanyrequests: You have reached your pull rate limit", "docker login"),
        ("BUSY", "all CUDA-capable devices are busy or unavailable", "close the program using the card"),
        ("TOOLKIT", "nvidia-container-cli: initialization error", "nvidia-container-cli info"),
        ("DISK", "12 GB free", "free at least 30 GB"),
        ("ERROR", "timed out after 900 s", "run step 2 again once"),
        ("NOT-RUN", "", "without --only"),
    ],
)
def test_a_failure_that_never_reached_the_card_is_inconclusive_not_none(status: str, error: str, fix: str) -> None:
    """Review of #1100, blocker 1: no docker, no runtime, a failed pull or a full disk is not 'the models cannot run'."""
    results = _results(cu129=status)
    results[-1]["error"] = error
    v = ep.verdict(results)
    assert v["answer"] == "inconclusive" and v["use"] is None
    assert fix in v["fix"] and fix in v["next"]
    assert "Stop here" not in v["next"] and "run step 2 again" in v["next"]


def test_a_preflight_block_is_inconclusive_with_its_fix() -> None:
    results = [{"name": t["name"], "status": "NOT-RUN"} for t in ep.TESTS]
    v = ep.verdict(results, ("Docker has no NVIDIA runtime", ep.FIX_RUNTIME))
    assert v["answer"] == "inconclusive" and ep.FIX_RUNTIME in v["next"] and ep.RERUN in v["next"]


def test_the_libs_variant_records_the_library_path_it_ran_with() -> None:
    """Review of #1100, blocker 3: the measuring run must use exactly what passed."""
    results = _results(pinned_libs="PASS")
    results[2]["probe"] = {**GOOD, "ld_library_path": "/usr/local/cuda/compat:/usr/local/nvidia/lib64:"}
    v = ep.verdict(results)
    assert v["env"] == {
        "NVIDIA_DISABLE_REQUIRE": "1",
        "LD_LIBRARY_PATH": "/usr/local/cuda/compat:/usr/local/nvidia/lib64",
    }


# ------------------------------------------------------------------------------------------------ the run
PULL_ERR = "Get https://registry-1.docker.io/v2/: dial tcp 10.0.0.7:443: i/o timeout"
PINNED = "vllm/vllm-openai:v0.32.0@sha256:" + "be" * 32


class Fake:
    """Answers the probe's commands; ``outcomes`` maps a test name to (rc, stdout, stderr) of its check."""

    def __init__(self, outcomes: dict[str, tuple[int, str, str]], free_kb: int = 200 * 1048576,
                 present: tuple[str, ...] = (), pull_rc: int = 0, docker_rc: int = 0, docker_err: str = "",
                 runtimes: str = '{"nvidia":{"path":"nvidia-container-runtime"},"runc":{}}', rm_rc: int = 0,
                 interrupt_on: str = "", cli_rc: int = 0, pull_err: str = PULL_ERR,
                 rm_err: str = "Error: image is being used by a stopped container") -> None:  # fmt: skip
        self.calls: list[list[str]] = []
        self.streamed: list[list[str]] = []
        self.outcomes, self.free_kb, self.present, self.pull_rc = outcomes, free_kb, set(present), pull_rc
        self.docker_rc, self.docker_err, self.runtimes, self.rm_rc = docker_rc, docker_err, runtimes, rm_rc
        self.interrupt_on, self.cli_rc, self.pull_err, self.rm_err = interrupt_on, cli_rc, pull_err, rm_err
        self.pulled: set[str] = set()

    def __call__(self, cmd: list[str], timeout: int, stream: bool = False) -> tuple[int, str, str]:
        self.calls.append(cmd)
        if stream:
            self.streamed.append(cmd)
        if cmd[0] == "nvidia-container-cli":
            return self.cli_rc, "", "" if self.cli_rc == 0 else "nvidia-container-cli: initialization error: nvml error"
        if self.interrupt_on == "preflight" and cmd[0] == "nvidia-smi":
            raise KeyboardInterrupt
        if cmd[0] == "nvidia-smi":
            if cmd[1] == "-L":
                return 0, "GPU 0: NVIDIA RTX A6000 (UUID: GPU-5f3c2a1b-77aa-4d2e-9b10-0123456789ab)\n", ""
            if "display_active" in cmd[1]:
                return 0, "Enabled, 412\n", ""
            return 0, "NVIDIA RTX A6000, 49140, 535.183.01, 8.6\n", ""
        if cmd[0] == "df":
            return 0, f"Filesystem 1024-blocks Used Available Capacity Mounted\n/dev/x 9 9 {self.free_kb} 90% /\n", ""
        sub = cmd[1:3]
        if sub == ["version", "--format"]:
            return (0, "27.3.1\n", "") if self.docker_rc == 0 else (self.docker_rc, "", self.docker_err)
        if sub == ["info", "--format"]:
            return 0, (self.runtimes if "Runtimes" in cmd[3] else "/var/lib/docker\n"), ""
        if cmd[1] == "pull":
            self.pulled.add(cmd[2])
            return self.pull_rc, "", "" if self.pull_rc == 0 else self.pull_err
        if sub == ["image", "inspect"]:
            ref = cmd[-1]
            if "--format" in cmd:
                return 0, json.dumps([ref.replace(":v0.32.0", "").replace(":v0.32.0-cu129", "")]) + "|24500000000\n", ""
            return (0 if ref in self.present or ref in self.pulled else 1), "", ""
        if sub == ["image", "rm"]:
            return self.rm_rc, "", "" if self.rm_rc == 0 else self.rm_err
        if sub == ["rm", "-f"]:
            return 0, "", ""
        if cmd[1] == "run":
            env = " ".join(cmd)
            ref = cmd[cmd.index("--entrypoint") + 2]
            assert ("NVIDIA_DISABLE_REQUIRE=1" in env) == (ref != ep.CU129 and ("VLLM_ENABLE_CUDA_COMPATIBILITY=1" in env
                                                                             or "LD_LIBRARY_PATH=" in cmd[-1]))  # fmt: skip
            name = ("cu129" if ref == ep.CU129 else
                    "pinned+compat" if "VLLM_ENABLE_CUDA_COMPATIBILITY=1" in env else
                    "pinned+libs" if "LD_LIBRARY_PATH=" in cmd[-1] else "pinned")  # fmt: skip
            if name == self.interrupt_on:
                raise KeyboardInterrupt
            return self.outcomes.get(name, (0, line({"available": False, "vllm": "0.32.0"}), DRIVER_SAYS))
        raise AssertionError(f"unexpected command {cmd}")


def _probe(fake: Fake, **kw: Any) -> dict[str, Any]:
    return ep.probe(fake, pinned=PINNED, hostname="igx-lab-07", say=lambda s: None, names=["owner1"], **kw)


def _pulls(fake: Fake) -> list[str]:
    return [c[2] for c in fake.calls if c[:2] == ["docker", "pull"]]


def test_one_image_at_a_time_each_removed_before_the_next_pull() -> None:
    fake = Fake({"cu129": (0, line(GOOD), "")})
    rec = _probe(fake)
    order = [(c[1], c[-1]) for c in fake.calls if c[0] == "docker" and c[1] in ("pull", "image") and
             (c[1] == "pull" or c[2] == "rm")]  # fmt: skip
    assert order == [("pull", PINNED), ("image", PINNED), ("pull", ep.CU129), ("image", ep.CU129)]
    assert fake.streamed == [["docker", "pull", PINNED], ["docker", "pull", ep.CU129]]  # progress is shown
    runs = [c for c in fake.calls if c[1] == "run"]
    assert len(runs) == 4 and all("--network" in c and "none" in c and "--gpus" in c and "--name" in c for c in runs)
    assert [t["status"] for t in rec["tests"]] == ["DRIVER", "DRIVER", "DRIVER", "PASS"]
    assert rec["verdict"]["use"] == "cu129"
    assert rec["images"]["pinned"]["removed"] and rec["images"]["cu129"]["removed"]
    assert rec["host"]["display_active"] == "Enabled" and rec["host"]["memory_used_mib"] == 412
    assert rec["host"]["card"] == "NVIDIA RTX A6000" and rec["host"]["driver"] == "535.183.01"


def test_after_a_pinned_pass_nothing_more_is_tried_or_pulled() -> None:
    """Review of #1100, blocker 1: a pinned pass is the answer; the second image is never pulled."""
    fake = Fake({"pinned": (0, line(GOOD), "")})
    rec = _probe(fake)
    assert _pulls(fake) == [PINNED]
    assert len([c for c in fake.calls if c[1] == "run"]) == 1
    assert [t["status"] for t in rec["tests"]] == ["PASS", "SKIPPED", "SKIPPED", "SKIPPED"]
    assert rec["verdict"]["use"] == "pinned" and ep.EXIT[rec["verdict"]["answer"]] == 0


@pytest.mark.parametrize(
    ("change", "fix"),
    [
        ({"docker_rc": 1, "docker_err": "permission denied while trying to connect to the Docker daemon socket"},
         "usermod -aG docker"),
        ({"docker_rc": 1, "docker_err": "Cannot connect to the Docker daemon. Is the docker daemon running?"},
         "systemctl start docker"),
        ({"docker_rc": 127}, "install Docker Engine"),
        ({"runtimes": '{"runc":{}}'}, "nvidia-ctk runtime configure"),
        ({"free_kb": 12 * 1048576}, "runbook §29 step 1"),
    ],
)  # fmt: skip
def test_nothing_is_downloaded_when_docker_the_runtime_or_the_disk_is_missing(change: dict[str, Any], fix: str) -> None:
    """Review of #1100, blocker 1: checked before any pull, not after an hour of downloads; inconclusive, exit 3."""
    fake = Fake({}, **change)
    rec = _probe(fake)
    assert _pulls(fake) == [] and not any(c[1] == "run" for c in fake.calls)
    v = rec["verdict"]
    assert v["answer"] == "inconclusive" and fix in v["next"] and ep.EXIT["inconclusive"] == 3
    assert {t["status"] for t in rec["tests"]} == {"NOT-RUN"}


def test_an_image_that_was_there_is_left_and_not_pulled() -> None:
    fake = Fake({"pinned": (0, line(GOOD), "")}, present=(PINNED,))
    rec = _probe(fake, only=["pinned"])
    assert _pulls(fake) == []
    assert not any(c[1:3] == ["image", "rm"] for c in fake.calls)
    assert rec["verdict"]["use"] == "pinned"


def test_a_failed_pull_is_inconclusive_said_and_scrubbed() -> None:
    rec = _probe(Fake({}, pull_rc=1))
    assert {t["status"] for t in rec["tests"]} == {"PULL-FAILED"}
    assert all("10.0.0.7" not in t["error"] and "<address>" in t["error"] for t in rec["tests"])
    assert rec["verdict"]["answer"] == "inconclusive" and "registry-1.docker.io" in rec["verdict"]["fix"]


def test_a_removal_that_fails_is_not_recorded_as_removed() -> None:
    """Review of #1100, item 7."""
    rec = _probe(Fake({"pinned": (0, line(GOOD), "")}, rm_rc=1))
    info = rec["images"]["pinned"]
    assert info["removed"] is False and "being used" in info["remove_failed"]
    assert f"docker image rm {PINNED}" in ep.table(rec)


def test_a_timed_out_check_has_its_container_removed() -> None:
    """Review of #1100, item 7: a timeout ends the docker client only; the container is removed by name."""
    fake = Fake({"pinned": (124, "", "timed out after 900 s")})
    rec = _probe(fake, only=["pinned"])
    removed = [c for c in fake.calls if c[:3] == ["docker", "rm", "-f"]]
    assert ["docker", "rm", "-f", "tb-engine-probe-pinned"] in removed
    assert rec["tests"][0]["status"] == "ERROR" and rec["verdict"]["answer"] == "inconclusive"


def test_ctrl_c_removes_the_container_and_the_image_and_says_so() -> None:
    fake = Fake({}, interrupt_on="pinned+compat")
    rec = _probe(fake)
    assert rec["interrupted"] is True
    assert ["docker", "rm", "-f", "tb-engine-probe-pinned-compat"] in fake.calls
    assert ["docker", "image", "rm", PINNED] in fake.calls
    assert ep.CU129 not in _pulls(fake)
    assert rec["verdict"]["answer"] == "inconclusive"


def test_the_result_file_names_no_host_serial_uuid_address_pci_or_user(tmp_path: Path) -> None:
    leaky = ("RuntimeError: CUDA error on GPU-5f3c2a1b-77aa-4d2e-9b10-0123456789ab at /home/someone/x, at host "
             "igx-lab-07 addr 192.168.1.20 fe80::1ff:fe23:4567:890a mac 00:1b:44:11:3a:b7 serial: 1324021012345 "
             "Serial Number 1423919000123 bus 00000000:01:00.0 user owner1 driver too old")  # fmt: skip
    fake = Fake({"pinned": (1, "", leaky), "cu129": (0, line({**GOOD, "matmul": None, "matmul_error": leaky}), "")})
    rec = _probe(fake)
    tests = json.dumps(rec["tests"])
    for secret in ("5f3c2a1b", "someone", "igx-lab-07", "192.168.1.20", "fe80", "00:1b:44", "1324021012345",
                   "1423919000123", "01:00.0", "owner1"):  # fmt: skip
        assert secret not in tests, secret
    assert "igx-lab-07" not in json.dumps(rec)
    assert set(rec) == {"schema", "at", "host", "images", "tests", "verdict"}
    cu = next(t for t in rec["tests"] if t["name"] == "cu129")
    assert cu["status"] == "PARTIAL" and cu["probe"]["device"] == "NVIDIA RTX A6000"


def test_scrub_keeps_what_says_what_failed() -> None:
    s = ep.scrub("ImportError: libcuda.so.1: cannot open shared object file (CUDA 12.9, sm_86) at 12:34:56.7 on "
                 "the host driver", names=[])  # fmt: skip
    assert "libcuda.so.1" in s and "12.9" in s and "sm_86" in s and "12:34:56.7" in s and "host driver" in s
    assert len(ep.scrub("x" * 5000, names=[])) == 400


def test_the_table_and_the_verdict_give_one_next_action() -> None:
    rec = _probe(Fake({"pinned+compat": (0, line(GOOD), "")}))
    out = ep.table(rec)
    assert "NVIDIA RTX A6000" in out and "535.183.01" in out
    assert "pinned+compat   PASS" in out and "verdict: pinned+compat" in out
    assert out.count("next:") == 1 and "Next:" not in out.split("verdict:")[0]
    rec = _probe(Fake({}, runtimes="{}"))
    out = ep.table(rec)
    assert "verdict: inconclusive" in out and out.count("next:") == 1 and ep.FIX_RUNTIME in out


def test_the_run_command_passes_the_check_and_the_switch() -> None:
    compat = next(t for t in ep.TESTS if t["name"] == "pinned+compat")
    cmd = ep.run_command(compat, PINNED, ["--gpus", "all"])
    assert cmd[:5] == ["docker", "run", "--rm", "--name", "tb-engine-probe-pinned-compat"]
    assert "VLLM_ENABLE_CUDA_COMPATIBILITY=1" in cmd and "ENGINE_PROBE_PY" in cmd
    libs = next(t for t in ep.TESTS if t["name"] == "pinned+libs")
    assert ep.run_command(libs, PINNED, [])[-1].startswith("LD_LIBRARY_PATH=/usr/local/cuda/compat:")


def test_the_check_itself_is_valid_python_and_reports_its_library_path() -> None:
    compile(ep.PROBE_PY, "<probe>", "exec")
    assert '"ld_library_path": os.environ.get("LD_LIBRARY_PATH", "")' in ep.PROBE_PY


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
    for fake, code in ((Fake({"cu129": (0, line(GOOD), "")}), 0), (Fake({}), 1), (Fake({}, pull_rc=1), 3)):
        f = tmp_path / "probe.json"
        f.write_text(json.dumps(_probe(fake)), encoding="utf-8")
        res = subprocess.run([sys.executable, "-S", "-s", "tools/engine_probe.py", "show", str(f)], cwd=ROOT, env=env,
                             capture_output=True, text=True, check=False)  # fmt: skip
        assert res.returncode == code, res.stdout
    assert ep.main(["run", "--only", "nonsense"]) == 2


# ------------------------------------------------------------------------------------------------ second review of #1100
def test_the_compatibility_forms_get_past_the_toolkits_cuda_requirement() -> None:
    """Item 1: the image declares cuda>=13.0; on driver 535 the toolkit refuses every plain form before the engine
    starts. The compatibility forms carry NVIDIA_DISABLE_REQUIRE (asserted by the fake on every run), and the
    winning form's environment carries it to the measuring run."""
    fake = Fake({"pinned": (125, "", REQUIRE_CUDA), "pinned+compat": (0, line(GOOD), "")})
    rec = _probe(fake)
    assert [t["status"] for t in rec["tests"]][:2] == ["REQUIRE", "PASS"]
    assert rec["verdict"]["env"] == {"NVIDIA_DISABLE_REQUIRE": "1", "VLLM_ENABLE_CUDA_COMPATIBILITY": "1"}
    assert ep.MEANING["REQUIRE"] != ep.MEANING["DRIVER"]  # the toolkit's refusal is told apart from CUDA's


def test_a_requirement_refusal_on_every_form_is_a_real_answer() -> None:
    rec = _probe(Fake({"pinned": (125, "", REQUIRE_CUDA), "cu129": (125, "", REQUIRE_CUDA)}))
    assert rec["verdict"]["answer"] == "none"


def test_a_busy_or_full_card_is_inconclusive_and_stops_the_probe() -> None:
    """Item 2: another program on the card says nothing about the engine."""
    fake = Fake({"pinned": (1, "", "RuntimeError: CUDA error: all CUDA-capable devices are busy or unavailable")})
    rec = _probe(fake)
    assert rec["verdict"]["answer"] == "inconclusive" and ep.FIX_BUSY in rec["verdict"]["next"]
    assert _pulls(fake) == [PINNED]  # no second image
    assert [t["status"] for t in rec["tests"]] == ["BUSY", "NOT-RUN", "NOT-RUN", "NOT-RUN"]


def test_no_card_given_stops_after_the_first_check() -> None:
    """Item 3: a NO-GPU is the same for every later form; the second image is not pulled."""
    fake = Fake({"pinned": (125, "", NO_RUNTIME)})
    rec = _probe(fake)
    assert _pulls(fake) == [PINNED] and len([c for c in fake.calls if c[1] == "run"]) == 1
    assert rec["verdict"]["answer"] == "inconclusive" and ep.FIX_RUNTIME in rec["verdict"]["fix"]


def test_a_toolkit_that_cannot_reach_the_driver_pulls_nothing_and_does_not_say_reconfigure() -> None:
    """Item 3: the runtime is registered but nvidia-container-cli fails: nothing to download, and `nvidia-ctk runtime
    configure` would not help."""
    fake = Fake({}, cli_rc=1)
    rec = _probe(fake)
    assert _pulls(fake) == []
    assert rec["verdict"]["fix"] == ep.FIX_TOOLKIT and "nvidia-ctk" not in rec["verdict"]["next"]


@pytest.mark.parametrize(
    ("err", "status", "answer", "says"),
    [
        ("no matching manifest for linux/arm64/v8 in the manifest list entries", "NO-BUILD", "none", "Stop here"),
        ("toomanyrequests: You have reached your pull rate limit", "PULL-FAILED", "inconclusive", "docker login"),
        ("write /var/lib/docker/tmp/x: no space left on device", "DISK", "inconclusive", "free at least 30 GB"),
    ],
)
def test_a_failed_download_is_told_apart(err: str, status: str, answer: str, says: str) -> None:
    """Item 3: an image with no Arm build is final for its forms; a rate limit and a full disk are fixable."""
    rec = _probe(Fake({}, pull_rc=1, pull_err=err))
    assert {t["status"] for t in rec["tests"]} == {status}
    assert rec["verdict"]["answer"] == answer and says in rec["verdict"]["next"]


def test_ctrl_c_during_the_pre_checks_is_a_record_not_a_traceback() -> None:
    rec = _probe(Fake({}, interrupt_on="preflight"))
    assert rec["interrupted"] is True and rec["verdict"]["answer"] == "inconclusive"
    assert {t["status"] for t in rec["tests"]} == {"NOT-RUN"}


def test_an_image_already_gone_is_not_a_failed_removal() -> None:
    rec = _probe(Fake({"pinned": (0, line(GOOD), "")}, rm_rc=1, rm_err="Error: No such image: vllm/vllm-openai"))
    assert rec["images"]["pinned"]["removed"] is True and "could not be removed" not in ep.table(rec)


def test_a_dashed_mac_is_scrubbed() -> None:
    assert "00-1b-44-11-3a-b7" not in ep.scrub("eth0 00-1b-44-11-3a-b7 down", names=[])


def test_the_next_step_after_a_pass_names_the_weights() -> None:
    v = ep.verdict(_results(pinned="PASS"))
    assert "step 4, then step 5 (the weights) and step 6" in v["next"]


def test_the_tools_the_owner_runs_with_the_hosts_python_need_nothing_newer_than_3_10() -> None:
    """The IGX runs Ubuntu 22.04 (Python 3.10). `datetime.UTC` is 3.11: `tools.fetch_weights` (it imports
    `tools.pin_model`) and `tools/serving_config.py capture` stopped at import there; checked by hand under 3.10."""
    for rel in ("tools/engine_probe.py", "tools/dgpu48.py", "tools/serving_config.py", "tools/pin_model.py",
                "tools/fetch_weights.py", "tools/security_contact.py", "tools/build_site.py"):  # fmt: skip
        code = "\n".join(ln.split("#", 1)[0] for ln in (ROOT / rel).read_text(encoding="utf-8").splitlines())
        assert "from datetime import UTC" not in code and "datetime.UTC" not in code, rel


# ------------------------------------------------------------------------------- the compiled-op modules' two name forms
FAKE_TORCH = """
__version__ = "0"
class version: cuda = "13.0"
class _T:
    def __matmul__(self, o): return self
    def sum(self): return self
    def item(self): return 262144.0
class cuda:
    is_available = staticmethod(lambda: True)
    get_device_name = staticmethod(lambda i: "stand-in")
    get_device_capability = staticmethod(lambda i: (10, 0))
def ones(*a, **k): return _T()
"""


def _run_check(tmp_path: Path, modules: list[str]) -> tuple[str, dict[str, Any] | None, str]:
    """The check itself (PROBE_PY) in this python3, with a stand-in torch and an engine package holding ``modules``."""
    (tmp_path / "torch.py").write_text(FAKE_TORCH, encoding="utf-8")
    pkg = tmp_path / "vllm"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('__version__ = "0.32.0"\n', encoding="utf-8")
    for m in modules:
        (pkg / f"{m}.py").write_text("", encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(tmp_path)!r})\n" + ep.PROBE_PY],
                       capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    return ep.classify(r.returncode, r.stdout, r.stderr)


@pytest.mark.parametrize("modules", [["_C", "_moe_C"], ["_C_stable_libtorch", "_moe_C_stable_libtorch"]])
def test_the_compiled_ops_pass_by_either_name_form(tmp_path: Path, modules: list[str]) -> None:
    status, probe, _ = _run_check(tmp_path, modules)
    assert status == "PASS" and probe is not None
    assert probe["vllm_ops"] == f"vllm.{modules[0]}" and probe["vllm_moe_ops"] == f"vllm.{modules[1]}"


@pytest.mark.parametrize("modules", [[], ["_C_stable_libtorch"], ["_moe_C"]])
def test_the_probe_fails_when_the_compiled_ops_are_missing(tmp_path: Path, modules: list[str]) -> None:
    status, probe, errors = _run_check(tmp_path, modules)
    assert status == "PARTIAL" and probe is not None and "No module named" in errors


def test_a_result_from_before_the_two_name_forms_still_passes() -> None:
    assert ep.classify(0, "TBPROBE " + json.dumps(GOOD), "")[0] == "PASS"
