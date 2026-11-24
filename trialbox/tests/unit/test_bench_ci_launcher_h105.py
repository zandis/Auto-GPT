"""H-105: the bench host's runner, in the repository's part (the host's part is the walk's install and verify).

The harms: a job that escapes its container reaches the owner's data and keys; a leaked token lets another machine
join as a runner. These tests hold the launcher's container arguments (no engine socket, no host folder but the job's
scratch, read-only where it can be, the job's own non-root user, the internal network), the CI cards' check with a
stand-in for the card query tool, the egress proxy's allow-list, and the install script's token and removal paths.
Nothing here starts a container or calls the code host."""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
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
    "TB_BENCH_REPO": "example-owner/example-repo",
    "TB_BENCH_ENGINE": "/usr/bin/engine",
    "TB_BENCH_SCRATCH": "/srv/ci-scratch",
    "TB_BENCH_CPU_SLOTS": "4",
    "TB_BENCH_ENGINE_SLOTS": "1",
    "TB_BENCH_GPU_SLOTS": "1",
    "TB_BENCH_CPUS": "16",
    "TB_BENCH_MEMORY": "64g",
    "TB_BENCH_RUNNER_VERSION": "9.9.9",
    "TB_BENCH_RUNNER_SHA256": "a" * 64,
    "TB_BENCH_CI_GPUS": "4,5",
    "TB_BENCH_RESERVED_GPUS": "1,2,3",
    "TB_BENCH_GPU_QUERY": "/usr/bin/cardquery",
    "TB_BENCH_GPU_DEVICE": "vendor.example/gpu",
}
CI_CARDS = [4, 5]
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


SCRATCH = Path("/srv/ci-scratch/tb-bench-cpu-1-0000")
HOST_HOME = re.compile(r"(?<![\w.-])/(home|root)\b")  # a host's home folder (the job's own is /scratch/home)


def _flags(args: list[str]) -> list[str]:
    return [a for a in args if a.startswith("-")]


def _values(args: list[str], flag: str) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a == flag]


# --- the settings file ------------------------------------------------------------------------------------------


def test_the_example_holds_placeholders_only_and_is_refused_as_it_is() -> None:
    with pytest.raises(launcher.SettingsError, match="placeholder"):
        launcher.parse_settings(EXAMPLE)
    # no host detail of the bench host: no address, no home folder, no user's name; the repository is a placeholder
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", EXAMPLE)
    assert "/home/" not in EXAMPLE and "~" not in EXAMPLE
    assert "TB_BENCH_REPO=<owner>/<repository>" in EXAMPLE
    assert "TB_BENCH_RESERVED_GPUS=1," in EXAMPLE  # the walk's card is kept from the first line on
    assert set(re.findall(r"^(TB_BENCH_[A-Z_0-9]+)=", EXAMPLE, re.M)) == launcher.KEYS


def test_filled_settings_are_read() -> None:
    s = _settings()
    assert s["TB_BENCH_LABEL"] == "tb-bench" and s.num("TB_BENCH_GPU_SLOTS") == 1


@pytest.mark.parametrize(
    ("over", "words"),
    [
        ({"TB_BENCH_CI_GPUS": "1,4"}, "keeps"),  # the walk's card
        ({"TB_BENCH_CI_GPUS": "3,4"}, "keeps"),  # a card of the bench
        ({"TB_BENCH_CI_GPUS": ""}, "a GPU slot needs"),
        ({"TB_BENCH_RESERVED_GPUS": "2,3"}, "card 1"),
        ({"TB_BENCH_GPU_SLOTS": "2"}, "0 or 1"),
        ({"TB_BENCH_ENGINE": "engine"}, "absolute"),
        ({"TB_BENCH_GPU_QUERY": "cardquery"}, "absolute"),
        ({"TB_BENCH_RUNNER_SHA256": "abc"}, "64 hex"),
        ({"TB_BENCH_CPUS": "many"}, "whole number"),
    ],
)
def test_settings_that_would_share_a_card_or_guess_a_path_are_refused(over: dict[str, str], words: str) -> None:
    with pytest.raises(launcher.SettingsError, match=words):
        _settings(**over)


def test_an_unknown_or_repeated_key_is_refused() -> None:
    with pytest.raises(launcher.SettingsError, match="not a known"):
        launcher.parse_settings(_filled() + "TB_BENCH_HOST_NETWORK=1\n")
    with pytest.raises(launcher.SettingsError, match="twice"):
        launcher.parse_settings(_filled() + "TB_BENCH_CPUS=2\n")


def test_the_settings_file_must_be_roots(tmp_path: Path) -> None:
    f = tmp_path / "settings.env"
    f.write_text(_filled(), encoding="utf-8")
    if os.getuid() != 0:
        with pytest.raises(launcher.SettingsError, match="owned by root"):
            launcher.read_settings(f)
    f.chmod(0o666)
    with pytest.raises(launcher.SettingsError, match="root"):
        launcher.read_settings(f)


def test_the_token_file_must_be_private(tmp_path: Path) -> None:
    f = tmp_path / "token"
    f.write_text("tok-for-a-test\n", encoding="utf-8")
    f.chmod(0o640)
    with pytest.raises(launcher.SettingsError, match="readable by others"):
        launcher.read_token(f)
    f.chmod(0o600)
    assert launcher.read_token(f) == "tok-for-a-test"
    f.write_text("two tokens\n", encoding="utf-8")
    with pytest.raises(launcher.SettingsError, match="more than one"):
        launcher.read_token(f)


# --- the job container's arguments ------------------------------------------------------------------------------


@pytest.mark.parametrize("profile", launcher.PROFILES)
def test_no_profile_sees_a_socket_a_home_the_host_network_or_any_folder_but_its_scratch(profile: str) -> None:
    args = launcher.container_args(_settings(), profile, "tb-bench-x", SCRATCH)
    text = " ".join(args)
    assert args[0] == "/usr/bin/engine" and args[1] == "run" and args[-1] == "localhost/tb-bench-runner:1"
    assert "--rm" in args and "--pull=never" in args
    # the one host folder: this job's scratch folder
    mounts = [a for a in args if a in ("--volume", "-v", "--mount")]
    assert mounts == ["--volume"] and _values(args, "--volume") == [f"{SCRATCH}:/scratch:rw"]
    assert not any(a.startswith(("--volume=", "-v=", "--mount=", "--volumes-from")) for a in args)
    # no engine socket, no home, no host namespace, no privilege, no file of the host's environment
    assert ".sock" not in text and "/run/user" not in text and "/var/run" not in text
    assert not HOST_HOME.search(text) and "~" not in text and "/etc/" not in text
    for bad in ("--privileged", "--pid", "--ipc", "--uts", "--env-file", "--env-host", "--http-proxy",
                "--add-host", "--cap-add", "--group-add", "--security-opt=seccomp=unconfined", "--systemd"):  # fmt: skip
        assert not any(a == bad or a.startswith(bad + "=") for a in args), bad
    assert "seccomp=unconfined" not in text and "apparmor=unconfined" not in text
    # the job's own non-root user, the host's tb-bench user mapped onto it
    assert _values(args, "--user") == ["1001:1001"] and "--userns=keep-id:uid=1001,gid=1001" in args
    assert not any(a.startswith("--userns=host") for a in args)
    # the internal network only: the proxy is the way out
    assert _values(args, "--network") == [launcher.JOBS_NET] and not any(a.startswith("--network=") for a in args)
    assert not any(a.startswith(("--net=", "--net ")) or a == "--net" for a in args)
    assert f"HTTPS_PROXY=http://{launcher.PROXY_NAME}:{launcher.PROXY_PORT}" in _values(args, "--env")
    # a share of the host, not all of it
    assert _values(args, "--cpus") == ["16"] and _values(args, "--memory") == ["64g"]
    assert _values(args, "--pids-limit") == ["8192"]
    # nothing of a token in the job's command line
    assert not any("TOKEN" in a.upper() for a in _values(args, "--env"))


def test_a_cpu_job_is_read_only_with_no_capability_and_no_new_privilege() -> None:
    args = launcher.container_args(_settings(), "cpu", "tb-bench-x", SCRATCH)
    assert "--read-only" in args and "--cap-drop=all" in args
    assert _values(args, "--security-opt") == ["no-new-privileges"]
    assert "--device" not in args


def test_an_engine_job_has_its_own_nested_engine_and_no_host_one() -> None:
    args = launcher.container_args(_settings(), "engine", "tb-bench-x", SCRATCH)
    assert _values(args, "--device") == ["/dev/fuse", "/dev/net/tun"]
    assert _values(args, "--security-opt") == ["label=disable"]
    # no card for an engine job
    assert not any(v.startswith("vendor.example/gpu") for v in _values(args, "--device"))


def test_a_gpu_job_gets_the_ci_cards_and_never_the_walks_or_the_benchs() -> None:
    args = launcher.container_args(_settings(), "gpu", "tb-bench-x", SCRATCH)
    cards = [v for v in _values(args, "--device") if v.startswith("vendor.example/gpu=")]
    assert cards == [f"vendor.example/gpu={i}" for i in CI_CARDS]
    assert not any(v.endswith(f"={r}") for v in cards for r in RESERVED)


def test_the_verify_probe_runs_with_the_cpu_jobs_arguments_exactly() -> None:
    s = _settings()
    scratch = Path("/srv/ci-scratch/tb-bench-probe-0000")
    probe = launcher.probe_args(s, scratch)
    job = launcher.container_args(s, "cpu", scratch.name, scratch)
    assert probe[:-3] == job[:-1] and probe[-3:] == ["--entrypoint", "/opt/tb-bench/probe.sh", job[-1]]


def test_the_proxy_container_is_the_only_one_on_the_way_out() -> None:
    args = launcher.proxy_args(_settings())
    assert _values(args, "--network") == [launcher.JOBS_NET, launcher.EGRESS_NET]
    assert "--read-only" in args and "--cap-drop=all" in args and _values(args, "--user") == ["1001:1001"]
    assert "--volume" not in args and "-v" not in args
    assert _values(args, "--allow") == [_settings()["TB_BENCH_ALLOW_HOSTS"]]
    for profile in launcher.PROFILES:
        assert launcher.EGRESS_NET not in launcher.container_args(_settings(), profile, "x", SCRATCH)


# --- the token and the code host --------------------------------------------------------------------------------


class _Conn:
    seen: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, host: str, timeout: float = 0) -> None:
        self.host = host

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> None:
        _Conn.seen.append({"host": self.host, "method": method, "path": path, "headers": headers or {}, "body": body})

    def getresponse(self) -> Any:
        class R:
            status = 201

            def read(self) -> bytes:
                return json.dumps({"runner": {"id": 7}, "encoded_jit_config": "CONFIG-FOR-A-TEST"}).encode()

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
    assert (config, rid) == ("CONFIG-FOR-A-TEST", 7)
    (call,) = _Conn.seen
    assert call["host"] == "api.github.com" and call["method"] == "POST"
    assert call["path"] == "/repos/example-owner/example-repo/actions/runners/generate-jitconfig"
    assert call["headers"]["Authorization"] == "Bearer tok-for-a-test"
    assert json.loads(call["body"])["labels"] == ["tb-bench", "tb-bench-cpu"]
    assert b"tok-for-a-test" not in call["body"]
    with pytest.raises(ValueError, match="runner endpoints"):
        launcher.api("GET", "/user", "tok-for-a-test")


def test_one_job_life_the_config_on_stdin_never_an_argument_then_gone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    s = _settings(TB_BENCH_SCRATCH=str(scratch_root))
    token = tmp_path / "token"
    token.write_text("tok-for-a-test\n", encoding="utf-8")
    token.chmod(0o600)
    calls: list[tuple[str, str]] = []

    def mint(*_a: Any) -> tuple[str, int]:
        calls.append(("mint", ""))
        return "CONFIG-FOR-A-TEST", 7

    monkeypatch.setattr(launcher, "jit_config", mint)
    monkeypatch.setattr(launcher, "remove_runner", lambda _s, _t, rid: calls.append(("remove", str(rid))))
    seen: dict[str, Any] = {}

    class Proc:
        def __init__(self, args: list[str], **kw: Any) -> None:
            seen["args"], seen["kw"] = args, kw
            spec = json.loads(
                (Path(args[args.index("--volume") + 1].split(":")[0]) / ".tb-bench" / "job.json").read_text()
            )
            seen["spec"] = spec

            class In:
                def write(self, text: str) -> None:
                    seen["stdin"] = text

                def close(self) -> None:
                    pass

            self.stdin = In()

        def wait(self, timeout: float | None = None) -> int:
            return 0

    ran: list[list[str]] = []
    monkeypatch.setattr("subprocess.Popen", Proc)
    monkeypatch.setattr("subprocess.run", lambda args, **kw: ran.append(args))
    assert launcher.run_slot(s, token, "cpu-1") == 0
    assert seen["stdin"] == "CONFIG-FOR-A-TEST\n"
    assert not any("CONFIG-FOR-A-TEST" in a or "tok-for-a-test" in a for a in seen["args"])
    assert "env" not in seen["kw"]  # the container gets no copy of the launcher's environment
    assert seen["spec"] == {"profile": "cpu"}
    assert calls == [("mint", ""), ("remove", "7")]
    (drop,) = ran
    assert drop[:4] == ["/usr/bin/engine", "unshare", "rm", "-rf"] and drop[-1].startswith(str(scratch_root))


def test_a_slot_name_is_checked() -> None:
    assert launcher.run_slot(_settings(), Path("/nonexistent"), "host-1") == 2
    with pytest.raises(ValueError, match="not a job scratch"):
        launcher.drop_scratch(_settings(), Path("/srv/ci-scratch/../etc"))


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
    def make(cards: str, apps: str = "") -> tuple[str, Path]:
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
    ("cards", "apps", "words"),
    [
        (SIX.replace("4, GPU-4, 3, 0", "4, GPU-4, 70000, 0"), "", "70000 MiB used"),
        (SIX.replace("5, GPU-5, 3, 0", "5, GPU-5, 3, 99"), "", "99% busy"),
        (SIX, "GPU-5, 512\n", "a compute process"),
        (SIX.replace("4, GPU-4, 3, 0", "4, GPU-4, [N/A], 0"), "", "busy"),  # a reading the tool cannot give
    ],
)
def test_a_busy_ci_card_stops_the_runner_with_a_clear_message(
    card_tool: Any, cards: str, apps: str, words: str
) -> None:
    tool, _ = card_tool(cards, apps)
    problems, _ = gpu_check.host_check(tool, CI_CARDS, RESERVED, 1024, 5)
    assert problems and "CI card" in problems[0] and "busy" in problems[0] and words in problems[0]


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
    tool, _ = card_tool(SIX, "GPU-4, 100\n")
    monkeypatch.setattr(launcher, "jit_config", lambda *_a: pytest.fail("a runner was registered"))
    assert launcher.run_slot(_settings(TB_BENCH_GPU_QUERY=tool), Path("/nonexistent"), "gpu-1") == 3


def test_the_jobs_own_check_refuses_busy_or_other_cards(
    card_tool: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # in the container the cards are numbered from 0: the check goes by UUID
    tool, _ = card_tool("0, GPU-4, 3, 0\n1, GPU-5, 3, 0\n")
    spec = tmp_path / "job.json"
    spec.write_text(json.dumps({"profile": "gpu", "tool": tool, "uuids": ["GPU-4", "GPU-5"], "busy_mib": 1024,
                                "busy_util": 5}), encoding="utf-8")  # fmt: skip
    assert gpu_check.main(["--in-job", str(spec)]) == 0
    tool, _ = card_tool("0, GPU-4, 3, 0\n1, GPU-5, 40000, 0\n")
    assert gpu_check.main(["--in-job", str(spec)]) == 1
    err = capsys.readouterr().err
    assert "busy" in err and "this job does not start" in err
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
    [("140.82.112.3", True), ("10.1.2.3", False), ("192.168.1.1", False), ("172.16.0.1", False),
     ("127.0.0.1", False), ("169.254.169.254", False), ("100.64.0.1", False), ("::1", False), ("fd00::1", False),
     ("fe80::1%eth0", False), ("2606:4700::1", True)],
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
    # the units get it as a systemd credential, by its folder, never by value
    assert "LoadCredential=token:/etc/tb-bench-ci/token" in RUNNER_UNIT and "--token-file %d/token" in RUNNER_UNIT
    assert not [ln for ln in RUNNER_UNIT.splitlines() if ln.startswith("Environment") and "TOKEN" in ln.upper()]
    assert "LoadCredential" not in PROXY_UNIT  # the proxy never holds it


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


def test_the_runner_archive_is_checked_and_the_networks_made_internal() -> None:
    assert "sha256sum -c --quiet -" in INSTALL and "TB_BENCH_RUNNER_SHA256" in INSTALL
    assert "network create --internal tb-bench-jobs" in INSTALL
    assert "{{.Internal}}" in INSTALL


def test_removal_takes_away_everything_it_made_and_says_what_is_left_to_the_owner() -> None:
    body = INSTALL[INSTALL.index("cmd_remove() {") : INSTALL.index("\n}\n", INSTALL.index("cmd_remove() {"))]
    for want in ("systemctl disable --now", 'rm -f "$UNITS/tb-bench-runner@.service" "$UNITS/tb-bench-proxy.service"',
                 "rm --all --force", "network rm --force tb-bench-jobs tb-bench-egress", "system reset --force",
                 'shred -u "$TOKEN"', 'rm -rf "$ETC" "$OPT"', 'loginctl disable-linger "$USER_NAME"',
                 'userdel --remove "$USER_NAME"', 'sed -i "/^$USER_NAME:/d" /etc/subuid /etc/subgid',
                 "remove any", "revoke the minting token", "LEFT"):  # fmt: skip
        assert want in body, want


def test_verify_checks_the_named_folders_as_the_runners_user_and_runs_the_probe() -> None:
    body = INSTALL[INSTALL.index("cmd_verify() {") : INSTALL.index("\n}\n", INSTALL.index("cmd_verify() {"))]
    assert 'for p in "$@"; do check "$USER_NAME cannot read or write $p" not sees "$p"; done' in body
    assert "at least one folder" in body and "as_tb_launcher probe" in body
    probe = (BENCH_CI / "probe.sh").read_text(encoding="utf-8")
    for want in ("not root", "engine socket", "no host folder but /scratch", "read-only", "no direct way out",
                 "off the allow-list", "written as a number"):  # fmt: skip
        assert want in probe, want


def test_the_image_runs_as_its_own_user_and_reads_its_config_from_stdin() -> None:
    assert re.search(r"^FROM [^\s]+@sha256:[0-9a-f]{64}$", DOCKERFILE, re.M)
    assert DOCKERFILE.rstrip().splitlines()[-3] == "USER 1001:1001"
    assert "useradd --uid 1001" in DOCKERFILE
    assert 'if [ "$(id -u)" = 0 ]' in ENTRYPOINT and "IFS= read -r config" in ENTRYPOINT
    assert 'exec ./run.sh --jitconfig "$config"' in ENTRYPOINT
    assert "ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/tb-bench/job_started.sh" in ENTRYPOINT
    hook = (BENCH_CI / "job_started.sh").read_text(encoding="utf-8")
    assert "gpu_check.py --in-job /scratch/.tb-bench/job.json" in hook


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
