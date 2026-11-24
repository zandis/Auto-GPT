"""H-105: the bench host's runner, in the repository's part (the host's part is the walk's install and verify).

The harms: a job that escapes its container reaches the owner's data and keys; a leaked token lets another machine
join as a runner. These tests hold the launcher's container arguments (no engine socket, no host folder but the job's
scratch, read-only where it can be, the job's own non-root user, the internal network), the CI cards' check with a
stand-in for the card query tool, the egress proxy's allow-list, and the install script's token and removal paths.
Nothing here starts a container or calls the code host."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import pwd
import re
import signal
import stat
import subprocess
from pathlib import Path
from typing import Any, ClassVar

import pytest

from tools.bench_ci import egress_proxy, gpu_check, launcher

ROOT = Path(__file__).resolve().parents[2]
BENCH_CI = ROOT / "tools" / "bench_ci"
EXAMPLE = (BENCH_CI / "settings.example.env").read_text(encoding="utf-8")
INSTALL = (BENCH_CI / "install.sh").read_text(encoding="utf-8")
RUNNER_UNIT = (BENCH_CI / "tb-bench-runner@.service").read_text(encoding="utf-8")
PROXY_UNIT = (BENCH_CI / "tb-bench-proxy.service").read_text(encoding="utf-8")
DOCKERFILE = (BENCH_CI / "runner.Dockerfile").read_text(encoding="utf-8")
ENTRYPOINT = (BENCH_CI / "entrypoint.sh").read_text(encoding="utf-8")

pytestmark = pytest.mark.nodb

FILLED = {
    "BENCH_REPO": "example-owner/example-repo",
    "BENCH_ENGINE": "/usr/bin/engine",
    "BENCH_SCRATCH": "/srv/ci-scratch",
    "BENCH_SUBNET_PREFIX": "10.213",
    "BENCH_CPU_SLOTS": "4",
    "BENCH_ENGINE_SLOTS": "1",
    "BENCH_GPU_SLOTS": "1",
    "BENCH_CPUS": "16",
    "BENCH_MEMORY": "64g",
    "BENCH_RUNNER_VERSION": "9.9.9",
    "BENCH_RUNNER_SHA256": "a" * 64,
    "BENCH_CI_GPUS": "4,5",
    "BENCH_RESERVED_GPUS": "1,2,3",
    "BENCH_GPU_QUERY": "/usr/bin/cardquery",
    "BENCH_GPU_DEVICE": "vendor.example/gpu",
    "BENCH_GPU_CAP_MIB": "1024",
    "BENCH_GPU_CAP_UTIL": "5",
    "BENCH_WEIGHTS": "/srv/weights",
}
CI_CARDS = [4, 5]
# global addresses built in code, so no real host's address is written here (the repository rule; review 1448-25)
PUBLIC_V4 = next(a for a in (ipaddress.IPv4Address(n << 24 | 1) for n in range(1, 224)) if a.is_global)
PUBLIC_V6 = ipaddress.IPv6Address(0x2A00 << 112 | 1)
RESERVED = [1, 2, 3]


def _filled(**over: str) -> str:
    values = {**FILLED, **over}
    out = []
    for line in EXAMPLE.splitlines():
        key = line.split("=", 1)[0]
        out.append(f"{key}={values[key]}" if key in values and "=" in line and not line.startswith("#") else line)
    return "\n".join(out) + "\n"


def _settings(**over: str) -> launcher.Settings:
    return launcher.parse_settings(_filled(**over))


SCRATCH = Path("/srv/ci-scratch/tb-bench-cpu-1")
HOST_HOME = re.compile(r"(?<![\w.-])/(home|root)\b")  # a host's home folder (the job's own is /scratch/home)


def _fake_run(ran: list[list[str]]) -> Any:
    """A stand-in for subprocess.run that records each command and answers 0."""

    def run(args: list[str], **_kw: Any) -> subprocess.CompletedProcess[bytes]:
        ran.append(args)
        return subprocess.CompletedProcess(args, 0)

    return run


def _values(args: list[str], flag: str) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a == flag]


def _args(profile: str, slot: str = "cpu-1") -> list[str]:
    return launcher.container_args(_settings(), profile, f"tb-bench-{slot}", SCRATCH, slot)


# --- the settings file ------------------------------------------------------------------------------------------


def test_the_example_holds_placeholders_only_and_is_refused_as_it_is() -> None:
    with pytest.raises(launcher.SettingsError, match="placeholder"):
        launcher.parse_settings(EXAMPLE)
    # no host detail of the bench host: no address, no home folder, no user's name; the repository is a placeholder
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", EXAMPLE)
    assert "/home/" not in EXAMPLE and "~" not in EXAMPLE
    assert "BENCH_REPO=<owner>/<repository>" in EXAMPLE
    assert "BENCH_RESERVED_GPUS=1," in EXAMPLE  # the walk's card is kept from the first line on
    assert set(re.findall(r"^(BENCH_[A-Z_0-9]+)=", EXAMPLE, re.M)) == launcher.KEYS


def test_the_allow_list_names_hosts_not_wildcards_and_no_upload_host() -> None:
    """F4: no storage wildcard, no user-content wildcard, no upload host; the one suffix is the job service's."""
    allow = next(ln for ln in EXAMPLE.splitlines() if ln.startswith("BENCH_ALLOW_HOSTS=")).split("=", 1)[1]
    exact, suffixes = egress_proxy.parse_allow(allow)
    assert suffixes == (".actions.githubusercontent.com",)
    assert not any(h.endswith(".blob.core.windows.net") and not h.startswith("productionresultssa") for h in exact)
    assert "uploads.github.com" not in exact and "githubusercontent.com" not in exact
    assert not any(s in (".githubusercontent.com", ".github.com", ".blob.core.windows.net") for s in suffixes)


def test_filled_settings_are_read() -> None:
    s = _settings()
    assert s["BENCH_LABEL"] == "tb-bench" and s.num("BENCH_GPU_SLOTS") == 1
    # the CI cards are shared by several GPU jobs at once (the owner's ruling of 2026-11-24, item 3)
    assert _settings(BENCH_GPU_SLOTS="3").num("BENCH_GPU_SLOTS") == 3


@pytest.mark.parametrize(
    ("over", "words"),
    [
        ({"BENCH_CI_GPUS": "1,4"}, "keeps"),  # the walk's card
        ({"BENCH_CI_GPUS": "3,4"}, "keeps"),  # a card of the bench
        ({"BENCH_CI_GPUS": ""}, "a GPU slot needs"),
        ({"BENCH_WEIGHTS": ""}, "a GPU slot needs"),
        ({"BENCH_WEIGHTS": "weights"}, "absolute"),
        ({"BENCH_RESERVED_GPUS": "2,3"}, "card 1"),
        ({"BENCH_GPU_CAP_MIB": "lots"}, "whole number"),
        ({"BENCH_ENGINE": "engine"}, "absolute"),
        ({"BENCH_GPU_QUERY": "cardquery"}, "absolute"),
        ({"BENCH_RUNNER_SHA256": "abc"}, "64 hex"),
        ({"BENCH_CPUS": "many"}, "whole number"),
        ({"BENCH_SUBNET_PREFIX": "10.213.0"}, "a.b"),
        ({"BENCH_ENGINE_SLOTS": "50"}, "at most 49"),
    ],
)
def test_settings_that_would_share_a_card_or_guess_a_path_are_refused(over: dict[str, str], words: str) -> None:
    with pytest.raises(launcher.SettingsError, match=words):
        _settings(**over)


def test_an_unknown_or_repeated_key_is_refused() -> None:
    with pytest.raises(launcher.SettingsError, match="not a known"):
        launcher.parse_settings(_filled() + "BENCH_HOST_NETWORK=1\n")
    with pytest.raises(launcher.SettingsError, match="twice"):
        launcher.parse_settings(_filled() + "BENCH_CPUS=2\n")


def test_the_settings_file_must_be_roots(tmp_path: Path) -> None:
    f = tmp_path / "settings.env"
    f.write_text(_filled(), encoding="utf-8")
    if os.getuid() != 0:
        with pytest.raises(launcher.SettingsError, match="owned by root"):
            launcher.read_settings(f)
    f.chmod(0o666)
    with pytest.raises(launcher.SettingsError, match="root"):
        launcher.read_settings(f)


def test_the_token_file_must_be_the_root_steps_own_and_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "token"
    f.write_text("tok-for-a-test\n", encoding="utf-8")
    f.chmod(0o640)
    with pytest.raises(launcher.SettingsError, match="mode 0600"):
        launcher.read_token(f)
    f.chmod(0o600)
    assert launcher.read_token(f) == "tok-for-a-test"
    monkeypatch.setattr("os.geteuid", lambda: f.stat().st_uid + 1)  # another user's file: refused
    with pytest.raises(launcher.SettingsError, match="reading user's"):
        launcher.read_token(f)
    monkeypatch.undo()
    f.write_text("two tokens\n", encoding="utf-8")
    with pytest.raises(launcher.SettingsError, match="more than one"):
        launcher.read_token(f)


# --- the job container's arguments ------------------------------------------------------------------------------


@pytest.mark.parametrize("profile", launcher.PROFILES)
def test_no_profile_sees_a_socket_a_home_the_host_network_or_any_folder_but_its_own(profile: str) -> None:
    args = _args(profile)
    text = " ".join(args)
    assert args[0] == "/usr/bin/engine" and args[1] == "run" and args[-1] == "localhost/tb-bench-runner:1"
    assert "--rm" in args and "--pull=never" in args
    # host folders: this job's scratch folder; a GPU job also the weights, read-only
    mounts = [a for a in args if a in ("--volume", "-v", "--mount")]
    want = [f"{SCRATCH}:/scratch:rw"] + (["/srv/weights:/weights:ro"] if profile == "gpu" else [])
    assert mounts == ["--volume"] * len(want) and _values(args, "--volume") == want
    assert not any(a.startswith(("--volume=", "-v=", "--mount=", "--volumes-from", "--tmpfs")) for a in args)
    # no engine socket, no home, no host namespace, no privilege, no file of the host's environment
    assert ".sock" not in text and "/run/user" not in text and "/var/run" not in text
    assert not HOST_HOME.search(text) and "~" not in text and "/etc/" not in text
    for bad in ("--privileged", "--pid", "--ipc", "--uts", "--env-file", "--env-host", "--http-proxy",
                "--add-host", "--group-add", "--security-opt=seccomp=unconfined", "--systemd", "--interactive"):  # fmt: skip
        assert not any(a == bad or a.startswith(bad + "=") for a in args), bad
    assert "seccomp=unconfined" not in text and "apparmor=unconfined" not in text and "label=disable" not in text
    # F5: every profile read-only, every capability dropped, no fuse or tun device
    assert "--read-only" in args and "--read-only-tmpfs=true" in args and "--cap-drop=all" in args
    assert "/dev/fuse" not in text and "/dev/net/tun" not in text
    assert "TMPDIR=/scratch/tmp" in _values(args, "--env")
    # the job's own non-root user, the host's tb-bench user mapped onto it
    assert _values(args, "--user") == ["1001:1001"] and "--userns=keep-id:uid=1001,gid=1001" in args
    assert not any(a.startswith("--userns=host") for a in args)
    # F7: the slot's own internal network; F4: no name service; the proxy by its fixed address
    assert _values(args, "--network") == ["tb-bench-job-cpu-1"] and not any(a.startswith("--network=") for a in args)
    assert _values(args, "--dns") == ["none"]
    assert not any(a.startswith(("--net=", "--net ")) or a == "--net" for a in args)
    assert "HTTPS_PROXY=http://10.213.1.2:3128" in _values(args, "--env")
    # a share of the host, not all of it
    assert _values(args, "--cpus") == ["16"] and _values(args, "--memory") == ["64g"]
    assert _values(args, "--pids-limit") == ["8192"]
    # nothing of a token or a configuration in the job's command line (F9: it is a file)
    assert not any("TOKEN" in a.upper() or "JIT" in a.upper() for a in args)


def test_a_cpu_job_keeps_no_capability_and_gets_no_new_privilege() -> None:
    args = _args("cpu")
    assert _values(args, "--security-opt") == ["no-new-privileges"] and "--cap-add" not in args
    assert "--device" not in args


@pytest.mark.parametrize("profile", ["engine", "gpu"])
def test_an_engine_or_gpu_job_keeps_only_the_set_id_pair_for_its_nested_engine(profile: str) -> None:
    """F5: the nested rootless engine maps its user namespace with the set-id helpers: SETUID and SETGID, and so no
    no-new-privileges; nothing else (the workflow keeps these profiles off lane pushes)."""
    args = _args(profile)
    assert _values(args, "--cap-add") == ["SETUID", "SETGID"] == list(launcher.ENGINE_CAPS)
    assert "--security-opt" not in args


def test_only_a_gpu_job_gets_the_ci_cards_and_the_weights_read_only() -> None:
    args = _args("gpu")
    cards = [v for v in _values(args, "--device") if v.startswith("vendor.example/gpu=")]
    assert cards == [f"vendor.example/gpu={i}" for i in CI_CARDS] == _values(args, "--device")
    assert not any(v.endswith(f"={r}") for v in cards for r in RESERVED)
    assert "/srv/weights:/weights:ro" in _values(args, "--volume")
    for other in ("cpu", "engine"):
        assert "--device" not in _args(other) and not any("weights" in a for a in _args(other))


def test_each_slot_has_its_own_network_and_address() -> None:
    s = _settings()
    seen = {launcher.subnet(s, slot) for slot in ("cpu-1", "cpu-2", "engine-1", "gpu-1", "probe-cpu", "probe-gpu")}
    assert len(seen) == 6
    assert launcher.subnet(s, "cpu-99") == ("10.213.99.0/24", "10.213.99.2")
    assert launcher.subnet(s, "engine-49") == ("10.213.149.0/24", "10.213.149.2")
    assert launcher.subnet(s, "gpu-1") == ("10.213.151.0/24", "10.213.151.2")
    assert launcher.job_net("gpu-1") != launcher.job_net("cpu-1")


def test_the_job_network_is_internal_without_a_name_service_and_the_proxy_joins_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[list[str]] = []
    monkeypatch.setattr("subprocess.run", _fake_run(ran))
    launcher.net_up(_settings(), "cpu-3")
    create = next(a for a in ran if a[1:3] == ["network", "create"])
    assert create == ["/usr/bin/engine", "network", "create", "--internal", "--disable-dns", "--subnet",
                      "10.213.3.0/24", "tb-bench-job-cpu-3"]  # fmt: skip
    connect = next(a for a in ran if a[1:3] == ["network", "connect"])
    assert connect == ["/usr/bin/engine", "network", "connect", "--ip", "10.213.3.2", "tb-bench-job-cpu-3",
                       "tb-bench-proxy"]  # fmt: skip


@pytest.mark.parametrize("profile", launcher.PROFILES)
def test_the_verify_probe_runs_with_each_profiles_arguments_exactly(profile: str) -> None:
    s = _settings()
    scratch = Path("/srv/ci-scratch/tb-bench-probe-x")
    probe = launcher.probe_args(s, profile, scratch)
    job = launcher.container_args(s, profile, scratch.name, scratch, f"probe-{profile}")
    assert probe[:-3] == job[:-1] and probe[-3:] == ["--entrypoint", "/opt/tb-bench/probe.sh", job[-1]]


def test_the_proxy_container_sits_on_its_way_out_only() -> None:
    args = launcher.proxy_args(_settings())
    assert _values(args, "--network") == [launcher.EGRESS_NET]
    assert "--read-only" in args and "--cap-drop=all" in args and _values(args, "--user") == ["1001:1001"]
    assert "--volume" not in args and "-v" not in args
    assert _values(args, "--allow") == [_settings()["BENCH_ALLOW_HOSTS"]]
    for profile in launcher.PROFILES:
        assert launcher.EGRESS_NET not in _args(profile)


# --- the token and the code host --------------------------------------------------------------------------------


class _Conn:
    seen: ClassVar[list[dict[str, Any]]] = []
    answer: ClassVar[tuple[int, dict[str, Any]]] = (201, {"runner": {"id": 7}, "encoded_jit_config": "CONFIG-X"})

    def __init__(self, host: str, timeout: float = 0) -> None:
        self.host = host

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> None:
        _Conn.seen.append({"host": self.host, "method": method, "path": path, "headers": headers or {}, "body": body})

    def getresponse(self) -> Any:
        status, body = _Conn.answer

        class R:
            def __init__(self) -> None:
                self.status = status

            def read(self) -> bytes:
                return json.dumps(body).encode()

        return R()

    def close(self) -> None:
        pass


def test_the_token_goes_to_the_code_hosts_api_only_whatever_a_callers_proxy_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Conn.seen = []
    monkeypatch.setattr("http.client.HTTPSConnection", _Conn)
    for var in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY"):
        monkeypatch.setenv(var, "http://elsewhere.invalid:8080")
    config, rid = launcher.jit_config(_settings(), "tok-for-a-test", "tb-bench-cpu-1-x", "cpu")
    assert (config, rid) == ("CONFIG-X", 7)
    (call,) = _Conn.seen
    assert call["host"] == "api.github.com" and call["method"] == "POST"
    assert call["path"] == "/repos/example-owner/example-repo/actions/runners/generate-jitconfig"
    assert call["headers"]["Authorization"] == "Bearer tok-for-a-test"
    assert json.loads(call["body"])["labels"] == ["tb-bench", "tb-bench-cpu"]
    assert b"tok-for-a-test" not in call["body"]
    with pytest.raises(ValueError, match="runner endpoints"):
        launcher.api("GET", "/user", "tok-for-a-test")
    with pytest.raises(ValueError, match="runner endpoints"):  # the token reads or writes nothing else
        launcher.api("PUT", f"/repos/example-owner/example-repo/contents/{launcher.WORKFLOW}", "t")


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A bench host in a folder: the scratch root, the root state folder, the token; the root steps run as root."""
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    state = tmp_path / "state"
    token = tmp_path / "token"
    token.write_text("tok-for-a-test\n", encoding="utf-8")
    token.chmod(0o600)
    calls: list[tuple[str, str]] = []

    def jit(*_a: Any) -> tuple[str, int]:
        calls.append(("jit", ""))
        return "CONFIG-X", 7

    monkeypatch.setattr(launcher, "jit_config", jit)
    monkeypatch.setattr(launcher, "remove_runner", lambda _s, _t, rid: calls.append(("remove", str(rid))))
    me = pwd.getpwuid(os.getuid())
    monkeypatch.setattr("pwd.getpwnam", lambda _n: me)
    monkeypatch.setattr("os.geteuid", lambda: 0)

    def read_token(path: Path) -> str:
        calls.append(("token", str(path)))
        return "tok"

    monkeypatch.setattr(launcher, "read_token", read_token)
    s = _settings(BENCH_SCRATCH=str(scratch_root))
    return s, token, state, calls


def test_the_root_mint_step_gives_the_jobs_user_one_jobs_configuration_and_never_the_token(host: Any) -> None:
    """F2: the long-lived token is read by the root mint step only; the jobs' user gets runner.jit (one job) and the
    gate's facts, in the slot's fresh scratch folder; the runner's id stays in root's state."""
    s, token, state, calls = host
    assert launcher.mint(s, "cpu-2", token_file=token, state=state) == 0
    folder = launcher.scratch_of(s, "cpu-2") / ".tb-bench"
    assert (folder / "runner.jit").read_text() == "CONFIG-X\n"
    assert stat.S_IMODE((folder / "runner.jit").stat().st_mode) == 0o600
    facts = json.loads((folder / "job.json").read_text())
    assert facts == {"profile": "cpu", "repo": "example-owner/example-repo", "workflow": launcher.WORKFLOW,
                     "proxy": "10.213.2.2:3128"}  # fmt: skip
    assert "tok" not in json.dumps(facts) and "tok" not in (folder / "runner.jit").read_text()
    assert json.loads((state / "cpu-2.json").read_text())["runner_id"] == 7
    assert calls[0] == ("token", str(token)) and ("jit", "") in calls


def test_the_mint_step_refuses_to_run_as_another_user(host: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    s, token, state, calls = host
    monkeypatch.setattr("os.geteuid", lambda: 1001)
    assert launcher.mint(s, "cpu-1", token_file=token, state=state) == 2
    assert calls == []


def test_the_jobs_users_step_never_reads_the_token(host: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """F2: run (the tb-bench user) reads no token; its container gets no configuration in its arguments (F9)."""
    s, token, state, calls = host
    launcher.mint(s, "cpu-1", token_file=token, state=state)
    calls.clear()
    seen: dict[str, Any] = {}

    class Proc:
        def __init__(self, args: list[str], **kw: Any) -> None:
            seen["args"], seen["kw"] = args, kw

        def wait(self, timeout: float | None = None) -> int:
            return 0

    ran: list[list[str]] = []
    monkeypatch.setattr("subprocess.Popen", Proc)
    monkeypatch.setattr("subprocess.run", _fake_run(ran))
    assert launcher.run_slot(s, "cpu-1") == 0
    assert calls == []  # no token read, no registration made or removed here
    assert not any("CONFIG-X" in a or "tok" in a for a in seen["args"])
    assert "env" not in seen["kw"] and seen["kw"].get("stdin") == subprocess.DEVNULL
    assert ["/usr/bin/engine", "network", "rm", "--force", "tb-bench-job-cpu-1"] in ran  # the network goes after


def test_a_stop_or_a_failure_takes_the_registration_and_the_scratch_folder_away(host: Any) -> None:
    """F8: cleanup (root, after a job, a failure or a stop) removes the registration and the folder."""
    s, token, state, calls = host
    launcher.mint(s, "cpu-1", token_file=token, state=state)
    calls.clear()
    assert launcher.cleanup(s, "cpu-1", token_file=token, state=state) == 0
    assert ("remove", "7") in calls
    assert not launcher.scratch_of(s, "cpu-1").exists() and not (state / "cpu-1.json").exists()


def test_a_new_job_never_finds_an_earlier_jobs_files(host: Any) -> None:
    s, token, state, _ = host
    launcher.mint(s, "cpu-1", token_file=token, state=state)
    left = launcher.scratch_of(s, "cpu-1") / "home" / "left-behind"
    left.write_text("x")
    (launcher.scratch_of(s, "cpu-1") / ".tb-bench" / "runner.jit").unlink()
    (launcher.scratch_of(s, "cpu-1") / ".tb-bench" / "job.json").unlink()
    assert launcher.mint(s, "cpu-1", token_file=token, state=state) == 0
    assert not left.exists()


def test_a_unit_stop_stops_the_container(host: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """F8: the run step answers the service manager's TERM by stopping the job's container."""
    s, token, state, _ = host
    launcher.mint(s, "cpu-1", token_file=token, state=state)
    ran: list[list[str]] = []
    handlers: dict[int, Any] = {}

    class Proc:
        def __init__(self, args: list[str], **kw: Any) -> None:
            pass

        def wait(self, timeout: float | None = None) -> int:
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            return 143

    monkeypatch.setattr("subprocess.Popen", Proc)
    monkeypatch.setattr("subprocess.run", _fake_run(ran))
    monkeypatch.setattr("signal.signal", handlers.__setitem__)
    launcher.run_slot(s, "cpu-1")
    assert ["/usr/bin/engine", "stop", "--time", "10", "tb-bench-cpu-1"] in ran


def test_a_slot_name_is_checked(host: Any) -> None:
    s, token, state, _ = host
    with pytest.raises(ValueError, match="not a slot"):
        launcher.run_slot(s, "host-1")
    with pytest.raises(ValueError, match="not a slot"):
        launcher.mint(s, "host-1", token, state)
    assert launcher.run_slot(s, "cpu-7") == 2  # no one-job configuration: nothing starts


# --- the CI cards, with a stand-in for the card query tool ------------------------------------------------------

STAND_IN = """#!/bin/sh
# a stand-in for the card query tool: the cards and the processes the test wrote, in the tool's CSV form
echo "$*" >> "{log}"
case "$1" in
  --query-gpu=*) cat "{cards}" ;;
  --query-compute-apps=*) cat "{apps}" ;;
  *) exit 9 ;;
esac
"""


@pytest.fixture
def card_tool(tmp_path: Path) -> Any:
    def make(cards: str, apps: str = "") -> tuple[str, Path]:  # apps: the tool's process list, which is not read
        (tmp_path / "cards.csv").write_text(cards, encoding="utf-8")
        (tmp_path / "apps.csv").write_text(apps, encoding="utf-8")
        log = tmp_path / "calls.log"
        tool = tmp_path / "cardquery"
        tool.write_text(
            STAND_IN.format(log=log, cards=tmp_path / "cards.csv", apps=tmp_path / "apps.csv"), encoding="utf-8"
        )
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
        return str(tool), log

    return make


SIX = "".join(f"{i}, GPU-{i}, 3, 0\n" for i in range(6))


def test_free_ci_cards_pass_and_give_their_uuids(card_tool: Any) -> None:
    tool, log = card_tool(SIX)
    assert gpu_check.host_check(tool, CI_CARDS, RESERVED, 1024, 5) == ([], ["GPU-4", "GPU-5"])
    assert "--query-gpu=index,uuid,memory.used,utilization.gpu" in log.read_text()


@pytest.mark.parametrize(
    ("cards", "words"),
    [
        (SIX.replace("4, GPU-4, 3, 0", "4, GPU-4, 1025, 0"), "1025 MiB in use (the cap is 1024)"),
        (SIX.replace("5, GPU-5, 3, 0", "5, GPU-5, 3, 6"), "6% load (the cap is 5%)"),
        (SIX.replace("4, GPU-4, 3, 0", "4, GPU-4, [N/A], 0"), "an unreadable MiB in use"),  # fails closed
        (SIX.replace("5, GPU-5, 3, 0", "5, GPU-5, 3, [N/A]"), "an unreadable% load"),
    ],
)
def test_a_ci_card_busy_beyond_its_cap_stops_the_runner_with_a_clear_message(
    card_tool: Any, cards: str, words: str
) -> None:
    tool, _ = card_tool(cards)
    problems, _ = gpu_check.host_check(tool, CI_CARDS, RESERVED, 1024, 5)
    assert problems and problems[0].startswith("CI card ") and "busy beyond its cap" in problems[0]
    assert words in problems[0]


def test_a_shared_ci_card_within_its_cap_is_used(card_tool: Any) -> None:
    """Another job on a CI card does not stop a GPU job by itself: only what it holds beyond the cap does."""
    tool, log = card_tool(SIX.replace("4, GPU-4, 3, 0", "4, GPU-4, 1024, 5"))
    assert gpu_check.host_check(tool, CI_CARDS, RESERVED, 1024, 5) == ([], ["GPU-4", "GPU-5"])
    assert "--query-compute-apps" not in log.read_text()


def test_a_missing_ci_card_is_named(card_tool: Any) -> None:
    tool, _ = card_tool("0, GPU-0, 3, 0\n4, GPU-4, 3, 0\n")
    problems, uuids = gpu_check.host_check(tool, CI_CARDS, RESERVED, 1024, 5)
    assert problems == ["CI card(s) [5] not found by the card query tool (it sees [0, 4])"] and uuids == []


def test_a_reserved_card_is_refused_before_any_query(card_tool: Any) -> None:
    tool, log = card_tool(SIX)
    problems, _ = gpu_check.host_check(tool, [1, 4], RESERVED, 1024, 5)
    assert problems and "walk" in problems[0]
    assert not log.exists()
    with pytest.raises(RuntimeError, match="absolute path"):
        gpu_check.host_check("cardquery", CI_CARDS, RESERVED, 1024, 5)


def test_a_gpu_slot_with_busy_cards_registers_nothing(card_tool: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    tool, _ = card_tool(SIX.replace("4, GPU-4, 3, 0", "4, GPU-4, 9000, 0"))
    monkeypatch.setattr(launcher, "jit_config", lambda *_a: pytest.fail("a runner was registered"))
    monkeypatch.setattr(launcher, "read_token", lambda *_a: pytest.fail("the token was read"))
    monkeypatch.setattr("os.geteuid", lambda: 0)
    assert launcher.mint(_settings(BENCH_GPU_QUERY=tool), "gpu-1", Path("/nonexistent"), Path("/nonexistent")) == 3


def test_the_jobs_own_check_refuses_busy_or_other_cards(
    card_tool: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # in the container the cards are numbered from 0: the check goes by UUID
    tool, _ = card_tool("0, GPU-4, 3, 0\n1, GPU-5, 3, 0\n")
    spec = tmp_path / "job.json"
    spec.write_text(json.dumps({"profile": "gpu", "tool": tool, "uuids": ["GPU-4", "GPU-5"], "cap_mib": 1024,
                                "cap_util": 5}), encoding="utf-8")  # fmt: skip
    assert gpu_check.main(["--in-job", str(spec)]) == 0
    tool, _ = card_tool("0, GPU-4, 3, 0\n1, GPU-5, 40000, 0\n")
    assert gpu_check.main(["--in-job", str(spec)]) == 1
    err = capsys.readouterr().err
    assert "busy beyond its cap" in err and "this job does not start" in err
    tool, _ = card_tool("0, GPU-4, 3, 0\n1, GPU-2, 3, 0\n")
    assert gpu_check.main(["--in-job", str(spec)]) == 1
    spec.write_text(json.dumps({"profile": "cpu"}), encoding="utf-8")
    assert gpu_check.main(["--in-job", str(spec)]) == 0
    assert gpu_check.main(["--in-job", str(tmp_path / "missing.json")]) == 1  # no card file: no job


# --- the egress proxy -------------------------------------------------------------------------------------------

ALLOW = "github.com,.githubusercontent.com,pypi.org"


@pytest.mark.parametrize(
    ("host", "ok"),
    [
        ("github.com", True),
        ("GitHub.com.", True),
        ("objects.githubusercontent.com", True),
        ("pypi.org", True),
        ("api.github.com", False),  # exact names are exact
        ("github.com.elsewhere.example", False),
        ("evilgithubusercontent.com", False),
        ("githubusercontent.com", False),  # a suffix entry is for names under it
        ("10.0.0.5", False),
        ("127.0.0.1", False),
        ("localhost", False),
        ("[::1]", False),
    ],
)
def test_the_allow_list(host: str, ok: bool) -> None:
    exact, suffixes = egress_proxy.parse_allow(ALLOW)
    assert egress_proxy.allowed(host, exact, suffixes) is ok


def test_only_connect_to_443_on_an_allowed_host() -> None:
    exact, suffixes = egress_proxy.parse_allow(ALLOW)
    assert (
        egress_proxy.decide(egress_proxy.parse_connect(b"CONNECT pypi.org:443 HTTP/1.1\r\n\r\n"), exact, suffixes) == ""
    )
    assert "port 22" in egress_proxy.decide(("pypi.org", 22), exact, suffixes)
    assert egress_proxy.parse_connect(b"GET http://pypi.org/ HTTP/1.1\r\n\r\n") is None
    assert egress_proxy.decide(None, exact, suffixes) == "not a CONNECT request"
    with pytest.raises(ValueError, match="empty"):
        egress_proxy.parse_allow(" , ")
    with pytest.raises(ValueError, match="not a host name"):
        egress_proxy.parse_allow("github.com,*.example.com")


@pytest.mark.parametrize(
    ("addr", "ok"),
    [(str(PUBLIC_V4), True), ("10.1.2.3", False), ("192.168.1.1", False), ("172.16.0.1", False),
     ("127.0.0.1", False), ("169.254.169.254", False), ("100.64.0.1", False), ("::1", False), ("fd00::1", False),
     ("fe80::1%eth0", False), (str(PUBLIC_V6), True), ("2001:db8::1", False)],
)  # fmt: skip
def test_only_a_public_address_is_reached(addr: str, ok: bool) -> None:
    assert egress_proxy.public(addr) is ok


def test_the_proxy_refuses_on_the_wire_without_reaching_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real socket on the loopback: plain HTTP, a host off the list, a listed name that resolves to a private
    address. Each is answered 403 and nothing is connected."""

    async def fake_getaddrinfo(*_a: Any, **_k: Any) -> list[Any]:
        return [(2, 1, 6, "", ("10.0.0.7", 443))]

    async def scenario() -> list[bytes]:
        proxy = egress_proxy.Proxy(*egress_proxy.parse_allow("inside.example"))
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
        server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        answers = []
        for req in (b"GET http://inside.example/ HTTP/1.1\r\n\r\n", b"CONNECT pypi.org:443 HTTP/1.1\r\n\r\n",
                    b"CONNECT inside.example:443 HTTP/1.1\r\n\r\n"):  # fmt: skip
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(req)
            await writer.drain()
            answers.append(await asyncio.wait_for(reader.read(), 10))
            writer.close()
        server.close()
        await server.wait_closed()
        return answers

    async def run_checked() -> list[bytes]:
        opened: list[Any] = []
        original = asyncio.open_connection

        async def watched(host: str, port: int, **kw: Any) -> Any:
            if host != "127.0.0.1":
                opened.append(host)
            return await original(host, port, **kw)

        monkeypatch.setattr("asyncio.open_connection", watched)
        try:
            return await scenario()
        finally:
            assert opened == []

    answers = asyncio.run(run_checked())
    assert all(a.startswith(b"HTTP/1.1 403") for a in answers), answers


# --- the install script, the units, the image ---------------------------------------------------------------------


def test_the_token_is_typed_into_a_root_only_file_and_never_shown() -> None:
    body = INSTALL[INSTALL.index("cmd_token() {") : INSTALL.index("\n}\n", INSTALL.index("cmd_token() {"))]
    assert "IFS= read -rs tok" in body  # typed or pasted, not echoed
    assert 'printf \'%s\\n\' "$tok" > "$tmp"' in body  # a shell builtin: never a process's argument
    assert "umask 077" in body and 'chmod 0600 "$tmp"' in body and 'mv -f "$tmp" "$TOKEN"' in body
    assert 'tok=""' in body
    assert not re.search(r"echo[^\n]*\$tok", INSTALL) and "set -x" not in INSTALL
    assert "$1" not in body  # never an argument
    # F2: no unit hands the jobs' user a copy (no credential of the service manager); only the root steps read it
    assert "LoadCredential" not in RUNNER_UNIT and "LoadCredential" not in PROXY_UNIT
    assert "token" not in RUNNER_UNIT.split("[Service]", 1)[1].lower()
    assert not [ln for ln in RUNNER_UNIT.splitlines() if ln.startswith("Environment") and "TOKEN" in ln.upper()]
    assert Path("/etc/tb-bench-ci/token") == launcher.TOKEN


def test_only_the_units_root_steps_read_the_token_and_the_jobs_user_runs_the_job() -> None:
    """F2: ExecStartPre and ExecStopPost run with full privileges ("+": root); ExecStart runs as tb-bench."""
    lines = {ln.split("=", 1)[0]: ln.split("=", 1)[1] for ln in RUNNER_UNIT.splitlines() if ln.startswith("Exec")}
    assert lines["ExecStartPre"].startswith("+/usr/bin/python3 -s -E -m tools.bench_ci.launcher mint ")
    assert lines["ExecStopPost"].startswith("+/usr/bin/python3 -s -E -m tools.bench_ci.launcher cleanup ")
    assert lines["ExecStart"].startswith("/usr/bin/python3 -s -E -m tools.bench_ci.launcher run ")
    assert "KillMode=mixed" in RUNNER_UNIT and "TimeoutStopSec=" in RUNNER_UNIT  # F8: TERM to the run step first
    body = INSTALL[INSTALL.index("cmd_verify() {") : INSTALL.index("\n}\n", INSTALL.index("cmd_verify() {"))]
    assert 'check "$USER_NAME cannot read the token file" not as_tb test -r "$TOKEN"' in body


def test_the_units_run_as_the_unprivileged_user_from_roots_files() -> None:
    for unit in (RUNNER_UNIT, PROXY_UNIT):
        assert "User=tb-bench" in unit and "Group=tb-bench" in unit
        assert "-s -E -m tools.bench_ci.launcher" in unit and "WorkingDirectory=/opt/tb-bench-ci" in unit
        assert "--settings /etc/tb-bench-ci/settings.env" in unit
    assert "useradd --system --user-group --create-home" in INSTALL and "--shell /usr/sbin/nologin" in INSTALL
    # in no other group (no engine group, no sudo): install stops, verify fails
    assert '[ "$(id -nG "$USER_NAME")" = "$USER_NAME" ] || die "$USER_NAME is in another group' in INSTALL
    assert 'no_group() { [ "$(id -nG "$USER_NAME")" = "$USER_NAME" ]; }' in INSTALL
    assert 'install -d -m 0750 -o root -g "$USER_NAME" "$ETC"' in INSTALL
    assert 'install -m 0644 -o root -g root "$SRC/$f" "$OPT/tools/bench_ci/$f"' in INSTALL


def test_the_runner_archive_is_checked_and_the_proxy_has_its_way_out() -> None:
    assert "sha256sum -c --quiet -" in INSTALL and "BENCH_RUNNER_SHA256" in INSTALL
    assert "network create tb-bench-egress" in INSTALL and "tb-bench-jobs" not in INSTALL


def test_removal_takes_away_everything_it_made_and_says_what_is_left_to_the_owner(tmp_path: Path) -> None:
    body = INSTALL[INSTALL.index("cmd_remove() {") : INSTALL.index("\n}\n", INSTALL.index("cmd_remove() {"))]
    for want in ("systemctl disable --now", 'rm -f "$UNITS/tb-bench-runner@.service" "$UNITS/tb-bench-proxy.service"',
                 "rm --all --force", 'network rm --force "$net"', "system reset --force",
                 'shred -u "$TOKEN"', 'rm -rf "$OPT"', 'loginctl disable-linger "$USER_NAME"',
                 'userdel --remove "$USER_NAME"', 'sed -i "/^$USER_NAME:/d" /etc/subuid /etc/subgid',
                 "remove any", "revoke the minting token", "LEFT"):  # fmt: skip
        assert want in body, want
    # the integrator's ruling (7133000201): remove takes $OPT, and the operator's settings folder with its planted
    # settings file survives, run with stand-ins for root's commands
    etc, opt = tmp_path / "etc", tmp_path / "opt"
    etc.mkdir()
    (etc / "settings.env").write_text("BENCH_REPO=o/r\n", encoding="utf-8")
    (opt / "tools").mkdir(parents=True)
    run = (
        f'set -euo pipefail\nsource "{BENCH_CI / "install.sh"}"\n'
        f'ETC="{etc}"; SETTINGS="$ETC/settings.env"; TOKEN="$ETC/token"; MADE="$ETC/made"; OPT="{opt}"\n'
        f'UNITS="{tmp_path}/units"; HOME_DIR="{tmp_path}/home-dir"\n'
        "need_root() { :; }; systemctl() { :; }; id() { return 1; }; sed() { :; }; get() { :; }; chown() { :; }\n"
        'record_made dir "$OPT"\ncmd_remove\n'
    )
    got = subprocess.run(["bash", "-c", run], check=False, capture_output=True, text=True)
    assert got.returncode == 0, got.stdout + got.stderr
    assert not opt.exists() and etc.is_dir()
    assert (etc / "settings.env").read_text(encoding="utf-8") == "BENCH_REPO=o/r\n"


def test_verify_checks_the_named_folders_as_the_runners_user_and_runs_the_probe() -> None:
    body = INSTALL[INSTALL.index("cmd_verify() {") : INSTALL.index("\n}\n", INSTALL.index("cmd_verify() {"))]
    assert 'for p in "$@"; do check "$USER_NAME cannot read or write $p" not sees "$p"; done' in body
    assert "at least one folder" in body
    # F5: every profile with slots is probed with its own arguments
    assert "for profile in cpu engine gpu; do" in body
    assert 'as_tb_launcher probe --settings "$SETTINGS" --profile "$profile"' in body
    probe = (BENCH_CI / "probe.sh").read_text(encoding="utf-8")
    for want in ("not root", "engine socket", "no host folder but /scratch", "the root is read-only",
                 "no direct way out", "off the allow-list", "written as a number", "no fuse or tun device",
                 "no name service", "getent hosts", "upload host", "the weights are read-only",
                 "test \"$caps\" = 0000000000000000", "test \"$caps\" = 00000000000000c0"):  # fmt: skip
        assert want in probe, want


def test_the_image_runs_as_its_own_user_and_takes_its_config_from_a_file() -> None:
    """F9: the one-job configuration is a file, read, deleted and unpacked; the runner starts with no argument."""
    assert re.search(r"^FROM [^\s]+@sha256:[0-9a-f]{64}$", DOCKERFILE, re.M)
    assert DOCKERFILE.rstrip().splitlines()[-3] == "USER 1001:1001"
    assert "useradd --uid 1001" in DOCKERFILE
    assert "gate.py" in DOCKERFILE and "unpack_jit.py" in DOCKERFILE
    assert not re.search(r"\b(fuse-overlayfs|slirp4netns|passt)\b", DOCKERFILE)  # F5: no fuse or tun helper
    assert 'if [ "$(id -u)" = 0 ]' in ENTRYPOINT
    assert 'python3 -I /opt/tb-bench/unpack_jit.py "$JIT" /scratch/runner' in ENTRYPOINT
    assert 'rm -f "$JIT"' in ENTRYPOINT.splitlines() and ENTRYPOINT.rstrip().endswith("exec ./run.sh")
    assert "--jitconfig" not in ENTRYPOINT and "read -r config" not in ENTRYPOINT
    assert "ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/tb-bench/job_started.sh" in ENTRYPOINT
    hook = (BENCH_CI / "job_started.sh").read_text(encoding="utf-8").splitlines()
    gate = hook.index("python3 -I /opt/tb-bench/gate.py --job /scratch/.tb-bench/job.json")
    cards = hook.index("exec python3 -I /opt/tb-bench/gpu_check.py --in-job /scratch/.tb-bench/job.json")
    assert "set -euo pipefail" in hook and gate < cards  # the gate first, and a refusal stops the hook


def test_no_bench_host_detail_in_the_committed_files() -> None:
    for f in sorted(BENCH_CI.iterdir()):
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            # the only addresses: any (the proxy's listen), the loopback, and a documentation address (the probe)
            addrs = set(re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text))
            assert addrs <= {"0.0.0.0", "127.0.0.1", "192.0.2.1"}, (f.name, addrs)
            # a home folder is named only where install.sh refuses it as the scratch folder
            kept = [ln for ln in text.splitlines() if not ln.lstrip().startswith('case "$scratch" in')]
            assert not HOST_HOME.search("\n".join(kept)), f.name


# --- part b: the GPU box rehearsal's script, with stand-ins for the card query tool and the engine -------------

GPU_BOX = BENCH_CI / "gpu_box.sh"


def _gpu_box(
    tmp_path: Path, *, tool_ok: bool = True, engine: str = "true", tool_in_file: bool = True, weights: str = "ro"
) -> Any:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tool = tmp_path / "cardquery"
    body = 'echo "Card Model X, 183000, 580.1"\necho "Card Model X, 183000, 580.1"\n' if tool_ok else "exit 7\n"
    tool.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    # a working tool on PATH too: the script must never find it there (only by the job's card file)
    (bin_dir / "cardquery").write_text('#!/bin/sh\necho "Card Model X, 183000, 580.1"\n', encoding="utf-8")
    (bin_dir / "cardquery").chmod(0o755)
    engine_stand_in = bin_dir / "podman"
    engine_stand_in.write_text(f"#!/bin/sh\necho {engine}\n", encoding="utf-8")
    for f in (tool, engine_stand_in):
        f.chmod(0o755)
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"profile": "gpu", "tool": str(tool) if tool_in_file else ""}), encoding="utf-8")
    out = tmp_path / "out"
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    folder = tmp_path / "weights"
    mounts = tmp_path / "mounts"
    lines = ["overlay / overlay ro,relatime 0 0"]  # a stand-in for the container's mount table
    if weights != "none":
        folder.mkdir()
        if weights in ("ro", "rw"):
            lines.append(f"/dev/sdz1 {folder} ext4 {weights},nosuid,nodev,relatime 0 0")
    mounts.write_text("\n".join(lines) + "\n", encoding="utf-8")
    args = ["bash", str(GPU_BOX), str(out), str(job), str(folder), str(mounts)]
    proc = subprocess.run(args, check=False, capture_output=True, text=True, env=env)
    return proc, out


def test_the_gpu_box_says_each_step_and_never_counts_a_step_not_run_as_passed(tmp_path: Path) -> None:
    proc, out = _gpu_box(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    steps = json.loads((out / "report.json").read_text())["steps"]
    assert steps == {"tpm": "PASS", "gpu": "PASS", "weights": "PASS", "engine": "PASS", "install": "NOT RUN",
                     "serving": "NOT RUN"}  # fmt: skip
    report = (out / "report.md").read_text()
    if not Path("/dev/tpmrm0").exists() and not Path("/dev/tpm0").exists():
        assert "no TPM: the passphrase path" in report
    assert "H-94 (3)" in report and "H105-03" in report  # why each step is not run
    record = json.loads((out / "gpu-record.json").read_text())
    assert record == {"count": 2, "cards": [{"model": "Card Model X", "memory_mib": 183000, "driver": "580.1"}] * 2}


def test_the_gpu_record_holds_no_serial_or_uuid() -> None:
    text = GPU_BOX.read_text(encoding="utf-8")
    query = re.search(r"--query-gpu=(\S+)", text)
    assert query and query.group(1) == "name,memory.total,driver_version"
    assert "uuid" not in query.group(1) and "serial" not in query.group(1)


@pytest.mark.parametrize(
    ("kw", "step"),
    [
        ({"tool_ok": False}, "gpu"),
        ({"tool_in_file": False}, "gpu"),
        ({"engine": "false"}, "engine"),
        ({"weights": "none"}, "weights"),
        ({"weights": "rw"}, "weights"),
        ({"weights": "plain"}, "weights"),
    ],
)
def test_the_gpu_box_fails_on_a_failed_step(tmp_path: Path, kw: dict[str, Any], step: str) -> None:
    proc, out = _gpu_box(tmp_path, **kw)
    assert proc.returncode == 1
    assert json.loads((out / "report.json").read_text())["steps"][step] == "FAIL"
    if not kw.get("tool_in_file", True):
        assert "no card query tool in the job's card file" in (out / "report.md").read_text()
    why = {"none": "no readable weights folder", "rw": "mounted writable", "plain": "is not a mount of its own"}
    if "weights" in kw:
        assert why[kw["weights"]] in (out / "report.md").read_text()


@pytest.mark.parametrize("answer", ['echo "Card Model X, [N/A], 580.1"', "exit 0", 'echo "Card Model X, 183000"'])
def test_the_gpu_box_fails_when_the_tools_answer_gives_no_record(tmp_path: Path, answer: str) -> None:
    """OCR 1466-4: a field the tool cannot read, no card at all, or a short row said PASS with an empty note."""
    tool = tmp_path / "cardquery"
    tool.write_text(f"#!/bin/sh\n{answer}\n", encoding="utf-8")
    tool.chmod(0o755)
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"profile": "gpu", "tool": str(tool)}), encoding="utf-8")
    out = tmp_path / "out"
    args = ["bash", str(GPU_BOX), str(out), str(job), str(tmp_path / "none"), str(tmp_path / "none")]
    subprocess.run(args, check=False, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert json.loads((out / "report.json").read_text())["steps"]["gpu"] == "FAIL"
    assert not (out / "gpu-record.json").exists()
