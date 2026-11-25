"""H-105, the external review of #1448 at a5297c6 (#639, 2026-11-24): one test (or more) per Medium finding, each
failing at a5297c6, from the review's own reproductions; and the cheap Lows. The Mediums:

* M-1448-1: root makes and fills the slot's scratch folder inside a folder the jobs' user owns: a link planted at the
  slot's name after the old folder is removed must not be followed;
* M-1448-2: BENCH_JOB_HOURS counts from the job being accepted (the gate's mark), not from the runner's start;
* M-1448-3: the example's BENCH_JOB_HOURS covers the longest timeout the bench workflow gives a job;
* M-1448-4: no job on the bench starts after the run was cancelled (``!cancelled()``, not ``always()``);
* M-1448-5: a waiting or running slot joins the egress proxy to its network again (a restarted proxy is on none);
* M-1448-6: the gate compares the job's workflow file with master's file NOW (read by master's current commit at the
  job's start), not with the blob master had when the runner was registered;
* M-1448-7: the claims of the card page and the docstrings match the code.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.bench_ci import egress_proxy, gate, gpu_check, launcher

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-bench-ci.yml"
EXAMPLE = (ROOT / "tools" / "bench_ci" / "settings.example.env").read_text(encoding="utf-8")
HOUR = 3600.0
FILL = {
    "BENCH_REPO": "example-owner/example-repo",
    "BENCH_ENGINE": "/usr/bin/engine",
    "BENCH_SCRATCH": "/srv/ci-scratch",
    "BENCH_SUBNET_PREFIX": "10.213",
    "BENCH_CPU_SLOTS": "1",
    "BENCH_ENGINE_SLOTS": "0",
    "BENCH_GPU_SLOTS": "0",
    "BENCH_CPUS": "4",
    "BENCH_MEMORY": "8g",
    "BENCH_RUNNER_VERSION": "9.9.9",
    "BENCH_RUNNER_SHA256": "a" * 64,
    "BENCH_JOB_HOURS": "6",
}
# a global address built in code (the first host of the first global /8), so no real host's address is written here
PUBLIC_V4 = next(a for a in (ipaddress.IPv4Address(n << 24 | 1) for n in range(1, 224)) if a.is_global)
GPU_ONLY = (
    "BENCH_CI_GPUS",
    "BENCH_RESERVED_GPUS",
    "BENCH_GPU_QUERY",
    "BENCH_GPU_DEVICE",
    "BENCH_GPU_CAP",
    "BENCH_WEIGHTS",
)


def _settings(**over: str) -> launcher.Settings:
    fill = {**FILL, **over}
    lines = []
    for line in EXAMPLE.splitlines():
        key = line.split("=", 1)[0]
        if line.startswith(GPU_ONLY):
            continue
        lines.append(f"{key}={fill[key]}" if key in fill and not line.startswith("#") else line)
    return launcher.parse_settings("\n".join(lines) + "\n")


def _fake_run(ran: list[list[str]]) -> Any:
    def run(args: list[str], **_kw: Any) -> subprocess.CompletedProcess[bytes]:
        ran.append(args)
        return subprocess.CompletedProcess(args, 0)

    return run


# --- M-1448-1 ---------------------------------------------------------------------------------------------------


@pytest.fixture
def minting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    root = tmp_path / "scratch"
    root.mkdir()
    s = _settings(BENCH_SCRATCH=str(root))
    state = tmp_path / "state"
    token = tmp_path / "token"
    token.write_text("tok\n", encoding="utf-8")
    token.chmod(0o600)
    me = pwd.getpwuid(os.getuid())
    monkeypatch.setattr("pwd.getpwnam", lambda _n: me)
    monkeypatch.setattr("os.geteuid", lambda: 0)
    monkeypatch.setattr(launcher, "read_token", lambda _p: "tok")
    monkeypatch.setattr(launcher, "jit_config", lambda *_a: ("CONFIG-X", 7))
    return s, token, state


def test_m1448_1_a_link_planted_at_the_slots_name_after_the_removal_is_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minting: Any
) -> None:
    s, token, state = minting
    victim = tmp_path / "victim"
    victim.mkdir()
    assert launcher.mint(s, "cpu-1", token_file=token, state=state) == 0  # an earlier job's folder is there
    real_rmtree = shutil.rmtree

    def rmtree_then_plant(path: Any, *a: Any, **k: Any) -> None:
        real_rmtree(path, *a, **k)
        Path(path).symlink_to(victim, target_is_directory=True)  # the jobs' user wins the race

    monkeypatch.setattr(shutil, "rmtree", rmtree_then_plant)
    with contextlib.suppress(OSError, RuntimeError):  # refusing is right
        launcher.mint(s, "cpu-1", token_file=token, state=state)
    assert list(victim.iterdir()) == [], "root made or wrote something through the planted link"


def test_m1448_1_a_link_planted_inside_the_new_folder_is_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minting: Any
) -> None:
    """The same race one level down: a link put where a subfolder is about to be made."""
    s, token, state = minting
    victim = tmp_path / "victim"
    victim.mkdir()
    real_mkdir = os.mkdir

    def mkdir_then_plant(path: Any, mode: int = 0o777, *, dir_fd: int | None = None) -> None:
        real_mkdir(path, mode, dir_fd=dir_fd)
        if Path(str(path)).name == "home":  # the next name root makes (by name or by path): a link is put there first
            os.symlink(victim, ".tb-bench", dir_fd=dir_fd)

    monkeypatch.setattr("os.mkdir", mkdir_then_plant)
    with contextlib.suppress(OSError, RuntimeError):
        launcher.mint(s, "cpu-1", token_file=token, state=state)
    assert list(victim.iterdir()) == [], "root made or wrote something through a planted link"


def test_m1448_1_a_subfolder_swapped_for_a_link_after_it_was_made_is_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minting: Any
) -> None:
    """The race between making a subfolder and opening it: the jobs' user replaces it with a link."""
    s, token, state = minting
    victim = tmp_path / "victim"
    victim.mkdir()
    real_mkdir = os.mkdir

    def mkdir_then_swap(path: Any, mode: int = 0o777, *, dir_fd: int | None = None) -> None:
        real_mkdir(path, mode, dir_fd=dir_fd)
        if Path(str(path)).name == ".tb-bench":  # by name or by path, as a5297c6 called it
            os.rmdir(".tb-bench", dir_fd=dir_fd)
            os.symlink(victim, ".tb-bench", dir_fd=dir_fd)

    monkeypatch.setattr("os.mkdir", mkdir_then_swap)
    with contextlib.suppress(OSError, RuntimeError):
        launcher.mint(s, "cpu-1", token_file=token, state=state)
    assert list(victim.iterdir()) == [], "root wrote the job's files through a swapped link"


# --- M-1448-2 and M-1448-5: the run step's wait -----------------------------------------------------------------


def _run_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accepted_at: float, ends_at: float
) -> tuple[bool, list[list[str]]]:
    """Run the slot with a stand-in container accepted at one time and ending at another: (stopped, the commands)."""
    s = _settings()  # the limit is 6 h
    folder = tmp_path / "tb-bench-cpu-1" / ".tb-bench"
    folder.mkdir(parents=True)
    (folder / "runner.jit").write_text("x", encoding="utf-8")
    monkeypatch.setattr(launcher, "scratch_of", lambda _s, _slot: tmp_path / "tb-bench-cpu-1")
    now = [0.0]
    stopped: list[bool] = []
    launched: list[bool] = []
    ended: list[bool] = []
    ran: list[list[str]] = []

    def run(args: list[str], **_kw: Any) -> subprocess.CompletedProcess[bytes]:
        ran.append(args)
        if launched and not ended and args[1:3] == ["rm", "--force"] and args[-1] == "tb-bench-cpu-1":
            stopped.append(True)  # the job's container removed after it started
        return subprocess.CompletedProcess(args, 0)

    class Proc:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            launched.append(True)
            ran.append(["<container started>"])

        def wait(self, timeout: float | None = None) -> int:
            if stopped:
                return 137
            target = ends_at if timeout is None else min(ends_at, now[0] + timeout)
            if now[0] < accepted_at <= target:
                (folder / "started").write_text("", encoding="utf-8")  # what the gate does when it accepts the job
            now[0] = target
            if target >= ends_at:
                ended.append(True)
                return 0
            raise subprocess.TimeoutExpired("engine", timeout or 0)

    monkeypatch.setattr("subprocess.Popen", Proc)
    monkeypatch.setattr("subprocess.run", run)
    monkeypatch.setattr("signal.signal", lambda *_a: None)
    monkeypatch.setattr("time.monotonic", lambda: now[0])
    launcher.run_slot(s, "cpu-1")
    return bool(stopped), ran


def test_m1448_2_a_job_accepted_late_in_the_runners_wait_gets_its_whole_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the runner waited 5 h (the limit is 6 h), then a job of 5 h: it ends at 10 h and is not cut at 6 h
    stopped, _ = _run_slot(tmp_path, monkeypatch, accepted_at=5 * HOUR, ends_at=10 * HOUR)
    assert stopped is False


def test_m1448_2_a_job_that_runs_past_the_limit_after_it_was_accepted_is_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped, _ = _run_slot(tmp_path, monkeypatch, accepted_at=1 * HOUR, ends_at=8 * HOUR)
    assert stopped is True


def test_m1448_2_a_runner_nobody_used_is_recycled_at_the_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stopped, _ = _run_slot(tmp_path, monkeypatch, accepted_at=99 * HOUR, ends_at=99 * HOUR)
    assert stopped is True


def test_m1448_2_the_gate_marks_an_accepted_job_and_only_that(tmp_path: Path) -> None:
    repo, wf, commit, head = "the-owner/the-repo", ".github/workflows/trialbox-bench-ci.yml", "a" * 40, "b" * 40
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"repo": repo, "workflow": wf, "proxy": "10.213.1.2:3128"}), encoding="utf-8")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"repository": {"full_name": repo, "fork": False}}), encoding="utf-8")
    env = {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REPOSITORY": repo,
        "GITHUB_REF": "refs/heads/train/1",
        "GITHUB_WORKFLOW_REF": f"{repo}/{wf}@refs/heads/train/1",
        "GITHUB_WORKFLOW_SHA": commit,
        "GITHUB_EVENT_PATH": str(event),
    }

    def fetch(*_a: str) -> bytes:
        return b"name: x\n"

    def master(*_a: str) -> str:
        return head

    refused = {**env, "GITHUB_EVENT_NAME": "pull_request"}
    assert gate.main(["--job", str(job)], env=refused, fetch=fetch, master=master) == 1
    assert not (tmp_path / "started").exists()
    assert gate.main(["--job", str(job)], env=env, fetch=fetch, master=master) == 0
    assert (tmp_path / "started").exists()


def test_m1448_5_a_waiting_slot_joins_the_proxy_to_its_network_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, ran = _run_slot(tmp_path, monkeypatch, accepted_at=10, ends_at=HOUR)
    after_start = ran[ran.index(["<container started>"]) :]
    joins = [a for a in after_start if a[1:3] == ["network", "connect"]]
    assert len(joins) >= 2, "the proxy is never joined to the slot's network again while the job waits or runs"
    proxy_ip = launcher.subnet(_settings(), "cpu-1")[1]
    assert joins[0] == [
        "/usr/bin/engine",
        "network",
        "connect",
        "--ip",
        proxy_ip,
        "tb-bench-job-cpu-1",
        "tb-bench-proxy",
    ]


# --- M-1448-3 ---------------------------------------------------------------------------------------------------


def test_m1448_3_the_example_job_hours_cover_the_longest_bench_job() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    longest = max(
        int(str(job["timeout-minutes"]).split()[0])
        for job in workflow["jobs"].values()
        if "self-hosted" in job["runs-on"]
    )
    m = re.search(r"^BENCH_JOB_HOURS=(\d+)$", EXAMPLE, re.M)
    assert m is not None
    assert int(m.group(1)) * 60 >= longest, f"BENCH_JOB_HOURS={m.group(1)} stops a {longest}-minute job early"


# --- M-1448-4 ---------------------------------------------------------------------------------------------------


def test_m1448_4_no_job_on_the_bench_starts_after_a_cancel() -> None:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    for name, job in jobs.items():
        if "self-hosted" in job["runs-on"]:
            assert "always()" not in str(job.get("if", "")), f"{name}: always() runs it after the run is cancelled"
    assert "!cancelled()" in jobs["full-set"]["if"]
    assert "always()" in jobs["bench-times"]["if"]  # the hosted times table is read after a cancel too


# --- M-1448-6 ---------------------------------------------------------------------------------------------------

REPO, WF, COMMIT = "the-owner/the-repo", ".github/workflows/trialbox-bench-ci.yml", "a" * 40
ENV = {
    "GITHUB_EVENT_NAME": "push",
    "GITHUB_REPOSITORY": REPO,
    "GITHUB_REF": "refs/heads/train/9",
    "GITHUB_WORKFLOW_REF": f"{REPO}/{WF}@refs/heads/train/9",
    "GITHUB_WORKFLOW_SHA": COMMIT,
}
EVENT = {"repository": {"full_name": REPO, "fork": False}}
OLD, NEW = b"name: old\n", b"name: new\n"


def _files(job_file: bytes, master_file: bytes) -> Any:
    """The code host as the gate reads it: the job's commit has one file, master's current commit another."""

    def fetch(_proxy: str, _repo: str, commit: str, _path: str) -> bytes:
        return job_file if commit == COMMIT else master_file

    return fetch


def test_m1448_6_a_train_carrying_masters_new_file_runs_on_a_runner_minted_before_the_change() -> None:
    """Master's file changed after the runner was registered: the job's file is master's now, so it runs."""
    facts = {"repo": REPO, "workflow": WF, "proxy": "10.213.1.2:3128", "workflow_blob": gate.blob_sha(OLD)}
    assert gate.decide(ENV, EVENT, facts, _files(NEW, NEW), master=lambda *_a: "f" * 40) == []


def test_m1448_6_a_branch_still_on_the_old_file_is_refused_whatever_the_runner_saw() -> None:
    facts = {"repo": REPO, "workflow": WF, "proxy": "10.213.1.2:3128", "workflow_blob": gate.blob_sha(OLD)}
    got = gate.decide(ENV, EVENT, facts, _files(OLD, NEW), master=lambda *_a: "f" * 40)
    assert len(got) == 1 and "is not master's" in got[0]


def test_m1448_6_masters_commit_is_read_from_the_code_hosts_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Master's current commit comes from the code host's ref list (by the proxy), never from the job."""
    pkt = (
        b"001e# service=git-upload-pack\n0000"
        b"0099" + b"c" * 40 + b" HEAD\x00multi_ack symref=HEAD:refs/heads/master agent=x\n"
        b"0043" + b"e" * 40 + b" refs/heads/master-old\n"  # a name that starts as master's: not master
        b"003f" + b"d" * 40 + b" refs/heads/master\n0000"
    )
    assert gate.master_from_refs(pkt) == "d" * 40
    with pytest.raises(RuntimeError, match="no master"):
        gate.master_from_refs(b"001e# service=git-upload-pack\n0000")


def test_m1448_6_the_mint_step_no_longer_reads_masters_file() -> None:
    """The host's mint no longer depends on master holding the file (no 404 loop before the merge)."""
    assert not hasattr(launcher, "master_blob")
    with pytest.raises(ValueError, match="runner endpoints"):
        launcher.api("GET", f"/repos/{REPO}/contents/{WF}?ref=master", "t")


# --- M-1448-7 ---------------------------------------------------------------------------------------------------

PAGE = (ROOT / "docs" / "handover" / "bench-ci-runner-h105-2026-11-24.md").read_text(encoding="utf-8")


def test_m1448_7_the_card_page_says_what_a_lane_push_gets() -> None:
    assert "a lane push gets the unit shards, the integration run, the GPU suites and the box rehearsal" not in PAGE
    assert "A lane push gets the unit shards and the integration run" in PAGE
    for path in (".github/workflows/trialbox-bench-ci.yml", ".github/actionlint.yaml", "trialbox/docs/RUNBOOK.md",
                 "trialbox/Makefile", "trialbox/tests/unit/test_ci_jobs_inside_ninety.py",
                 "trialbox/tests/unit/test_image_config_scans.py"):  # fmt: skip
        assert path in PAGE.split("## Files outside the card", 1)[1].split("\n## ", 1)[0], path


def test_m1448_7_the_docstrings_say_what_their_lists_now_hold() -> None:
    ninety = (ROOT / "tests" / "unit" / "test_ci_jobs_inside_ninety.py").read_text(encoding="utf-8")
    assert "The list may only shrink" not in ninety and "grows only by a ruling" in ninety
    scans = (ROOT / "tests" / "unit" / "test_image_config_scans.py").read_text(encoding="utf-8")
    report = re.search(r"^HADOLINT_REPORT := (.*?)(?<!\\)\n", (ROOT / "Makefile").read_text(), re.M | re.S)
    assert report is not None
    count = len(report.group(1).replace("\\\n", " ").split())
    words = {5: "five", 6: "six", 7: "seven"}
    assert re.search(rf"\b{words[count]} it lints report-only", scans), count


def test_m1448_7_the_rulings_the_page_cites_are_the_threads() -> None:
    """The ids the lead checked against the thread (#639): the card, item 8, the review, the weights, the ninety."""
    for cid in ("7117447272", "7117870645", "7118916382", "7118754451", "7119929149"):
        assert cid in PAGE, cid
    ninety = (ROOT / "tests" / "unit" / "test_ci_jobs_inside_ninety.py").read_text(encoding="utf-8")
    assert "7119929149" in ninety


# --- the cheap Lows ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("addr", "ok"),
    [
        ("64:ff9b::a00:1", False),  # NAT64 of 10.0.0.1
        (str(ipaddress.IPv6Address(int(ipaddress.ip_address("64:ff9b::")) | int(PUBLIC_V4))), True),  # NAT64, public
        ("::a00:1", False),  # IPv4-compatible 10.0.0.1
        ("::ffff:10.0.0.1", False),  # IPv4-mapped
        ("fec0::1", False),  # site-local
    ],
)
def test_l1448_8_a_wrapped_private_address_is_not_public(addr: str, ok: bool) -> None:
    assert egress_proxy.public(addr) is ok


def test_l1448_9_the_proxy_tries_the_next_address(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    tried: list[str] = []

    async def opener(host: str, port: int, **_kw: Any) -> Any:
        tried.append(host)
        if host.startswith("2001:db8"):
            raise OSError("no route")
        return ("reader", "writer")

    monkeypatch.setattr("asyncio.open_connection", opener)
    got: Any = asyncio.run(egress_proxy.connect_any(["2001:db8::1", "192.0.2.10"]))  # documentation addresses
    assert got == ("reader", "writer") and tried == ["2001:db8::1", "192.0.2.10"]


@pytest.mark.parametrize(
    ("over", "words"),
    [
        ({"BENCH_SUBNET_PREFIX": "8.8"}, "private"),
        ({"BENCH_SUBNET_PREFIX": "127.0"}, "private"),
        ({"BENCH_SUBNET_PREFIX": "169.254"}, "private"),
        ({"BENCH_SUBNET_PREFIX": "172.32"}, "private"),
        ({"BENCH_JOB_HOURS": "0"}, "at least 1"),
        ({"BENCH_CPUS": "²"}, "whole number"),
    ],
)
def test_l1448_10_settings_the_launcher_cannot_work_with_are_refused(over: dict[str, str], words: str) -> None:
    with pytest.raises(launcher.SettingsError, match=words):
        _settings(**over)
    for good in ("10.213", "172.16", "172.31", "192.168"):
        assert _settings(BENCH_SUBNET_PREFIX=good)["BENCH_SUBNET_PREFIX"] == good


INSTALL = (ROOT / "tools" / "bench_ci" / "install.sh").read_text(encoding="utf-8")


def test_l1448_11_an_interrupted_token_step_leaves_no_copy(tmp_path: Path) -> None:
    """Run, not read (1448-23): a signal right after the copy is written leaves no copy and ends the step."""
    at = next(i for i, line in enumerate(TOKEN_LINES) if 'printf \'%s\\n\' "$tok" > "$tmp"' in line)
    got, etc = _token_step(tmp_path, [*TOKEN_LINES[: at + 1], "  kill -s TERM $$", *TOKEN_LINES[at + 1 :]])
    assert got.returncode != 0 and [p.name for p in etc.iterdir()] == []


def test_l1448_12_the_page_says_when_to_change_the_token() -> None:
    page = (ROOT / "docs" / "runbook" / "13-bench-ci-runner.md").read_text(encoding="utf-8")
    assert "a slot that is running a job is restarted too" in page


def test_l1448_13_a_container_that_never_took_a_job_fails_the_run_step_and_the_handler_comes_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _settings()
    folder = tmp_path / "tb-bench-cpu-1" / ".tb-bench"
    folder.mkdir(parents=True)
    (folder / "runner.jit").write_text("x", encoding="utf-8")
    monkeypatch.setattr(launcher, "scratch_of", lambda _s, _slot: tmp_path / "tb-bench-cpu-1")
    order: list[str] = []

    class Proc:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            order.append("container")

        def wait(self, timeout: float | None = None) -> int:
            return 125  # the engine could not start it

    def run(args: list[str], **_kw: Any) -> subprocess.CompletedProcess[bytes]:
        if args[1:3] == ["network", "create"]:
            order.append("network")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("subprocess.Popen", Proc)
    monkeypatch.setattr("subprocess.run", run)
    monkeypatch.setattr("signal.signal", lambda *_a: order.append("handler"))
    assert launcher.run_slot(s, "cpu-1") == 125
    assert order.index("handler") < order.index("network") < order.index("container")


def test_l1448_17_an_early_cancel_writes_no_huge_wall_time() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "s=$(( $(date +%s) - TB_BENCH_T0 ))" not in text
    jobs = yaml.safe_load(text)["jobs"]
    # the integrator's condition (7129949024): the six bench jobs by name, so a dropped one cannot pass
    timed = {n for n, j in jobs.items() for st in j.get("steps", []) if st.get("name") == "Wall time"}
    assert timed == {"unit-shard", "integration", "gpu-suites", "full-set", "rehearse-box", "rehearse-gpu-box"}
    assert text.count("s=$(( $(date +%s) - ${TB_BENCH_T0:-$(date +%s)} ))") == 6


def test_l1448_18_the_install_stops_before_any_change_without_a_running_service_manager() -> None:
    body = INSTALL[INSTALL.index("prerequisites() {") : INSTALL.index("\n}\n", INSTALL.index("prerequisites() {"))]
    assert "[ -d /run/systemd/system ] || die" in body
    assert body.index("[ -d /run/systemd/system ]") < body.index("chown root:root")


def test_l1448_19_the_switch_compares_without_case_as_the_code_host_does() -> None:
    from tests.unit import test_bench_ci_workflow_h105 as wf

    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["unit-shard"]
    ctx = {"github.event_name": "push", "github.ref": "refs/heads/train/1", "vars.TB_BENCH_CI": "ON"}
    assert wf._evaluate(wf._norm(job["if"]), ctx) is True


# --- the re-review of #1448 at 0624f4f: 1448-20 (Medium) and the Lows ------------------------------------------

TOKEN_BODY = re.search(r"^cmd_token\(\) \{\n(.*?)^\}\n", INSTALL, re.M | re.S)
assert TOKEN_BODY is not None
TOKEN_LINES = TOKEN_BODY.group(1).splitlines()
TOKEN_FIRST = next(i for i, line in enumerate(TOKEN_LINES) if '[ -n "$tok" ]' in line) + 1
TOKEN_LAST = next(i for i, line in enumerate(TOKEN_LINES) if line.lstrip().startswith("say "))
TOKEN_PRELUDE = """set -euo pipefail
umask 022
ETC="$1"; TOKEN="$ETC/token"
die() { echo "die: $*" >&2; exit 1; }
say() { echo "SAY: $*"; }
need_root() { :; }
chown() { [ -e "${@: -1}" ]; }
start_units() { echo START_UNITS; }
slots() { echo tb-bench-runner@cpu-1.service; }
systemctl() { echo "SYSTEMCTL $*"; }
"""


def _token_step(tmp_path: Path, lines: list[str]) -> tuple[subprocess.CompletedProcess[str], Path]:
    """The real cmd_token body, run with stand-ins for root's commands (the review's harness)."""
    etc = tmp_path / "etc"
    etc.mkdir()
    etc.chmod(0o750)
    script = tmp_path / "run.sh"
    script.write_text(TOKEN_PRELUDE + "cmd_token() {\n" + "\n".join(lines) + "\n}\ncmd_token\n", encoding="utf-8")
    args = ["bash", str(script), str(etc)]
    got = subprocess.run(args, check=False, input="tok-for-a-test\n", text=True, capture_output=True)
    return got, etc


@pytest.mark.parametrize("sig", ["INT", "TERM", "HUP"])
@pytest.mark.parametrize("at", range(TOKEN_FIRST, TOKEN_LAST))
def test_m1448_20_a_signal_in_the_token_step_ends_it(tmp_path: Path, sig: str, at: int) -> None:
    """A signal after any line of the token step ends it: it never says the token is kept, never restarts the slots,
    leaves no temporary copy, and no copy of the token is ever readable by others."""
    lines = [*TOKEN_LINES[: at + 1], f"  kill -s {sig} $$", *TOKEN_LINES[at + 1 :]]
    got, etc = _token_step(tmp_path, lines)
    assert got.returncode != 0, f"a {sig} after {TOKEN_LINES[at].strip()!r} let the step go on:\n{got.stdout}"
    assert "kept" not in got.stdout and "START_UNITS" not in got.stdout, got.stdout
    assert [p.name for p in etc.iterdir() if p.name.startswith(".token.")] == []
    token = etc / "token"
    if token.exists():
        assert stat.S_IMODE(token.stat().st_mode) == 0o600


def test_m1448_20_without_a_signal_the_token_is_kept_root_only(tmp_path: Path) -> None:
    got, etc = _token_step(tmp_path, TOKEN_LINES)
    assert got.returncode == 0 and "kept" in got.stdout, got.stdout + got.stderr
    assert (etc / "token").read_text(encoding="utf-8") == "tok-for-a-test\n"
    assert stat.S_IMODE((etc / "token").stat().st_mode) == 0o600


def test_m1448_20_a_failed_move_is_a_failure_not_a_kept_token(tmp_path: Path) -> None:
    lines = [ln.replace('mv -f "$tmp" "$TOKEN"', "false") for ln in TOKEN_LINES]
    got, _ = _token_step(tmp_path, lines)
    assert got.returncode != 0 and "kept" not in got.stdout and "START_UNITS" not in got.stdout


def test_m1448_21_a_translated_private_address_is_not_public() -> None:
    """1448-21: the IPv4-translated form (::ffff:0:0:0/96) is judged by the IPv4 address inside, as NAT64 is."""
    prefix = int(ipaddress.ip_address("::ffff:0:0:0"))
    private = next(a for a in (ipaddress.IPv4Address(n << 24 | 1) for n in range(1, 224)) if a.is_private)
    assert egress_proxy.public(str(ipaddress.IPv6Address(prefix | int(private)))) is False
    assert egress_proxy.public(str(ipaddress.IPv6Address(prefix | int(PUBLIC_V4)))) is True


def test_m1448_22_the_install_refuses_a_scratch_folder_under_a_folder_others_can_change() -> None:
    """1448-22: no folder above the scratch folder may be a link, not root's, or writable by others."""
    body = INSTALL[INSTALL.index("install_files() {") : INSTALL.index("\n}\n", INSTALL.index("install_files() {"))]
    assert 'while [ "$up" != / ]; do' in body and '[ ! -L "$up" ]' in body
    assert '[ "$(stat -c %u "$up")" = 0 ]' in body and "& 022" in body
    flags = (ROOT / "tools" / "bench_ci" / "launcher.py").read_text(encoding="utf-8")
    assert "os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)" in flags


def test_m1448_22_the_scratch_root_as_a_link_is_refused(tmp_path: Path, minting: Any) -> None:
    s, token, state = minting
    real = Path(s["BENCH_SCRATCH"])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    real.rmdir()
    real.symlink_to(elsewhere, target_is_directory=True)
    with contextlib.suppress(OSError, RuntimeError):
        launcher.mint(s, "cpu-1", token_file=token, state=state)
    assert list(elsewhere.iterdir()) == [], "root made the slot's folder through a scratch root that is a link"


def test_m1448_24_an_idle_runner_recycled_at_the_limit_is_no_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codes: list[int] = []
    real = launcher.run_slot

    def run_slot(s: launcher.Settings, slot: str) -> int:
        codes.append(real(s, slot))
        return codes[-1]

    monkeypatch.setattr(launcher, "run_slot", run_slot)
    stopped, _ = _run_slot(tmp_path, monkeypatch, accepted_at=99 * HOUR, ends_at=99 * HOUR)
    assert stopped is True and codes == [0]


def test_m1448_25_no_real_address_in_the_bench_tests() -> None:
    """The repository rule: no host's address in a committed file; the tests use documentation ranges, wrap a private
    one, or build a public one in code (an address the proxy would reach is a real host's)."""
    for f in sorted((ROOT / "tests" / "unit").glob("test_bench_ci_*_h105.py")):
        text = f.read_text(encoding="utf-8")
        for addr in re.findall(r"(?<![\w.:])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])", text):
            ip = ipaddress.ip_address(addr)
            assert not egress_proxy.public(addr) or ip in ipaddress.ip_network("192.0.2.0/24"), (f.name, addr)
        for addr in re.findall(r"(?<![\w:])([0-9a-f]{1,4}(?::[0-9a-f]{0,4}){2,7})(?![\w:])", text):
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            assert not egress_proxy.public(addr) or ip in ipaddress.ip_network("2001:db8::/32"), (f.name, addr)


def test_l1448_14_the_example_says_no_upload_host_only_as_the_proxy_can_tell() -> None:
    assert "no upload host, no user-content wildcard" not in EXAMPLE
    assert "no upload host the proxy can tell from a download host" in EXAMPLE


# --- H-105b: the Lows of the review of #1448 at bfc1408 (7126706872) ------------------------------------------


@pytest.mark.parametrize("sig", ["INT", "TERM", "HUP"])
@pytest.mark.parametrize("at", range(TOKEN_FIRST, len(TOKEN_LINES)))
def test_1448_26_a_signal_says_whether_the_token_was_kept(tmp_path: Path, sig: str, at: int) -> None:
    """A signal after any line, the move included: the step says what is true (kept, or not), never the other."""
    got, etc = _token_step(tmp_path, [*TOKEN_LINES[: at + 1], f"  kill -s {sig} $$", *TOKEN_LINES[at + 1 :]])
    assert got.returncode != 0
    token = etc / "token"
    kept = token.exists() and token.read_text(encoding="utf-8") == "tok-for-a-test\n"
    if kept:  # moved into place: the step must never say otherwise
        assert "no token was kept" not in got.stderr and "the new token is kept" in got.stderr, got.stderr
    else:
        assert "kept" not in got.stdout and "the new token is kept" not in got.stderr, got.stdout + got.stderr
    assert [p.name for p in etc.iterdir() if p.name.startswith(".token.")] == []


@pytest.mark.parametrize("step", ['chown root:root "$tmp"', 'chmod 0600 "$tmp"', 'mv -f "$tmp" "$TOKEN"'])
def test_1448_27_any_failed_step_of_the_keep_is_a_failure(tmp_path: Path, step: str) -> None:
    """A failed chown or chmod (which set -e ignores inside a list), not only a failed move, ends the step."""
    lines = [ln.replace(step, "false") for ln in TOKEN_LINES]
    assert lines != TOKEN_LINES
    got, etc = _token_step(tmp_path, lines)
    assert got.returncode != 0 and "kept" not in got.stdout and "START_UNITS" not in got.stdout, got.stdout
    assert [p.name for p in etc.iterdir() if p.name.startswith(".token.")] == []


LOOP = re.search(r'^  local up="\$scratch"\n(.*?^  done\n)', INSTALL, re.M | re.S)


def _scratch_loop(scratch: Path) -> subprocess.CompletedProcess[str]:
    """install_files' check of the folders above the scratch folder, run as written (1448-27: not read as text)."""
    assert LOOP is not None
    script = 'set -euo pipefail\ndie() { echo "die: $*" >&2; exit 1; }\nscratch="$1"\n'
    script += '  local_up() {\n  local up="$scratch"\n' + LOOP.group(1) + "}\nlocal_up\necho FOLDERS-OK\n"
    return subprocess.run(["bash", "-c", script, "loop", str(scratch)], check=False, capture_output=True, text=True)


def test_1448_27_the_scratch_check_refuses_a_folder_others_can_change(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o1777)  # a shared sticky folder, as the system's temporary folders are
    got = _scratch_loop(shared / "ci-scratch")
    assert got.returncode != 0 and "must be root's, not a link, and writable by root only" in got.stderr
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    assert _scratch_loop(link / "ci-scratch").returncode != 0  # a link above it


def _scratch_loop_on(scratch: Path, top: Path, owners: dict[str, tuple[int, str]]) -> subprocess.CompletedProcess[str]:
    """The same loop, on a folder chain the test makes: ``stat`` answers each folder's owner and mode from ``owners``
    (the test's own facts, whatever account it runs as), and ``dirname`` of ``top`` is ``/``, so no folder of the host
    above the chain is read (``/`` itself is never a link)."""
    assert LOOP is not None
    facts = "".join(f'    "{path}") answer {uid} {mode} "$2" ;;\n' for path, (uid, mode) in owners.items())
    stand_ins = (
        'answer() { if [ "$3" = %u ]; then echo "$1"; else echo "$2"; fi; }\n'
        f'stat() {{ case "$3" in\n{facts}    *) echo "stat: no stand-in for $3" >&2; return 1 ;;\n  esac; }}\n'
        f'dirname() {{ if [ "$1" = "{top}" ]; then echo /; else command dirname "$1"; fi; }}\n'
    )
    script = 'set -euo pipefail\ndie() { echo "die: $*" >&2; exit 1; }\nscratch="$1"\n' + stand_ins
    script += '  local_up() {\n  local up="$scratch"\n' + LOOP.group(1) + "}\nlocal_up\necho FOLDERS-OK\n"
    return subprocess.run(["bash", "-c", script, "loop", str(scratch)], check=False, capture_output=True, text=True)


def test_1448_27_the_scratch_check_takes_a_folder_under_roots_own_folders(tmp_path: Path) -> None:
    """Every folder above <root>/usr/share/<name> is root's and written by root only: the test makes the chain and
    says so itself (the integrator's ruling 7157261830: a test sets what it depends on, the account it runs as too)."""
    top = tmp_path / "root"
    share = top / "usr" / "share"
    share.mkdir(parents=True)
    owners = {str(share): (0, "755"), str(top / "usr"): (0, "755"), str(top): (0, "755"), "/": (0, "755")}
    got = _scratch_loop_on(share / "tb-bench-ci-scratch", top, owners)
    assert got.returncode == 0 and "FOLDERS-OK" in got.stdout, got.stderr


def _cards_tool(tmp_path: Path, busy_reads: int, uuids: tuple[str, ...] = ("GPU-4", "GPU-5")) -> Path:
    """A stand-in for the card query tool: the first ``busy_reads`` answers show card GPU-4 busy, then free."""
    count = tmp_path / "reads"
    count.write_text("0", encoding="utf-8")
    tool = tmp_path / "cardquery"
    rows = "\n".join(f'echo "{i}, {u}, ${{mem{i}}}, 0"' for i, u in enumerate(uuids))
    tool.write_text(
        "#!/bin/sh\n"
        f'n=$(cat "{count}"); echo $((n + 1)) > "{count}"\n'
        f'mem0=3; [ "$n" -lt {busy_reads} ] && mem0=90000\n'
        "mem1=3\n" + rows + "\n",
        encoding="utf-8",
    )
    tool.chmod(0o755)
    return tool


def _card_file(tmp_path: Path, tool: Path, wait: int) -> Path:
    spec = {"profile": "gpu", "tool": str(tool), "uuids": ["GPU-4", "GPU-5"], "cap_mib": 1024, "cap_util": 5,
            "wait_seconds": wait}  # fmt: skip
    job = tmp_path / "job.json"
    job.write_text(json.dumps(spec), encoding="utf-8")
    return job


def test_1448_15_a_gpu_job_waits_for_busy_cards_and_starts_when_they_are_free(tmp_path: Path) -> None:
    slept: list[float] = []
    job = _card_file(tmp_path, _cards_tool(tmp_path, busy_reads=3), wait=1800)
    assert gpu_check.main(["--in-job", str(job)], sleep=slept.append) == 0
    assert slept == [gpu_check.POLL_SECONDS] * 3


def test_1448_15_a_gpu_job_refuses_when_the_cards_stay_busy_past_the_wait(tmp_path: Path) -> None:
    slept: list[float] = []
    job = _card_file(tmp_path, _cards_tool(tmp_path, busy_reads=10_000), wait=120)
    assert gpu_check.main(["--in-job", str(job)], sleep=slept.append) == 1
    assert sum(slept) == 120


def test_1448_15_the_wrong_cards_are_refused_at_once_without_waiting(tmp_path: Path) -> None:
    slept: list[float] = []
    job = _card_file(tmp_path, _cards_tool(tmp_path, busy_reads=0, uuids=("GPU-4", "GPU-9")), wait=1800)
    assert gpu_check.main(["--in-job", str(job)], sleep=slept.append) == 1
    assert slept == []


def test_1448_15_the_launcher_gives_gpu_jobs_a_wait() -> None:
    assert launcher.GPU_WAIT_SECONDS > 0
    source = (ROOT / "tools" / "bench_ci" / "launcher.py").read_text(encoding="utf-8")
    assert '"wait_seconds": GPU_WAIT_SECONDS' in source
